# LectureLearnLoop 系统架构梳理

> 梳理时间：2026-09-27  
> 分支：web-version（最新提交 d4c62b1 - Flask Web版）  
> 定位：从 Qt 桌面应用改造为 Flask Web 应用的**中间状态**

---

## 一、系统定位

**LectureLearnLoop（柯基学习小助手）** 是一个面向个人的 AI 驱动学习系统，核心理念是 **"学-练-记"闭环**：

1. **学**：从文本资料 / 音频（网课）中，借助 LLM 自动提取知识点
2. **练**：基于知识点 / 错题生成练习题，AI 评估答题结果
3. **记**：知识点掌握度追踪、错题熟练度管理、脑图可视化、学习路径规划

---

## 二、技术栈

| 层面 | 技术选型 | 说明 |
|------|---------|------|
| **后端框架** | Flask 2.0.1 | 从 PySide6 Qt 改造而来 |
| **模板引擎** | Jinja2 3.1.4 | 服务端渲染 |
| **前端样式** | Tailwind CSS (CDN) | 通过 `tailwind.config` 自定义色板 |
| **前端交互** | jQuery 3.7.1 + 原生 Fetch API | 通过 `api.js` 封装统一调用 |
| **树形组件** | jsTree | 文件管理树形结构 |
| **数据库** | SQLite3（内置） | 两套独立数据库文件 |
| **会话管理** | Flask-Session (filesystem) | 文件存储 session |
| **LLM 集成** | 工厂模式，4 种提供商 | Ollama / Gemini / DeepSeek / Qwen |
| **音频处理** | Whisper + PyAudio | 语音转文字（网课笔记） |
| **向量检索** | qdrant-client | 知识点相似度检索（预留） |

---

## 三、项目文件结构

```
LectureLearnLoop/
│
├── app_flask.py                  # ★ Flask 主入口（388行）
├── app_qt.py                     # 原 Qt 入口（3020行，已废弃但保留）
├── config.py                     # 配置定义 + load/save（107行）
├── app_config.json               # 运行时配置（LLM选择、API Key等）
│
├── knowledge_management.py       # ★★ 核心业务逻辑（3192行，8个类）
├── llm_provider_factory.py       # LLM 工厂模式（452行）
├── llm_call_logger.py            # LLM 调用日志记录（296行）
│
├── dal/                          # 数据访问层
│   └── practice_dao.py           # 练习数据 DAO（437行）
├── services/                     # 业务服务层
│   └── practice_service.py       # 练习服务（488行）
├── database/
│   └── create_practice_tables.sql # 练习表建表脚本（150行）
│
├── init_database.py              # 数据库初始化 + 数据迁移脚本
│
├── templates/                    # Jinja2 模板
│   ├── base.html                 # ★ 基础模板（6064行，含大量JS）
│   ├── spa_layout.html           # SPA 布局模板（286行）
│   ├── components/               # 可复用组件
│   │   ├── sidebar.html          # 侧边栏导航（111行）
│   │   ├── header.html           # 顶部栏（9行）
│   │   ├── unsaved_changes_guard.html  # 未保存守卫（368行）
│   │   └── practice_welcome.html # 练习欢迎组件（84行）
│   └── pages/                    # 页面模板
│       ├── dashboard.html        # 工作台（82行）
│       ├── learn_from_materials.html  # 资料学习（4937行）
│       ├── online_course_notes.html   # 网课笔记（11996行）
│       ├── practice_materials.html    # 练习脑图（4610行）
│       ├── knowledge_base.html        # 知识库管理（142行）
│       ├── settings.html              # 设置（630行）
│       ├── llm_logs.html              # LLM日志（428行）
│       ├── practice_knowledge.html    # 知识点练习（56行）
│       ├── practice_errors.html       # 错题练习（69行）
│       ├── memory_knowledge.html      # 知识点记忆（81行）
│       ├── memory_errors.html         # 错题记忆（103行）
│       └── *_backup.html              # 多个备份文件
│
├── static/js/
│   ├── api.js                    # ★ API 封装（423行）
│   ├── jquery-3.7.1.min.js
│   ├── jstree.min.js
│   └── practice_welcome.js
│
├── vault/                        # 用户笔记文件存储（Markdown）
├── conversations/                # 对话历史 JSON
├── logs/                         # 应用日志
├── geminworklog/                 # Gemini 工作日志
├── requirements.txt              # Python 依赖（237个）
└── .gitignore
```

---

## 四、后端架构详解

### 4.1 Flask 应用入口（app_flask.py）

```
启动流程:
  app_flask.py
  ├── 创建 Flask app
  ├── 配置 Session（filesystem）、CORS（全开）、日志（RotatingFileHandler）
  ├── 初始化全局业务对象:
  │     config = load_config()
  │     km_system = KnowledgeManagementSystem(config)
  │     llm_factory = LLMProviderFactory()
  ├── 定义页面路由（7个）
  ├── 定义 API 路由（10个）
  └── app.run(debug=True, host=0.0.0.0, port=5000)
```

**页面路由表：**

| 路由 | 模板 | 功能 |
|------|------|------|
| `/` | `pages/dashboard.html` | 工作台首页 |
| `/learn_materials` | `pages/learn_from_materials.html` | 资料学习 |
| `/online_course` | `pages/online_course_notes.html` | 网课笔记 |
| `/practice` | `pages/practice_materials.html` | 练习脑图 |
| `/knowledge_base` | `pages/knowledge_base.html` | 知识库管理 |
| `/settings` | `pages/settings.html` | 系统设置 |
| `/llm_logs` | `pages/llm_logs.html` | LLM调用日志 |

**已实现的 API 端点：**

| 方法 | 端点 | 功能 | 状态 |
|------|------|------|------|
| POST | `/api/knowledge/extract` | 提取知识点 | ✅ 已实现 |
| GET | `/api/knowledge/list` | 获取知识点列表 | ✅ 已实现 |
| POST | `/api/knowledge/create` | 创建知识点 | ✅ 已实现 |
| POST | `/api/llm/call` | 调用 LLM | ✅ 已实现 |
| GET | `/api/llm/logs` | LLM 调用日志 | ✅ 已实现 |
| GET | `/api/llm/stats` | LLM 调用统计 | ✅ 已实现 |
| GET | `/api/config/get` | 获取配置 | ✅ 已实现 |
| POST | `/api/config/save` | 保存配置 | ✅ 已实现 |
| POST | `/api/file/save` | 保存文件 | ✅ 已实现 |
| GET | `/api/file/load` | 加载文件 | ✅ 已实现 |

**前端已定义但后端未实现的 API：**

| 模块 | 缺失端点 | 影响 |
|------|---------|------|
| 练习 | `/api/practice/generate`, `/evaluate`, `/history`, `/detail`, `/save` | 练习功能完全不可用 |
| 笔记 | `/api/notes/save`, `/load`, `/list`, `/delete` | 笔记管理不可用 |
| 文件 | `/api/file/list`, `/delete`, `/upload` | 文件管理不完整 |
| 配置 | `/api/config/reset` | 无法重置配置 |
| LLM | `/api/llm/test` | 设置页测试连接不可用 |

### 4.2 核心业务层（knowledge_management.py）

**8 个类的职责与行数：**

```
knowledge_management.py (3192行)
│
├── DatabaseManager (L16-248)         数据库初始化 + 连接管理
│   └── 创建 10+ 张表，含迁移逻辑
│
├── SubjectManager (L251-308)         学科管理
│   └── 增/查/改学科
│
├── KnowledgePointManager (L311-1071) 知识点管理（最重）
│   ├── extract_knowledge_points()    LLM 提取知识点 + 自动降级
│   ├── save/find/merge 知识点
│   ├── find_similar_knowledge_points 相似度匹配
│   └── 内含 _extract_with_deepseek/gemini/ollama/qwen 四个私有方法
│
├── PracticeRecordManager (L1073-1106) 练习记录管理
│   └── 保存/查询练习记录
│
├── ErrorQuestionManager (L1108-1449)  错题管理
│   ├── 错题 CRUD + 熟练度追踪
│   ├── generate_targeted_questions()  针对性出题（含LLM调用）
│   └── 熟练度历史时间序列
│
├── LegacyKnowledgeManagementSystem (L1451-1748)  旧版系统（保留）
│
├── KnowledgeManagementSystem (L1776-2468)  ★ 主系统类
│   ├── 组合所有子管理器
│   ├── 知识点提取 + 确认 + 保存
│   ├── 笔记注册 + UUID关联
│   ├── 错题/收藏/练习 统一入口
│   └── 脑图/学习路径 生成与缓存
│
└── MindmapManager (L2470-3192)        脑图 + 学习路径
    ├── 脑图 CRUD + LLM 生成
    ├── 学习路径 CRUD + LLM 生成
    └── 熟练度/知识点信息合并
```

### 4.3 LLM 调用架构

```
                    ┌──────────────────────┐
                    │  knowledge_management │
                    │      .py             │
                    │                      │
                    │  KnowledgePointMgr   │──→ 直接调用各 LLM API
                    │  ErrorQuestionMgr    │    （未走工厂，重复实现）
                    └──────────────────────┘
                                │
                    ┌──────────────────────┐
                    │ llm_provider_factory │
                    │      .py             │
                    │                      │
                    │  LLMProviderFactory  │──→ 统一工厂入口
                    │   ├─ OllamaProvider  │    （脑图/学习路径使用）
                    │   ├─ GeminiProvider  │
                    │   ├─ DeepSeekProvider│
                    │   └─ QwenProvider    │
                    └──────────────────────┘
                                │
                    ┌──────────────────────┐
                    │  llm_call_logger.py  │
                    │                      │
                    │  LLMCallLogger       │──→ 记录每次调用
                    │  (单例 + 线程安全)    │    写入 JSONL 日志
                    └──────────────────────┘
```

**关键问题：** `knowledge_management.py` 中的 `KnowledgePointManager` 和 `ErrorQuestionManager` **各自直接调用 LLM API**（含 `_extract_with_deepseek`、`_extract_with_gemini` 等私有方法），没有复用 `llm_provider_factory.py` 的工厂模式。导致 LLM 调用逻辑存在两套实现。

**自动降级链：**
- 选 DeepSeek → 失败 → Gemini → 失败 → Ollama → 失败 → 规则提取
- 选 Gemini → 失败 → Ollama → 失败 → 规则提取
- 选 Qwen → 失败 → Ollama → 失败 → 规则提取
- 选 Ollama → 失败 → Gemini → 失败 → 规则提取

### 4.4 配置管理

```
config.py
  ├── 编译时默认值（SUMMARY_PROMPT、LLM_PROVIDER 等）
  ├── load_config() → 从 app_config.json 读取，缺失字段用默认值补齐
  └── save_config() → 写入 app_config.json

app_config.json（运行时配置）
  ├── llm_provider: 当前选择的 LLM 提供商
  ├── 各提供商的 API Key / URL / Model
  ├── 总结模式配置
  └── LLM 日志开关
```

---

## 五、前端架构详解

### 5.1 模板继承关系

```
base.html (6064行)
  ├── 定义全局 CSS 样式 + AI 助手浮窗样式
  ├── 引入 api.js（API 封装）
  ├── 引入 Tailwind CSS (CDN)
  ├── 引入 Material Icons
  ├── 包含 unsaved_changes_guard.html
  ├── {% block extra_head %}
  ├── {% block content %}           ← 子模板填充
  ├── 大量内联 JavaScript:
  │     ├── AI 助手浮窗（拖拽、聊天、总结）
  │     ├── 菜单路由映射 menuRoutes
  │     ├── handleMenuClick() 导航函数
  │     └── bridgeReady 事件触发
  └── {% block on_bridge_ready %}   ← 子模板的初始化代码

spa_layout.html extends base.html
  ├── 包含 sidebar.html
  ├── 包含 header.html
  └── {% block page_content %}

各 pages/*.html 有两种使用方式：
  方式1: extends base.html（直接继承，如 dashboard.html）
  方式2: extends spa_layout.html（通过SPA布局，含侧边栏）
```

### 5.2 前端导航机制

```javascript
// base.html 中定义的路由映射
const menuRoutes = {
    'dashboard':              '/',
    'learn_from_materials':   '/learn_materials',
    'online_course_notes':    '/online_course',
    'practice_knowledge':     '/practice',
    'practice_materials':     '/practice',
    'memory_knowledge':       '/practice',
    'knowledge_base':         '/knowledge_base',
    'settings':               '/settings',
    'llm_logs':               '/llm_logs'
};

// 点击菜单 → handleMenuClick() → window.location.href = route
// 注意：这是全页面跳转，不是 SPA 局部加载
```

### 5.3 API 封装层（api.js）

```
api.js
├── class API              通用请求封装（fetch + JSON）
│   ├── request()          统一请求方法
│   ├── get/post/put/delete
│
├── KnowledgeAPI           知识点: extract / list / create / update / delete
├── PracticeAPI            练习: generate / evaluate / getHistory / getDetail / save
├── LLMAPI                 LLM: call / getLogs / getStats / test
├── FileAPI                文件: save / load / list / delete / upload
├── NoteAPI                笔记: save / load / list / delete
├── ConfigAPI              配置: get / save / reset
│
└── window.pybridge        兼容层（模拟原 Qt QWebChannel 桥接）
    ├── extractKnowledgePoints(text, callback)
    ├── getKnowledgePoints(subject, callback)
    ├── callLLM(prompt, provider, callback)
    ├── saveFile(path, content, callback)
    ├── loadFile(path, callback)
    ├── getConfig(callback)
    └── saveConfig(config, callback)
```

**设计意图：** 通过 `pybridge` 兼容层，原有前端代码中 `window.pybridge.xxx()` 的调用无需修改，只需将底层实现从 QWebChannel 替换为 Fetch API。

---

## 六、数据库架构

### 6.1 两套独立数据库

| 数据库文件 | 管理者 | 用途 |
|-----------|--------|------|
| `knowledge_management.db` | `DatabaseManager`（knowledge_management.py） | 知识点、错题、笔记、脑图 |
| `practice_history.db` | `PracticeDAO`（dal/practice_dao.py） | 练习会话、提交、评估 |
| `practice_data.db` | `PracticeService`（services/practice_service.py） | 练习数据（与上面功能重叠） |

### 6.2 knowledge_management.db 表结构

```
user_subjects          用户学科（user_id, subject_name）
knowledge_points       知识点（subject, point_name, mastery_score）
practice_records       练习记录（question, answer, is_correct）
error_questions        错题（proficiency, correct_answer, explanation）
error_proficiency_history  错题熟练度历史（时间序列）
notes                  笔记（note_uuid, file_path, content_hash）
knowledge_point_sources   知识点-笔记来源关联
knowledge_mindmaps     知识脑图缓存（JSON）
learning_paths         学习路径缓存（JSON）
favorite_questions     收藏题目
```

### 6.3 practice_history.db 表结构

```
practice_sessions      练习会话（practice_id, selected_text, questions, status）
practice_submissions   答题提交（user_answers, time_spent）
practice_evaluations   AI评估（evaluation_result, score, level）
practice_statistics    统计（total_submissions, avg_score, best_score）

VIEW: practice_history_overview   汇总视图
TRIGGER: update_practice_statistics_on_submission    自动更新统计
TRIGGER: update_practice_statistics_on_evaluation    自动更新统计
```

---

## 七、核心业务流程

### 7.1 知识点提取流程

```
用户输入文本 → KnowledgePointManager.extract_knowledge_points()
  │
  ├── 构建 Prompt（要求提取核心概念，JSON 格式输出）
  ├── 根据配置选择 LLM 提供商
  ├── 调用 LLM（失败则自动降级）
  ├── 解析 JSON 结果
  │
  ▼
  extract_and_process_knowledge_points()
  │
  ├── 对每个提取的知识点:
  │     └── find_similar_knowledge_points() → 查找已有相似项
  │
  ▼
  返回给前端 → 用户确认（merge/new/skip）
  │
  ▼
  confirm_knowledge_points()
  │
  ├── merge → 合并到已有知识点
  ├── new   → 创建新知识点 + 关联笔记 UUID
  └── skip  → 跳过
```

### 7.2 练习流程（设计意图 vs 实际状态）

```
设计意图:
  选择知识点/文本 → 生成练习题 → 用户答题 → AI评估 → 记录统计

实际状态:
  前端 PracticeAPI 已定义 → 后端 API 端点未实现 → ❌ 不可用
```

### 7.3 脑图/学习路径生成流程

```
用户请求 → MindmapManager
  │
  ├── 检查数据库缓存
  │     ├── 命中 → 直接返回
  │     └── 未命中 → 继续
  │
  ├── 获取学科知识点列表
  ├── 构建 Prompt（含知识点列表 + JSON格式要求）
  ├── 调用 LLMProviderFactory.call_llm()
  ├── 解析 JSON 响应
  ├── 合并熟练度信息到节点
  ├── 保存到数据库缓存
  └── 返回给前端渲染
```

---

## 八、架构问题清单

### P0 - 阻塞性问题（功能不可用）

| # | 问题 | 影响范围 | 说明 |
|---|------|---------|------|
| 1 | **练习模块后端 API 全部缺失** | 练习功能 | 前端定义了 5 个 PracticeAPI，后端一个都没实现 |
| 2 | **笔记模块后端 API 全部缺失** | 笔记管理 | 前端定义了 4 个 NoteAPI，后端一个都没实现 |
| 3 | **文件管理 API 不完整** | 文件列表/删除/上传 | 只实现了 save/load，缺 list/delete/upload |

### P1 - 严重问题（安全 / 数据）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 4 | API Key 硬编码在源码中 | `config.py` L66, `settings.html` L157 | 通义千问 Key 明文暴露 |
| 5 | API Key 明文存储 | `app_config.json` | 无加密保护 |
| 6 | SECRET_KEY 每次重启变化 | `app_flask.py` L33 | `os.urandom(24)` 导致所有用户 Session 失效 |
| 7 | 路径遍历风险 | `app_flask.py` L290-293 | `startswith` 检查可被编码绕过 |
| 8 | CORS 全开 | `app_flask.py` L40 | 生产环境安全隐患 |

### P2 - 架构设计问题

| # | 问题 | 说明 |
|---|------|------|
| 9 | **LLM 调用两套实现** | `knowledge_management.py` 直接调用各 LLM API，未复用 `llm_provider_factory.py` |
| 10 | **两套数据库** | `knowledge_management.db` 和 `practice_history.db` 独立，无统一连接管理 |
| 11 | **三套练习数据层** | `PracticeDAO` + `PracticeService` + `practice_data.db` / `practice_history.db` 功能重叠 |
| 12 | **巨型文件** | `base.html` 6064行、`online_course_notes.html` 11996行、`knowledge_management.py` 3192行 |
| 13 | **全局状态** | `config` 和 `km_system` 作为全局变量，`api_save_config` 用 `global` 修改 |
| 14 | **无连接池** | 每次数据库操作都新建连接 `sqlite3.connect()` → 操作 → `close()` |
| 15 | **无用户认证** | user_id 硬编码 `"0001"`，无登录/注册 |

### P3 - 代码质量问题

| # | 问题 | 说明 |
|---|------|------|
| 16 | 无输入验证 | API 端点不校验参数类型/长度 |
| 17 | 错误响应格式不统一 | 有些返回 `{success, data}`，有些直接抛异常 |
| 18 | 无事务回滚 | 多数数据库操作缺少 rollback |
| 19 | 无单元测试 | 整个项目零测试 |
| 20 | 依赖臃肿 | 237 个依赖，含 torch/transformers 等大型库 |
| 21 | 前端无请求超时 | Fetch API 调用无 timeout 设置 |
| 22 | Dashboard 数据写死 | 统计数字使用 `default(12)` 等硬编码值 |
| 23 | 多个 backup 文件 | `*_backup.html` 散落在 templates 中，应纳入版本管理 |

---

## 九、模块依赖关系图

```
app_flask.py
  ├── config.py ─────────── load_config / save_config
  ├── knowledge_management.py ─── KnowledgeManagementSystem
  │     ├── DatabaseManager ── SQLite (knowledge_management.db)
  │     ├── SubjectManager
  │     ├── KnowledgePointManager ── 直接调用 LLM API ⚠️
  │     ├── PracticeRecordManager
  │     ├── ErrorQuestionManager ── 直接调用 LLM API ⚠️
  │     ├── FavoriteQuestionManager
  │     └── MindmapManager ── LLMProviderFactory ✅
  ├── llm_provider_factory.py ─── LLMProviderFactory
  │     ├── OllamaProvider
  │     ├── GeminiProvider
  │     ├── DeepSeekProvider
  │     └── QwenProvider
  └── llm_call_logger.py ─── LLMCallLogger

前端模板
  base.html
    ├── api.js ─── API 封装
    │     └── window.pybridge ─── 兼容层
    ├── sidebar.html ─── 导航菜单
    └── pages/*.html ─── 各页面

练习子系统（独立）
  dal/practice_dao.py ─── PracticeDAO ── SQLite (practice_history.db)
  services/practice_service.py ─── PracticeService ── SQLite (practice_data.db)
  database/create_practice_tables.sql ─── 建表脚本
```

---

## 十、当前状态总结

### 已完成
- [x] Flask 基础框架搭建（路由、模板渲染、Session、CORS）
- [x] 知识点提取 API（/api/knowledge/extract, list, create）
- [x] LLM 调用 API（/api/llm/call, logs, stats）
- [x] 配置管理 API（/api/config/get, save）
- [x] 文件读写 API（/api/file/save, load）
- [x] 前端 api.js 封装 + pybridge 兼容层
- [x] 前端页面模板（7个页面 + 组件）
- [x] AI 助手浮窗（聊天 + 总结）
- [x] LLM 多提供商工厂 + 自动降级
- [x] LLM 调用日志系统
- [x] 知识脑图 / 学习路径生成（含缓存）

### 未完成
- [ ] 练习模块后端 API（5个端点）
- [ ] 笔记管理后端 API（4个端点）
- [ ] 文件管理补全（list/delete/upload）
- [ ] 前端页面与后端 API 的对接联调
- [ ] 用户认证系统
- [ ] 单元测试

### 需要重构
- [ ] 统一 LLM 调用路径（全部走工厂）
- [ ] 合并两套练习数据库
- [ ] 拆分巨型文件（base.html、knowledge_management.py）
- [ ] API Key 安全存储（环境变量 / 加密）
- [ ] 数据库连接池
