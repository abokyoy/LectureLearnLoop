---
kind: build_system
name: 基于 PowerShell 的轻量级构建与打包流程
category: build_system
scope:
    - '**'
source_files:
    - start_app.ps1
    - server/tests/p7_package.ps1
    - desktop/package.json
    - server/requirements.txt
    - server/.env.example
---

## 总体方案
本项目没有 Makefile、Dockerfile、CI 流水线或 `pyproject.toml`，也没有统一的构建工具链。构建与发布完全依赖 **PowerShell 脚本** + **Electron 原生 dist 复制** + **Python requirements.txt**，属于“手工脚本驱动”的轻量级方式。

## 关键文件与职责
- `start_app.ps1`（根目录）：一键启动入口。默认拉起 Flask 服务端（`server/app.py`，端口 6001），然后启动已打包的便携版客户端 `dist/win-unpacked/LectureLearnLoop.exe`；传入 `-Dev` 则直接通过 `desktop/node_modules/electron/dist/electron.exe` 从源码运行 Electron，并开启 CDP `:9222` 供自动化测试使用。
- `server/tests/p7_package.ps1`：便携版打包脚本。原理是复制 Electron 官方 `desktop/node_modules/electron/dist` 到 `dist/win-unpacked`，再把 `desktop/main.js / preload.js / asr_proxy.js / package.json` 以及运行时依赖 `ws` 注入到 `resources/app`，最后把 `electron.exe` 重命名为 `LectureLearnLoop.exe`。该脚本硬编码了 Windows 路径 `E:\LLM\LectureLearnLoop`，因此只能在作者本机直接运行。
- `desktop/package.json`：Electron 应用清单，仅声明 `main: main.js`、`scripts.start/start:debug` 和极少的依赖（`ws`、`electron`）。未使用 electron-builder/electron-packager，而是由 `p7_package.ps1` 手动拼装。
- `server/requirements.txt`：Flask 服务端 Python 依赖清单，包含 `flask>=3.0`、`flask-cors`、`pyjwt`、`python-dotenv`、`httpx`、`requests`、`psycopg2-binary`、`deepgram-sdk`、`websockets`。
- `server/.env` / `.env.example`：服务端运行时配置（数据库、密钥等）。

## 架构约定
1. **双进程模型**：Flask 服务（后端）+ Electron 桌面客户端（前端），两者通过 HTTP/WebSocket 通信，端口 6001 为约定值。
2. **开发模式 vs 发布模式**：
   - 开发：`start_app.ps1 -Dev` → 直接从 `desktop/` 源码启动 Electron，配合 CDP 做 E2E 自动化。
   - 发布：先运行 `server/tests/p7_package.ps1` 生成 `dist/win-unpacked/LectureLearnLoop.exe`，再 `start_app.ps1` 启动便携版。
3. **无 CI/CD**：仓库中不存在 `.github/workflows`、`.gitlab-ci.yml`、`Dockerfile`、`Makefile`、`setup.py`、`pyproject.toml` 等标准构建工件。
4. **版本管理**：Electron 应用版本号写死在 `desktop/package.json` 的 `version: "0.1.0"`；Python 端没有集中式版本文件。
5. **平台限制**：所有构建脚本均为 PowerShell，且 `p7_package.ps1` 内嵌绝对路径，当前仅支持 Windows。

## 开发者应遵循的规则
- 新增 Python 依赖必须同步写入 `server/requirements.txt`。
- 新增 Electron 依赖需更新 `desktop/package.json`，并确保 `p7_package.ps1` 会将其复制到 `resources/app/node_modules`。
- 修改 Electron 主入口或预加载脚本后，重新运行 `server/tests/p7_package.ps1` 以刷新便携版。
- 本地调试统一通过 `start_app.ps1 [-Dev]`，不要各自用 `python server/app.py` 和 `npm start` 分别启动。
- 如需跨平台或 CI，应在现有 PowerShell 脚本基础上扩展，而不是引入新的构建系统；若引入新工具，需在根目录提供等价的一键入口脚本。