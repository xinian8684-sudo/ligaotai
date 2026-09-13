"""FastAPI 应用。只给本机用：只认 127.0.0.1 / localhost 的 Host，不开 CORS。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from . import __version__
from . import entities as ent
from .book import STEP_LABELS, STEPS, Book, create_book, list_books, open_book, recover_interrupted
from .cards import is_fresh, load_card, load_cards, run_cards
from .config import (
    APP_DIR,
    AppConfig,
    apply_update,
    library_path,
    load_config,
    public_config,
    save_config,
)
from .dedup import run_dedup, set_main
from .fsutil import ensure_within, read_json
from .importer import check_import_folder, run_import
from .jobs import BusyError, JobCancelled, JobRunner
from .llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend, check_model
from .readers import read_text
from .scenes import SCENE_ID_RE, get_scene, load_scenes, run_split

RUNNABLE = ("split", "dedup", "cards", "entities")
PAUSED = "已暂停：做完的部分已经保存，重跑会接着做"


class NewBook(BaseModel):
    title: str


class ImportReq(BaseModel):
    folder: str


class MainReq(BaseModel):
    scene_id: str


class IdsReq(BaseModel):
    ids: list[str]


class MergeReq(BaseModel):
    ids: list[str]
    canonical: str | None = None


class RenameReq(BaseModel):
    canonical: str


class SplitReq(BaseModel):
    names: list[str]


def create_app(
    app_dir: Path = APP_DIR,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
    backend_factory: Callable[[AppConfig], ChatBackend] = OpenAIBackend,
) -> FastAPI:
    app = FastAPI(title="理稿台", version=__version__)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    runner = JobRunner()
    app.state.runner = runner

    def library() -> Path:
        lib = library_path(load_config(app_dir), app_dir)
        lib.mkdir(parents=True, exist_ok=True)
        return lib

    recover_interrupted(library())

    def get_book(name: str) -> Book:
        try:
            return open_book(library(), name)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "没有这本书")

    def make_backend(cfg: AppConfig) -> ChatBackend:
        try:
            return backend_factory(cfg)
        except NoKeyError as e:
            raise HTTPException(400, str(e))

    def make_client(book: Book) -> LLMClient:
        cfg = load_config(app_dir)
        return LLMClient(cfg, make_backend(cfg), log_dir=book.logs_dir)

    def submit(book: Book, step: str, fn: Callable[[Callable], dict]) -> dict:
        def work(progress: Callable) -> dict:
            book.set_step(step, "running")
            try:
                return fn(progress)
            except JobCancelled:
                book.set_step(step, "failed", {"error": PAUSED})
                raise
            except BaseException as e:
                book.set_step(step, "failed", {"error": f"{type(e).__name__}: {e}"})
                raise

        try:
            return runner.submit(step, book.name, work).to_dict()
        except BusyError as e:
            raise HTTPException(409, str(e))

    def require_upstream(book: Book, step: str) -> None:
        for prev in STEPS[: STEPS.index(step)]:
            if book.step(prev)["status"] != "done":
                raise HTTPException(409, f"请先完成上一步：{STEP_LABELS[prev]}")

    def step_work(book: Book, step: str) -> Callable[[Callable], dict]:
        if step == "split":
            return lambda p: run_split(book, p)
        if step == "dedup":
            return lambda p: run_dedup(book, p)
        client = make_client(book)
        if step == "cards":
            return lambda p: run_cards(book, client, p)
        return lambda p: ent.run_entities(book, client, p)

    def entity_op(fn: Callable[[], object]):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "没有这个实体")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/config")
    def get_config() -> dict:
        return public_config(load_config(app_dir), app_dir)

    @app.put("/api/config")
    def put_config(cfg: AppConfig) -> dict:
        save_config(apply_update(load_config(app_dir), cfg), app_dir)
        return get_config()

    @app.post("/api/config/test")
    def test_config() -> list:
        cfg = load_config(app_dir)
        return check_model(cfg, make_backend(cfg))

    @app.get("/api/books")
    def books() -> list:
        return list_books(library())

    @app.post("/api/books", status_code=201)
    def new_book(req: NewBook) -> dict:
        try:
            b = create_book(library(), req.title)
        except FileExistsError:
            raise HTTPException(409, "这本书已经有了")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"name": b.name, **b.load()}

    @app.get("/api/books/{name}")
    def book_meta(name: str) -> dict:
        b = get_book(name)
        return {"name": b.name, **b.load()}

    @app.post("/api/books/{name}/import", status_code=202)
    def do_import(name: str, req: ImportReq) -> dict:
        b = get_book(name)
        folder = Path(req.folder)
        if not folder.is_dir():
            raise HTTPException(400, f"文件夹不存在：{req.folder}")
        try:
            check_import_folder(b, folder)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return submit(b, "import", lambda p: run_import(b, folder, p))

    @app.post("/api/books/{name}/steps/{step}/run", status_code=202)
    def run_step(name: str, step: str) -> dict:
        b = get_book(name)
        if step not in RUNNABLE:
            raise HTTPException(400, f"这一步现在还不能跑：{step}")
        require_upstream(b, step)
        return submit(b, step, step_work(b, step))

    @app.get("/api/jobs/current")
    def current_job() -> dict | None:
        job = runner.current()
        return job.to_dict() if job else None

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(404, "没有这个任务")
        return job.to_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = runner.cancel(job_id)
        if job is None:
            raise HTTPException(404, "没有这个任务")
        return job.to_dict()

    @app.get("/api/books/{name}/scenes")
    def scenes(name: str, include_removed: bool = False) -> list:
        b = get_book(name)
        return [s.meta() for s in load_scenes(b) if include_removed or not s.removed]

    @app.get("/api/books/{name}/scenes/{sid}")
    def scene(name: str, sid: str) -> dict:
        b = get_book(name)
        try:
            sc = get_scene(b, sid)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        return {**sc.meta(), "text": sc.text}

    @app.get("/api/books/{name}/cards")
    def cards(name: str) -> list:
        b = get_book(name)
        records = load_cards(b)
        out = []
        for s in load_scenes(b):
            if s.removed:
                continue
            r = records.get(s.id)
            card = (r.get("card") if r else None) or {}
            problems = (r.get("problems") if r else None) or []
            dropped = (r.get("dropped") if r else None) or {}
            out.append({
                "id": s.id,
                "fresh": is_fresh(r, s),
                "kind": card.get("kind"),
                "summary": card.get("summary") or "",
                "problems": len(problems),
                "dropped": sum(len(v) for v in dropped.values()),
            })
        return out

    @app.get("/api/books/{name}/cards/{sid}")
    def card(name: str, sid: str) -> dict:
        b = get_book(name)
        record = load_card(b, sid) if SCENE_ID_RE.match(sid) else None
        if record is None:
            raise HTTPException(404, "这个场景还没有场景卡")
        return record

    @app.post("/api/books/{name}/cards/{sid}/regenerate", status_code=202)
    def regenerate_card(name: str, sid: str) -> dict:
        b = get_book(name)
        try:
            get_scene(b, sid)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        require_upstream(b, "cards")
        client = make_client(b)
        return submit(b, "cards", lambda p: run_cards(b, client, p, only=[sid]))

    @app.get("/api/books/{name}/entities")
    def entities(name: str) -> dict:
        b = get_book(name)
        return read_json(b.entities_path, {"entities": []})

    @app.post("/api/books/{name}/entities/confirm")
    def confirm_entities(name: str, req: IdsReq) -> list:
        b = get_book(name)
        return entity_op(lambda: ent.confirm(b, req.ids))

    @app.post("/api/books/{name}/entities/merge")
    def merge_entities(name: str, req: MergeReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.merge(b, req.ids, req.canonical))

    @app.put("/api/books/{name}/entities/{eid}")
    def rename_entity(name: str, eid: str, req: RenameReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.rename(b, eid, req.canonical))

    @app.post("/api/books/{name}/entities/{eid}/split")
    def split_entity(name: str, eid: str, req: SplitReq) -> dict:
        b = get_book(name)
        return entity_op(lambda: ent.split(b, eid, req.names))

    @app.get("/api/books/{name}/versions")
    def versions(name: str) -> dict:
        b = get_book(name)
        return read_json(b.versions_path, {"params": {}, "groups": []})

    @app.put("/api/books/{name}/versions/{gid}/main")
    def put_main(name: str, gid: str, req: MainReq) -> dict:
        b = get_book(name)
        try:
            return set_main(b, gid, req.scene_id)
        except KeyError:
            raise HTTPException(404, "没有这个版本组")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/books/{name}/source")
    def source(name: str, path: str) -> dict:
        b = get_book(name)
        files = read_json(b.manifest_path, {"files": {}})["files"]
        if path not in files:
            raise HTTPException(404, "没有这个原稿")
        text, enc = read_text(ensure_within(b.originals_dir, b.originals_dir / path))
        return {"path": path, "encoding": enc, "text": text}

    return app
