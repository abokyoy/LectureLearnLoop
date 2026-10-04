# 柯基学习乐园 设计系统（DESIGN.md）

> 定稿依据：Stitch 混合主题候选稿 `design/stitch_candidates/D_orange_mint_mix.png`（2026-10-01 用户拍板 A/C 混合方向）。
> 本文档是全套界面重设计的唯一设计契约，所有页面改造必须引用此处的 token，禁止散落自定义色值/圆角/阴影（见 AGENTS.md 架构收敛原则）。
> 代码实现载体：CSS 变量（`--cl-*` 前缀）+ Tailwind 工具类；组件规范对齐 ui-generator-skill（禁手写原生 CSS 样式值、禁行内样式）。

## 1. 设计基调

- 面向学生的现代极简 SaaS 学习软件：明快、简洁、轻松、略带小可爱
- 拒绝后台管理系统感；拒绝蓝绿紫多主色失控
- 橙色为主行动色、薄荷绿为辅助点缀色，两色不同权重，禁止打架

## 2. 色彩 Token

| Token | 值 | 用途 |
|-------|-----|------|
| `--cl-primary` | `#F97316` | 主按钮、当前导航态、关键数字强调 |
| `--cl-primary-hover` | `#EA6C0B` | 主按钮 hover |
| `--cl-primary-soft` | `#FFF1E7` | 主色浅底（选中项背景、橙色徽标底） |
| `--cl-secondary` | `#10B981` | 进度条、成功徽标、「记」模块点缀 |
| `--cl-secondary-soft` | `#E7F8F1` | 绿色浅底 |
| `--cl-bg` | `#FAF7F2` | 页面背景（米白暖灰） |
| `--cl-surface` | `#FFFFFF` | 卡片/面板表面 |
| `--cl-border` | `#EFE9E0` | 极细边框（1px） |
| `--cl-text` | `#292524` | 主文字（stone-800） |
| `--cl-text-2` | `#78716C` | 辅助文字 |
| `--cl-text-3` | `#A8A29E` | 占位/弱化文字 |
| `--cl-danger` | `#EF4444` | 错误、删除 |
| `--cl-warning` | `#F59E0B` | 警示 |

色彩纪律：一屏之内主色（橙）只出现在行动点与关键数字；绿色仅用于状态与进度；不得出现 token 表以外的彩色。

## 3. 字体与字阶

- 字体族：`system-ui, "PingFang SC", "Microsoft YaHei", sans-serif`
- 字阶（桌面 1280 基准）：

| 层级 | 字号/字重 | 用途 |
|------|----------|------|
| display | 28px / 700 | 页面大数字（掌握度等） |
| h1 | 22px / 700 | 页面标题 |
| h2 | 17px / 600 | 卡片标题、区块标题 |
| body | 14px / 400 | 正文（基准） |
| caption | 12px / 400 | 辅助说明、时间戳 |

## 4. 圆角 / 阴影 / 描边

- 圆角：卡片 `12px (rounded-xl)`、按钮/输入框 `10px (rounded-lg)`、徽标/头像 `full`
- 边框：统一 `1px solid var(--cl-border)`，禁止灰黑粗边框
- 阴影：静态 `0 1px 2px rgba(41,37,36,.04)`；hover 卡片 `0 6px 16px rgba(41,37,36,.08)`；禁止多层重阴影

## 5. 间距

- 8px 网格；页面内容区左右 padding `32px`，区块垂直间距 `24px`，卡片内 padding `20-24px`，卡片间 gap `16-20px`

## 6. 布局骨架（壳层规范）

- 左侧边栏：宽 `72px` 窄图标栏（图标+12px 文字），项：工作台、学、练、记、知识库、设置；底部用户头像；当前项 `--cl-primary-soft` 底 + 橙色图标
- 顶栏：高 `56px`，仅页面标题 + 右侧轻操作（连续学习天数徽标等），不放搜索大框浪费空间
- 主区：`max-width 1120px` 居中，滚动内容区

## 7. 核心组件规范

| 组件 | 规范 |
|------|------|
| 主按钮 | 橙底白字 rounded-lg，hover 加深；每屏至多 1 个主按钮 |
| 次按钮 | 白底橙字橙边（ghost-outline） |
| 功能卡 | 白底 + 1px 细边 + 微阴影；左上模块图标（学=橙、练=橙、记=绿）、标题、一句说明、大数字、底部操作按钮 |
| 徽标 | 浅底深字（primary-soft/secondary-soft），rounded-full，caption 字号 |
| 活动列表项 | 48px 圆形图标底 + 标题/摘要两行 + 右侧时间/操作，行间 1px 分隔 |
| 进度条 | 高 6px rounded-full，绿底轨道 `--cl-secondary-soft`，填充 `--cl-secondary` |
| 空态 | 插画位（可用柯基元素）+ 一句引导 + 行动按钮，禁止裸文字"暂无数据" |
| 图标 | Lucide 线性图标，统一 1.5px 描边，禁止 Material Icons CDN 依赖（走查 G4） |

## 8. 暗色悬浮窗（overlay）

- 悬浮窗保持深色独立主题：底 `#1C1917`（stone-900）透明度 92%，文字 `#FAFAF9`，强调橙 `#FB923C`；控件必须与主题同源（禁原生 select/input 裸样式，走查 G7）

## 9. 验收基准

每屏重设计完成后，用 `server/tests/ui_pw_shot.py` 截图与本文档逐条对照 + 识图审查，须满足：token 色值一致、字阶一致、组件规范一致、无 Material Icons 退化文本、空态/真实数据无假数。

*定稿日期：2026-10-01*
