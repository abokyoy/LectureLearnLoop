---
kind: frontend_style
name: 基于 Tailwind CSS CDN + Material Icons 的 Flask Jinja2 模板样式体系
category: frontend_style
scope:
    - '**'
source_files:
    - server/templates/base.html
    - server/templates/spa_layout.html
    - desktop/renderer/index.html
    - docs/原则/系统架构梳理.md
---

## 1. 整体方案

本仓库的前端 UI 由两部分组成：
- **Flask 服务端渲染页面**（`server/templates/`）：采用 Jinja2 模板，通过 `<script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>` 在运行时加载 Tailwind CSS（CDN），并通过 `tailwind.config` 注入自定义色板、字体与圆角。
- **Electron 桌面客户端**（`desktop/renderer/index.html`）：极简引导页，使用内联 `<style>`，不依赖任何前端框架或样式库。

没有独立的 `.css` / `.scss` 文件，也没有构建工具链（无 webpack/vite/postcss）。Tailwind 以浏览器端 JIT 模式运行，所有样式类直接写在 HTML 中。

## 2. 关键文件

- `server/templates/base.html`：全局布局基模板，集中定义 Tailwind 配置、Material IconsOutlined 字体图标、统一弹窗（覆盖原生 `alert`）、AI 助手浮窗等样式。
- `server/templates/spa_layout.html`：SPA 子页面共享布局。
- `server/templates/pages/*.html`：各业务页面（笔记、知识点、练习、在线课程笔记等），大量使用 Tailwind utility class。
- `server/templates/components/*.html`：可复用组件片段（如 `unsaved_changes_guard.html`、`user_settings.html`）。
- `desktop/renderer/index.html`：Electron 渲染进程入口，仅含内联样式。
- `docs/原则/系统架构梳理.md`：文档明确记录“前端样式 = Tailwind CSS (CDN)，通过 tailwind.config 自定义色板”。

## 3. 设计令牌与主题约定

Tailwind 配置集中在 `base.html` 的 `tailwind.config` 对象中：

- **主色** `primary: "#32C77F"`（绿色），配合 `warning: "#FF9B27"`、`danger: "#ED4B4B"`。
- **文本色**：`text-dark-brown`、`text-medium-brown`、`text-gray`。
- **背景色**：`bg-light-blue`、`bg-beige`、`bg-light-green`、`bg-light-gray`、`bg-light-blue-gray`。
- **字体**：`sans: ['"Noto Sans SC"', 'sans-serif']`，中文优先 Noto Sans SC。
- **圆角**：扩展 `xl: '1rem'`。
- **暗色模式**：启用 `darkMode: "class"`，但当前模板中未见实际 dark 类切换逻辑。

图标统一使用 Google 的 `Material Icons Outlined`（`<link href="...Material+Icons+Outlined" rel="stylesheet">`），通过 `material-icons-outlined` 类名调用，如 `quiz`、`add_circle_outline`、`history`、`school` 等。

## 4. 样式组织惯例

- **全局样式**：`base.html` 的 `<style>` 块承载跨页面复用的组件样式（AI 助手浮窗、统一 alert 弹窗、debug 面板、积分徽章等）。
- **页面级样式**：部分页面（如 `online_course_notes.html`）内嵌 `<style>` 处理 jstree、highlight.js、katex 等第三方库的主题覆盖。
- **行内样式**：大量使用 `style.cssText` 或 `element.style.xxx` 动态设置（toast、调试面板、设备选择器等），属于快速实现风格，尚未统一到 CSS 类。
- **Jinja2 组件化**：通过 `{% include "components/..." %}` 复用 UI 片段，而非 CSS 组件。

## 5. 开发者应遵循的规则

1. **新增页面**：继承 `base.html` 或 `spa_layout.html`，不要重复引入 Tailwind CDN 或 Material Icons。
2. **颜色/字体/圆角**：优先使用已定义的 Tailwind 自定义 token（`text-primary`、`bg-light-blue`、`rounded-xl` 等），禁止硬编码十六进制色值。
3. **图标**：统一使用 `material-icons-outlined` 类 + Google 图标名，不使用 emoji 作为功能图标。
4. **复杂交互组件**：若需要多状态样式，先在 `base.html` 的 `<style>` 中定义 CSS 类，再在 JS 中切换类名；避免继续堆砌 `style.cssText`。
5. **第三方库样式**：如需引入 highlight.js / katex / jstree 等，保持其 CDN 引用位置一致，并在对应页面顶部集中管理。
6. **Electron 渲染页**：`desktop/renderer/index.html` 是独立轻量页，不继承 Flask 模板，保持内联样式即可。
7. **禁用原生对话框**：已有覆盖 `window.alert` 的统一弹窗实现，业务代码应继续使用 `alert()`，不要自行实现新弹窗。