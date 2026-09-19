"""提示词：仓库根目录 prompts/<名字>.md。

文件里用「## system」「## user」两个标题分段，第一个标题之前是写给人看的说明（会被忽略）。
变量写成 $名字（string.Template），真要写美元符号就写 $$。每次都重新读文件，改了不用重启。
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

from .config import APP_DIR

PROMPTS_DIR = APP_DIR / "prompts"
_SECTION = re.compile(r"^## (system|user)[ \t]*$", re.M)


def load_prompt(name: str, prompts_dir: Path | None = None) -> tuple[Template, Template]:
    # 目录在调用时才取 PROMPTS_DIR（不在定义时绑死），测试才能换一份提示词目录
    text = (Path(prompts_dir or PROMPTS_DIR) / f"{name}.md").read_text(encoding="utf-8")
    parts = _SECTION.split(text)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if set(sections) != {"system", "user"}:
        raise ValueError(f"提示词 {name}.md 要有「## system」和「## user」两段")
    return Template(sections["system"]), Template(sections["user"])


def render(name: str, prompts_dir: Path | None = None, **values: str) -> tuple[str, str]:
    system, user = load_prompt(name, prompts_dir)
    return system.substitute(values), user.substitute(values)
