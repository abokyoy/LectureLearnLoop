---
kind: dependency_management
name: 多语言依赖管理：Python requirements.txt + Node package.json 双轨制
category: dependency_management
scope:
    - '**'
source_files:
    - server/requirements.txt
    - desktop/package.json
    - desktop/package-lock.json
    - tools/node/package.json
    - tools/node/package-lock.json
    - start_app.ps1
    - AGENTS.md
---

## 总体方案

本仓库是一个聚合型项目，包含 Flask 服务端、Electron 桌面客户端与若干 Node 工具脚本，因此采用**按子工程隔离的依赖声明**方式，没有统一的顶层 `requirements.txt` 或 `package.json`。

| 子系统 | 包管理器 | 依赖清单 | 锁定文件 | 私有源/镜像 |
|---|---|---|---|---|
| Python（Flask 服务端） | pip | `server/requirements.txt` | 无（未提交 lockfile） | 默认 PyPI |
| Electron 桌面端 | npm | `desktop/package.json` | `desktop/package-lock.json`（lockfileVersion=3） | npm 镜像 `registry.npmmirror.com` |
| tools/node 工具集 | npm | `tools/node/package.json` | `tools/node/package-lock.json` | npm 镜像 `registry.npmmirror.com` |

## Python 侧：`server/requirements.txt`

- 位于 `server/requirements.txt`，仅声明运行时依赖，共 9 个顶级包：
  - Web 框架：`flask>=3.0`、`flask-cors>=4.0`
  - 认证：`pyjwt>=2.8`
  - 配置：`python-dotenv>=1.0`
  - HTTP 客户端：`httpx>=0.27`、`requests`（无版本约束）
  - 数据库：`psycopg2-binary>=2.9`（PostgreSQL 驱动）
  - 语音服务：`deepgram-sdk>=3.7`、`websockets`
- **未使用** `Pipfile` / `poetry` / `pyproject.toml` / `setup.py`，也没有 `requirements-dev.txt` 或测试专用依赖清单。
- **未提交** `requirements.lock` / `pip freeze` 产物，可重现性完全依赖 CI 或开发机上的 pip 缓存；这也是文档中记录的“掉坑”来源之一（如 FSRS 包在不同版本间语义不一致）。
- PowerShell 启动脚本 `start_app.ps1` 在启动前检查服务是否就绪，并提示 `pip install -r server\requirements.txt and server\.env`，把依赖安装视为前置步骤而非自动化流程的一部分。

## Node 侧：`desktop/package.json` + `tools/node/package.json`

- `desktop/package.json`：
  - 运行依赖仅 `ws ^8.18.0`（WebSocket 客户端），用于与后端通信。
  - 开发依赖 `electron ^37.0.0`，通过 `scripts.start` / `scripts.start:debug` 启动。
  - 已提交 `package-lock.json`（lockfileVersion=3），锁定所有传递依赖及 sha512 integrity。
  - 从 lock 文件中可见实际解析到的是 `https://registry.npmmirror.com/...`，说明本地或全局 npm 配置了国内镜像。
- `tools/node/package.json`：
  - 仅一个依赖 `@ffmpeg-installer/ffmpeg ^1.1.0`，并通过 optionalDependencies 按平台分发二进制（darwin-arm64/x64、linux-arm/arm64/ia32/x64、win32-ia32/x64）。
  - 同样有 `package-lock.json` 锁定。

## 约定与规则（来自 AGENTS.md 与计划文档）

1. **新增依赖必须先查 `requirements.txt`**：AGENTS.md 明确禁止“引入新的依赖库不评估影响”，要求先审查现有依赖再决策。
2. **显式化隐性依赖**：改造方案文档明确要求将 `psycopg2-binary>=2.9` 补入 `requirements.txt`，因为此前它是作为 psycopg2 的可选依赖被隐式拉入的——这是本次仓库对依赖声明规范的一次修正。
3. **版本号策略**：Python 侧普遍使用 `>=X.Y` 宽松下限，Node 侧使用 `^` 语义化版本范围；两者均未做严格的版本上限锁定。
4. **无 vendoring**：未发现 `vendor/`、`third_party/` 或任何源码级 vendoring 目录；所有第三方代码均通过包管理器下载至 `node_modules` / pip cache。
5. **无私有注册表配置**：未见 `.npmrc`、`.pypirc`、`PIP_INDEX_URL` 等私有源配置；npm 锁文件中的 `resolved` URL 指向 `registry.npmmirror.com`，是镜像而非私有源。
6. **环境隔离**：Python 侧通过 `server/.env` / `server/.env.example` 管理环境变量，但依赖本身不与环境绑定（无 `pyproject.toml` 的 `[tool.poetry]` 或 PEP 621 元数据）。

## 开发者应遵循的规则

- 新增 Python 依赖 → 编辑 `server/requirements.txt`，优先加最小版本下限（`>=`），避免裸写包名（如 `requests` 应改为 `requests>=X.Y`）。
- 新增 Node 依赖 → 编辑对应子工程的 `package.json`，并在提交前运行 `npm install` 生成/更新 `package-lock.json`。
- 升级依赖时注意跨版本语义差异（FSRS 包的历史教训已在 `docs/掉坑笔记/掉坑笔记.md` 记录）。
- 不要手动修改 `package-lock.json` 或 `requirements.txt` 中的哈希值；由包管理器生成。
- 不要在根目录新增 `requirements.txt` 或 `pyproject.toml` 来覆盖子工程隔离结构。