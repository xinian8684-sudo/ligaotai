"""模型调用的通用封装：缓存、失败清单、没解决的问题、进度回调。

从 threads.py（归线排序）抽出来，好让步骤 7（档案）也能用同一套逻辑。缓存文件路径和
tag 前缀通过 Caller 的构造参数传入，不再写死指向归线自己的文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .book import Book
from .fsutil import read_json, write_json
from .jobs import JobCancelled
from .llm import FatalLLMError, LLMClient, LLMError, cache_config, cache_key
from .prompts import render

Progress = Callable[..., None]


def _noop(*args, **kwargs) -> None:
    pass


def load_cache(path: Path) -> dict[str, dict]:
    """缓存坏了就当没有：大不了重新调一遍模型。形状不对的条目丢掉。"""
    try:
        data = read_json(path, {})
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and isinstance(v.get("data"), dict) and isinstance(v.get("problems"), list)
    }


def _broken(e: Exception) -> str:
    return f"检查或清理出错：{type(e).__name__}: {e}"


class Caller:
    """一次运行里所有模型调用共用：缓存、失败清单、没解决的问题、进度。"""

    def __init__(
        self,
        book: Book,
        client: LLMClient,
        progress: Progress,
        *,
        cache_path: Path,
        tag_prefix: str = "threads",
    ):
        self.book = book
        self.client = client
        self.progress = progress
        # 必须显式传：忘传很容易变成「别的步骤的 Caller 悄悄读写了归线自己的缓存文件」
        # （归线缓存是真花过钱的结果，被误清空没法找补）。
        self.cache_path = cache_path
        self.tag_prefix = tag_prefix
        self.cfg = cache_config(client, "synth")
        self.cache = load_cache(self.cache_path)
        self.used: set[str] = set()
        self.failed: list[dict] = []
        self.unresolved: list[dict] = []
        self.done = 0
        self.total = 0

    def plan(self, n: int) -> None:
        """又要调 n 次：总数加上去（进度条的分母随阶段增长）。"""
        self.total += n
        self.progress(self.done, self.total)

    def _save(self) -> None:
        try:
            write_json(self.cache_path, self.cache)
        except OSError:
            pass  # 缓存写失败不该让已经花了钱的这次调用也跟着失败

    async def call(self, prompt: str, values: dict, check, tag: str, *, score=None, clean=None, usable=None):
        """调一次综合档（先查缓存）。返回 clean(模型输出)，没给 clean 就返回模型输出；失败返回 None。

        失败有三种，都记进 failed、返回 None，由调用方兜底：
        - 这一次调用失败（LLMError）；
        - 检查 / 打分 / 清理抛了异常（本不该发生）：这条缓存删掉，免得坏结果钉死在缓存里，
          下次同样的调用会重新调模型；
        - 传了 usable（清理结果 → 这次回复能不能用）：清理之后调 usable(结果)，返回假、或者
          usable 自己抛异常，都当「这次回复没法用」——跟清理出错走同一条路：缓存删掉、记
          「模型回复没法用（重试后仍然没有可用的结果）」，下次同样的调用会重新调模型（重跑正是
          作者想要的：花钱换一次新的重试）。
        FatalLLMError（欠费、key 失效）、JobCancelled（暂停）和 BaseException 系照样往外抛。"""
        system, user = render(prompt, **values)
        key = cache_key(system, user, self.cfg)
        entry = self.cache.get(key)
        if entry is None:
            try:
                data, problems = await self.client.chat_json(
                    "synth", system, user, check, tag=f"{self.tag_prefix}/{tag}", score=score
                )
            except FatalLLMError:
                raise
            except LLMError as e:  # 这一次调用失败，由调用方决定怎么兜底
                self.failed.append({"call": tag, "error": str(e)})
            except JobCancelled:
                raise
            except Exception as e:  # 检查 / 打分抛了异常，chat_json 没返回结果，缓存里也没有这条
                self.failed.append({"call": tag, "error": _broken(e)})
            else:
                entry = self.cache[key] = {"data": data, "problems": problems}
                self._save()
        result = None
        if entry is not None:
            result = entry["data"]
            if clean is not None:
                try:
                    result = clean(entry["data"])
                except (FatalLLMError, JobCancelled):
                    raise
                except Exception as e:
                    self.failed.append({"call": tag, "error": _broken(e)})
                    self.cache.pop(key, None)
                    self._save()
                    entry = result = None
        if entry is not None and usable is not None:
            try:
                bad = not usable(result)
            except (FatalLLMError, JobCancelled):
                raise
            except Exception as e:
                self.failed.append({"call": tag, "error": _broken(e)})
                bad = True
            else:
                if bad:
                    self.failed.append({"call": tag, "error": "模型回复没法用（重试后仍然没有可用的结果）"})
            if bad:
                self.cache.pop(key, None)
                self._save()
                entry = result = None
        if entry is not None:
            self.used.add(key)
            if entry["problems"]:
                self.unresolved.append({"call": tag, "problems": list(entry["problems"])[:5]})
        self.done += 1
        self.progress(self.done, self.total)  # 暂停检查点：做完的调用都在缓存里
        return result

    def prune_cache(self) -> None:
        """跑成功了：这次没用到的缓存条目清掉，免得越积越多。"""
        if set(self.cache) - self.used:
            try:
                write_json(self.cache_path, {k: v for k, v in self.cache.items() if k in self.used})
            except OSError:
                pass
