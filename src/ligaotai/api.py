"""FastAPI 应用。只给本机用：只认 127.0.0.1 / localhost 的 Host，不开 CORS。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from . import entities as ent
from . import threads_ops as tops
from .archive import load_index, run_archive, write_index
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
from .fsutil import ensure_within, read_json, safe_name
from .importer import check_import_folder, run_import
from .jobs import BusyError, JobCancelled, JobRunner
from .llm import ChatBackend, LLMClient, NoKeyError, OpenAIBackend, check_model
from .readers import read_text
from .scenes import SCENE_ID_RE, BrokenSceneFile, get_scene, load_scenes, run_split
from .threads import normalize, run_threads

RUNNABLE = ("split", "dedup", "cards", "entities", "threads", "archive")
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


class NameReq(BaseModel):
    name: str


class MoveReq(BaseModel):
    ids: list[str]
    position: int | None = None
    as_outline: bool = False


class SplitThreadReq(BaseModel):
    from_scene: str


class MainThreadReq(BaseModel):
    thread: str


class WorldReq(BaseModel):
    world: str


class RerunReq(BaseModel):
    threads: list[str] = []
    worlds: list[str] = []
    map: bool = False


def _读坏了(what: str, detail: str) -> HTTPException:
    """手改坏的文件不能让接口返回裸 500——把出错的文件/条目和原因说清楚。"""
    return HTTPException(500, f"{what} 读不了：{detail}。这个文件多半被手动改过或来自别处。")


def _within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def create_app(
    app_dir: Path = APP_DIR,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
    backend_factory: Callable[[AppConfig], ChatBackend] = OpenAIBackend,
    web_dist: Path | None = None,
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

    def submit(
        book: Book, step: str, fn: Callable[[Callable], dict], track_step: bool = True
    ) -> dict:
        # track_step=False：单卡重做用，不把 step 的状态标成 running/failed——
        # 状态是不是变，交给 fn 自己决定（cards.run_cards 的 only 模式会原样保留）。
        def work(progress: Callable) -> dict:
            if track_step:
                book.set_step(step, "running")
            try:
                return fn(progress)
            except JobCancelled:
                if track_step:
                    book.set_step(step, "failed", {"error": PAUSED})
                raise
            except BaseException as e:
                if track_step:
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
        if step == "threads":
            return lambda p: run_threads(book, client, p)
        if step == "archive":
            return lambda p: run_archive(book, client, p)
        return lambda p: ent.run_entities(book, client, p)

    def entity_op(fn: Callable[[], object]):
        try:
            return fn()
        except ent.NoSuchEntity:
            raise HTTPException(404, "没有这个实体")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ent.BrokenEntitiesFile as e:
            raise _读坏了("实体.json", str(e))
        except json.JSONDecodeError as e:
            raise _读坏了("实体.json", f"不是合法 JSON，第 {e.lineno} 行")
        except KeyError as e:
            # ent.NoSuchEntity（上面已经接住）是「给的 id 找不到」，这里剩下的是别的
            # KeyError——条目本身缺字段（比如少了 canonical/type/names），文件多半被手动
            # 改过，不是「没有这个实体」，不能报 404。
            raise HTTPException(500, f"实体条目缺字段 {e}，文件多半被手动改过。")
        except ValueError as e:
            raise HTTPException(400, str(e))

    def thread_op(fn: Callable[[], object]):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "没有这条线或这个世界")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except tops.BrokenThreadsFile as e:
            raise HTTPException(409, str(e))
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
        return book_payload(b)

    def book_payload(b) -> dict:
        # 建书和取书返回同一个形状（前端都标成 BookMeta，roots 必填）；新书还没导入，roots 是 {}
        manifest = read_json(b.manifest_path, {"files": {}})
        return {"name": b.name, **b.load(), "roots": manifest.get("roots", {})}

    @app.get("/api/books/{name}")
    def book_meta(name: str) -> dict:
        return book_payload(get_book(name))

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
        try:
            all_scenes = load_scenes(b)
        except BrokenSceneFile as e:
            raise HTTPException(500, str(e))
        return [s.meta() for s in all_scenes if include_removed or not s.removed]

    @app.get("/api/books/{name}/scenes/{sid}")
    def scene(name: str, sid: str) -> dict:
        b = get_book(name)
        try:
            sc = get_scene(b, sid)
        except BrokenSceneFile as e:
            # BrokenSceneFile 继承 ValueError，必须排在下面那条前面，不然被吃成「没有这个场景」
            raise HTTPException(500, str(e))
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        return {**sc.meta(), "text": sc.text}

    @app.get("/api/books/{name}/cards")
    def cards(name: str) -> list:
        b = get_book(name)
        records = load_cards(b)
        out = []
        try:
            all_scenes = load_scenes(b)
        except BrokenSceneFile as e:
            raise HTTPException(500, str(e))
        for s in all_scenes:
            if s.removed:
                continue
            r = records.get(s.id)
            try:
                card = (r.get("card") if r else None) or {}
                n_problems = len((r.get("problems") if r else None) or [])
                dropped = (r.get("dropped") if r else None) or {}
                n_dropped = len(dropped.get("facts") or []) + len(dropped.get("names") or [])
                summary = card.get("summary") or ""
                kind = card.get("kind")
            except (AttributeError, TypeError) as e:
                # 卡文件结构被手改坏了（比如 card/dropped 本该是对象却是字符串），
                # .get() 在非 dict 上会炸——带上是哪张卡，别让作者对着裸 500 猜。
                # "problems": 5 / "dropped": {"facts": 5} 这类在 len() 上炸的是 TypeError。
                raise _读坏了(f"场景卡 {s.id}", str(e))
            out.append({
                "id": s.id,
                "fresh": is_fresh(r, s),
                "kind": kind,
                "summary": summary,
                "problems": n_problems,
                # 2c task04：dropped 里加了 attrs / long_values 两个 int 计数键，不是列表；
                # attrs 只是归一不算丢弃，long_values 已经并进了 facts 列表，这里只数
                # facts / names 两项真正被丢掉的东西，跟原来的语义一致。
                "dropped": n_dropped,
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
        except BrokenSceneFile as e:
            raise HTTPException(500, str(e))
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "没有这个场景")
        require_upstream(b, "cards")
        client = make_client(b)
        return submit(
            b, "cards", lambda p: run_cards(b, client, p, only=[sid]), track_step=False
        )

    @app.get("/api/books/{name}/entities")
    def entities(name: str) -> dict:
        b = get_book(name)
        try:
            return ent.check_entities_shape(read_json(b.entities_path, {"entities": []}))
        except json.JSONDecodeError as e:
            raise _读坏了("实体.json", f"不是合法 JSON，第 {e.lineno} 行")
        except ent.BrokenEntitiesFile as e:
            raise _读坏了("实体.json", str(e))

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

    @app.get("/api/books/{name}/threads")
    def threads(name: str) -> dict:
        b = get_book(name)
        try:
            return normalize(tops.read_threads(b))
        except tops.BrokenThreadsFile as e:
            raise HTTPException(409, str(e))

    @app.post("/api/books/{name}/threads/confirm")
    def confirm_threads(name: str, req: IdsReq) -> list:
        b = get_book(name)
        return thread_op(lambda: tops.confirm(b, req.ids))

    @app.post("/api/books/{name}/threads/reject")
    def reject_pending(name: str, req: IdsReq) -> list:
        # 拒绝模型的归入建议：pending → unassigned，落盘（归线页「拒绝」按钮用）
        b = get_book(name)
        return thread_op(lambda: tops.reject_pending(b, req.ids))

    @app.put("/api/books/{name}/threads/main")
    def set_main_thread(name: str, req: MainThreadReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.set_main(b, req.thread))

    @app.post("/api/books/{name}/threads/merge")
    def merge_threads(name: str, req: IdsReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.merge_threads(b, req.ids))

    @app.put("/api/books/{name}/threads/{oid}/name")
    def rename_thread(name: str, oid: str, req: NameReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.rename(b, oid, req.name))

    @app.post("/api/books/{name}/threads/{tid}/scenes")
    def move_scenes(name: str, tid: str, req: MoveReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.move_scenes(b, req.ids, tid, req.position, req.as_outline))

    @app.post("/api/books/{name}/threads/{tid}/split")
    def split_thread(name: str, tid: str, req: SplitThreadReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.split_thread(b, tid, req.from_scene))

    @app.put("/api/books/{name}/threads/{tid}/world")
    def move_thread(name: str, tid: str, req: WorldReq) -> dict:
        b = get_book(name)
        return thread_op(lambda: tops.move_thread(b, tid, req.world))

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

    @app.get("/api/books/{name}/archive")
    def archive_index(name: str) -> dict:
        b = get_book(name)
        # I2（9-20 定）：附上当前配置的模型名，好让界面跟每份档案 index 里记的
        # model 字段比对，提示作者「这份档案是 X 模型写的，当前配置是 Y，要不要重跑」。
        # 只读配置，不建后端连接——不需要真的能连上模型才能看这个对比。
        return {**load_index(b), "current_model": load_config(app_dir).synth.model}

    @app.get("/api/books/{name}/contradictions")
    def contradictions(name: str) -> dict:
        b = get_book(name)
        return read_json(b.contradictions_path, {"groups": [], "stats": {}})

    @app.get("/api/books/{name}/archive/{kind}/{oid}")
    def archive_body(name: str, kind: str, oid: str) -> dict:
        b = get_book(name)
        if kind not in ("thread", "world"):
            raise HTTPException(400, "kind 只能是 thread 或 world")
        base = b.thread_archive_dir if kind == "thread" else b.world_archive_dir
        try:
            path = ensure_within(base, base / f"{safe_name(oid)}.md")
        except ValueError:
            # safe_name("..")/"."/"   " 之类的边界输入会抛 ValueError("名字不能为空")——
            # 这就是「没有这份档案」，不该是裸 500。
            raise HTTPException(404, "没有这份档案")
        if not path.exists():
            raise HTTPException(404, "没有这份档案")
        return {"id": oid, "body": path.read_text(encoding="utf-8")}

    @app.post("/api/books/{name}/archive/rerun")
    def archive_rerun(name: str, req: RerunReq) -> dict:
        """把指定的档案标过期，下次跑步骤 7 只重跑它们。

        I2（9-20 GHIJ 审查）：`archive_rerun` 对 档案/index.json 做读-改-写，
        `_Run._save_index()`（archive.py）每落一份档案就把整份 index 覆盖写一遍。
        两边都没锁，这本书有任务在跑时点这个接口，要么标记被下一次 _save_index()
        用进程内旧副本静默盖掉（作者以为标了，其实没标），要么反过来把 job 刚写的
        sig/generated/model 回退成旧值（一份刚花钱生成的档案在 index 里「不存在」，
        下一轮再付一次钱）。最小修法：跟 submit() 的 BusyError 同一套话术，有任务在
        跑（不分是不是这本书）就 409，不做读-改-写。"""
        cur = runner.current()
        if cur is not None and cur.status in ("queued", "running"):
            raise HTTPException(409, f"已有任务在跑：{cur.name}（{cur.book}）")
        b = get_book(name)
        # I5（9-20 GHIJ 审查）：这里原来直接 read_json(b.threads_path, {})，脏文件（坏
        # JSON）会抛 JSONDecodeError，缺 id / 非 dict 的条目会抛 KeyError/TypeError，
        # 全都没接，接口裸 500。同一个文件在 GET /threads 那边有 BrokenThreadsFile →
        # 409 的映射（tops.read_threads + thread_op），这里没有，口径不一致。改成套
        # thread_op(...) 读（JSON 坏了给 409），再照 archive.prepare_inputs 那样
        # isinstance 过滤，缺 id / 非 dict 的条目直接跳过，不让它们炸整个请求。
        data = thread_op(lambda: tops.read_threads(b)) or {}
        tids = {t["id"] for t in data.get("threads") or []
               if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"]}
        wids = {w["id"] for w in data.get("worlds") or []
               if isinstance(w, dict) and isinstance(w.get("id"), str) and w["id"]}
        bad = [x for x in req.threads if x not in tids] + [x for x in req.worlds if x not in wids]
        if bad:
            raise HTTPException(400, "没有这些编号：" + "、".join(bad))
        index = load_index(b)
        for tid in req.threads:
            index["threads"].setdefault(tid, {})["outdated"] = True
        for wid in req.worlds:
            index["worlds"].setdefault(wid, {})["outdated"] = True
        if req.map:
            index["map"]["outdated"] = True
        write_index(b, index)
        return {"ok": True}

    # 前端静态站。必须在所有 /api 路由注册之后挂，兜底路由才不会抢在 API 前面。
    dist = Path(web_dist) if web_dist is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    index_html = dist / "index.html"
    if index_html.exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def _index() -> FileResponse:
            return FileResponse(index_html)

        @app.get("/{full_path:path}")
        def _spa(full_path: str) -> FileResponse:
            # 单页应用：前端路由直接刷新时回 index.html，交给前端路由器。
            # /api 开头的交给上面的真路由；走到这儿说明那个 API 不存在，照常 404。
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(404, "没有这个接口")
            candidate = dist / full_path
            if candidate.is_file() and _within(dist, candidate):
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app
