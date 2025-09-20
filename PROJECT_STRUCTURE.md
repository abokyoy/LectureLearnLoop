# 柯基学习小助手 - 项目结构

## 📁 项目目录结构

```
e:\LLM\summary\
├── 📄 overlay_drag_corgi_app.py      # 主应用程序
├── 📄 template_manager.py            # 模板管理器
├── 📄 PROJECT_STRUCTURE.md           # 项目结构说明（本文件）
├── 📁 templates/                     # 模板文件目录
│   ├── 📄 base.html                  # 基础模板
│   ├── 📄 spa_layout.html            # SPA主布局模板
│   ├── 📁 components/                # 组件模板
│   │   ├── 📄 sidebar.html           # 侧边栏组件
│   │   └── 📄 header.html            # 顶部栏组件
│   └── 📁 pages/                     # 页面模板
│       ├── 📄 dashboard.html         # 工作台页面
│       ├── 📄 learn_from_materials.html # 从资料学习页面
│       ├── 📄 learn_from_audio.html  # 从音视频学习页面
│       └── 📄 settings.html          # 设置页面
├── 📁 static/                        # 静态资源目录（预留）
│   ├── 📁 js/                        # JavaScript文件
│   └── 📁 css/                       # CSS文件
├── 📁 vault/                         # 学习资料存储目录
└── 📁 practice_sessions/             # 练习会话数据
```

## 🏗️ 架构说明

### 模板系统架构
- **base.html**: 基础模板，包含通用的HTML结构、CSS和JavaScript
- **spa_layout.html**: 继承base.html，实现单页面应用的布局结构
- **components/**: 可复用的UI组件，如侧边栏、头部等
- **pages/**: 具体的页面内容模板，支持数据绑定

### Python模块架构
- **overlay_drag_corgi_app.py**: 主应用程序，包含窗口管理和业务逻辑
- **template_manager.py**: 模板管理器，负责模板的加载、渲染和缓存

## 🔄 数据流

```
用户操作 → JavaScript事件 → WebChannel → Python后端 → 模板渲染 → HTML更新 → 用户界面
```

## 🎯 重构优势

### 1. 关注点分离
- **HTML模板**: 专注于界面结构和样式
- **Python代码**: 专注于业务逻辑和数据处理
- **JavaScript**: 专注于用户交互和动态效果

### 2. 开发效率提升
- **IDE支持**: HTML文件享受完整的语法高亮和自动补全
- **团队协作**: 前端开发者可直接编辑模板文件
- **热重载**: 模板修改无需重启应用（计划功能）

### 3. 维护性改善
- **模块化**: 组件化设计，便于复用和维护
- **版本控制**: HTML和Python修改分离，便于追踪变更
- **错误隔离**: 模板错误不会影响Python应用稳定性

## 🚀 技术栈

- **后端**: Python 3.10+ + PySide6
- **模板引擎**: Jinja2
- **前端框架**: Tailwind CSS + Material Icons
- **通信机制**: Qt WebChannel
- **架构模式**: SPA (Single Page Application)

## 📈 性能特性

- **模板缓存**: Jinja2内置模板缓存机制
- **按需加载**: 页面内容动态加载，减少初始加载时间
- **组件复用**: 公共组件避免重复渲染
- **错误恢复**: 模板渲染失败时自动降级到备用方案

## 🔧 开发工具支持

- **语法高亮**: HTML/CSS/JavaScript完整支持
- **自动补全**: Jinja2模板语法智能提示
- **错误检查**: 模板语法错误实时检测
- **格式化**: 代码自动格式化和美化

---

*最后更新: 2025-09-19*
*重构阶段: 第一阶段完成 - 基础设施建设*
