# Flask改造快速开始指南

## 🚀 5分钟快速体验

### 第一步：安装依赖（1分钟）

```bash
# 激活虚拟环境
venv\Scripts\activate

# 安装Flask相关依赖（大部分已有）
pip install Flask-CORS
```

### 第二步：启动Flask应用（1分钟）

```bash
# 方式1：使用启动脚本（推荐）
start_flask.bat

# 方式2：直接运行
python app_flask.py
```

### 第三步：访问应用（1分钟）

打开浏览器访问：
- 主页：http://localhost:5000
- 资料学习：http://localhost:5000/learn_materials
- 网课笔记：http://localhost:5000/online_course
- 练习脑图：http://localhost:5000/practice

### 第四步：测试API（2分钟）

打开浏览器控制台，测试API调用：

```javascript
// 测试知识点提取
const result = await KnowledgeAPI.extract('这是一段测试文本');
console.log(result);

// 测试LLM调用
const response = await LLMAPI.call('你好');
console.log(response);

// 测试配置获取
const config = await ConfigAPI.get();
console.log(config);
```

---

## 📋 完整实施步骤

### 阶段1：环境准备（第1天）

#### 1.1 创建新分支
```bash
git checkout -b flask-migration
git add .
git commit -m "开始Flask改造"
```

#### 1.2 安装依赖
```bash
pip install Flask-CORS
```

#### 1.3 创建目录结构
```bash
# 已创建的文件
app_flask.py           # ✅ Flask主应用
static/js/api.js       # ✅ API封装
start_flask.bat        # ✅ 启动脚本

# 需要创建的目录
mkdir static\css
mkdir static\images
mkdir logs
mkdir flask_session
```

### 阶段2：核心功能迁移（第2-5天）

#### 2.1 优先级列表

**高优先级（必须）**：
1. ✅ 知识点提取API
2. ✅ LLM调用API
3. ✅ 文件保存/加载API
4. ✅ 配置管理API

**中优先级（重要）**：
5. 练习生成API
6. 练习评估API
7. 笔记管理API
8. 知识库管理API

**低优先级（可选）**：
9. 录音转写功能
10. 实时通信功能

#### 2.2 API迁移对照表

| Qt方法 | Flask路由 | 状态 | 优先级 |
|--------|----------|------|--------|
| `extractKnowledgePoints` | `POST /api/knowledge/extract` | ✅ 已实现 | 高 |
| `callLLM` | `POST /api/llm/call` | ✅ 已实现 | 高 |
| `saveFile` | `POST /api/file/save` | ✅ 已实现 | 高 |
| `loadFile` | `GET /api/file/load` | ✅ 已实现 | 高 |
| `getConfig` | `GET /api/config/get` | ✅ 已实现 | 高 |
| `saveConfig` | `POST /api/config/save` | ✅ 已实现 | 高 |
| `generatePractice` | `POST /api/practice/generate` | ⏳ 待实现 | 中 |
| `evaluatePractice` | `POST /api/practice/evaluate` | ⏳ 待实现 | 中 |
| `getKnowledgePoints` | `GET /api/knowledge/list` | ✅ 已实现 | 中 |
| `createKnowledgePoint` | `POST /api/knowledge/create` | ✅ 已实现 | 中 |

### 阶段3：前端改造（第6-8天）

#### 3.1 改造顺序（由简到难）

**第1天：设置页面**
- 文件：`templates/pages/settings.html`
- 难度：⭐
- 原因：只有配置读写，逻辑简单

**第2天：LLM日志页面**
- 文件：`templates/pages/llm_logs.html`
- 难度：⭐⭐
- 原因：只读操作，无复杂交互

**第3天：资料学习页面**
- 文件：`templates/pages/learn_from_materials.html`
- 难度：⭐⭐⭐
- 原因：有文件操作和知识点提取

**第4天：网课笔记页面**
- 文件：`templates/pages/online_course_notes.html`
- 难度：⭐⭐⭐⭐
- 原因：有编辑器和文件树

**第5天：练习脑图页面**
- 文件：`templates/pages/practice_materials.html`
- 难度：⭐⭐⭐⭐⭐
- 原因：有复杂的可视化和交互

#### 3.2 改造模板

每个页面的改造步骤：

```html
<!-- 1. 移除QWebChannel -->
<!-- 删除这行 -->
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>

<!-- 2. 添加API封装 -->
<script src="{{ url_for('static', filename='js/api.js') }}"></script>

<!-- 3. 修改API调用 -->
<script>
    // 改造前
    window.pybridge.method(params, callback);
    
    // 改造后（方式1：使用新API）
    const result = await API.method(params);
    
    // 改造后（方式2：使用兼容层）
    window.pybridge.method(params, callback); // 无需修改
</script>

<!-- 4. 修改静态资源路径 -->
<!-- 改造前 -->
<link href="qrc:///styles/main.css">

<!-- 改造后 -->
<link href="{{ url_for('static', filename='css/main.css') }}">
```

### 阶段4：测试与优化（第9-10天）

#### 4.1 功能测试清单

**基础功能**：
- [ ] 页面能正常访问
- [ ] 静态资源加载正常
- [ ] API调用正常
- [ ] 错误处理正常

**核心功能**：
- [ ] 知识点提取功能
- [ ] LLM调用功能
- [ ] 文件保存/加载
- [ ] 配置管理

**高级功能**：
- [ ] 练习生成
- [ ] 练习评估
- [ ] 笔记编辑
- [ ] 知识库管理

#### 4.2 性能优化

```python
# 添加缓存
from flask_caching import Cache

cache = Cache(app, config={
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': 300
})

@app.route('/api/knowledge/list')
@cache.cached(timeout=60, query_string=True)
def get_knowledge_list():
    # 缓存60秒
    pass
```

#### 4.3 错误处理

```python
# 统一错误响应格式
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f'Unhandled exception: {str(e)}')
    return jsonify({
        'success': False,
        'error': str(e),
        'type': type(e).__name__
    }), 500
```

---

## 🎯 关键决策点

### 决策1：改造策略

**选项A：完全重写前端（推荐用于长期项目）**
- 优点：代码现代化，易维护
- 缺点：工作量大
- 时间：2-3周

**选项B：使用兼容层（推荐用于快速迁移）**
- 优点：改造量最小
- 缺点：保留旧代码风格
- 时间：1周

**选项C：渐进式改造（推荐用于本项目）** ⭐
- 优点：平滑过渡，风险低
- 缺点：需要维护两套代码
- 时间：1-2周

### 决策2：部署方式

**开发阶段**：
```bash
python app_flask.py
```

**生产阶段**：
```bash
# 方式1：Gunicorn（推荐）
gunicorn -w 4 -b 0.0.0.0:5000 app_flask:app

# 方式2：Docker
docker-compose up -d

# 方式3：Nginx + Gunicorn
# 配置见文档
```

### 决策3：数据库

**保持SQLite**（推荐）：
- 优点：无需迁移，兼容性好
- 缺点：并发性能有限
- 适用：中小规模应用

**迁移到PostgreSQL**（可选）：
- 优点：性能好，功能强
- 缺点：需要数据迁移
- 适用：大规模应用

---

## 📊 进度跟踪

### 第1周

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| Day 1 | 环境准备 | ✅ | 已完成 |
| Day 2 | Flask应用搭建 | ✅ | 已完成 |
| Day 3 | 核心API实现 | ✅ | 已完成 |
| Day 4 | API封装开发 | ✅ | 已完成 |
| Day 5 | 设置页面改造 | ⏳ | 进行中 |

### 第2周

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| Day 1 | LLM日志页面 | ⏳ | 待开始 |
| Day 2 | 资料学习页面 | ⏳ | 待开始 |
| Day 3 | 网课笔记页面 | ⏳ | 待开始 |
| Day 4 | 练习脑图页面 | ⏳ | 待开始 |
| Day 5 | 功能测试 | ⏳ | 待开始 |

### 第3周

| 日期 | 任务 | 状态 | 备注 |
|------|------|------|------|
| Day 1-2 | 性能优化 | ⏳ | 待开始 |
| Day 3-4 | 部署配置 | ⏳ | 待开始 |
| Day 5 | 文档整理 | ⏳ | 待开始 |

---

## 🔍 验证方法

### 快速验证

```bash
# 1. 启动应用
python app_flask.py

# 2. 打开浏览器
# http://localhost:5000

# 3. 打开控制台，运行测试
```

```javascript
// 测试API是否可用
console.log('测试开始...');

// 测试1：配置API
const config = await ConfigAPI.get();
console.log('✅ 配置API正常:', config);

// 测试2：知识点API
const knowledge = await KnowledgeAPI.extract('测试文本');
console.log('✅ 知识点API正常:', knowledge);

// 测试3：LLM API
const llm = await LLMAPI.call('你好');
console.log('✅ LLM API正常:', llm);

console.log('✅ 所有测试通过！');
```

### 完整测试

创建测试脚本：

```python
# test_flask_app.py
import requests
import json

BASE_URL = 'http://localhost:5000'

def test_api():
    # 测试配置API
    response = requests.get(f'{BASE_URL}/api/config/get')
    assert response.status_code == 200
    print('✅ 配置API测试通过')
    
    # 测试知识点提取API
    response = requests.post(
        f'{BASE_URL}/api/knowledge/extract',
        json={'text': '测试文本'}
    )
    assert response.status_code == 200
    print('✅ 知识点API测试通过')
    
    print('✅ 所有API测试通过！')

if __name__ == '__main__':
    test_api()
```

---

## 📞 问题排查

### 常见问题

**Q1: 启动报错 "ModuleNotFoundError: No module named 'flask'"**
```bash
# 解决：安装Flask
pip install Flask Flask-CORS Flask-Session
```

**Q2: 访问页面404**
```bash
# 检查：
# 1. Flask应用是否正常启动
# 2. 路由是否正确定义
# 3. 模板文件是否存在
```

**Q3: API调用失败**
```javascript
// 检查：
// 1. 打开浏览器控制台查看错误
// 2. 检查Network标签查看请求详情
// 3. 查看Flask日志
```

**Q4: 静态资源404**
```html
<!-- 检查路径是否正确 -->
<script src="{{ url_for('static', filename='js/api.js') }}"></script>

<!-- 确保文件存在 -->
static/js/api.js
```

---

## 🎉 成功标准

### 最小可用版本（MVP）

- ✅ Flask应用能正常启动
- ✅ 主要页面能访问
- ✅ 核心API能调用
- ✅ 基础功能正常

### 完整版本

- ✅ 所有页面正常工作
- ✅ 所有API正常工作
- ✅ 性能满足要求
- ✅ 错误处理完善
- ✅ 文档完整

---

## 📚 参考资源

### 官方文档
- [Flask文档](https://flask.palletsprojects.com/)
- [Jinja2文档](https://jinja.palletsprojects.com/)
- [Fetch API文档](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API)

### 项目文档
- `Flask改造实施方案.md` - 完整实施方案
- `模板改造示例.md` - 模板改造指南
- `app_flask.py` - Flask应用示例
- `static/js/api.js` - API封装示例

---

**准备好了吗？让我们开始Flask改造之旅！** 🚀

运行 `start_flask.bat` 开始体验！
