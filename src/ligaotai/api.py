"""FastAPI 应用。只给本机用：只认 127.0.0.1 / localhost 的 Host，不开 CORS。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from . import __version__
from .book import STEP_LABELS, STEPS, Book, create_book, list_books, open_book, recover_interrupted
from .config import APP_DIR, AppConfig, library_path, load_config, save_config
from .dedup import run_dedup, set_main
from .fsutil import ensure_within, read_json
from .importer import check_import_folder, run_import
from .jobs import BusyError, JobRunner
from .readers import read_text
from .scenes import get_scene, load_scenes, run_split

STEP_RUNNERS = {"split": run_split, "dedup": run_dedup}


class NewBook(BaseModel):
    title: str


class ImportReq(BaseModel):
    folder: str


class MainReq(BaseModel):
    scene_id: str


def create_app(
    app_dir: Path = APP_DIR, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
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

    def submit(book: Book, step: str, fn: Callable[[Callable], dict]) -> dict:
        def work(progress: Callable) -> dict:
            book.set_step(step, "running")
            try:
                return fn(progress)
            except BaseException as e:
                book.set_step(step, "failed", {"error": f"{type(e).__name__}: {e}"})
                raise

        try:
            return runner.submit(step, book.name, work).to_dict()
        except BusyError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/config")
    def get_config() -> dict:
        cfg = load_config(app_dir)
        return {**cfg.model_dump(), "library_path": str(library_path(cfg, app_dir))}

    @app.put("/api/config")
    def put_config(cfg: AppConfig) -> dict:
        save_config(cfg, app_dir)
        return get_config()

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
        fn = STEP_RUNNERS.get(step)
        if fn is None:
            raise HTTPException(400, f"这一步现在还不能跑：{step}")
        for prev in STEPS[: STEPS.index(step)]:
            if b.step(prev)["status"] != "done":
                raise HTTPException(409, f"请先完成上一步：{STEP_LABELS[prev]}")
        return submit(b, step, lambda p: fn(b, p))

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
