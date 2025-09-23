---
trigger: always_on
alwaysApply: true
---
### **1. 模板与业务逻辑分离**
- **严格禁止**在 Python 代码中直接编写 HTML、CSS 或前端脚本字符串。
- 所有 HTML 代码必须放在独立的模板文件中（推荐路径：`templates/` 目录下，按功能模块细分子目录）。
- 模板文件命名使用 kebab-case（如 `user-profile.html`），并通过 Jinja2 的变量（`{{ variable }}`）和标签（`{% if %}`）与 Python 代码进行数据交互。
- Python 代码仅负责生成模板所需的数据和逻辑控制，不得通过字符串拼接生成 HTML 片段。


### **2. 分层架构设计**
#### **2.1 数据访问层（Data Access Layer, DAL）**
- 必须创建独立的 `dal/` 目录，存放所有数据访问相关代码。
- 采用 DAO（Data Access Object）模式：每个数据库表/实体对应一个 DAO 类，单独放在一个文件中（如 `user_dao.py`、`order_dao.py`）。
- DAO 类仅负责数据的 CRUD（创建、读取、更新、删除）操作，不包含业务逻辑。
- 数据库连接、事务管理等基础功能需封装在 `dal/base_dao.py` 中，其他 DAO 类继承此类。

#### **2.2 业务逻辑层（Business Logic Layer, BLL）**
- 创建 `services/` 目录，存放核心业务逻辑代码。
- 每个业务模块对应一个服务类（如 `user_service.py`、`payment_service.py`），依赖 DAO 层获取数据，实现具体业务规则。
- 服务类需对外提供清晰的接口（如 `def create_user(user_data: UserDTO) -> UserDTO`），内部逻辑不得暴露数据库细节。

#### **2.3 控制层（Controller Layer）**
- 创建 `controllers/` 目录，负责接收前端请求、调用业务服务、组织响应数据。
- 每个控制器处理特定模块的请求（如 `auth_controller.py` 处理登录注册），单个文件代码不超过 200 行。
- 控制器仅负责请求参数校验、调用对应服务、选择模板或返回数据，不包含业务逻辑。

#### **2.4 通信层（Communication Layer）**
- 创建 `signals/` 目录，统一管理前端与后端的交互信号（如事件、回调、IPC 通信）。
- 每种类型的信号（如 UI 事件、数据更新通知）需封装为独立的类或函数（如 `ui_signals.py`、`data_signals.py`）。
- 信号的定义与处理需解耦：发送方不依赖接收方实现，通过接口约定通信格式。

#### **2.5 数据传输层（Data Transfer Layer）**
- 创建 `dto/` 目录，定义数据传输对象（DTO），用于各层之间的数据传递。
- 每个 DTO 类对应一种数据结构（如 `UserDTO.py`、`OrderDTO.py`），包含字段定义和类型注解，禁止包含业务方法。
- 前后端数据交互必须通过 DTO 进行，避免直接传递数据库模型或原始字典。

#### **2.6 表示层（Presentation Layer）**
- 前端代码（HTML、JavaScript、CSS）统一放在 `frontend/` 目录，按 SPA 框架规范拆分（如 `components/`、`pages/`、`styles/`）。
- 前端与后端的交互必须通过通信层定义的接口，禁止直接调用 DAO 或服务层方法。


### **3. 模块化设计原则**
- **单一职责**：每个模块（文件）只负责一个独立功能（如 `logger.py` 仅处理日志，`validator.py` 仅处理参数校验）。
- **物理隔离**：功能相关的类、函数必须放在同一个文件中；不相关的功能必须拆分到不同文件（如用户管理和订单管理不能放在同一文件）。
- **文件大小限制**：单个 Python 文件代码不超过 300 行，前端文件不超过 500 行，超出则必须拆分。
- **模块依赖**：模块之间的依赖必须明确（通过 `import` 声明），禁止循环依赖；高层模块（如控制器）可依赖低层模块（如服务、DAO），反之则不可。
- **接口暴露**：每个模块通过 `__init__.py` 明确导出公共接口（如 `from .user_dao import UserDAO`），隐藏内部实现细节。


### **4. 前端与数据分离**
- 前端（SPA）仅负责 UI 渲染和用户交互，不直接操作数据库。
- 前端所需数据必须通过后端接口（经控制器、服务层处理后）获取，禁止在前端代码中嵌入 SQL 或数据访问逻辑。
- 前端状态管理（如用户会话、表单数据）应独立于后端数据，通过通信层同步更新。


### **5. 命名与目录规范**
- 目录结构示例：
  ```
  project/
  ├── templates/               # Jinja2 模板文件
  │   ├── auth/                # 按模块细分
  │   │   ├── login.html
  │   │   └── register.html
  ├── dal/                     # 数据访问层
  │   ├── base_dao.py
  │   ├── user_dao.py
  │   └── order_dao.py
  ├── services/                # 业务逻辑层
  │   ├── user_service.py
  │   └── payment_service.py
  ├── controllers/             # 控制层
  │   ├── auth_controller.py
  │   └── order_controller.py
  ├── signals/                 # 通信层
  │   ├── ui_signals.py
  │   └── data_signals.py
  ├── dto/                     # 数据传输层
  │   ├── user_dto.py
  │   └── order_dto.py
  ├── frontend/                # 前端 SPA
  │   ├── components/
  │   ├── pages/
  │   └── styles/
  ```
- 其他命名规则遵循原有约定（如 PascalCase 用于类，camelCase 用于函数等）。