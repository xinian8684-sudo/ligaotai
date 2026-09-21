# 理稿台 计划③ 实施计划：网页界面

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做出一期的 9 个网页页面，让作者不碰命令行就能把一本乱稿从导入跑到步骤 7，并看清全景、场景、设定库和矛盾。

**Architecture:** 新建 `web/`，Vue 3 + Vite + TypeScript 单页应用，构建成静态文件由 FastAPI 托管（运行时不需要 Node）。三个会算错的纯函数（断轴成轴、段生成、缺口聚合）抽进 `web/src/lib/`，先于任何组件实现并单测。后端只做 spec 第 8 章那四条错误处理修复和一个静态目录挂载，不动业务逻辑。

**Tech Stack:** Vue 3（Composition API）、Vite、TypeScript、Vue Router、Pinia、Vitest、@vue/test-utils。后端 Python 3.12 + FastAPI + pytest（已有 860 测试）。

**设计文档：** `docs/superpowers/specs/2026-09-21-ligaotai-plan3-ui-design.md`（下称「spec」）。上级：`docs/superpowers/specs/2026-09-10-ligaotai-design.md`（下称「总 spec」）。

---

## 约定（每个任务都适用）

- 只在本计划的分支（`plan3`）上干活；**禁止 `git stash` / `git checkout --` / `git reset` / `git restore`**，`git add` 只加自己这个任务的文件。
- **包管理器用 `npm`，不用 pnpm**（这台机器上 pnpm 的符号链接在 D 盘踩过坑）。
- 跑前端测试：`cd web && npm run test`。跑后端测试：`uv run pytest -q`。
- **别在工具参数里敲 `\u` 转义**（会被吃掉，用 `chr(92)` 拼）。
- 中文输出别信终端（Windows 按 GBK 解码会全乱），要看结果就写文件再读。
- 后端 `tools/` 下的脚本必须能 `uv run python tools/xxx.py` 直接跑（`tests/test_tools_scripts.py` 守着）。
- 每个任务最后一步是 commit，message 用中文，结尾带 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。
- **计划里的代码没有跑过。** ②c 期间任务书自带的代码被抓出 6 个真 bug。照抄之前先自己验，不一致要在报告里说明。

## 后端已有的事实（不要凭印象改）

跑 `uv run python -c "..."` 或直接读源码确认，以下是实测：

- 后端入口 `python -m ligaotai`，监听 **127.0.0.1:8765**（`src/ligaotai/__main__.py`）。
- `create_app(app_dir, allowed_hosts=("127.0.0.1","localhost"), backend_factory)`，挂了 `TrustedHostMiddleware`。
- 步骤：`STEPS = ["import","split","dedup","cards","entities","threads","archive"]`，可跑的是 `RUNNABLE = ("split","dedup","cards","entities","threads","archive")`（导入走 `/import` 单独的接口）。
- 步骤状态：`STATUSES = ("todo","running","done","failed","outdated")`。
- `GET /api/books` → `[{name, title, created}]`；`GET /api/books/{name}` → `{name, schema, title, created, settings, steps:{<step>:{status, updated, summary}}}`。
- `Job` → `{id, name, book, status, done, total, message, error, result, started, finished, cancel_requested}`；`status` 是 `queued/running/done/failed/cancelled`。**全局同时只允许一个任务**，撞了抛 `BusyError`。
- `GET /api/config` → `AppConfig` 的字段加上 `api_key`（打码）、`has_key`、`key_from_env`、`library_path`。`PUT /api/config` **整份替换**，前端必须提交完整表单。
- `GET /api/books/{name}/archive` → `{...index, current_model}`。
- 归线结果的真实形状见 Task 10 导出的 fixture。**`thread.status` 和 `thread.end.state` 是正交的两件事，别混用**：`status` 是「作者确认过这条线的划分没有」（`threads.py`：`CONFIRMED if t.locked else DRAFT`）；**故事写完没有看 `end.state`**（`"完结"` / `"待定"`）。

---

## 文件结构

```
web/                                   新建
  package.json  tsconfig.json  tsconfig.node.json  vite.config.ts  index.html
  src/
    main.ts  App.vue  router.ts
    api/
      client.ts        fetch 封装：拼 /api、抛带 detail 的错误
      types.ts         所有接口的 TS 类型（按后端真实返回写）
      endpoints.ts     37 个接口的函数
    stores/
      book.ts          当前书 + 步骤状态
      job.ts           全局任务轮询与「忙不忙」
      config.ts        配置
    lib/
      axis.ts          断轴成轴（纯函数，spec 4.2）
      segments.ts      段生成（纯函数，spec 4.3）
      gaps.ts          缺口两层聚合（纯函数，spec 4.4）
    components/
      AppShell.vue  NavRail.vue  JobBar.vue  ErrorBox.vue  LaneChart.vue
      __fixtures__/  从真书导出的归线样本（提交进仓库）
    pages/
      BooksPage.vue      PipelinePage.vue   EntitiesPage.vue
      ThreadsPage.vue    PanoramaPage.vue   ScenesPage.vue
      ArchivePage.vue    ContradictionsPage.vue  SettingsPage.vue
    styles/
      tokens.css       原样搬原型的 CSS 变量表
      base.css         布局骨架
tools/
  export_lane_fixtures.py              从 data/ 提 fixture（可重跑）
src/ligaotai/api.py                    改：静态托管 + spec 第 8 章四条修复
src/ligaotai/cards.py                  改：only 模式保留 summary
tests/test_api_static.py               新建：静态托管
tests/test_api_errors.py               新建：四条错误处理
```

**里程碑**（一份计划，内部分五段控风险，每段做完跑一次全量测试）：

| 段 | 任务 | 做完能验证什么 |
|---|---|---|
| A 地基 | 1–5 | 前端起得来、连得上后端、任务进度能显示 |
| B 后端修复 | 6–9 | 手改坏的文件不再返回裸 500 |
| C 泳道图算法 | 10–13 | 三个纯函数在真数据上算对 |
| D 页面 | 14–23 | 9 个页面都能用 |
| E 收尾 | 24–25 | 构建产物能被 FastAPI 托管，全页面人工看过 |

---

## Task 1: 前端脚手架

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.ts`
- Create: `web/src/App.vue`
- Create: `web/.gitignore`
- Test: `web/src/smoke.test.ts`

- [ ] **Step 1: 建 `web/package.json`**

```json
{
  "name": "ligaotai-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "vue-tsc --noEmit"
  },
  "dependencies": {
    "pinia": "^2.2.0",
    "vue": "^3.5.0",
    "vue-router": "^4.4.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "@vue/test-utils": "^2.4.6",
    "jsdom": "^25.0.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0",
    "vue-tsc": "^2.1.0"
  }
}
```

- [ ] **Step 2: 建 `web/vite.config.ts`**

`base` 用相对路径，这样 FastAPI 挂在任何前缀下都能找到资源。dev 时把 `/api` 代理到后端 8765。

```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
```

注意 `changeOrigin: false`：后端挂了 `TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost"])`，保持原 Host 头正好落在白名单里。

- [ ] **Step 3: 建 `web/tsconfig.json` 和 `web/tsconfig.node.json`**

`web/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "resolveJsonModule": true,
    "esModuleInterop": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vitest/globals"],
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "vite.config.ts"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`web/tsconfig.node.json`：

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["node"],
    "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: 建 `web/index.html`、`web/src/main.ts`、`web/src/App.vue`、`web/.gitignore`**

`web/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>理稿台</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

`<meta charset="utf-8">` 不能少——原型就因为漏了它，在中文 Windows 上被按 GBK 解码整页乱码。

`web/src/main.ts`：

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

createApp(App).use(createPinia()).mount('#app')
```

`web/src/App.vue`：

```vue
<script setup lang="ts"></script>

<template>
  <div>理稿台</div>
</template>
```

`web/.gitignore`：

```
node_modules/
dist/
```

- [ ] **Step 5: 写冒烟测试 `web/src/smoke.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import App from './App.vue'

describe('脚手架', () => {
  it('App 挂得起来', () => {
    const w = mount(App)
    expect(w.text()).toContain('理稿台')
  })
})
```

- [ ] **Step 6: 装依赖并跑测试**

```bash
cd web && npm install && npm run test
```

Expected: `1 passed`。装依赖第一次会慢。

- [ ] **Step 7: 跑一次 typecheck**

```bash
cd web && npm run typecheck
```

Expected: 无输出、退出码 0。

- [ ] **Step 8: Commit**

```bash
git add web/
git commit -m "feat(web): Vue 3 + Vite + TS 脚手架

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: FastAPI 托管前端静态文件

后端要能把 `web/dist` 当静态站点发出去，且**单页应用的任意路由刷新都要回 index.html**（否则 `/b/xxx/panorama` 直接刷新会 404）。同时 `web/dist` 不存在时（没构建过）不能让后端起不来。

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_static.py`

- [ ] **Step 1: 写失败的测试 `tests/test_api_static.py`**

```python
"""前端静态托管：dist 在就发，不在也不能让后端起不来。"""

import pytest
from fastapi.testclient import TestClient

from ligaotai.api import create_app


@pytest.fixture
def 假dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><title>理稿台</title>", encoding="utf-8")
    assets = d / "assets"
    assets.mkdir()
    (assets / "main.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_没有dist时后端照常起得来(tmp_path):
    app = create_app(app_dir=tmp_path, web_dist=tmp_path / "不存在")
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True


def test_根路径发index(tmp_path, 假dist):
    c = TestClient(create_app(app_dir=tmp_path, web_dist=假dist))
    r = c.get("/")
    assert r.status_code == 200
    assert "理稿台" in r.text


def test_静态资源按原路径发(tmp_path, 假dist):
    c = TestClient(create_app(app_dir=tmp_path, web_dist=假dist))
    r = c.get("/assets/main.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_前端路由刷新回index(tmp_path, 假dist):
    """SPA：/b/某书/panorama 直接刷新要拿到 index.html，不是 404。"""
    c = TestClient(create_app(app_dir=tmp_path, web_dist=假dist))
    r = c.get("/b/某书/panorama")
    assert r.status_code == 200
    assert "理稿台" in r.text


def test_不存在的api路径仍然404(tmp_path, 假dist):
    """兜底不能把 /api 下的 404 也吃掉，否则前端拿到一坨 HTML 当 JSON 解。"""
    c = TestClient(create_app(app_dir=tmp_path, web_dist=假dist))
    r = c.get("/api/没有这个接口")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `uv run pytest tests/test_api_static.py -v`
Expected: FAIL，`create_app() got an unexpected keyword argument 'web_dist'`。

- [ ] **Step 3: 改 `src/ligaotai/api.py`**

在文件顶部的 import 区加：

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

`create_app` 的签名加一个参数（默认指向仓库里的 `web/dist`）：

```python
def create_app(
    app_dir: Path = APP_DIR,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
    backend_factory: Callable[[AppConfig], ChatBackend] = OpenAIBackend,
    web_dist: Path | None = None,
) -> FastAPI:
```

在 `create_app` 的**最末尾**（所有 `@app.get("/api/...")` 都注册完之后，`return app` 之前）加：

```python
    # 前端静态站。必须在所有 /api 路由注册之后挂，兜底路由才不会抢在 API 前面。
    dist = Path(web_dist) if web_dist is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    index = dist / "index.html"
    if index.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def _index() -> FileResponse:
            return FileResponse(index)

        @app.get("/{full_path:path}")
        def _spa(full_path: str) -> FileResponse:
            # 单页应用：前端路由直接刷新时回 index.html，交给前端路由器。
            # /api 开头的交给上面的真路由；走到这儿说明那个 API 不存在，照常 404。
            if full_path.startswith("api/"):
                raise HTTPException(404, "没有这个接口")
            candidate = dist / full_path
            if candidate.is_file() and _within(dist, candidate):
                return FileResponse(candidate)
            return FileResponse(index)

    return app
```

在模块级加一个小工具（`api.py` 已经从 `fsutil` 导入过 `ensure_within`，但那个会抛异常，这里只要布尔判断）：

```python
def _within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
```

`assets` 子目录可能不存在（比如假 dist 只有 index.html），`StaticFiles` 会在启动时报错，所以挂之前判断一下：

```python
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
```

用这一段替换上面那行无条件的 `app.mount`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_api_static.py -v`
Expected: 5 passed。

- [ ] **Step 5: 跑全量，确认兜底路由没抢掉已有接口**

Run: `uv run pytest -q`
Expected: 865 passed（原 860 + 本任务 5）。

**这一步是本任务的关键**：`@app.get("/{full_path:path}")` 是个吃掉一切的路由，如果注册位置错了会把 37 个 API 全盖住。全量测试绿才算数。

- [ ] **Step 6: Commit**

```bash
git add src/ligaotai/api.py tests/test_api_static.py
git commit -m "feat(api): 托管前端静态文件，SPA 路由刷新回 index

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: 视觉底座与应用外壳

把原型的 CSS 变量表原样搬过来，搭出「左侧窄导航 + 右侧主区」的骨架。**变量值一个都不要改**——原型的配色作者已经认过。

**Files:**
- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/base.css`
- Create: `web/src/components/AppShell.vue`
- Create: `web/src/components/NavRail.vue`
- Modify: `web/src/App.vue`
- Test: `web/src/components/NavRail.test.ts`

- [ ] **Step 1: 建 `web/src/styles/tokens.css`**

从 `docs/prototype/ligaotai-prototype.html` 第 7–42 行原样抄过来（`:root`、`@media (prefers-color-scheme: dark)` 里的 `:root:not([data-theme="light"])`、`:root[data-theme="dark"]` 三块），一个值都不改。字体那三行也照抄：

```css
:root{
  --ground:#EEF0EC; --panel:#F9FAF7; --sunk:#E5E8E2;
  --ink:#1B2130; --ink-2:#4A5163; --ink-3:#7A8192;
  --line:#D6D9D1; --line-2:#E4E6E0;
  --accent:#33508C; --accent-soft:#DFE5F2; --on-accent:#FFFFFF;
  --red:#B5372A; --red-soft:#F5DFDA;
  --green:#3A7866; --green-soft:#DAEBE4;
  --amber:#A26F1C; --amber-soft:#F2E5CD;
  --w1:#5A7BB5; --w2:#3A8A80; --w3:#9468A4;
  --serif:"Noto Serif SC","Songti SC","SimSun",serif;
  --sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#13161C; --panel:#1A1E26; --sunk:#10131862;
    --ink:#E3E5EA; --ink-2:#AEB4C0; --ink-3:#7D8494;
    --line:#2D323D; --line-2:#232832;
    --accent:#8FA7DB; --accent-soft:#243049; --on-accent:#10131A;
    --red:#E26C5D; --red-soft:#3A2225;
    --green:#6CB19D; --green-soft:#1D322C;
    --amber:#D9A650; --amber-soft:#382E1B;
    --w1:#7E9ED6; --w2:#5DB2A6; --w3:#B68BC6;
  }
}
:root[data-theme="dark"]{
  --ground:#13161C; --panel:#1A1E26; --sunk:#10131862;
  --ink:#E3E5EA; --ink-2:#AEB4C0; --ink-3:#7D8494;
  --line:#2D323D; --line-2:#232832;
  --accent:#8FA7DB; --accent-soft:#243049; --on-accent:#10131A;
  --red:#E26C5D; --red-soft:#3A2225;
  --green:#6CB19D; --green-soft:#1D322C;
  --amber:#D9A650; --amber-soft:#382E1B;
  --w1:#7E9ED6; --w2:#5DB2A6; --w3:#B68BC6;
}
```

**不引 Google Fonts。** 原型用 `<link>` 拉 Noto Serif SC，理稿台是本地离线工具，断网时会卡在字体请求上。字体栈里的 `Songti SC` / `SimSun` / `Microsoft YaHei` 是系统自带的，够用。

- [ ] **Step 2: 建 `web/src/styles/base.css`**

```css
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:14px; line-height:1.6; margin:0;
}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.num{font-variant-numeric:tabular-nums}
h1,h2,h3{font-family:var(--serif);font-weight:700;margin:0 0 .4em}
h1{font-size:22px} h2{font-size:18px} h3{font-size:15px}
a{color:var(--accent)}

.app{display:grid;grid-template-columns:188px minmax(0,1fr);min-height:100vh}
.rail{
  border-right:1px solid var(--line); padding:20px 12px;
  display:flex; flex-direction:column; gap:18px; background:var(--panel);
}
.main{padding:24px 28px;min-width:0}
```

- [ ] **Step 3: 写失败的测试 `web/src/components/NavRail.test.ts`**

导航要按 spec 第 3 章：四个常驻 + 两条子路由（按有没有待办决定显不显示）+ 底部书架/设置。

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import NavRail from './NavRail.vue'

const 基本 = { bookName: 'test', bookTitle: '归墟', pendingEntities: 0, pendingThreads: 0, contradictions: 0 }

describe('NavRail', () => {
  it('四个常驻项总是在', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: true } } })
    const t = w.text()
    for (const 项 of ['理稿流水线', '全景', '场景浏览', '设定库', '矛盾']) {
      expect(t).toContain(项)
    }
  })

  it('没有待确认项时两条子路由都不显示', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: true } } })
    expect(w.text()).not.toContain('实体确认')
    expect(w.text()).not.toContain('归线确认')
  })

  it('有待确认项时子路由出现并带数字', () => {
    const w = mount(NavRail, {
      props: { ...基本, pendingEntities: 4, pendingThreads: 2 },
      global: { stubs: { RouterLink: true } },
    })
    expect(w.text()).toContain('实体确认')
    expect(w.text()).toContain('4')
    expect(w.text()).toContain('归线确认')
    expect(w.text()).toContain('2')
  })

  it('矛盾数为 0 时不显示角标', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: true } } })
    expect(w.find('[data-test="矛盾角标"]').exists()).toBe(false)
  })

  it('二期页面不出现在导航里', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: true } } })
    expect(w.text()).not.toContain('取舍')
    expect(w.text()).not.toContain('骨架')
    expect(w.text()).not.toContain('补写')
  })
})
```

- [ ] **Step 4: 跑测试确认它失败**

Run: `cd web && npm run test`
Expected: FAIL，找不到 `./NavRail.vue`。

- [ ] **Step 5: 写 `web/src/components/NavRail.vue`**

```vue
<script setup lang="ts">
defineProps<{
  bookName: string
  bookTitle: string
  pendingEntities: number
  pendingThreads: number
  contradictions: number
}>()
</script>

<template>
  <aside class="rail">
    <div class="brand">
      <b>理稿台</b>
      <small>长篇手稿整理与成书</small>
    </div>

    <div class="book">
      <div class="t">《{{ bookTitle }}》</div>
    </div>

    <nav>
      <RouterLink class="tab" :to="`/b/${bookName}/pipeline`">
        <span>理稿流水线</span><span class="step">1–7</span>
      </RouterLink>
      <RouterLink
        v-if="pendingEntities > 0"
        class="tab sub"
        :to="`/b/${bookName}/pipeline/entities`"
      >
        <span>↳ 实体确认</span><span class="n" data-test="实体角标">{{ pendingEntities }}</span>
      </RouterLink>
      <RouterLink
        v-if="pendingThreads > 0"
        class="tab sub"
        :to="`/b/${bookName}/pipeline/threads`"
      >
        <span>↳ 归线确认</span><span class="n" data-test="归线角标">{{ pendingThreads }}</span>
      </RouterLink>

      <RouterLink class="tab" :to="`/b/${bookName}/panorama`"><span>全景</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/scenes`"><span>场景浏览</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/archive`"><span>设定库</span></RouterLink>
      <RouterLink class="tab" :to="`/b/${bookName}/contradictions`">
        <span>矛盾</span>
        <span v-if="contradictions > 0" class="n" data-test="矛盾角标">{{ contradictions }}</span>
      </RouterLink>
    </nav>

    <div class="foot">
      <RouterLink to="/">书架</RouterLink>
      ·
      <RouterLink to="/settings">设置</RouterLink>
    </div>
  </aside>
</template>

<style scoped>
.brand{padding:0 8px}
.brand b{font-family:var(--serif);font-size:22px;letter-spacing:.08em;display:block;line-height:1.2}
.brand small{color:var(--ink-3);font-size:12px}
.book{padding:10px 8px;border-top:1px solid var(--line-2);border-bottom:1px solid var(--line-2)}
.book .t{font-family:var(--serif);font-size:15px}
nav{display:flex;flex-direction:column;gap:2px}
.tab{
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:8px 10px;border-radius:6px;text-decoration:none;color:var(--ink-2);
}
.tab:hover{background:var(--sunk);color:var(--ink)}
.tab.router-link-active{background:var(--accent-soft);color:var(--accent);font-weight:500}
.tab.sub{padding:4px 10px 4px 22px;font-size:13px}
.step{color:var(--ink-3);font-size:12px}
.n{color:var(--red);font-size:12px;font-variant-numeric:tabular-nums}
.foot{margin-top:auto;padding:0 8px;color:var(--ink-3);font-size:12px}
.foot a{color:var(--ink-3);text-decoration:none}
.foot a:hover{color:var(--accent)}
</style>
```

- [ ] **Step 6: 写 `web/src/components/AppShell.vue`**

```vue
<script setup lang="ts">
import NavRail from './NavRail.vue'

defineProps<{
  bookName: string
  bookTitle: string
  pendingEntities: number
  pendingThreads: number
  contradictions: number
}>()
</script>

<template>
  <div class="app">
    <NavRail
      :book-name="bookName"
      :book-title="bookTitle"
      :pending-entities="pendingEntities"
      :pending-threads="pendingThreads"
      :contradictions="contradictions"
    />
    <main class="main"><slot /></main>
  </div>
</template>
```

- [ ] **Step 7: 改 `web/src/App.vue` 引入样式**

```vue
<script setup lang="ts">
import './styles/tokens.css'
import './styles/base.css'
</script>

<template>
  <div>理稿台</div>
</template>
```

（路由是 **Task 14** 建的，不是 Task 4——Task 4 做的是 API 客户端层。这里只保证样式加载和冒烟测试仍然过。）

- [ ] **Step 8: 跑测试**

Run: `cd web && npm run test`
Expected: 6 passed（冒烟 1 + NavRail 5）。

- [ ] **Step 9: Commit**

```bash
git add web/src/styles/ web/src/components/ web/src/App.vue
git commit -m "feat(web): 视觉底座与应用外壳，导航按有没有待办收起子路由

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: API 客户端层与类型

把 37 个接口封一遍，类型**按后端真实返回写**，不按想象写。②c 的教训：测试自己捏的假契约，测的是自己的假设（`canonical_map` 键写成中文那次，28 个测试全绿但真跑一条都归一不了）。

**Files:**
- Create: `web/src/api/client.ts`
- Create: `web/src/api/types.ts`
- Create: `web/src/api/endpoints.ts`
- Test: `web/src/api/client.test.ts`

- [ ] **Step 1: 写失败的测试 `web/src/api/client.test.ts`**

错误处理是重点：后端的错误信息在 `detail` 里，必须原样带出来给界面显示（spec 第 8 章要求「前端统一展示后端给的 detail，不吞」）。

```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { request, ApiError } from './client'

function 假响应(status: number, body: unknown, contentType = 'application/json') {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': contentType },
  })
}

afterEach(() => { vi.unstubAllGlobals() })

describe('request', () => {
  it('成功时返回解析后的 JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(假响应(200, { ok: true })))
    await expect(request('/health')).resolves.toEqual({ ok: true })
  })

  it('路径自动拼上 /api 前缀', async () => {
    const f = vi.fn().mockResolvedValue(假响应(200, {}))
    vi.stubGlobal('fetch', f)
    await request('/books')
    expect(f.mock.calls[0][0]).toBe('/api/books')
  })

  it('出错时把后端的 detail 原样带出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(500, { detail: '场景文件读不了：场景/S-0012.json' })
    ))
    await expect(request('/books/x/scenes')).rejects.toThrow('场景文件读不了：场景/S-0012.json')
  })

  it('detail 不是字符串时也不能丢信息', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(422, { detail: [{ loc: ['body', 'title'], msg: '不能为空' }] })
    ))
    const e = await request('/books').catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.detail).toContain('不能为空')
  })

  it('返回的不是 JSON 时（比如 SPA 兜底发回了 HTML）也要报出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(404, '<!doctype html><title>理稿台</title>', 'text/html')
    ))
    const e = await request('/没有这个接口').catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(404)
  })

  it('ApiError 带得上 status，界面才能区分 409 忙碌和别的错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(409, { detail: '已有任务在跑：cards（归墟）' })
    ))
    const e = await request('/books/x/steps/cards/run', { method: 'POST' }).catch((x) => x)
    expect(e.status).toBe(409)
    expect(e.detail).toContain('已有任务在跑')
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd web && npm run test -- src/api/client.test.ts`
Expected: FAIL，找不到 `./client`。

- [ ] **Step 3: 写 `web/src/api/client.ts`**

```ts
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

/** 把后端的错误信息挖出来。detail 可能是字符串、也可能是 FastAPI 的校验错误数组。 */
async function 挖错误(r: Response): Promise<string> {
  const text = await r.text()
  try {
    const body = JSON.parse(text)
    const d = body?.detail
    if (typeof d === 'string') return d
    if (d !== undefined) return JSON.stringify(d)
    return text || `HTTP ${r.status}`
  } catch {
    // 不是 JSON：可能是 SPA 兜底发回的 HTML，别把整页塞进错误信息
    return r.status === 404 ? `没有这个接口（HTTP 404）` : `HTTP ${r.status}`
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new ApiError(r.status, await 挖错误(r))
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
}
```

- [ ] **Step 4: 写 `web/src/api/types.ts`**

**以下每一条都是读源码确认过的，别改。** 拿不准就去看对应的 `src/ligaotai/*.py`。

```ts
// ---------- 步骤与书 ----------
export type StepName = 'import' | 'split' | 'dedup' | 'cards' | 'entities' | 'threads' | 'archive'
export const STEPS: StepName[] = ['import', 'split', 'dedup', 'cards', 'entities', 'threads', 'archive']
export const STEP_LABELS: Record<StepName, string> = {
  import: '导入', split: '切场景', dedup: '查重', cards: '场景卡',
  entities: '实体合并', threads: '归线排序', archive: '档案+矛盾+地图',
}
/** 能通过 /steps/{step}/run 跑的。import 走单独的 /import 接口。 */
export const RUNNABLE: StepName[] = ['split', 'dedup', 'cards', 'entities', 'threads', 'archive']

export type StepStatus = 'todo' | 'running' | 'done' | 'failed' | 'outdated'

export interface StepState {
  status: StepStatus
  updated: string | null
  /** 每步自己的统计，形状按步骤不同。里头有 cost_usd，界面一律不渲染（spec 7.3）。 */
  summary: Record<string, unknown>
}

export interface BookSummary { name: string; title: string; created: string }

export interface BookMeta {
  name: string
  schema: number
  title: string
  created: string
  settings: Record<string, unknown>
  steps: Record<StepName, StepState>
}

// ---------- 任务 ----------
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  id: string
  name: string
  book: string
  status: JobStatus
  done: number
  total: number
  message: string
  error: string
  result: Record<string, unknown> | null
  started: string
  finished: string
  cancel_requested: boolean
}

// ---------- 配置 ----------
export interface TierConfig { model: string; max_tokens: number; [k: string]: unknown }

export interface PublicConfig {
  library_dir: string
  api_base: string
  /** 打码后的 key，形如 sk-…abcd */
  api_key: string
  concurrency: number
  timeout: number
  /** 后端保留、界面不渲染（spec 7.3） */
  price_input: number
  price_output: number
  batch: TierConfig
  synth: TierConfig
  has_key: boolean
  key_from_env: boolean
  library_path: string
}

// ---------- 场景与卡 ----------
export interface SceneMeta { id: string; [k: string]: unknown }

export interface CardRow {
  id: string
  fresh: boolean
  kind: string | null
  summary: string
  problems: number
  dropped: number
}

// ---------- 实体 ----------
export type EntityType = 'person' | 'location' | 'organization'
export type EntityStatus = 'draft' | 'confirmed' | 'single'

export interface Entity {
  id: string            // E-0001
  type: EntityType
  canonical: string
  names: string[]
  status: EntityStatus
  reason: string
  scenes: string[]
}

export interface EntitiesFile { next_id: number; entities: Entity[] }

/**
 * 跨批冲突。注意：**conflicts 不在 实体.json 里**，它只出现在步骤跑完的
 * summary 中，也就是 BookMeta.steps.entities.summary.conflicts。
 * 界面要从那儿读（spec 第 5 章「conflicts 必须单独列出给作者手动处理」）。
 */
export interface EntityConflict { type: EntityType; chunk: number; names: string[] }

// ---------- 归线 ----------
export interface World {
  id: string            // W-01
  name: string
  reason: string
  status: string
  notes: string[]
  outlines: unknown[]
}

export interface SceneTime {
  /** 线内故事时间。**可能是 null**——有场景估不出时间（spec 4.5）。 */
  t: number | null
  conf: string          // 高 / 中 / 低
}

export interface ThreadEnd {
  /** 真值是「完结」/「待定」。注意不是 thread.status。 */
  state: string
  note: string
  last: string
}

export interface Thread {
  id: string            // L-001
  world: string         // W-01
  name: string
  about: string
  /**
   * 作者确认过这条线的划分没有：draft / confirmed
   * （threads.py：CONFIRMED if t.locked else DRAFT）。
   * **不是**「故事写完没有」——那个看 end.state。两者正交。
   */
  status: string
  scenes: string[]
  times: Record<string, SceneTime>
  outlines: unknown[]   // 两本真书里都是空数组（spec 4.3）
  /** 该线相对全局时间轴的偏移。全局时间 = offset + times[sid].t。 */
  offset: number
  end: ThreadEnd | null
  order_failed: boolean
}

export interface Intersection { thread: string; scene: string; main_scene: string; reason: string }

export interface Gap {
  id: string            // Q-001，每次重跑会重排，别拿它当稳定标识
  world: string
  event: string
  mentioned_in: string[]
  thread: string | null
  /** 场景编号，不是时间。两个都可能是 null（spec 4.4）。 */
  after: string | null
  before: string | null
}

export interface PendingScene { scene: string; thread: string; reason: string }
export interface UnassignedScene { scene: string; reason: string }

export interface ThreadsFile {
  next_world: number
  next_thread: number
  time_unit: string     // 实测是「年」
  main_thread: string
  main_by: string       // auto / author（不是 manual）
  worlds: World[]
  threads: Thread[]
  intersections: Intersection[]
  gaps: Gap[]
  unassigned: UnassignedScene[]
  pending: PendingScene[]
}

// ---------- 版本组 ----------
export interface VersionGroup { id: string; [k: string]: unknown }
export interface VersionsFile { params: Record<string, unknown>; groups: VersionGroup[] }

// ---------- 档案与矛盾 ----------
export interface ArchiveEntry {
  /** 生成这份档案用的模型名。跟 current_model 不一致时提示作者（spec 第 5 章）。 */
  model?: string
  outdated?: boolean
  [k: string]: unknown
}

export interface ArchiveIndex {
  current_model: string
  [k: string]: unknown
}

export interface ContradictionsFile {
  groups: unknown[]
  stats: Record<string, unknown>
}
```

`VersionGroup`、`SceneMeta`、`ArchiveEntry`、`ContradictionsFile` 的细节字段在 Task 20/22/23 用到时再照真实返回补全——**补的时候先跑一次真接口看返回，别照着想象写。**

- [ ] **Step 5: 写 `web/src/api/endpoints.ts`**

```ts
import { get, post, put } from './client'
import type {
  ArchiveIndex, BookMeta, BookSummary, CardRow, ContradictionsFile,
  EntitiesFile, Job, PublicConfig, SceneMeta, StepName, ThreadsFile, VersionsFile,
} from './types'

const b = (name: string) => `/books/${encodeURIComponent(name)}`

// 健康与配置
export const health = () => get<{ ok: boolean; version: string }>('/health')
export const getConfig = () => get<PublicConfig>('/config')
export const putConfig = (cfg: unknown) => put<PublicConfig>('/config', cfg)
export const testConfig = () => post<unknown[]>('/config/test')

// 书
export const listBooks = () => get<BookSummary[]>('/books')
export const createBook = (title: string) => post<BookMeta>('/books', { title })
export const getBook = (name: string) => get<BookMeta>(b(name))
export const importFolder = (name: string, folder: string) => post<Job>(`${b(name)}/import`, { folder })

// 步骤与任务
export const runStep = (name: string, step: StepName) => post<Job>(`${b(name)}/steps/${step}/run`)
export const currentJob = () => get<Job | null>('/jobs/current')
export const getJob = (id: string) => get<Job>(`/jobs/${id}`)
export const cancelJob = (id: string) => post<Job>(`/jobs/${id}/cancel`)

// 场景与卡
export const listScenes = (name: string, includeRemoved = false) =>
  get<SceneMeta[]>(`${b(name)}/scenes?include_removed=${includeRemoved}`)
export const getScene = (name: string, sid: string) => get<unknown>(`${b(name)}/scenes/${sid}`)
export const listCards = (name: string) => get<CardRow[]>(`${b(name)}/cards`)
export const getCard = (name: string, sid: string) => get<unknown>(`${b(name)}/cards/${sid}`)
export const regenerateCard = (name: string, sid: string) => post<Job>(`${b(name)}/cards/${sid}/regenerate`)

// 实体
export const getEntities = (name: string) => get<EntitiesFile>(`${b(name)}/entities`)
export const confirmEntities = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/entities/confirm`, { ids })
export const mergeEntities = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/entities/merge`, { ids })
export const updateEntity = (name: string, eid: string, body: unknown) => put<unknown>(`${b(name)}/entities/${eid}`, body)
export const splitEntity = (name: string, eid: string, body: unknown) => post<unknown>(`${b(name)}/entities/${eid}/split`, body)

// 归线
export const getThreads = (name: string) => get<ThreadsFile>(`${b(name)}/threads`)
export const confirmThreads = (name: string, ids: string[]) => post<unknown[]>(`${b(name)}/threads/confirm`, { ids })
export const setMainThread = (name: string, body: unknown) => put<unknown>(`${b(name)}/threads/main`, body)
export const mergeThreads = (name: string, body: unknown) => post<unknown>(`${b(name)}/threads/merge`, body)
export const renameThread = (name: string, oid: string, body: unknown) => put<unknown>(`${b(name)}/threads/${oid}/name`, body)
export const moveScenes = (name: string, tid: string, body: unknown) => post<unknown>(`${b(name)}/threads/${tid}/scenes`, body)
export const splitThread = (name: string, tid: string, body: unknown) => post<unknown>(`${b(name)}/threads/${tid}/split`, body)
export const setThreadWorld = (name: string, tid: string, body: unknown) => put<unknown>(`${b(name)}/threads/${tid}/world`, body)

// 版本组与原稿
export const getVersions = (name: string) => get<VersionsFile>(`${b(name)}/versions`)
export const setMainVersion = (name: string, gid: string, sceneId: string) =>
  put<unknown>(`${b(name)}/versions/${gid}/main`, { scene_id: sceneId })
export const getSource = (name: string, path: string) =>
  get<{ path: string; encoding: string; text: string }>(`${b(name)}/source?path=${encodeURIComponent(path)}`)

// 档案与矛盾
export const getArchiveIndex = (name: string) => get<ArchiveIndex>(`${b(name)}/archive`)
export const getArchiveBody = (name: string, kind: 'thread' | 'world', oid: string) =>
  get<{ id: string; body: string }>(`${b(name)}/archive/${kind}/${encodeURIComponent(oid)}`)
export const getContradictions = (name: string) => get<ContradictionsFile>(`${b(name)}/contradictions`)
export const rerunArchive = (name: string, body: unknown) => post<unknown>(`${b(name)}/archive/rerun`, body)
```

- [ ] **Step 6: 跑测试与 typecheck**

```bash
cd web && npm run test && npm run typecheck
```

Expected: 12 passed（冒烟 1 + NavRail 5 + client 6），typecheck 无报错。

- [ ] **Step 7: Commit**

```bash
git add web/src/api/
git commit -m "feat(web): API 客户端与类型，类型按后端真实返回写

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: 全局任务 store

后端 `JobRunner` **全局只允许一个任务在跑**，撞上会 409。前端据此做一个全局 store：轮询当前任务、暴露「忙不忙」，所有会触发任务或会跟运行中任务打架的按钮统一靠它禁用。

这一条同时解决待办里那句「查重任务正在运行时作者点『设为主版本』，有极小概率被查重结果覆盖」——不在每个页面各写一遍。

**Files:**
- Create: `web/src/stores/job.ts`
- Test: `web/src/stores/job.test.ts`

- [ ] **Step 1: 写失败的测试 `web/src/stores/job.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useJobStore } from './job'
import * as api from '@/api/endpoints'
import type { Job } from '@/api/types'

function 造任务(over: Partial<Job> = {}): Job {
  return {
    id: 'j1', name: 'cards', book: '归墟', status: 'running',
    done: 3, total: 10, message: '', error: '', result: null,
    started: '2026-09-21T10:00:00', finished: '', cancel_requested: false,
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('job store', () => {
  it('轮询到运行中的任务时 busy 为真', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务())
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)
    expect(s.current?.done).toBe(3)
  })

  it('没有任务时 busy 为假', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(null)
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(false)
  })

  it('任务已结束时 busy 为假', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'done' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(false)
  })

  it('queued 也算忙', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'queued' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)
  })

  it('任务从运行变成完成时触发一次 onFinish 回调', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)

    await s.refresh()
    expect(回调).not.toHaveBeenCalled()

    spy.mockResolvedValue(造任务({ status: 'done', done: 10 }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)

    // 再轮询一次，同一个任务不能重复触发
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
  })

  it('任务失败也算结束，同样触发 onFinish', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)
    await s.refresh()
    spy.mockResolvedValue(造任务({ status: 'failed', error: '接口拒绝了请求（401）' }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
    expect(s.current?.error).toContain('401')
  })

  it('轮询出错不能把 busy 卡死在真', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)

    spy.mockRejectedValue(new Error('后端断了'))
    await s.refresh()
    // 连不上后端时不知道到底忙不忙，保守起见保持上次状态，但要把错误露出来
    expect(s.pollError).toContain('后端断了')
  })

  it('start 之后每秒轮询一次，stop 之后不再轮询', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(null)
    const s = useJobStore()
    s.start()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)
    const 次数 = spy.mock.calls.length
    expect(次数).toBeGreaterThanOrEqual(2)

    s.stop()
    await vi.advanceTimersByTimeAsync(3000)
    expect(spy.mock.calls.length).toBe(次数)
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd web && npm run test -- src/stores/job.test.ts`
Expected: FAIL，找不到 `./job`。

- [ ] **Step 3: 写 `web/src/stores/job.ts`**

```ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { currentJob } from '@/api/endpoints'
import type { Job } from '@/api/types'

const 轮询间隔 = 1000
const 未结束 = new Set<Job['status']>(['queued', 'running'])

export const useJobStore = defineStore('job', () => {
  const current = ref<Job | null>(null)
  const pollError = ref('')
  let timer: ReturnType<typeof setInterval> | null = null
  const 回调组: Array<(job: Job) => void> = []
  /** 已经播报过「结束了」的任务 id，防止重复触发。 */
  const 已播报 = new Set<string>()

  const busy = computed(() => !!current.value && 未结束.has(current.value.status))

  async function refresh(): Promise<void> {
    try {
      const job = await currentJob()
      pollError.value = ''
      const 前一个 = current.value
      current.value = job
      if (job && !未结束.has(job.status) && !已播报.has(job.id)) {
        // 只在「本来在跑、现在不跑了」时播报；一进来就看到已完成的任务不播报
        if (前一个 && 前一个.id === job.id && 未结束.has(前一个.status)) {
          已播报.add(job.id)
          for (const fn of 回调组) fn(job)
        }
      }
    } catch (e) {
      // 连不上后端时保持上次的 busy 状态（不知道到底忙不忙，保守），把错误露出来
      pollError.value = e instanceof Error ? e.message : String(e)
    }
  }

  function onFinish(fn: (job: Job) => void): void {
    回调组.push(fn)
  }

  function start(): void {
    if (timer !== null) return
    void refresh()
    timer = setInterval(() => { void refresh() }, 轮询间隔)
  }

  function stop(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  return { current, pollError, busy, refresh, onFinish, start, stop }
})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test -- src/stores/job.test.ts`
Expected: 8 passed。

- [ ] **Step 5: 跑全量前端测试和 typecheck**

```bash
cd web && npm run test && npm run typecheck
```

Expected: 20 passed。

- [ ] **Step 6: Commit**

```bash
git add web/src/stores/
git commit -m "feat(web): 全局任务 store，轮询进度并统一控制忙碌禁用

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 里程碑 A 完成检查

- [ ] `cd web && npm run test` → 20 passed
- [ ] `cd web && npm run typecheck` → 无报错
- [ ] `uv run pytest -q` → 865 passed
- [ ] 手动验证一次：一个终端跑 `uv run python -m ligaotai`，另一个跑 `cd web && npm run dev`，浏览器开 `http://localhost:5173`，页面能出「理稿台」且 devtools 里 `fetch('/api/health')` 能拿到 `{ok:true}`。

---

## Task 6: `GET /scenes` 报出错的文件名

待办原文：「某个场景文件被改坏时，`GET /scenes` 只返回 500，没把出错的文件名告诉界面。」

**Files:**
- Modify: `src/ligaotai/scenes.py`（`load_scenes`）
- Modify: `src/ligaotai/api.py`（`scenes` 路由）
- Test: `tests/test_api_errors.py`

- [ ] **Step 1: 先读现状**

```bash
uv run python -c "import inspect, ligaotai.scenes as s; print(inspect.getsource(s.load_scenes))"
```

把真实实现看清楚再动。下面的代码是按「`load_scenes` 遍历 `场景/` 下的 json 并逐个解析」写的，如果实际结构不同，按实际的改，并在报告里说明。

- [ ] **Step 2: 写失败的测试 `tests/test_api_errors.py`**

```python
"""手改坏的文件不能让接口返回裸 500 —— 要把出错的文件名和原因告诉界面。

程序自己写的文件不会长这样，这几条只影响手改和外来文件。
"""

import json

import pytest
from fastapi.testclient import TestClient

from ligaotai.api import create_app
from ligaotai.book import create_book


@pytest.fixture
def 客户端和书(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"library_dir": str(lib)}), encoding="utf-8")
    b = create_book(lib, "测试书")
    app = create_app(app_dir=tmp_path, web_dist=tmp_path / "不存在")
    return TestClient(app), b


def test_场景文件坏了要报出是哪个文件(客户端和书):
    c, b = 客户端和书
    b.scenes_dir.mkdir(parents=True, exist_ok=True)
    (b.scenes_dir / "S-0012.json").write_text("{这不是合法 JSON", encoding="utf-8")

    r = c.get("/api/books/测试书/scenes")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "S-0012" in detail, f"出错的文件名没告诉界面：{detail}"


def test_场景目录正常时照常返回(客户端和书):
    c, _ = 客户端和书
    r = c.get("/api/books/测试书/scenes")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 3: 跑测试确认它失败**

Run: `uv run pytest tests/test_api_errors.py -v`
Expected: `test_场景文件坏了要报出是哪个文件` FAIL——detail 里没有文件名（当前是 `JSONDecodeError` 的原始信息或一个裸 500）。

- [ ] **Step 4: 改代码**

在 `src/ligaotai/scenes.py` 定义一个带文件名的异常：

```python
class BrokenSceneFile(Exception):
    """某个场景文件读不出来。带上文件名，好让界面说清是哪一个。"""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"场景文件读不了：{path.name}（{reason}）")
```

`load_scenes` 里逐个文件解析的地方包上：

```python
        try:
            data = read_json(p)
        except json.JSONDecodeError as e:
            raise BrokenSceneFile(p, f"不是合法 JSON，第 {e.lineno} 行") from e
        except OSError as e:
            raise BrokenSceneFile(p, str(e)) from e
```

在 `src/ligaotai/api.py` 的 `scenes` 路由里接住：

```python
    @app.get("/api/books/{name}/scenes")
    def scenes(name: str, include_removed: bool = False) -> list:
        b = get_book(name)
        try:
            all_scenes = load_scenes(b)
        except BrokenSceneFile as e:
            raise HTTPException(500, str(e))
        return [s.meta() for s in all_scenes if include_removed or not s.removed]
```

记得在 `api.py` 顶部 import `BrokenSceneFile`。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_api_errors.py -v`
Expected: 2 passed。

- [ ] **Step 6: 跑全量**

Run: `uv run pytest -q`
Expected: 867 passed。`load_scenes` 被很多地方用，**全量绿才算数**——新异常可能让别的调用方炸。

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/scenes.py src/ligaotai/api.py tests/test_api_errors.py
git commit -m "fix(api): 场景文件坏了要报出是哪个文件，不再是裸 500

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: 卡片列表与实体接口的坏文件处理

待办原文：「卡文件结构被手改坏（`dropped` 里某项是 null、`card` 是字符串）时，卡片列表接口整体 500；实体.json 不是合法 JSON 时 `GET /entities` 500、confirm 等操作 400 且 detail 是原始 JSONDecodeError；实体条目缺字段的 KeyError 也会被报成『没有这个实体』404。」

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_errors.py`（接着上一个任务的文件写）

- [ ] **Step 1: 追加失败的测试**

```python
def test_卡文件被改坏时报出是哪张卡(客户端和书):
    c, b = 客户端和书
    b.scenes_dir.mkdir(parents=True, exist_ok=True)
    # 先造一个正常的场景，卡片接口才会去读卡
    ...  # 按 scenes.py 的真实落盘格式写一个场景，见 Step 2

    b.cards_dir.mkdir(parents=True, exist_ok=True)
    (b.cards_dir / "S-0001.json").write_text(json.dumps({"card": "本该是个对象"}), encoding="utf-8")

    r = c.get("/api/books/测试书/cards")
    assert r.status_code == 500
    assert "S-0001" in r.json()["detail"]


def test_实体文件不是合法JSON时给得出人话(客户端和书):
    c, b = 客户端和书
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text("{坏掉的", encoding="utf-8")

    r = c.get("/api/books/测试书/entities")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "实体" in detail
    assert "JSONDecodeError" not in detail, "别把 Python 异常类名甩给界面"


def test_实体条目缺字段不能报成404(客户端和书):
    c, b = 客户端和书
    b.entities_path.parent.mkdir(parents=True, exist_ok=True)
    b.entities_path.write_text(
        json.dumps({"next_id": 2, "entities": [{"id": "E-0001"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    r = c.put("/api/books/测试书/entities/E-0001", json={"canonical": "张三"})
    assert r.status_code != 404, "缺字段是文件坏了，不是『没有这个实体』"
    assert r.status_code == 500
    assert "E-0001" in r.json()["detail"]
```

- [ ] **Step 2: 先把场景的真实落盘格式弄清楚**

测试里那个 `...` 要填成真实格式。跑：

```bash
uv run python -c "import inspect, ligaotai.scenes as s; print(inspect.getsource(s))" > /tmp/scenes_src.txt
```

（Windows 上写到 `%TEMP%` 或 scratchpad，别用 `/tmp`。）读出 `Scene` 的落盘字段，照着造一个最小的合法场景文件。**已有测试里多半已经有造场景的 helper**，先搜 `tests/conftest.py`：

```bash
grep -n "场景\|scene" tests/conftest.py | head -30
```

有现成的 fixture 就直接用，别重复造轮子。

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_api_errors.py -v`
Expected: 三个新测试 FAIL。

- [ ] **Step 4: 改 `api.py`**

加一个统一的包装，别在每个路由里各写一遍 try：

```python
def _读坏了(what: str, detail: str) -> HTTPException:
    return HTTPException(500, f"{what}读不了：{detail}。这个文件多半被手动改过或来自别处。")
```

`cards` 路由里逐条读卡的地方包上，出错时带上场景编号：

```python
            try:
                card = (r.get("card") if r else None) or {}
                problems = (r.get("problems") if r else None) or []
                dropped = (r.get("dropped") if r else None) or {}
                n_dropped = len(dropped.get("facts") or []) + len(dropped.get("names") or [])
            except AttributeError as e:
                raise _读坏了(f"场景卡 {s.id}", str(e))
```

`entities` 路由：

```python
    @app.get("/api/books/{name}/entities")
    def entities(name: str) -> dict:
        b = get_book(name)
        try:
            return read_json(b.entities_path, {"entities": []})
        except json.JSONDecodeError as e:
            raise _读坏了("实体.json", f"不是合法 JSON，第 {e.lineno} 行")
```

`entity_op`（confirm / merge / update / split 共用的包装）里，把 `KeyError` 区分开：**找不到 id** 才是 404，**条目缺字段**是 500。

```python
def entity_op(fn):
    try:
        return fn()
    except ent.NoSuchEntity as e:       # 如果 entities.py 里没有这个异常，就新建一个
        raise HTTPException(404, str(e))
    except KeyError as e:
        raise HTTPException(500, f"实体条目缺字段 {e}，文件多半被手动改过。")
    except json.JSONDecodeError as e:
        raise _读坏了("实体.json", f"不是合法 JSON，第 {e.lineno} 行")
```

**先读 `entity_op` 的真实实现再改**——它现在怎么把异常翻成 404 的，决定了这里要改哪几行：

```bash
uv run python -c "import inspect, ligaotai.api as a; print(inspect.getsource(a))" | grep -n -A12 "def entity_op"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_api_errors.py -v`
Expected: 5 passed。

- [ ] **Step 6: 跑全量**

Run: `uv run pytest -q`
Expected: 870 passed。

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/api.py tests/test_api_errors.py
git commit -m "fix(api): 卡片和实体接口遇到坏文件时给出具体原因

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: `safe_name` 的边界输入返回 404 而不是 500

待办原文：「`safe_name("..")` / `"."` / `"   "` 会让接口裸 500 —— 这三种输入会让 `safe_name` 抛 `ValueError("名字不能为空")`，`archive_body` 等接口没接这个异常，返回的是 500 而不是 404。」

**Files:**
- Modify: `src/ligaotai/api.py`
- Test: `tests/test_api_errors.py`

- [ ] **Step 1: 追加失败的测试**

```python
@pytest.mark.parametrize("坏名字", ["..", ".", "   "])
def test_档案接口遇到边界名字返回404(客户端和书, 坏名字):
    c, _ = 客户端和书
    r = c.get(f"/api/books/测试书/archive/thread/{坏名字}")
    assert r.status_code == 404, f"{坏名字!r} 应该是 404 不是 {r.status_code}"


@pytest.mark.parametrize("坏名字", ["..", ".", "   "])
def test_建书遇到边界名字返回400(坏名字, tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"library_dir": str(lib)}), encoding="utf-8")
    c = TestClient(create_app(app_dir=tmp_path, web_dist=tmp_path / "不存在"))
    r = c.post("/api/books", json={"title": 坏名字})
    assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api_errors.py -v -k 边界名字`
Expected: 档案那三个 FAIL（500 而不是 404）。建书那三个可能已经通过（`new_book` 已经接了 `ValueError`）——**已经通过的就是回归测试，留着**。

- [ ] **Step 3: 改 `archive_body` 路由**

```python
    @app.get("/api/books/{name}/archive/{kind}/{oid}")
    def archive_body(name: str, kind: str, oid: str) -> dict:
        b = get_book(name)
        if kind not in ("thread", "world"):
            raise HTTPException(400, "kind 只能是 thread 或 world")
        base = b.thread_archive_dir if kind == "thread" else b.world_archive_dir
        try:
            path = ensure_within(base, base / f"{safe_name(oid)}.md")
        except ValueError:
            raise HTTPException(404, "没有这份档案")
        if not path.exists():
            raise HTTPException(404, "没有这份档案")
        return {"id": oid, "body": path.read_text(encoding="utf-8")}
```

- [ ] **Step 4: 搜一遍还有谁在路由里直接调 `safe_name`**

```bash
grep -n "safe_name" src/ligaotai/api.py
```

每一处都照上面的方式接住 `ValueError`。**别漏**——待办里说的是「`archive_body` 等接口」，「等」字说明当时没数全。

- [ ] **Step 5: 跑测试与全量**

```bash
uv run pytest tests/test_api_errors.py -v && uv run pytest -q
```

Expected: 11 passed / 876 passed。

- [ ] **Step 6: Commit**

```bash
git add src/ligaotai/api.py tests/test_api_errors.py
git commit -m "fix(api): safe_name 的边界输入返回 404 而不是裸 500

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: 场景卡单卡重做不要盖掉「已暂停」

待办原文：「场景卡步骤被暂停后，步骤状态是 failed、`summary.error` 是『已暂停：…』；这之后如果单独重做某一张卡，步骤状态仍保持 failed（`only` 模式不改状态），但 summary 会被换成这一张卡的统计，『已暂停』的原始信息没了。作者看到的是一个『失败』的步骤配一张看起来全部成功的 summary。」

**Files:**
- Modify: `src/ligaotai/cards.py`
- Test: `tests/test_cards.py`

- [ ] **Step 1: 先看清 `only` 模式现在怎么写 summary**

```bash
uv run python -c "import inspect, ligaotai.cards as c; print(inspect.getsource(c.run_cards))" > %TEMP%\cards_src.txt
```

（Windows：写到 `%TEMP%` 或 scratchpad，再用 Read 看，别指望终端里的中文。）

找到 `only` 参数影响状态/summary 写入的那几行。

- [ ] **Step 2: 写失败的测试，追加到 `tests/test_cards.py`**

```python
def test_暂停后单卡重做不覆盖已暂停的summary(tmp_path):
    """only 模式下，如果步骤本来不是 done，保留原来的 summary 和 error。

    否则作者看到的是「失败」的步骤配一张全部成功的 summary，
    「已暂停」这条信息就没了。
    """
    b = create_book(tmp_path, "测试书")
    # 造出「被暂停过」的状态
    b.set_step("cards", "failed", {"error": "已暂停：做完 12 张，还剩 88 张"})
    before = b.load()["steps"]["cards"]
    assert before["status"] == "failed"

    # 单卡重做（only 模式），用假 client 让它「成功」
    ...  # 按 tests/test_cards.py 里已有的假 client fixture 来，见 Step 3

    after = b.load()["steps"]["cards"]
    assert after["status"] == "failed", "only 模式不该改步骤状态"
    assert "已暂停" in str(after["summary"].get("error", "")), \
        f"「已暂停」的信息被单卡统计盖掉了：{after['summary']}"
```

- [ ] **Step 3: 把 `...` 填成真实调用**

`tests/test_cards.py` 里已经有跑 `run_cards` 的测试和假 client。先看：

```bash
grep -n "def test_\|假\|fake\|client" tests/test_cards.py | head -30
```

照最接近的那个测试的写法调 `run_cards(b, 假client, only=["S-0001"])`。

- [ ] **Step 4: 跑测试确认失败**

Run: `uv run pytest tests/test_cards.py -k 暂停后单卡重做 -v`
Expected: FAIL，`after["summary"]` 里没有 `error`。

- [ ] **Step 5: 改 `cards.py`**

在写 summary 的地方加判断：

```python
    # only 模式（单卡重做）：步骤本来不是 done 的话，保留原来的 summary/error。
    # 不然「已暂停：做完 12 张，还剩 88 张」会被这一张卡的统计盖掉，
    # 作者看到的是一个 failed 的步骤配一张全部成功的 summary。
    if only and book.load()["steps"]["cards"]["status"] != "done":
        return result          # 只返回结果，不写 summary
```

具体写在哪一行按 Step 1 看到的真实结构定。**关键是判断条件**：`only` 为真 **且** 原状态不是 done。

- [ ] **Step 6: 跑测试与全量**

```bash
uv run pytest tests/test_cards.py -v && uv run pytest -q
```

Expected: 全绿，877 passed。

- [ ] **Step 7: Commit**

```bash
git add src/ligaotai/cards.py tests/test_cards.py
git commit -m "fix(cards): 暂停后单卡重做保留「已暂停」的 summary

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 里程碑 B 完成检查

- [ ] `uv run pytest -q` → 877 passed
- [ ] `grep -n "safe_name" src/ligaotai/api.py` 的每一处都接住了 `ValueError`
- [ ] 四条待办逐条对照 `docs/已知问题与待办.md`，做完的在文档里划掉或移到「已解决」

---

## Task 10: 从真书导出泳道图 fixture

三个纯函数要拿真数据测。`data/` 在 `.gitignore` 里，测试不能依赖它，所以导出一份瘦身样本提交进仓库。

**样本必须原样保留这几个真实形态**（它们各自对应一个会写错的地方）：

| 形态 | 在哪 | 不保留就会怎样 |
|---|---|---|
| `offset` 相差三个数量级 | 西游记 0 / -871.8 / -19 | 断轴根本不会触发，测了等于没测 |
| `times[sid].t` 有 `null` | 雪月梅 L-001 有一个 | 排除 null 的逻辑没被测到 |
| `gaps` 只有 `before` 没有 `after` | 雪月梅 41 个 | 定位退化逻辑没被测到 |
| `gaps` 两端都没有 | 雪月梅 6 个 | orphan 分流没被测到 |
| `status` 全是 `draft`、完没完在 `end.state` | 两本的线都没被确认过 | 会拿错字段判完没完；且 fixture 覆盖不到 `confirmed` |
| `outlines` 是空数组 | 两本都是 | 会画一个永远为空的图例 |

**Files:**
- Create: `tools/export_lane_fixtures.py`
- Create: `web/src/components/__fixtures__/xiyouji-threads.json`
- Create: `web/src/components/__fixtures__/xueyuemei-threads.json`
- Test: `tests/test_tools_scripts.py`（已存在，加一条）

- [ ] **Step 1: 写 `tools/export_lane_fixtures.py`**

```python
"""把验收书库里的归线结果瘦身成前端测试用的 fixture。

长文本截断到 60 字（结构和数值一个不动），体积小下来但真实形态全留着。
用法：uv run python tools/export_lane_fixtures.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
默认源 = REPO / "data" / "验收书库"
默认目标 = REPO / "web" / "src" / "components" / "__fixtures__"

来源 = {
    "xiyouji-threads.json": "验收-实体-乱稿-西游记-s7",
    "xueyuemei-threads.json": "验收-实体-乱稿-雪月梅-c-s7",
}

长文本字段 = ("about", "reason", "note", "event", "name")
截断到 = 60


def 瘦身(obj):
    if isinstance(obj, dict):
        return {k: (截断(v) if k in 长文本字段 and isinstance(v, str) else 瘦身(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [瘦身(x) for x in obj]
    return obj


def 截断(s: str) -> str:
    return s if len(s) <= 截断到 else s[:截断到] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description="导出泳道图 fixture")
    ap.add_argument("--src", type=Path, default=默认源)
    ap.add_argument("--out", type=Path, default=默认目标)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    缺的 = []
    for 文件名, 书名 in 来源.items():
        src = args.src / 书名 / "世界与支线.json"
        if not src.exists():
            缺的.append(str(src))
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        out = args.out / 文件名
        out.write_text(
            json.dumps(瘦身(data), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"{文件名}: {len(data['threads'])} 条线, {len(data.get('gaps') or [])} 个缺口, "
              f"{out.stat().st_size // 1024} KB")
    if 缺的:
        print("这些源文件不在（验收书库没跑过就会这样，不算错）：")
        for s in 缺的:
            print("  " + s)
        return 1 if len(缺的) == len(来源) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 跑一次导出**

```bash
uv run python tools/export_lane_fixtures.py
```

Expected: 打出两行，形如 `xiyouji-threads.json: 3 条线, 42 个缺口, NN KB`。

- [ ] **Step 3: 核对导出的样本真的保留了那六个形态**

**别跳过这一步。** 写一个一次性脚本（写成 `.py` 文件再跑，别用 `python -c` 传中文）核对：

```python
import json, pathlib
base = pathlib.Path("web/src/components/__fixtures__")
报告 = []
for f in ["xiyouji-threads.json", "xueyuemei-threads.json"]:
    d = json.loads((base / f).read_text(encoding="utf-8"))
    offsets = [t.get("offset") for t in d["threads"]]
    有null = any(v.get("t") is None for t in d["threads"] for v in (t.get("times") or {}).values())
    只有before = sum(1 for g in d["gaps"] if not g.get("after") and g.get("before"))
    都没有 = sum(1 for g in d["gaps"] if not g.get("after") and not g.get("before"))
    状态 = {t.get("status") for t in d["threads"]}
    大纲 = all(not t.get("outlines") for t in d["threads"])
    报告.append(f"{f}: offsets={offsets} t有null={有null} 只有before={只有before} "
                f"都没有={都没有} status={状态} outlines全空={大纲}")
pathlib.Path("fixture核对.txt").write_text("\n".join(报告), encoding="utf-8")
```

然后 Read 那个文件。期望：
- `xiyouji`: `offsets=[0, -871.8, -19]`、`status={'draft'}`、`outlines全空=True`
- `xueyuemei`: `t有null=True`、`只有before=41`、`都没有=6`

**任何一条对不上就是导出脚本瘦身瘦过头了**，回去改，别将就。核对完删掉临时文件。

- [ ] **Step 4: 给 `tests/test_tools_scripts.py` 加一条**

先看这个文件现在怎么写的：

```bash
uv run python -c "print(open('tests/test_tools_scripts.py', encoding='utf-8').read()[:2000])"
```

照它的模式加：脚本要能 `uv run python tools/export_lane_fixtures.py --help` 跑起来不报错。

- [ ] **Step 5: 跑测试**

Run: `uv run pytest tests/test_tools_scripts.py -v`
Expected: 全绿。

- [ ] **Step 6: Commit（fixture 要提交进仓库）**

```bash
git add tools/export_lane_fixtures.py web/src/components/__fixtures__/ tests/test_tools_scripts.py
git commit -m "feat(web): 从真书导出泳道图 fixture，保留六个会写错的真实形态

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: 断轴成轴（`axis.ts`）

spec 4.2。这是三个纯函数里最要紧的一个——西游记真数据上，它决定主线是占 1.6% 还是 28%。

**Files:**
- Create: `web/src/lib/axis.ts`
- Test: `web/src/lib/axis.test.ts`

- [ ] **Step 1: 写失败的测试 `web/src/lib/axis.test.ts`**

下面每个数字都是拿真 fixture 手算过的，**不要改断言去迁就实现**。

```ts
import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import 西游记 from '@/components/__fixtures__/xiyouji-threads.json'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import type { ThreadsFile } from '@/api/types'

/** 把一本书的全部场景摊成全局时间点（t 为 null 的排除）。 */
function 全局点(d: ThreadsFile): number[] {
  const out: number[] = []
  for (const t of d.threads) {
    const off = t.offset ?? 0
    for (const v of Object.values(t.times ?? {})) {
      if (v?.t !== null && v?.t !== undefined) out.push(off + v.t)
    }
  }
  return out
}

describe('buildAxis 边界', () => {
  it('一个点都没有时返回 null（调用方出空态）', () => {
    expect(buildAxis([])).toBeNull()
  })

  it('全部点相同时给一个满宽的区块', () => {
    const a = buildAxis([5, 5, 5])!
    expect(a.blocks).toHaveLength(1)
    expect(a.breaks).toHaveLength(0)
    expect(a.x(5)).toBeCloseTo(0, 5)
  })

  it('单个点', () => {
    const a = buildAxis([3])!
    expect(a.blocks).toHaveLength(1)
    expect(a.lo).toBe(3)
    expect(a.hi).toBe(3)
  })

  it('间隙没超阈值时不断轴', () => {
    // 跨度 100，阈值 5；最大间隙 4，不该断
    const a = buildAxis([0, 4, 8, 50, 54, 100])!
    expect(a.breaks).toHaveLength(0)
  })

  it('间隙恰好等于阈值时不断轴（判据是严格大于）', () => {
    // 跨度 100，阈值 5，间隙正好 5
    const a = buildAxis([0, 5, 100])!
    const 大间隙 = a.breaks.filter((b) => b.years === 5)
    expect(大间隙).toHaveLength(0)
  })

  it('间隙刚超过阈值就断', () => {
    const a = buildAxis([0, 5.1, 100])!
    expect(a.breaks.length).toBeGreaterThanOrEqual(1)
  })

  it('x 单调不减', () => {
    const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!
    const 点 = [...new Set(全局点(西游记 as unknown as ThreadsFile))].sort((p, q) => p - q)
    for (let i = 1; i < 点.length; i++) {
      expect(a.x(点[i])).toBeGreaterThanOrEqual(a.x(点[i - 1]) - 1e-9)
    }
  })

  it('最左的点在 0%，最右的点在 100%', () => {
    const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!
    expect(a.x(a.lo)).toBeCloseTo(0, 4)
    expect(a.x(a.hi)).toBeCloseTo(100, 4)
  })
})

describe('buildAxis 在《西游记》真数据上', () => {
  const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!

  it('范围是 -871.8 ~ 14', () => {
    expect(a.lo).toBeCloseTo(-871.8, 4)
    expect(a.hi).toBeCloseTo(14, 4)
  })

  it('切出 3 个区块、2 个断口', () => {
    expect(a.blocks).toHaveLength(3)
    expect(a.breaks).toHaveLength(2)
  })

  it('两个断口分别跨掉 360 年和 480.7 年', () => {
    expect(a.breaks[0].years).toBeCloseTo(360, 1)
    expect(a.breaks[1].years).toBeCloseTo(480.7, 1)
  })

  it('主线从 1.6% 变成 28.7%（这是整个断轴的意义）', () => {
    // L-001 全局 0 ~ 14
    const 宽 = a.x(14) - a.x(0)
    expect(宽).toBeGreaterThan(25)
    expect(宽).toBeCloseTo(28.67, 1)
    // 对照：等比例轴下只有 14/885.8 = 1.58%
    expect(14 / 885.8 * 100).toBeCloseTo(1.58, 1)
  })

  it('单点区块拿到的是最小宽度 1%', () => {
    const 第一块 = a.blocks[0]
    expect(第一块.t0).toBeCloseTo(-871.8, 2)
    expect(第一块.t1).toBeCloseTo(-871.8, 2)
    expect(第一块.x1 - 第一块.x0).toBeCloseTo(1, 4)
  })

  it('没退化成等比例轴', () => {
    expect(a.degraded).toBe(false)
  })
})

describe('buildAxis 在《雪月梅》真数据上', () => {
  const a = buildAxis(全局点(雪月梅 as unknown as ThreadsFile))!

  it('范围 -10 ~ 6.6，2 个区块 1 个断口', () => {
    expect(a.lo).toBeCloseTo(-10, 4)
    expect(a.hi).toBeCloseTo(6.6, 4)
    expect(a.blocks).toHaveLength(2)
    expect(a.breaks).toHaveLength(1)
  })

  it('第二个区块占 96%', () => {
    const b = a.blocks[1]
    expect(b.x0).toBeCloseTo(4, 2)
    expect(b.x1).toBeCloseTo(100, 2)
  })
})

describe('buildAxis 参数', () => {
  it('breakRatio 调大后断口变少', () => {
    const 点 = 全局点(西游记 as unknown as ThreadsFile)
    const 松 = buildAxis(点, { breakRatio: 0.6 })!
    expect(松.breaks.length).toBeLessThan(2)
  })

  it('区块碎到放不下时退回等比例轴并标记 degraded', () => {
    // 造 40 个彼此远离的点：40 个区块保底 40% + 39 个断口 117% > 100%
    const 点 = Array.from({ length: 40 }, (_, i) => i * 1000)
    const a = buildAxis(点)!
    expect(a.x(点[0])).toBeCloseTo(0, 4)
    expect(a.x(点[39])).toBeCloseTo(100, 4)
    // 要么把断口压窄放下了，要么退化；两种都可以，但不能算出超过 100% 的坐标
    for (const p of 点) {
      expect(a.x(p)).toBeGreaterThanOrEqual(-1e-6)
      expect(a.x(p)).toBeLessThanOrEqual(100 + 1e-6)
    }
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd web && npm run test -- src/lib/axis.test.ts`
Expected: FAIL，找不到 `./axis`。

- [ ] **Step 3: 写 `web/src/lib/axis.ts`**

```ts
/** 断轴成轴：把「一个场景都没有的长空白」压成固定宽度的断口。spec 4.2。 */

export interface AxisBlock {
  /** 这一块覆盖的时间范围 */
  t0: number
  t1: number
  /** 对应的百分比范围 [0,100] */
  x0: number
  x1: number
}

export interface AxisBreak {
  /** 这个断口跨掉了多少年（要显示给作者，不然他以为两段是挨着的） */
  years: number
  x0: number
  x1: number
}

export interface Axis {
  lo: number
  hi: number
  blocks: AxisBlock[]
  breaks: AxisBreak[]
  /** 时间 → 百分比 */
  x: (t: number) => number
  /** 区块太碎放不下、退回了等比例轴 */
  degraded: boolean
}

export interface AxisOptions {
  /** 间隙超过「全局跨度 × 它」才算断口。默认 0.05 */
  breakRatio?: number
  /** 每个断口占的百分比。默认 3 */
  breakWidth?: number
  /** 每个区块的保底百分比。默认 1 */
  minBlock?: number
}

const 默认 = { breakRatio: 0.05, breakWidth: 3, minBlock: 1 }

/** 时间点为空时返回 null——调用方据此出空态，不要画一张空图。 */
export function buildAxis(points: number[], opts: AxisOptions = {}): Axis | null {
  const { breakRatio, breakWidth, minBlock } = { ...默认, ...opts }
  const pts = [...new Set(points)].sort((a, b) => a - b)
  if (pts.length === 0) return null

  const lo = pts[0]
  const hi = pts[pts.length - 1]
  const span = hi - lo

  // 全部点重合：一个区块占满
  if (span === 0) {
    const blocks: AxisBlock[] = [{ t0: lo, t1: hi, x0: 0, x1: 100 }]
    return { lo, hi, blocks, breaks: [], x: () => 0, degraded: false }
  }

  // 切区块：间隙「严格大于」阈值才断
  const 阈值 = span * breakRatio
  const ranges: Array<[number, number]> = []
  const 间隙: number[] = []
  let start = pts[0]
  for (let i = 1; i < pts.length; i++) {
    const d = pts[i] - pts[i - 1]
    if (d > 阈值) {
      ranges.push([start, pts[i - 1]])
      间隙.push(d)
      start = pts[i]
    }
  }
  ranges.push([start, hi])

  // 宽度分配：先扣断口和保底，剩下的按各区块跨度比例分
  let bw = breakWidth
  const 固定 = () => 间隙.length * bw + ranges.length * minBlock
  let degraded = false
  if (固定() >= 100) {
    // 断口按比例压窄，最小不低于 1%
    const 可给断口 = Math.max(0, 100 - ranges.length * minBlock)
    bw = 间隙.length > 0 ? Math.max(1, (可给断口 * 0.4) / 间隙.length) : 0
  }
  if (固定() >= 100) {
    // 还是放不下：退回等比例轴
    const blocks: AxisBlock[] = [{ t0: lo, t1: hi, x0: 0, x1: 100 }]
    return {
      lo, hi, blocks, breaks: [], degraded: true,
      x: (t: number) => clamp(((t - lo) / span) * 100),
    }
  }

  const 余 = 100 - 固定()
  const 总跨度 = ranges.reduce((s, [a, b]) => s + (b - a), 0)
  const blocks: AxisBlock[] = []
  const breaks: AxisBreak[] = []
  let x = 0
  ranges.forEach(([a, b], i) => {
    const share = 总跨度 > 0 ? ((b - a) / 总跨度) * 余 : 余 / ranges.length
    const w = minBlock + share
    blocks.push({ t0: a, t1: b, x0: x, x1: x + w })
    x += w
    if (i < 间隙.length) {
      breaks.push({ years: 间隙[i], x0: x, x1: x + bw })
      x += bw
    }
  })
  // 浮点累计误差：把最后一块钉到 100
  if (blocks.length > 0) blocks[blocks.length - 1].x1 = 100

  function x映射(t: number): number {
    if (t <= lo) return 0
    if (t >= hi) return 100
    for (const blk of blocks) {
      if (t >= blk.t0 && t <= blk.t1) {
        if (blk.t1 === blk.t0) return blk.x0
        return clamp(blk.x0 + ((t - blk.t0) / (blk.t1 - blk.t0)) * (blk.x1 - blk.x0))
      }
    }
    // 落进断口——按定义不该发生（断口内部没有点）。防御：吸附到最近的区块边界。
    let best = blocks[0]
    let bestD = Infinity
    for (const blk of blocks) {
      const d = t < blk.t0 ? blk.t0 - t : t - blk.t1
      if (d < bestD) { bestD = d; best = blk }
    }
    return clamp(t < best.t0 ? best.x0 : best.x1)
  }

  return { lo, hi, blocks, breaks, x: x映射, degraded }
}

function clamp(v: number): number {
  return Math.min(100, Math.max(0, v))
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test -- src/lib/axis.test.ts`
Expected: 全绿。

**如果「主线 28.67%」那条不过**，先别改断言——去核实现里的宽度分配顺序。期望值是这么来的：断口 2×3=6，保底 3×1=3，余 91，按跨度 0 / 12.1 / 33（总 45.1）分，主线所在的第三块得 1 + 33/45.1×91 = 67.59%，主线在块内占 33 年里的 14 年 → 67.59 × 14/33 = 28.67%。

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/axis.ts web/src/lib/axis.test.ts
git commit -m "feat(web): 断轴成轴，西游记主线从 1.6% 变 28.7%

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: 段生成（`segments.ts`）

spec 4.3。真数据里每个场景存一个时间点，没有「段」——段要从「落在同一个有效区块内的连续场景」推出来。

**Files:**
- Create: `web/src/lib/segments.ts`
- Test: `web/src/lib/segments.test.ts`

- [ ] **Step 1: 写失败的测试 `web/src/lib/segments.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { buildSegments, threadPoints } from './segments'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import 西游记 from '@/components/__fixtures__/xiyouji-threads.json'
import type { Thread, ThreadsFile } from '@/api/types'

const 雪 = 雪月梅 as unknown as ThreadsFile
const 西 = 西游记 as unknown as ThreadsFile

function 全局点(d: ThreadsFile): number[] {
  return d.threads.flatMap((t) => threadPoints(t))
}

describe('threadPoints', () => {
  it('把 offset 加到线内时间上', () => {
    const t = { offset: 10, times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: 2, conf: '中' } } } as unknown as Thread
    expect(threadPoints(t)).toEqual([11, 12])
  })

  it('排除 t 为 null 的场景，不插值', () => {
    const t = {
      offset: 0,
      times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: null, conf: '低' }, 'S-3': { t: 3, conf: '中' } },
    } as unknown as Thread
    expect(threadPoints(t)).toEqual([1, 3])
  })

  it('真数据里确实有 t 为 null 的场景', () => {
    const 全部 = 雪.threads.flatMap((t) => Object.values(t.times ?? {}))
    expect(全部.some((v) => v.t === null)).toBe(true)
  })
})

describe('buildSegments', () => {
  it('同一区块内的点合成一段', () => {
    const axis = buildAxis([0, 1, 2, 3])!
    const segs = buildSegments([0, 1, 2, 3], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].t0).toBe(0)
    expect(segs[0].t1).toBe(3)
  })

  it('跨区块自然断成两段', () => {
    const axis = buildAxis([0, 1, 500, 501])!
    expect(axis.blocks).toHaveLength(2)
    const segs = buildSegments([0, 1, 500, 501], axis)
    expect(segs).toHaveLength(2)
  })

  it('一条线在某个区块里一个点都没有时，那个区块不产段', () => {
    const axis = buildAxis([0, 1, 500, 501])!
    const segs = buildSegments([0, 1], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].t1).toBe(1)
  })

  it('单点段给最小宽度，不是 0 宽', () => {
    const axis = buildAxis([0, 1, 2, 3])!
    const segs = buildSegments([2], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x1 - segs[0].x0).toBeGreaterThan(0)
  })

  it('空输入给空数组', () => {
    const axis = buildAxis([0, 1, 2])!
    expect(buildSegments([], axis)).toEqual([])
  })

  it('《雪月梅》L-002 横跨断口，要断成两段', () => {
    // 这条线有一个场景在 -10 年，其余在 0 年之后——断轴正好从中间切过
    const axis = buildAxis(全局点(雪))!
    const l2 = 雪.threads.find((t) => t.id === 'L-002')!
    const segs = buildSegments(threadPoints(l2), axis)
    expect(segs).toHaveLength(2)
    expect(segs[0].x0).toBeCloseTo(0, 1)
    expect(segs[0].x1).toBeCloseTo(1, 1)
    expect(segs[1].x0).toBeCloseTo(4, 1)
    expect(segs[1].x1).toBeCloseTo(68, 0)
  })

  it('《西游记》主线只在最后一个区块里，一段', () => {
    const axis = buildAxis(全局点(西))!
    const l1 = 西.threads.find((t) => t.id === 'L-001')!
    const segs = buildSegments(threadPoints(l1), axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x1 - segs[0].x0).toBeCloseTo(28.67, 1)
  })

  it('《西游记》L-002 也横跨断口', () => {
    const axis = buildAxis(全局点(西))!
    const l2 = 西.threads.find((t) => t.id === 'L-002')!
    const segs = buildSegments(threadPoints(l2), axis)
    expect(segs).toHaveLength(2)
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd web && npm run test -- src/lib/segments.test.ts`
Expected: FAIL，找不到 `./segments`。

- [ ] **Step 3: 写 `web/src/lib/segments.ts`**

```ts
/** 一条线的「段」。真数据只有每场景一个时间点，段由断轴区块推出来。spec 4.3。 */

import type { Axis } from './axis'
import type { Thread } from '@/api/types'

export interface Segment {
  t0: number
  t1: number
  x0: number
  x1: number
}

/**
 * 单点段的最小宽度（百分比）。比 axis 的 minBlock（1）小一点是故意的——
 * 段画在区块里面，跟区块一样宽会顶满边界看不出这是个「点」。
 */
const 单点宽 = 0.6

/**
 * 一条线的全局时间点，升序。
 * `t` 为 null 的场景直接排除——**不插值**，插值等于编造位置（spec 4.5）。
 */
export function threadPoints(thread: Thread): number[] {
  const off = thread.offset ?? 0
  const out: number[] = []
  for (const v of Object.values(thread.times ?? {})) {
    if (v && v.t !== null && v.t !== undefined) out.push(off + v.t)
  }
  return out.sort((a, b) => a - b)
}

/** 把一条线的时间点按断轴区块切成段。 */
export function buildSegments(points: number[], axis: Axis): Segment[] {
  if (points.length === 0) return []
  const pts = [...points].sort((a, b) => a - b)
  const segs: Segment[] = []

  for (const blk of axis.blocks) {
    const 块内 = pts.filter((p) => p >= blk.t0 && p <= blk.t1)
    if (块内.length === 0) continue
    const t0 = 块内[0]
    const t1 = 块内[块内.length - 1]
    let x0 = axis.x(t0)
    let x1 = axis.x(t1)
    if (x1 - x0 < 单点宽) {
      // 单个点或几乎重合：给一点宽度，不然画出来什么都看不见
      const 中 = (x0 + x1) / 2
      x0 = Math.max(blk.x0, 中 - 单点宽 / 2)
      x1 = Math.min(blk.x1, x0 + 单点宽)
    }
    segs.push({ t0, t1, x0, x1 })
  }
  return segs
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test -- src/lib/segments.test.ts`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/segments.ts web/src/lib/segments.test.ts
git commit -m "feat(web): 段生成，按断轴区块切开

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: 缺口两层聚合（`gaps.ts`）

spec 4.4。真数据里雪月梅 81 个缺口、单条线最多 36 个，其中 41 个只有 `before` 没有 `after`、6 个两端都没有。**一个都不能静默丢掉。**

**Files:**
- Create: `web/src/lib/gaps.ts`
- Test: `web/src/lib/gaps.test.ts`

- [ ] **Step 1: 写失败的测试 `web/src/lib/gaps.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { threadPoints } from './segments'
import { layoutGaps, sceneTimeLookup } from './gaps'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import type { Gap, ThreadsFile } from '@/api/types'

const 雪 = 雪月梅 as unknown as ThreadsFile
const 全局点 = 雪.threads.flatMap((t) => threadPoints(t))
const axis = buildAxis(全局点)!
const 查时间 = sceneTimeLookup(雪)

function 某线缺口(tid: string): Gap[] {
  return 雪.gaps.filter((g) => g.thread === tid)
}

describe('sceneTimeLookup', () => {
  it('查得到场景的全局时间', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[0]
    expect(查时间(sid)).not.toBeNull()
  })

  it('查不到的场景返回 null', () => {
    expect(查时间('S-9999')).toBeNull()
  })
})

describe('layoutGaps 定位', () => {
  it('有 before 时用 before', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: null, before: sid }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters[0].x).toBeCloseTo(axis.x(查时间(sid)!), 4)
  })

  it('没有 before 时退到 after', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: sid, before: null }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters[0].x).toBeCloseTo(axis.x(查时间(sid)!), 4)
  })

  it('before 指向一个 t 为 null 的场景时退到 after', () => {
    // 造一个：before 查不到时间，after 查得到
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const 好 = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: 好, before: 'S-9999' }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters).toHaveLength(1)
  })

  it('两端都查不到时进 orphans，不丢掉', () => {
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: null, before: null }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.clusters).toHaveLength(0)
    expect(r.orphans.map((x) => x.id)).toEqual(['Q-x'])
  })

  it('一个缺口都不丢：簇里的 + orphan = 输入总数', () => {
    for (const tid of ['L-001', 'L-002', 'L-003', 'L-004', 'L-005']) {
      const gs = 某线缺口(tid)
      const r = layoutGaps(gs, 查时间, axis)
      const 进簇 = r.clusters.reduce((s, c) => s + c.gaps.length, 0)
      expect(进簇 + r.orphans.length).toBe(gs.length)
    }
  })
})

describe('layoutGaps 两层聚合（《雪月梅》L-005 真数据）', () => {
  const gs = 某线缺口('L-005')
  const r = layoutGaps(gs, 查时间, axis)

  it('这条线有 36 个缺口，31 个定得了位、5 个 orphan', () => {
    expect(gs).toHaveLength(36)
    expect(r.clusters.reduce((s, c) => s + c.gaps.length, 0)).toBe(31)
    expect(r.orphans).toHaveLength(5)
  })

  it('两层聚合后收成 13 个落点', () => {
    expect(r.clusters).toHaveLength(13)
  })

  it('第二层确实起了作用：只做第一层是 14 个落点', () => {
    // x(0.7)=14.18% 和 x(0.8)=15.64% 相差 1.45% < 1.5%，会被第二层并掉
    const 只做第一层 = layoutGaps(gs, 查时间, axis, { clusterRatio: 0 })
    expect(只做第一层.clusters).toHaveLength(14)
  })

  it('合并簇的位置是成员 x 的中点', () => {
    const 合并的 = r.clusters.find((c) => c.gaps.length === 7)
    expect(合并的).toBeDefined()
    expect(合并的!.x).toBeCloseTo(14.91, 1)
  })

  it('落点按 x 升序', () => {
    for (let i = 1; i < r.clusters.length; i++) {
      expect(r.clusters[i].x).toBeGreaterThan(r.clusters[i - 1].x)
    }
  })

  it('clusterRatio 调大后落点变少（窄屏会走到这一支）', () => {
    const 窄 = layoutGaps(gs, 查时间, axis, { clusterRatio: 10 })
    expect(窄.clusters.length).toBeLessThan(r.clusters.length)
    const 进簇 = 窄.clusters.reduce((s, c) => s + c.gaps.length, 0)
    expect(进簇 + 窄.orphans.length).toBe(36)
  })
})

describe('layoutGaps 迭代收敛', () => {
  it('一串等距的点，合并后又靠近的要继续合，不能只合一轮', () => {
    const a = buildAxis([0, 100])!
    // 在 x 上等距 1% 排 5 个点，clusterRatio=1.5 时应该全部并成 1 个
    const 场景时间: Record<string, number> = { a: 0, b: 1, c: 2, d: 3, e: 4 }
    const 查: (sid: string) => number | null = (s) => 场景时间[s] ?? null
    const gs: Gap[] = Object.keys(场景时间).map((s) => ({
      id: `Q-${s}`, world: 'W', event: 'e', mentioned_in: [], thread: 'L-1', after: null, before: s,
    }))
    const r = layoutGaps(gs, 查, a, { clusterRatio: 1.5 })
    expect(r.clusters).toHaveLength(1)
    expect(r.clusters[0].gaps).toHaveLength(5)
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd web && npm run test -- src/lib/gaps.test.ts`
Expected: FAIL，找不到 `./gaps`。

- [ ] **Step 3: 写 `web/src/lib/gaps.ts`**

```ts
/** 缺口的落点与两层聚合。spec 4.4。 */

import type { Axis } from './axis'
import type { Gap, ThreadsFile } from '@/api/types'

export interface GapCluster {
  /** 百分比位置 */
  x: number
  gaps: Gap[]
}

export interface GapLayout {
  clusters: GapCluster[]
  /** 两端都定不了位的。挂到线尾标签里，**不能静默丢掉**。 */
  orphans: Gap[]
}

export interface GapOptions {
  /** 相邻簇的 x 距离小于它就合并。默认 1.5（百分比）。 */
  clusterRatio?: number
}

/** 建一张「场景编号 → 全局时间」的表。t 为 null 的场景查出来是 null。 */
export function sceneTimeLookup(data: ThreadsFile): (sid: string) => number | null {
  const table = new Map<string, number>()
  for (const t of data.threads) {
    const off = t.offset ?? 0
    for (const [sid, v] of Object.entries(t.times ?? {})) {
      if (v && v.t !== null && v.t !== undefined) table.set(sid, off + v.t)
    }
  }
  return (sid: string) => (table.has(sid) ? table.get(sid)! : null)
}

export function layoutGaps(
  gaps: Gap[],
  sceneTime: (sid: string) => number | null,
  axis: Axis,
  opts: GapOptions = {},
): GapLayout {
  const clusterRatio = opts.clusterRatio ?? 1.5

  // 定位：有 before 用 before，否则退到 after，都取不到就是 orphan
  const anchored: Array<{ x: number; gap: Gap }> = []
  const orphans: Gap[] = []
  for (const g of gaps) {
    const t =
      (g.before ? sceneTime(g.before) : null) ??
      (g.after ? sceneTime(g.after) : null)
    if (t === null || t === undefined) orphans.push(g)
    else anchored.push({ x: axis.x(t), gap: g })
  }
  anchored.sort((a, b) => a.x - b.x)

  // 第一层：x 完全相同的合并
  let clusters: GapCluster[] = []
  for (const a of anchored) {
    const last = clusters[clusters.length - 1]
    if (last && Math.abs(last.x - a.x) < 1e-9) last.gaps.push(a.gap)
    else clusters.push({ x: a.x, gaps: [a.gap] })
  }

  // 第二层：相邻簇的 x 距离 < clusterRatio 就合并，位置取中点，迭代到稳定
  if (clusterRatio > 0) {
    let changed = true
    while (changed) {
      changed = false
      const merged: GapCluster[] = []
      for (const c of clusters) {
        const last = merged[merged.length - 1]
        if (last && c.x - last.x < clusterRatio) {
          last.x = (last.x + c.x) / 2
          last.gaps = last.gaps.concat(c.gaps)
          changed = true
        } else {
          merged.push({ x: c.x, gaps: [...c.gaps] })
        }
      }
      clusters = merged
    }
  }

  return { clusters, orphans }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test -- src/lib/gaps.test.ts`
Expected: 全绿。

**如果「13 个落点」那条不过**，先核 `axis` 有没有按默认参数建（`breakRatio=0.05` 等），再核第二层是不是漏了迭代。期望值来自真 fixture 手算。

- [ ] **Step 5: 跑全量前端测试**

Run: `cd web && npm run test && npm run typecheck`
Expected: 全绿。

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/gaps.ts web/src/lib/gaps.test.ts
git commit -m "feat(web): 缺口两层聚合，定不了位的进 orphans 不丢

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 里程碑 C 完成检查

- [ ] `cd web && npm run test` → axis / segments / gaps 三组全绿
- [ ] 三个函数都拿真 fixture 测过，不是只测了手捏的小数据
- [ ] 「一个缺口都不丢」那条覆盖了全部 5 条线
- [ ] `uv run pytest -q` → 877 passed

---

## 里程碑 D 的共同约定

从这里开始每个页面任务都遵守：

- **页面只负责取数和展示，算法一律调 `lib/` 里的纯函数。** 页面里不准出现第二份断轴/聚合逻辑。
- **所有会触发任务的按钮**都接 `useJobStore().busy`，忙的时候 `disabled` 并给出「有任务在跑」的提示。
- **catch 到 `ApiError` 一律用 `ErrorBox` 显示 `detail` 原文**，不要换成自己编的话（spec 第 8 章：界面要拿到具体错误信息）。
- **一个数字都不显示费用**：`summary.cost_usd`、`usage`、单价字段，一律不渲染（spec 7.3）。
- 每个页面至少三条测试：空态、正常态、后端报错时的展示。

先建一个共用的 `ErrorBox`（Task 14 Step 1），后面各页复用。

---

## Task 14: 路由骨架 + 书架/导入页

带一条后端改动：manifest 要记下每个原稿根目录对应的**来源文件夹完整路径**，界面才比得出「同名但不是同一个文件夹」。

待办原文：「两个不同位置、同名的文件夹（比如 `D:\我的稿子` 和 `E:\我的稿子`）会共用 `原稿/我的稿子/`，后导入的覆盖前面的，并算作「改动」。导入界面要显示并记录来源文件夹路径，路径不同时提醒。」

**Files:**
- Modify: `src/ligaotai/importer.py`
- Test: `tests/test_importer.py`
- Create: `web/src/router.ts`
- Create: `web/src/components/ErrorBox.vue`
- Create: `web/src/pages/BooksPage.vue`
- Modify: `web/src/App.vue`
- Test: `web/src/pages/BooksPage.test.ts`

- [ ] **Step 1: 后端——manifest 记来源路径**

先看 manifest 现在长什么样：

```bash
uv run python -c "import inspect, ligaotai.importer as m; print(inspect.getsource(m.run_import))" > %TEMP%\imp.txt
```

写失败的测试，追加到 `tests/test_importer.py`：

```python
def test_manifest记下每个原稿根目录的来源路径(tmp_path):
    """同名但不同位置的两个文件夹会共用一个 root_name，
    manifest 要记住它上次是从哪来的，界面才提醒得了。"""
    lib = tmp_path / "书库"
    lib.mkdir()
    b = create_book(lib, "测试书")

    src = tmp_path / "甲" / "我的稿子"
    src.mkdir(parents=True)
    (src / "a.txt").write_text("正文", encoding="utf-8")

    run_import(b, src)
    manifest = read_json(b.manifest_path, {})
    assert manifest["roots"]["我的稿子"] == str(src.resolve())


def test_同名不同路径再导入时来源路径会被更新(tmp_path):
    lib = tmp_path / "书库"
    lib.mkdir()
    b = create_book(lib, "测试书")
    甲 = tmp_path / "甲" / "我的稿子"
    乙 = tmp_path / "乙" / "我的稿子"
    for d in (甲, 乙):
        d.mkdir(parents=True)
        (d / "a.txt").write_text("正文", encoding="utf-8")

    run_import(b, 甲)
    run_import(b, 乙)
    manifest = read_json(b.manifest_path, {})
    assert manifest["roots"]["我的稿子"] == str(乙.resolve())
```

跑：`uv run pytest tests/test_importer.py -k 来源路径 -v` → FAIL（没有 `roots` 键）。

改 `run_import`，在写 manifest 的地方加：

```python
    manifest.setdefault("roots", {})[root_name] = str(folder)
```

放在 `root_name = safe_name(folder.name)` 之后、写盘之前。

再跑：2 passed。然后 `uv run pytest -q` → 879 passed。

- [ ] **Step 2: 后端——把 roots 吐给界面**

`GET /api/books/{name}` 现在返回 `{name, **b.load()}`，里面没有 manifest。加一个字段：

```python
    @app.get("/api/books/{name}")
    def book_meta(name: str) -> dict:
        b = get_book(name)
        manifest = read_json(b.manifest_path, {"files": {}})
        return {"name": b.name, **b.load(), "roots": manifest.get("roots", {})}
```

在 `tests/test_api.py` 加一条：导入过之后 `GET /books/{name}` 的 `roots` 里有那个文件夹。

`web/src/api/types.ts` 的 `BookMeta` 加：

```ts
  /** 原稿根目录名 → 上次导入时的来源文件夹完整路径 */
  roots: Record<string, string>
```

- [ ] **Step 3: 建 `web/src/components/ErrorBox.vue`**

```vue
<script setup lang="ts">
defineProps<{ message: string }>()
</script>

<template>
  <div v-if="message" class="err" role="alert">
    <b>出错了</b>
    <pre>{{ message }}</pre>
  </div>
</template>

<style scoped>
.err{
  border:1px solid var(--red); background:var(--red-soft); color:var(--ink);
  border-radius:6px; padding:10px 12px; margin:12px 0;
}
.err b{color:var(--red);display:block;margin-bottom:4px}
.err pre{margin:0;white-space:pre-wrap;font-family:var(--mono);font-size:12px}
</style>
```

`<pre>` 是故意的——后端的 `detail` 可能带路径和多行，原样显示。

- [ ] **Step 4: 建 `web/src/router.ts`**

```ts
import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'books', component: () => import('./pages/BooksPage.vue') },
    { path: '/settings', name: 'settings', component: () => import('./pages/SettingsPage.vue') },
    { path: '/b/:name/pipeline', name: 'pipeline', component: () => import('./pages/PipelinePage.vue'), props: true },
    { path: '/b/:name/pipeline/entities', name: 'entities', component: () => import('./pages/EntitiesPage.vue'), props: true },
    { path: '/b/:name/pipeline/threads', name: 'threads', component: () => import('./pages/ThreadsPage.vue'), props: true },
    { path: '/b/:name/panorama', name: 'panorama', component: () => import('./pages/PanoramaPage.vue'), props: true },
    { path: '/b/:name/scenes', name: 'scenes', component: () => import('./pages/ScenesPage.vue'), props: true },
    { path: '/b/:name/archive', name: 'archive', component: () => import('./pages/ArchivePage.vue'), props: true },
    { path: '/b/:name/contradictions', name: 'contradictions', component: () => import('./pages/ContradictionsPage.vue'), props: true },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
```

九条路由对应 spec 第 1 章那张表。**先建全部九条**，页面文件后面几个任务陆续补——没补的先各建一个占位组件（`<template><div>待做</div></template>`），不然路由会加载失败。

改 `web/src/main.ts` 挂上 router：

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './styles/tokens.css'
import './styles/base.css'

createApp(App).use(createPinia()).use(router).mount('#app')
```

`web/src/App.vue` 改成只放 `<RouterView />`：

```vue
<template>
  <RouterView />
</template>
```

**冒烟测试会因此失败**（它断言页面上有「理稿台」三个字）——把 `web/src/smoke.test.ts` 改成断言 `RouterView` 挂得起来，或者直接删掉它，由各页面自己的测试接手。

- [ ] **Step 5: 写失败的测试 `web/src/pages/BooksPage.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BooksPage from './BooksPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'

const stubs = { RouterLink: true }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('BooksPage', () => {
  it('没有书时给空态，不是一张空表', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('还没有书')
  })

  it('列出书名和字数', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('归墟')
  })

  it('后端报错时把 detail 原样显示', async () => {
    vi.spyOn(api, 'listBooks').mockRejectedValue(new ApiError(500, '书库目录读不了：E:\\不存在'))
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('书库目录读不了')
    expect(w.text()).toContain('E:\\不存在')
  })

  it('导入同名但不同路径的文件夹时提醒', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    vi.spyOn(api, 'getBook').mockResolvedValue({
      name: 'guixu', schema: 1, title: '归墟', created: '', settings: {},
      steps: {} as never,
      roots: { 我的稿子: 'D:\\甲\\我的稿子' },
    } as never)
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()

    await w.find('[data-test="选书"]').trigger('click')
    await w.find('[data-test="来源文件夹"]').setValue('E:\\乙\\我的稿子')
    await flushPromises()

    expect(w.text()).toContain('同名')
    expect(w.text()).toContain('D:\\甲\\我的稿子')
  })

  it('同名且同路径不提醒', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    vi.spyOn(api, 'getBook').mockResolvedValue({
      name: 'guixu', schema: 1, title: '归墟', created: '', settings: {},
      steps: {} as never,
      roots: { 我的稿子: 'D:\\甲\\我的稿子' },
    } as never)
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    await w.find('[data-test="选书"]').trigger('click')
    await w.find('[data-test="来源文件夹"]').setValue('D:\\甲\\我的稿子')
    await flushPromises()
    expect(w.text()).not.toContain('同名')
  })

  it('有任务在跑时导入按钮禁用', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([])
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: '归墟', status: 'running',
      done: 1, total: 9, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    const s = useJobStore()
    await s.refresh()
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="导入"]')
    if (按钮.exists()) expect(按钮.attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 6: 跑测试确认失败，然后写 `web/src/pages/BooksPage.vue`**

页面要有：

1. 书列表（`listBooks`），每行书名 + 建立时间，点进去到 `/b/:name/pipeline`。
2. 空态：「还没有书。填个书名建一本，然后选文件夹导入。」
3. 新建书：一个输入框 + 按钮，调 `createBook`。
4. 导入：选中一本书后，一个文本输入框填**来源文件夹的完整路径**（浏览器拿不到本地路径，只能手填；输入框旁写清「填完整路径，比如 `D:\我的稿子`」），调 `importFolder`。
5. **同名不同路径提醒**：输入路径后，取它的 basename（注意要同时处理 `\` 和 `/`），去当前书的 `roots` 里查；查到了且记录的路径跟这次填的不同，就显示：

   > ⚠ 这本书里已经有一个叫「我的稿子」的原稿目录，上次是从 `D:\甲\我的稿子` 导入的。
   > 从不同位置的同名文件夹导入会覆盖它，并算作「改动」。

   取 basename 的实现：

   ```ts
   function 取名(p: string): string {
     const s = p.replace(/[\\/]+$/, '')
     const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'))
     return i >= 0 ? s.slice(i + 1) : s
   }
   ```

   **别用 `split('/')`**——这是 Windows 工具，路径分隔符是 `\`。

6. 导入按钮和新建按钮接 `useJobStore().busy`。
7. 所有 catch 用 `ErrorBox`。

- [ ] **Step 7: 跑测试与 typecheck，然后 Commit**

```bash
cd web && npm run test && npm run typecheck
```

```bash
git add src/ligaotai/importer.py src/ligaotai/api.py tests/test_importer.py tests/test_api.py web/src/api/types.ts web/src/router.ts web/src/main.ts web/src/App.vue web/src/components/ErrorBox.vue web/src/pages/
git commit -m "feat: 路由骨架与书架/导入页，manifest 记来源路径并提醒同名不同位置

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 15: 流水线页

七步进度。**不显示任何费用数字**（spec 7.3）。

**Files:**
- Create: `web/src/pages/PipelinePage.vue`
- Create: `web/src/components/JobBar.vue`
- Test: `web/src/pages/PipelinePage.test.ts`

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PipelinePage from './PipelinePage.vue'
import * as api from '@/api/endpoints'
import type { BookMeta, StepName, StepState } from '@/api/types'

const stubs = { RouterLink: true }

function 造书(steps: Partial<Record<StepName, Partial<StepState>>> = {}): BookMeta {
  const 全部: StepName[] = ['import', 'split', 'dedup', 'cards', 'entities', 'threads', 'archive']
  const s = {} as Record<StepName, StepState>
  for (const k of 全部) s[k] = { status: 'todo', updated: null, summary: {}, ...steps[k] }
  return { name: 'guixu', schema: 1, title: '归墟', created: '', settings: {}, steps: s, roots: {} }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('PipelinePage', () => {
  it('七步都列出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    for (const 名 of ['导入', '切场景', '查重', '场景卡', '实体合并', '归线排序', '档案+矛盾+地图']) {
      expect(w.text()).toContain(名)
    }
  })

  it('一个费用数字都不显示', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'done', summary: { cost_usd: 1.2345, calls: 468, written: 133 } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const t = w.text()
    expect(t).not.toContain('1.2345')
    expect(t).not.toContain('$')
    expect(t).not.toContain('费用')
    expect(t).not.toContain('cost')
  })

  it('调用次数也不显示', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'done', summary: { cost_usd: 1.2, calls: 468, written: 133 } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).not.toContain('468')
  })

  it('上游没做完时下游的「跑」按钮禁用', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({ import: { status: 'todo' } }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="跑-cards"]')
    expect(按钮.attributes('disabled')).toBeDefined()
  })

  it('步骤失败时把 summary.error 显示出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'failed', summary: { error: '已暂停：做完 12 张，还剩 88 张' } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('已暂停：做完 12 张，还剩 88 张')
  })

  it('过期的步骤要标出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({ cards: { status: 'outdated', summary: {} } }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('过期')
  })

  it('有任务在跑时所有「跑」按钮都禁用', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      import: { status: 'done' }, split: { status: 'done' }, dedup: { status: 'done' },
    }))
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'running',
      done: 3, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    for (const s of ['split', 'dedup', 'cards']) {
      const b = w.find(`[data-test="跑-${s}"]`)
      if (b.exists()) expect(b.attributes('disabled')).toBeDefined()
    }
  })

  it('任务跑完后自动重新拉书的状态', async () => {
    const spy = vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'running',
      done: 3, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    const s = useJobStore()
    mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 次数 = spy.mock.calls.length

    await s.refresh()
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'done',
      done: 10, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    await s.refresh()
    await flushPromises()
    expect(spy.mock.calls.length).toBeGreaterThan(次数)
  })
})
```

- [ ] **Step 2: 写 `web/src/components/JobBar.vue`**

固定在主区顶部的一条，显示当前任务：步骤名 + `done/total` 进度条 + `message` + 暂停按钮。没任务时不渲染。`pollError` 非空时显示「连不上后端」。

**不显示费用。**

- [ ] **Step 3: 写 `web/src/pages/PipelinePage.vue`**

七行，每行：序号、步骤名（`STEP_LABELS`）、状态徽章、一句话结果、操作按钮。

- 状态徽章：`todo` 灰 / `running` 蓝 / `done` 绿 / `failed` 朱红 / `outdated` 琥珀（用 tokens 里的 `--green` `--red` `--amber` `--accent`）。
- 「一句话结果」从 `summary` 里挑**跟费用无关**的字段拼。各步的 summary 字段不一样，写一个 `摘要(step, summary)` 函数分别处理，**白名单取字段**，别把整个 summary 倒出来——那样 `cost_usd` 会漏出去。
- `failed` 时显示 `summary.error`。
- `outdated` 时显示「上游变了，这一步的结果已过期」。
- 「跑」按钮：`import` 那行是「导入」（跳去书架页的导入区），其余用 `runStep`。上游任一步不是 `done` 时禁用（跟后端 `require_upstream` 一致）；`busy` 时禁用。
- 第 5、6 步做完后，如果有待确认项，给一个「去确认」的链接到子路由。
- 挂载时 `useJobStore().start()`，卸载时 `stop()`；`onFinish` 里重新 `getBook`。

- [ ] **Step 4: 跑测试与 Commit**

```bash
cd web && npm run test && npm run typecheck
git add web/src/pages/PipelinePage.vue web/src/pages/PipelinePage.test.ts web/src/components/JobBar.vue
git commit -m "feat(web): 流水线页，七步进度，不显示任何费用数字

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 16: 实体确认页

重点是待办那条：**`conflicts` 要列出来给作者手动处理**。

⚠ **`conflicts` 不在 `实体.json` 里**，它只出现在步骤跑完的 summary 中，也就是 `BookMeta.steps.entities.summary.conflicts`，形状是 `[{type, chunk, names}]`。去 `GET /entities` 里找是找不到的。

**Files:**
- Create: `web/src/pages/EntitiesPage.vue`
- Test: `web/src/pages/EntitiesPage.test.ts`

- [ ] **Step 1: 写失败的测试**

```ts
it('conflicts 从 steps.entities.summary 里读，并单独列出来', async () => {
  vi.spyOn(api, 'getBook').mockResolvedValue(造书({
    entities: {
      status: 'done',
      summary: { conflicts: [{ type: 'person', chunk: 2, names: ['觀世音', '觀音菩薩'] }] },
    },
  }))
  vi.spyOn(api, 'getEntities').mockResolvedValue({ next_id: 5, entities: [] })
  const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('觀世音')
  expect(w.text()).toContain('觀音菩薩')
  expect(w.find('[data-test="冲突区"]').exists()).toBe(true)
})

it('没有 conflicts 时不显示那一区', async () => {
  vi.spyOn(api, 'getBook').mockResolvedValue(造书({ entities: { status: 'done', summary: {} } }))
  vi.spyOn(api, 'getEntities').mockResolvedValue({ next_id: 1, entities: [] })
  const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="冲突区"]').exists()).toBe(false)
})

it('只把 draft 状态的组当待确认', async () => {
  vi.spyOn(api, 'getBook').mockResolvedValue(造书())
  vi.spyOn(api, 'getEntities').mockResolvedValue({
    next_id: 9,
    entities: [
      { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清', '清儿'], status: 'draft', reason: '同一人', scenes: ['S-1'] },
      { id: 'E-0002', type: 'person', canonical: '张三', names: ['张三'], status: 'single', reason: '', scenes: ['S-2'] },
      { id: 'E-0003', type: 'person', canonical: '李四', names: ['李四', '四郎'], status: 'confirmed', reason: '', scenes: ['S-3'] },
    ],
  })
  const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.findAll('[data-test="待确认组"]')).toHaveLength(1)
})

it('实体文件坏了时显示后端给的 detail', async () => {
  vi.spyOn(api, 'getBook').mockResolvedValue(造书())
  vi.spyOn(api, 'getEntities').mockRejectedValue(
    new ApiError(500, '实体.json读不了：不是合法 JSON，第 3 行。这个文件多半被手动改过或来自别处。'))
  const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('不是合法 JSON，第 3 行')
})
```

- [ ] **Step 2: 写页面**

三区：

1. **待确认的合并组**（`status === 'draft'`）：每组显示 `canonical`、全部 `names`、模型给的 `reason`、涉及的场景数。每组两个按钮「接受」（`confirmEntities([id])`）和「拆开」（`splitEntity`）。顶上一个「全部接受」。
2. **跨批冲突**（从 `steps.entities.summary.conflicts` 读）：每条显示 `type`、`names`。给一句话解释：「这几个叫法在不同批里被分到了不同组，程序不敢自动合。要合的话在下面的『手动合并』里选。」再给一个「手动合并」入口，调 `mergeEntities(ids)`。
3. **已确认 / single**：折叠，可搜索。

- [ ] **Step 3: 跑测试与 Commit**

```bash
git add web/src/pages/EntitiesPage.vue web/src/pages/EntitiesPage.test.ts
git commit -m "feat(web): 实体确认页，conflicts 从 summary 读并单独列出

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 17: 归线确认页

待办原文：「模型建议归入已确认线的块（`pending`）要让作者一键接受 / 拒绝；未分配的块（`unassigned`）要能拖进线；排序失败（`order_failed`）的线要醒目提示。」

**Files:**
- Create: `web/src/pages/ThreadsPage.vue`
- Test: `web/src/pages/ThreadsPage.test.ts`

- [ ] **Step 1: 写失败的测试**

```ts
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'

it('order_failed 的线要醒目提示', async () => {
  const d = structuredClone(雪月梅) as unknown as ThreadsFile
  d.threads[0].order_failed = true
  vi.spyOn(api, 'getThreads').mockResolvedValue(d)
  const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="排序失败"]').exists()).toBe(true)
  expect(w.text()).toContain('顺序不可信')
})

it('pending 逐条给接受和拒绝', async () => {
  const d = structuredClone(雪月梅) as unknown as ThreadsFile
  d.pending = [{ scene: 'S-0099', thread: 'L-001', reason: '模型建议' }]
  vi.spyOn(api, 'getThreads').mockResolvedValue(d)
  const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="接受-S-0099"]').exists()).toBe(true)
  expect(w.find('[data-test="拒绝-S-0099"]').exists()).toBe(true)
})

it('unassigned 列出来并能选线归入', async () => {
  const d = structuredClone(雪月梅) as unknown as ThreadsFile
  d.unassigned = [{ scene: 'S-0123', reason: '没归上' }]
  vi.spyOn(api, 'getThreads').mockResolvedValue(d)
  const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('S-0123')
  expect(w.find('[data-test="归入-S-0123"]').exists()).toBe(true)
})

it('线的完没完取 end.state，不取 status', async () => {
  // status 是「划分确认了没有」不是「故事完了没有」，拿它判完结会全错
  const d = structuredClone(雪月梅) as unknown as ThreadsFile
  vi.spyOn(api, 'getThreads').mockResolvedValue(d)
  const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('完结')   // L-001 的 end.state
  expect(w.text()).toContain('待定')   // 其余几条
})

it('归线文件坏了（409）时显示后端的话', async () => {
  vi.spyOn(api, 'getThreads').mockRejectedValue(new ApiError(409, '世界与支线.json 结构不对：threads 不是数组'))
  const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('threads 不是数组')
})
```

- [ ] **Step 2: 写页面**

四区：

1. **排序失败的线**（`order_failed`）：顶到最上面，朱红底，「这条线排序失败，顺序不可信。可以手动调，或者重跑步骤 6。」
2. **待确认的块**（`pending`）：每条一行「S-0099 → L-001 岑秀入仕兴家（模型建议）」，两个按钮接受 / 拒绝。接受调 `confirmThreads([scene])`，拒绝调 `moveScenes` 把它移到 unassigned（**具体调哪个接口先看 `threads_ops.py` 里 confirm / 移动的真实语义**，不要照抄这句话，看完在报告里写清你用的是哪个）。
3. **未分配的块**（`unassigned`）：每条一行 + 一个线的下拉，选了就 `moveScenes(tid, {scenes:[sid]})`。**一期用下拉不做拖拽**——拖拽在测试里很难验，而下拉一样能完成任务。
4. **线列表**：线名（可改，`renameThread`）、世界、场景数、`end.state`、`about`。主线标出来，可 `setMainThread`。

- [ ] **Step 3: 跑测试与 Commit**

```bash
git add web/src/pages/ThreadsPage.vue web/src/pages/ThreadsPage.test.ts
git commit -m "feat(web): 归线确认页，pending 一键接受拒绝、unassigned 可归入、排序失败醒目

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 18: 设置页

**Files:**
- Create: `web/src/pages/SettingsPage.vue`
- Create: `web/src/stores/config.ts`
- Test: `web/src/pages/SettingsPage.test.ts`

- [ ] **Step 1: 写失败的测试**

```ts
const 配置 = {
  library_dir: '', api_base: 'https://api.deepseek.com', api_key: 'sk-…3f2a',
  concurrency: 8, timeout: 120, price_input: 0.3, price_output: 1.2,
  batch: { model: 'deepseek-flash', max_tokens: 8192 },
  synth: { model: 'deepseek-flash', max_tokens: 32768 },
  has_key: true, key_from_env: false, library_path: 'D:\\ligaotai\\书库',
}

it('不显示单价字段', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
  const w = mount(SettingsPage, { global: { stubs } })
  await flushPromises()
  expect(w.text()).not.toContain('单价')
  expect(w.text()).not.toContain('0.3')
  expect(w.text()).not.toContain('1.2')
  expect(w.find('[data-test="price_input"]').exists()).toBe(false)
})

it('提交时把单价原样带回去，不能丢', async () => {
  // PUT /api/config 是整份替换，漏字段会把后端的单价冲成默认值，
  // 而 tools/eval_* 还在用它。
  vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
  const put = vi.spyOn(api, 'putConfig').mockResolvedValue(配置 as never)
  const w = mount(SettingsPage, { global: { stubs } })
  await flushPromises()
  await w.find('[data-test="保存"]').trigger('click')
  await flushPromises()
  expect(put.mock.calls[0][0]).toMatchObject({ price_input: 0.3, price_output: 1.2 })
})

it('key 打过码，不回填明文，留空表示不改', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
  const w = mount(SettingsPage, { global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('sk-…3f2a')
})

it('key 来自环境变量时说清楚', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue({ ...配置, key_from_env: true } as never)
  const w = mount(SettingsPage, { global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('环境变量')
})

it('测试连接把后端返回的结果显示出来', async () => {
  vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
  vi.spyOn(api, 'testConfig').mockResolvedValue([{ tier: 'batch', ok: true }] as never)
  const w = mount(SettingsPage, { global: { stubs } })
  await flushPromises()
  await w.find('[data-test="测试连接"]').trigger('click')
  await flushPromises()
  expect(w.find('[data-test="连接结果"]').exists()).toBe(true)
})
```

- [ ] **Step 2: 写页面**

字段：书库目录（显示 `library_path` 只读 + `library_dir` 可改）、接口地址、API key（打码显示，输入框留空表示不改）、并发数、超时、两档模型（`batch.model`、`synth.model`、`max_tokens`）。

**关键实现点**：`PUT /api/config` 是整份替换。页面必须把 `getConfig` 拿到的整份对象存下来，保存时在它上面改动字段再提交——**包括不显示的 `price_input` / `price_output`**。漏了会把后端的单价冲成默认值，而 `tools/eval_threads.py`、`tools/eval_archives.py` 还在用它。

「测试连接」调 `testConfig()`，把返回原样列出来（先跑一次真接口看返回形状，`check_model` 的返回结构这里没写死）。

- [ ] **Step 3: 跑测试与 Commit**

```bash
git add web/src/pages/SettingsPage.vue web/src/pages/SettingsPage.test.ts web/src/stores/config.ts
git commit -m "feat(web): 设置页，不显示单价但提交时原样带回

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 19: `LaneChart` 组件

把 Task 11–13 的三个纯函数接成一张图。组件**不做任何计算**，只负责把纯函数算出来的坐标画成 DOM。

**Files:**
- Create: `web/src/components/LaneChart.vue`
- Test: `web/src/components/LaneChart.test.ts`

- [ ] **Step 1: 定好组件的输入输出**

```ts
// props
{
  data: ThreadsFile
  selectedThread?: string | null
  /** 容器宽度（px），用来把 clusterRatio 换算成「多少百分比才不挤」。默认 1200。 */
  width?: number
}
// emits
{
  'select-thread': [threadId: string]
  'select-cluster': [payload: { threadId: string; gaps: Gap[] }]
  'select-orphans': [payload: { threadId: string; gaps: Gap[] }]
}
```

`clusterRatio` 按容器宽度算：一个角标大约要 28px 才不挤，所以 `clusterRatio = 28 / width * 100`。**在渲染层算、resize 时重算，不缓存**（spec 4.4）。

- [ ] **Step 2: 写失败的测试 `web/src/components/LaneChart.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LaneChart from './LaneChart.vue'
import 西游记 from './__fixtures__/xiyouji-threads.json'
import 雪月梅 from './__fixtures__/xueyuemei-threads.json'
import type { ThreadsFile } from '@/api/types'

const 西 = 西游记 as unknown as ThreadsFile
const 雪 = 雪月梅 as unknown as ThreadsFile

describe('LaneChart 结构', () => {
  it('每条线一条泳道', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="泳道"]')).toHaveLength(3)
  })

  it('按世界分组', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="世界"]')).toHaveLength(1)
  })

  it('断口画出来并标明跨掉多少年', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    const 断口 = w.findAll('[data-test="断口"]')
    expect(断口).toHaveLength(2)
    expect(w.text()).toContain('360')
    expect(w.text()).toContain('480')
  })

  it('一个时间点都没有时出空态，不画空图', () => {
    const 空: ThreadsFile = { ...雪, threads: [] }
    const w = mount(LaneChart, { props: { data: 空 } })
    expect(w.findAll('[data-test="泳道"]')).toHaveLength(0)
    expect(w.text()).toContain('还没有')
  })
})

describe('LaneChart 段', () => {
  it('《西游记》主线一段，占 28% 以上', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    const 道 = w.find('[data-test="泳道-L-001"]')
    const 段 = 道.findAll('[data-test="段"]')
    expect(段).toHaveLength(1)
    const style = 段[0].attributes('style') ?? ''
    const m = /width:\s*([\d.]+)%/.exec(style)
    expect(m).not.toBeNull()
    expect(Number(m![1])).toBeGreaterThan(25)
  })

  it('《雪月梅》L-002 横跨断口，画成两段', () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    expect(w.find('[data-test="泳道-L-002"]').findAll('[data-test="段"]')).toHaveLength(2)
  })

  it('不画「只有提纲碎片」那种条带（outlines 在真数据里全是空的）', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.find('[data-test="提纲段"]').exists()).toBe(false)
    expect(w.text()).not.toContain('提纲')
  })
})

describe('LaneChart 标记', () => {
  it('完没完取 end.state 不取 status', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    // L-001、L-002 是「完结」，L-003 是「待定」
    expect(w.findAll('[data-test="标记-完"]')).toHaveLength(2)
    expect(w.findAll('[data-test="标记-待定"]')).toHaveLength(1)
  })

  it('交汇点按 intersections 画', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="交汇"]')).toHaveLength(西.intersections.length)
  })

  it('order_failed 的线整条标出来', () => {
    const d = structuredClone(雪) as ThreadsFile
    d.threads[0].order_failed = true
    const w = mount(LaneChart, { props: { data: d } })
    expect(w.find('[data-test="泳道-L-001"]').classes()).toContain('排序失败')
  })
})

describe('LaneChart 缺口', () => {
  it('L-005 的 36 个缺口一个不丢：簇里的 + orphan = 36', () => {
    const w = mount(LaneChart, { props: { data: 雪, width: 1200 } })
    const 道 = w.find('[data-test="泳道-L-005"]')
    const 簇 = 道.findAll('[data-test="缺口簇"]')
    const 总数 = 簇.reduce((s, e) => s + Number(e.attributes('data-count') ?? 0), 0)
    const orphan元素 = 道.find('[data-test="缺口orphan"]')
    // find() 找不到时返回的是空 wrapper，直接调 attributes() 会抛，所以先判 exists
    const orphan = orphan元素.exists() ? Number(orphan元素.attributes('data-count') ?? 0) : 0
    expect(总数 + orphan).toBe(36)
    expect(orphan).toBe(5)
  })

  it('定不了位的 5 个有可见的落脚处，不是悄悄没了', () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 标签 = w.find('[data-test="泳道-L-005"]').find('[data-test="缺口orphan"]')
    expect(标签.exists()).toBe(true)
    expect(标签.text()).toContain('5')
  })

  it('窄容器下落点变少（二次聚合按像素算）', () => {
    const 宽 = mount(LaneChart, { props: { data: 雪, width: 2000 } })
    const 窄 = mount(LaneChart, { props: { data: 雪, width: 400 } })
    const 数 = (w: typeof 宽) => w.find('[data-test="泳道-L-005"]').findAll('[data-test="缺口簇"]').length
    expect(数(窄)).toBeLessThan(数(宽))
  })

  it('t 为 null 的场景不参与画图，也不插值', () => {
    // 雪月梅 L-001 有一个场景 t 是 null
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 道 = w.find('[data-test="泳道-L-001"]')
    const 标签 = 道.find('[data-test="无时间场景"]')
    expect(标签.exists()).toBe(true)
  })
})

describe('LaneChart 交互', () => {
  it('点泳道抛 select-thread', async () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    await w.find('[data-test="泳道-L-001"]').trigger('click')
    expect(w.emitted('select-thread')?.[0]).toEqual(['L-001'])
  })

  it('点缺口簇抛 select-cluster，带上这一簇的全部缺口', async () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 簇 = w.find('[data-test="泳道-L-005"]').find('[data-test="缺口簇"]')
    await 簇.trigger('click')
    const e = w.emitted('select-cluster')?.[0]?.[0] as { threadId: string; gaps: unknown[] }
    expect(e.threadId).toBe('L-005')
    expect(e.gaps.length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 3: 跑测试确认失败，然后写 `LaneChart.vue`**

结构（照原型的 DOM 组织，CSS 用 `tokens.css` 的变量）：

```
.lanes
  .axis        ← 刻度：每个区块画几个整数年的刻度；断口处画斜纹 + 「跨了 N 年」
  .world       ← 世界名（按 data.worlds 分组，颜色用 --w1/--w2/--w3 轮换）
    .lane      ← 一条线，data-test="泳道-L-001"
      .label   ← 线名 + 场景数
      .track
        .seg   ← buildSegments 出来的段，data-test="段"
        .meet  ← 交汇点圆圈，data-test="交汇"
        .ver   ← 多版本角标（Task 20 传进来）
        .mark  ← 断/完/待定，data-test="标记-完" 等
        .gap   ← 缺口簇，data-test="缺口簇"，带 data-count
        .orph  ← orphan 标签，data-test="缺口orphan"，带 data-count
        .nt    ← 「N 个场景估不出时间」，data-test="无时间场景"
```

实现要点：

```ts
const axis = computed(() => buildAxis(
  props.data.threads.flatMap((t) => threadPoints(t))
))
const 查时间 = computed(() => sceneTimeLookup(props.data))
const clusterRatio = computed(() => (28 / (props.width ?? 1200)) * 100)

function 线的段(t: Thread) {
  return axis.value ? buildSegments(threadPoints(t), axis.value) : []
}
function 线的缺口(t: Thread) {
  if (!axis.value) return { clusters: [], orphans: [] }
  const gs = props.data.gaps.filter((g) => g.thread === t.id)
  return layoutGaps(gs, 查时间.value, axis.value, { clusterRatio: clusterRatio.value })
}
function 无时间场景数(t: Thread) {
  return Object.values(t.times ?? {}).filter((v) => v?.t === null || v?.t === undefined).length
}
function 结束标记(t: Thread): '完' | '待定' | '断' {
  const s = t.end?.state ?? ''
  if (s === '完结') return '完'
  if (s === '待定') return '待定'
  return '断'
}
```

**`axis.value` 为 null 时整张图不渲染**，出空态「这本书还没有估出故事时间，先跑完步骤 6」。

颜色：世界用 `--w1` / `--w2` / `--w3` 轮换；段用所属世界的颜色；缺口、断口、排序失败一律 `--red`（spec 7.2：朱红只用于断点/缺口/严重矛盾）。

- [ ] **Step 4: 跑测试与 Commit**

```bash
cd web && npm run test -- src/components/LaneChart.test.ts
git add web/src/components/LaneChart.vue web/src/components/LaneChart.test.ts
git commit -m "feat(web): LaneChart 泳道图，断轴 + 段 + 缺口两层聚合

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 20: 全景页

**Files:**
- Create: `web/src/pages/PanoramaPage.vue`
- Test: `web/src/pages/PanoramaPage.test.ts`

- [ ] **Step 1: 写失败的测试**

```ts
it('拉归线和版本组两份数据', async () => {
  const t = vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
  const v = vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(t).toHaveBeenCalled()
  expect(v).toHaveBeenCalled()
})

it('顶部统计不含任何费用', async () => {
  vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
  vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).not.toContain('$')
  expect(w.text()).not.toContain('费用')
})

it('选中一条线时右侧出详情', async () => {
  vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
  vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  await w.findComponent(LaneChart).vm.$emit('select-thread', 'L-001')
  await flushPromises()
  expect(w.find('[data-test="详情"]').text()).toContain('岑秀')
})

it('详情里显示 end.note（写到哪）', async () => {
  vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
  vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  await w.findComponent(LaneChart).vm.$emit('select-thread', 'L-001')
  await flushPromises()
  expect(w.find('[data-test="详情"]').text()).toContain('大结局')
})

it('点缺口簇时右侧列出那几处缺口的原文', async () => {
  vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
  vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  const gaps = (雪 as unknown as ThreadsFile).gaps.slice(0, 2)
  await w.findComponent(LaneChart).vm.$emit('select-cluster', { threadId: 'L-005', gaps })
  await flushPromises()
  expect(w.find('[data-test="详情"]').text()).toContain(gaps[0].event.slice(0, 8))
})

it('步骤 6 没跑时出空态而不是报错', async () => {
  vi.spyOn(api, 'getThreads').mockResolvedValue({
    next_world: 1, next_thread: 1, time_unit: '年', main_thread: '', main_by: 'auto',
    worlds: [], threads: [], intersections: [], gaps: [], unassigned: [], pending: [],
  })
  vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
  const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('还没有')
})
```

- [ ] **Step 2: 写页面**

- 顶部一条统计：总场景数、线数、世界数、`end.state` 各多少、多版本组数、缺口总数。**不含费用。**
- 中间 `LaneChart`，宽度用 `ResizeObserver` 量容器实际宽度传进去。
- 右侧详情面板，两种模式：选中线（线名/世界/`end.state`/场景数/`about`/`end.note`/该线缺口数/`order_failed` 提示）、选中缺口簇（逐条列 `event` 和 `mentioned_in`）。
- 多版本角标：把 `getVersions` 的 `groups` 按场景编号映射到位置，传给 `LaneChart`。**`VersionGroup` 的真实字段先跑一次接口确认**，别照想象写。

- [ ] **Step 3: 跑测试与 Commit**

```bash
git add web/src/pages/PanoramaPage.vue web/src/pages/PanoramaPage.test.ts
git commit -m "feat(web): 全景页

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 21: 场景浏览页

**Files:**
- Create: `web/src/pages/ScenesPage.vue`
- Test: `web/src/pages/ScenesPage.test.ts`

- [ ] **Step 1: 先确认两个接口的真实返回**

```bash
# 起后端，拿一本真书跑
uv run python -c "
import json
from fastapi.testclient import TestClient
from ligaotai.api import create_app
c = TestClient(create_app())
books = c.get('/api/books').json()
print(json.dumps(books, ensure_ascii=False)[:300])
" > %TEMP%\scenes_probe.txt
```

把 `GET /scenes`、`GET /scenes/{sid}`、`GET /cards/{sid}`、`GET /versions` 的真实返回抄进 `web/src/api/types.ts`，把 `SceneMeta`、`VersionGroup` 补全。**这一步不做完不要往下写**——后面三个页面都要用这些类型。

- [ ] **Step 2: 写测试**

至少覆盖：
- 列表分页/虚拟滚动（西游记 268 个场景，雪月梅 133 个；一次全渲染也还行，但要测「1000 个场景不卡死」用造的数据）。
- 选中一个场景：左边原文（`getScene`）、右边场景卡（`getCard`）。
- 卡还没生成时 `getCard` 返回 404 → 显示「这个场景还没有场景卡」，不是红色报错。
- 版本组并排对比：同组的几个场景并列，能 `setMainVersion`。
- **查重任务在跑时「设为主版本」禁用**（待办那条）：
  ```ts
  it('查重在跑时设为主版本禁用', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue({ /* name: 'dedup', status: 'running' */ } as never)
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    // ...挂载页面，断言按钮 disabled
  })
  ```
- 全文搜索：原文和卡片都搜。
- `GET /scenes` 报 500（场景文件坏了）时显示后端给的文件名。

- [ ] **Step 3: 写页面，跑测试，Commit**

```bash
git add web/src/pages/ScenesPage.vue web/src/pages/ScenesPage.test.ts web/src/api/types.ts
git commit -m "feat(web): 场景浏览页，原文与场景卡并排、版本组对比

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 22: 设定库页

重点：**换模型提示**。

**Files:**
- Create: `web/src/pages/ArchivePage.vue`
- Test: `web/src/pages/ArchivePage.test.ts`

- [ ] **Step 1: 确认 index 的真实结构**

```bash
uv run python -c "
import json, pathlib
p = pathlib.Path('书库')
for d in p.iterdir():
    f = d / '档案' / 'index.json'
    if f.exists():
        print(json.dumps(json.loads(f.read_text(encoding='utf-8')), ensure_ascii=False, indent=1)[:1500])
        break
" > %TEMP%\archive_index.txt
```

没有真书的话，看 `src/ligaotai/archive.py` 里 `load_index` 写进去的字段，以及 `tests/test_archive_index.py` 里的断言。把 `ArchiveIndex` / `ArchiveEntry` 补全。

- [ ] **Step 2: 写测试**

```ts
it('档案的模型跟当前配置不一样时提示', async () => {
  vi.spyOn(api, 'getArchiveIndex').mockResolvedValue({
    current_model: 'deepseek-v5',
    threads: { 'L-001': { model: 'deepseek-flash', outdated: false } },
  } as never)
  const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('deepseek-flash')
  expect(w.text()).toContain('deepseek-v5')
  expect(w.find('[data-test="换模型提示"]').exists()).toBe(true)
})

it('模型一样时不提示', async () => {
  vi.spyOn(api, 'getArchiveIndex').mockResolvedValue({
    current_model: 'deepseek-flash',
    threads: { 'L-001': { model: 'deepseek-flash', outdated: false } },
  } as never)
  const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="换模型提示"]').exists()).toBe(false)
})

it('outdated 的档案要标出来', async () => {
  vi.spyOn(api, 'getArchiveIndex').mockResolvedValue({
    current_model: 'deepseek-flash',
    threads: { 'L-001': { model: 'deepseek-flash', outdated: true } },
  } as never)
  const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.text()).toContain('过期')
})

it('没有 model 字段的老档案不能崩', async () => {
  vi.spyOn(api, 'getArchiveIndex').mockResolvedValue({
    current_model: 'deepseek-flash',
    threads: { 'L-001': {} },
  } as never)
  const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
  await flushPromises()
  expect(w.find('[data-test="换模型提示"]').exists()).toBe(false)
})
```

- [ ] **Step 3: 写页面**

- 左边：支线档案列表 + 世界设定集列表 + 全书地图。每项带 `model`、`outdated` 标记。
- 右边：选中项的正文（`getArchiveBody`），Markdown 按纯文本等宽显示即可（**一期不引 Markdown 渲染库**，档案里有 `S-` 编号和小节名，纯文本已经能读；引库是额外依赖和额外的 XSS 面）。
- 换模型提示条：`entry.model && entry.model !== index.current_model` 时显示「这份是 X 模型写的，当前配置是 Y，要重跑吗」+ 一个调 `rerunArchive` 的按钮。
- `rerunArchive` 只是**标过期**，不立刻跑（看 `archive_rerun` 的 docstring）。按钮文案要说清：「标记为需要重跑（下次跑步骤 7 时才会真跑）」。

- [ ] **Step 4: 跑测试与 Commit**

```bash
git add web/src/pages/ArchivePage.vue web/src/pages/ArchivePage.test.ts web/src/api/types.ts
git commit -m "feat(web): 设定库页，档案模型跟当前配置不一致时提示

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 23: 矛盾页

一期**只展示不裁决**（spec 第 5 章）。

**Files:**
- Create: `web/src/pages/ContradictionsPage.vue`
- Test: `web/src/pages/ContradictionsPage.test.ts`

- [ ] **Step 1: 确认 `矛盾.json` 的真实结构**

看 spec ②c 的 7.2 节（`docs/superpowers/specs/2026-09-16-ligaotai-plan2c-archives-design.md`）和 `src/ligaotai/contradictions.py`。注意 ②c 之后新增了 `verdict_sig` / `verdict_stale` 两个字段（②c 的进度记录里写着「新字段还没写进 spec 7.2」——**以代码为准**）。把 `ContradictionsFile` 补全。

- [ ] **Step 2: 写测试**

- 默认只展开「严重」，「无法判断」和「合理变化」折叠（②c 设计决定 2：矛盾宁可多报，界面默认只展开严重的）。
- 每组显示：主语、属性、几个不同的值、各值出自哪些场景、模型的判断和理由。
- `verdict_stale` 为真的要标出来（「这条判断是在旧数据上做的」）。
- **一期不给裁决按钮**：断言页面上没有「确认矛盾 / 不是矛盾」这类按钮。
- `矛盾.json` 不存在（步骤 7 没跑）时出空态。

- [ ] **Step 3: 写页面，跑测试，Commit**

```bash
git add web/src/pages/ContradictionsPage.vue web/src/pages/ContradictionsPage.test.ts web/src/api/types.ts
git commit -m "feat(web): 矛盾页，一期只展示，默认只展开严重的

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 里程碑 D 完成检查

- [ ] `cd web && npm run test` 全绿，`npm run typecheck` 无报错
- [ ] `uv run pytest -q` 全绿
- [ ] 九个路由都能打开，没有占位组件残留
- [ ] 全局搜一遍确认没有费用泄漏：
  ```bash
  cd web && grep -rn "cost_usd\|price_input\|price_output\|费用\|\\$" src/pages/ src/components/ | grep -v "\.test\.ts"
  ```
  除了测试文件里的断言，应该**一条都没有**。

---

## Task 24: 构建集成与文档

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Test: `tests/test_api_static.py`（加一条真实 dist 的用例）

- [ ] **Step 1: 真构建一次**

```bash
cd web && npm run build
```

Expected: 生成 `web/dist/index.html` 和 `web/dist/assets/*`。`vue-tsc --noEmit` 先跑，有类型错会直接失败。

- [ ] **Step 2: 确认 `web/dist` 和 `web/node_modules` 没被提交**

```bash
git status --short web/
```

`web/.gitignore` 里已经写了这两条（Task 1）。**如果 `git status` 里出现 dist 或 node_modules，先修 .gitignore 再往下走**。

- [ ] **Step 3: 端到端跑一次真的**

```bash
uv run python -m ligaotai
```

浏览器开 `http://127.0.0.1:8765/`：

- [ ] 书架页出得来
- [ ] 随便点进一本书，侧栏九个入口都在
- [ ] 在 `/b/<书名>/panorama` 直接按 F5 刷新，**不是 404**（这是 Task 2 那个 SPA 兜底路由的真实验证）
- [ ] devtools 的 Network 里没有对 `fonts.googleapis.com` 的请求（Task 3 说过不引 Google Fonts）
- [ ] devtools 的 Console 里没有报错

- [ ] **Step 4: README 补一节**

在 README 里加「界面怎么用」：

```markdown
## 界面

后端自带网页界面，开发时需要 Node，**日常使用不需要**。

首次构建：

    cd web
    npm install
    npm run build

然后照常启动后端，浏览器打开 http://127.0.0.1:8765/ ：

    uv run python -m ligaotai

开发时前后端分开跑（前端改动热更新）：

    uv run python -m ligaotai          # 一个终端
    cd web && npm run dev              # 另一个终端，开 http://localhost:5173
```

再补一句界面能做什么（九个页面各一行）。

- [ ] **Step 5: 把总 spec 里被本计划推翻的那两句改掉**

本计划的 spec 第 7.3 节推翻了总 spec 的两处，**总 spec 那个文件到这里还没动过**，不改的话下一个人照它做还会把费用做回来。

改 `docs/superpowers/specs/2026-09-10-ligaotai-design.md`：

1. **第 8 章**那张页面表里，「流水线」一行的作用写着「7 步进度、失败项、重跑、**累计费用估算**」——去掉「累计费用估算」。
2. **第 9 章**那条「从接口返回的 usage 统计 token，乘以设置里的单价，估算累计费用，显示在流水线页」——改成：

   > 从接口返回的 usage 统计 token，连同按单价算出的费用一并记进 `book.json`（`tools/eval_*` 要用）。**界面不显示任何费用数字，也不做事前估价**——估价在本项目里反复失准（②b 估 $1.32 实花 $1.57；②c Task 24 计划里的「约 $0.3」真实是 $2.77～$4.15），作者 2026-09-21 拍板去掉。详见计划③ spec 第 7.3 节。

3. 第 8 章那张表里「实体确认」「归线确认」两行的「期」不变，但在表下补一句：这两页在计划③ 里做成了流水线的子路由（`/b/:name/pipeline/entities`），没有待确认项时导航里收起。

改完 `git diff` 看一眼，确认只动了这三处。

- [ ] **Step 6: 给 `tests/test_api_static.py` 加一条「真 dist 在就服务它」**

```python
def test_仓库里真的构建过就能直接服务(tmp_path):
    """构建过之后，默认的 web/dist 要被找到。没构建过就跳过。"""
    from pathlib import Path
    import ligaotai.api as api_mod

    dist = Path(api_mod.__file__).resolve().parents[2] / "web" / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("web/dist 还没构建，跳过")
    c = TestClient(create_app(app_dir=tmp_path))
    assert c.get("/").status_code == 200
```

- [ ] **Step 7: 跑全量测试与 Commit**

```bash
uv run pytest -q && cd web && npm run test
git add README.md tests/test_api_static.py web/.gitignore docs/superpowers/specs/2026-09-10-ligaotai-design.md
git commit -m "docs: 界面的构建与使用说明，总 spec 去掉费用显示那两句

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 25: 九个页面人工过一遍

**测试和 typecheck 抓不到任何画面硬伤。** 这一步不是走过场——前面所有页面任务的测试都只断言 DOM 结构和数据，没有一条能发现「文字叠在一起」「深色模式下看不见」「1400px 屏上泳道图溢出」。

**Files:**
- Create: `docs/验收记录/2026-XX-XX-计划3-界面.md`（日期按实际）

- [ ] **Step 1: 准备一本有完整数据的书**

`书库/` 里得有一本跑完步骤 1–7 的书。没有的话，从 `data/验收书库/` 里复制一份现成的验收书进 `书库/`（那几本是 ②c 真跑完的，四件产出齐全），**别为了看界面重新花钱跑模型**。

- [ ] **Step 2: 逐页看，每页存一张截图**

按这个清单，**每页都要真的看到，不是假定它对**：

| 页面 | 至少确认 |
|---|---|
| 书架 | 书列表、空态、导入框的路径提示 |
| 流水线 | 七行对齐、状态徽章颜色分得开、失败那行的 error 完整显示、**一个 `$` 都没有** |
| 实体确认 | 待确认组、conflicts 那一区、长名单不溢出 |
| 归线确认 | 排序失败的线够醒目、pending/unassigned 两区、下拉能选线 |
| 全景 | **泳道图是本页重点**：断口斜纹看得见、「跨了 N 年」的字没被挡、缺口角标不重叠、主线宽度明显、右侧详情不溢出 |
| 场景浏览 | 原文与卡片并排、长场景滚动、版本组对比 |
| 设定库 | 档案正文可读、换模型提示条 |
| 矛盾 | 默认只展开严重的、理由文字完整 |
| 设置 | **没有单价字段**、key 打码、测试连接有反馈 |

- [ ] **Step 3: 深色模式再过一遍**

系统切到深色（或在 devtools 里 `Rendering → prefers-color-scheme: dark`），**九页全部再看一遍**。重点看：朱红在深色下够不够亮、段的世界色跟背景分得开、`--sunk` 那半透明的底在深色下会不会糊。

- [ ] **Step 4: 窄窗口过一遍**

把窗口拖到 1000px 左右，看全景页的缺口角标会不会挤在一起（二次聚合应该自动合并，**如果还是挤，说明 `width` 没传对或没监听 resize**）。

- [ ] **Step 5: 写验收记录**

`docs/验收记录/2026-XX-XX-计划3-界面.md`，照 `docs/验收记录/2026-09-21-计划2c-档案矛盾地图.md` 的格式。要写：

- 九页逐页的判定（过 / 有问题，有问题的写清是什么）
- 深色模式和窄窗口两轮的结果
- **没做的和留下的问题**，如实写，别只写好的
- 截图放 `docs/验收记录/图/`

- [ ] **Step 6: 把待办文档里做掉的条目移走**

`docs/已知问题与待办.md` 的「计划③（界面）要处理的」那节，逐条核对：做掉的移到「已解决」并写清做法；没做的留着并说明为什么。

**这一节做完应该基本清空**——留下的只该有「故事时间线冲突检查」那条（明确不做）。

- [ ] **Step 7: Commit**

```bash
git add docs/验收记录/ docs/已知问题与待办.md
git commit -m "docs: 计划③ 界面验收记录，九页逐页过

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 里程碑 E 完成检查

- [ ] `uv run pytest -q` 全绿
- [ ] `cd web && npm run test && npm run typecheck && npm run build` 全绿
- [ ] `python -m ligaotai` 之后浏览器能用，前端路由刷新不 404
- [ ] 九页都人工看过，浅色深色各一遍，验收记录写了
- [ ] `docs/已知问题与待办.md` 的「计划③」那节已清理

## 全部做完之后

按 `superpowers:finishing-a-development-branch` 处理 `plan3` 分支。**推 GitHub 之前先问作者**（本地 master 已经比 origin 多 60 多个提交，历次都是本地合并、暂不推）。
