# LectureLearnLoop API方法索引文档

## 概述

本文档提供了 LectureLearnLoop 学习系统中两个主要应用程序的API方法完整索引：

1. **overlay_drag_corgi_app.py** - 现代化主应用程序中所有 `@Slot` 装饰的API方法
2. **app_qt.py** - 传统Qt应用程序的核心方法和信号槽机制

文档按功能模块分类，包含方法签名、参数说明、返回值格式和调用示例。

## 界面渲染机制说明

### 重要说明：UI文件夹与实际界面的关系

**UI/ 文件夹**：
- 包含25个设计稿文件（PNG图片和HTML原型）
- 这些文件仅用于UI设计参考，与实际运行的项目无关
- 不参与程序运行，可以视为设计文档

**实际界面渲染**：
- 所有界面都通过 `templates/` 目录下的模板文件渲染
- 使用 Jinja2 模板引擎 + TemplateManager 类统一管理
- 通过 `loadContent(content_id)` API方法动态加载页面内容

### 界面与模板文件映射关系

| 界面功能 | content_id | 模板文件 | 文件大小 | 主要API方法 |
|----------|------------|----------|----------|-------------|
| 工作台 | `dashboard` | `pages/dashboard.html` | 4KB | `loadContent` |
| 从资料学习 | `learn_from_materials` | `pages/learn_from_materials.html` | 201KB | `getFileStructure`, `loadMarkdownRaw`, `extractKnowledgePoints` |
| 网课笔记 | `online_course_notes` | `pages/online_course_notes.html` | 314KB | `startRecording`, `stopRecording`, `summarizeText` |
| 基于学习资料练习 | `practice_materials` | `pages/practice_materials.html` | 169KB | `getOrGenerateMindmap`, `getKnowledgePointDetail` |
| 基于知识点练习 | `practice_knowledge` | `pages/practice_knowledge.html` | 3KB | `generatePracticeQuestions` |
| 基于错题练习 | `practice_errors` | `pages/practice_errors.html` | 3KB | `getErrorQuestions` |
| 基于知识点记忆 | `memory_knowledge` | `pages/memory_knowledge.html` | 4KB | `getKnowledgePoints` |
| 基于错题记忆 | `memory_errors` | `pages/memory_errors.html` | 6KB | `getErrorHistory` |
| 知识库管理 | `knowledge_base` | `pages/knowledge_base.html` | 8KB | `getSubjectStats`, `manageKnowledge` |
| 设置 | `settings` | `pages/settings.html` | 25KB | `saveSettings`, `loadSettings` |
| LLM调用日志 | `llm_logs` | `pages/llm_logs.html` | 13KB | `getLLMCallLogs` |

### 模板渲染流程

1. **前端调用** → `window.pybridge.loadContent(content_id)`
2. **后端处理** → `CorgiWebBridge.loadContent()`
3. **模板渲染** → `template_manager.render_page_content(content_id)`
4. **Jinja2处理** → 加载 `templates/pages/{content_id}.html`
5. **HTML返回** → 渲染后的完整HTML内容
6. **前端更新** → 动态更新页面内容区域

## overlay_drag_corgi_app.py API方法索引

### 1. 窗口控制类 (Window Control)

#### 1.1 minimizeWindow()
- **签名**: `@Slot()`
- **功能**: 最小化应用程序窗口
- **参数**: 无
- **返回值**: 无
- **调用示例**: 
  ```javascript
  window.pybridge.minimizeWindow();
  ```

#### 1.2 maximizeWindow()
- **签名**: `@Slot()`
- **功能**: 最大化或还原窗口
- **参数**: 无
- **返回值**: 无
- **调用示例**: 
  ```javascript
  window.pybridge.maximizeWindow();
  ```

#### 1.3 closeWindow()
- **签名**: `@Slot()`
- **功能**: 关闭应用程序窗口
- **参数**: 无
- **返回值**: 无
- **调用示例**: 
  ```javascript
  window.pybridge.closeWindow();
  ```

### 2. 导航与菜单类 (Navigation & Menu)

#### 2.1 toggleMenu(menu_id)
- **签名**: `@Slot(str, result=str)`
- **功能**: 切换菜单展开/收缩状态
- **参数**: 
  - `menu_id` (str): 菜单项ID
- **返回值**: JSON字符串，包含更新后的菜单状态
- **调用示例**: 
  ```javascript
  const menuState = window.pybridge.toggleMenu('learn_menu');
  ```

#### 2.2 loadContent(content_id)
- **签名**: `@Slot(str)`
- **功能**: 加载指定内容页面
- **参数**: 
  - `content_id` (str): 内容页面ID
- **返回值**: 无
- **调用示例**: 
  ```javascript
  window.pybridge.loadContent('learn_from_materials');
  ```

#### 2.3 getMenuState()
- **签名**: `@Slot(result=str)`
- **功能**: 获取当前菜单状态
- **参数**: 无
- **返回值**: JSON字符串，包含菜单状态信息
- **调用示例**: 
  ```javascript
  const menuState = window.pybridge.getMenuState();
  ```

### 3. 文件管理类 (File Management)

#### 3.1 getFileStructure()
- **签名**: `@Slot(result=str)`
- **功能**: 获取vault文件夹的文件结构
- **参数**: 无
- **返回值**: JSON字符串，包含文件树结构
- **返回格式**: 
  ```json
  [
    {
      "name": "文件夹名",
      "type": "folder",
      "children": [...]
    },
    {
      "name": "文件名.md",
      "type": "file",
      "path": "相对路径"
    }
  ]
  ```
- **调用示例**: 
  ```javascript
  const fileStructure = JSON.parse(window.pybridge.getFileStructure());
  ```

#### 3.2 loadMarkdownFile(file_path)
- **签名**: `@Slot(str, result=str)`
- **功能**: 加载Markdown文件内容并转换为HTML
- **参数**: 
  - `file_path` (str): 文件路径
- **返回值**: HTML格式的文件内容
- **调用示例**: 
  ```javascript
  const htmlContent = window.pybridge.loadMarkdownFile('vault/notes/example.md');
  ```

#### 3.3 loadMarkdownRaw(file_path)
- **签名**: `@Slot(str, result=str)`
- **功能**: 加载Markdown文件的原始内容
- **参数**: 
  - `file_path` (str): 文件路径
- **返回值**: 原始Markdown文本
- **调用示例**: 
  ```javascript
  const rawContent = window.pybridge.loadMarkdownRaw('vault/notes/example.md');
  ```

#### 3.4 saveMarkdownFile(file_path, content)
- **签名**: `@Slot(str, str, result=bool)`
- **功能**: 保存Markdown文件
- **参数**: 
  - `file_path` (str): 文件路径
  - `content` (str): 文件内容
- **返回值**: 布尔值，表示保存是否成功
- **调用示例**: 
  ```javascript
  const success = window.pybridge.saveMarkdownFile('vault/notes/new.md', '# 新笔记\n内容...');
  ```

### 4. 练习生成与评估类 (Practice & Evaluation)

#### 4.1 generatePracticeQuestions(selected_text)
- **签名**: `@Slot(str, result=str)`
- **功能**: 根据选中文本生成练习题目
- **参数**: 
  - `selected_text` (str): 选中的文本内容
- **返回值**: 生成的练习题目文本
- **调用示例**: 
  ```javascript
  const questions = window.pybridge.generatePracticeQuestions('选中的学习内容');
  ```

#### 4.2 evaluatePracticeAnswer(evaluation_data_json)
- **签名**: `@Slot(str, result=str)`
- **功能**: 评估单个练习答案
- **参数**: 
  - `evaluation_data_json` (str): JSON格式的评估数据
- **参数格式**: 
  ```json
  {
    "question": "题目内容",
    "user_answer": "用户答案",
    "context": "相关上下文"
  }
  ```
- **返回值**: JSON格式的评估结果
- **返回格式**: 
  ```json
  {
    "success": true,
    "score": 85,
    "feedback": "评估反馈",
    "correct_answer": "正确答案",
    "is_correct": true
  }
  ```

#### 4.3 generateNewPractice()
- **签名**: `@Slot(result=str)`
- **功能**: 生成新的练习题目
- **参数**: 无
- **返回值**: JSON格式的练习题目
- **调用示例**: 
  ```javascript
  const newPractice = JSON.parse(window.pybridge.generateNewPractice());
  ```

#### 4.4 evaluatePracticeAnswers(questions, answers)
- **签名**: `@Slot(str, str, result=str)`
- **功能**: 评判多个练习答案
- **参数**: 
  - `questions` (str): 题目内容
  - `answers` (str): 答案内容
- **返回值**: 评估结果文本
- **调用示例**: 
  ```javascript
  const evaluation = window.pybridge.evaluatePracticeAnswers(questions, answers);
  ```

### 5. 错题管理类 (Error Bank)

#### 5.1 addToErrorBank(error_data_json)
- **签名**: `@Slot(str, result=str)`
- **功能**: 将错题添加到错题库
- **参数**: 
  - `error_data_json` (str): JSON格式的错题数据
- **参数格式**: 
  ```json
  {
    "questions": ["题目1", "题目2"],
    "user_answers": ["答案1", "答案2"],
    "correct_answers": ["正确答案1", "正确答案2"],
    "explanations": ["解释1", "解释2"]
  }
  ```
- **返回值**: JSON格式的处理结果

#### 5.2 matchKnowledgePointsForSubject(match_data_json)
- **签名**: `@Slot(str, result=str)`
- **功能**: 为选定学科的错题匹配知识点
- **参数**: 
  - `match_data_json` (str): 匹配数据JSON
- **返回值**: JSON格式的匹配结果

#### 5.3 saveErrorsToKnowledgeBase(save_data_json)
- **签名**: `@Slot(str, result=str)`
- **功能**: 保存选中的错题到知识库
- **参数**: 
  - `save_data_json` (str): 保存数据JSON
- **返回值**: JSON格式的保存结果

### 6. 配置管理类 (Configuration)

#### 6.1 getConfig()
- **签名**: `@Slot(result=str)`
- **功能**: 获取当前配置
- **参数**: 无
- **返回值**: JSON格式的配置信息
- **调用示例**: 
  ```javascript
  const config = JSON.parse(window.pybridge.getConfig());
  ```

#### 6.2 saveConfig(config_json)
- **签名**: `@Slot(str, result=bool)`
- **功能**: 保存配置
- **参数**: 
  - `config_json` (str): JSON格式的配置数据
- **返回值**: 布尔值，表示保存是否成功
- **调用示例**: 
  ```javascript
  const success = window.pybridge.saveConfig(JSON.stringify(configData));
  ```

### 7. 知识点提取类 (Knowledge Extraction)

#### 7.1 extractKnowledgePoints(file_path)
- **签名**: `@Slot(str, result=str)`
- **功能**: 提取文档的知识点
- **参数**: 
  - `file_path` (str): 文件路径
- **返回值**: JSON格式的知识点列表
- **返回格式**: 
  ```json
  {
    "success": true,
    "knowledge_points": [
      {
        "id": "kp_001",
        "name": "知识点名称",
        "description": "知识点描述",
        "difficulty": "中等",
        "category": "分类"
      }
    ]
  }
  ```

### 8. 学习路径类 (Learning Path)

#### 8.1 getOrGenerateLearningPath(subject_name)
- **签名**: `@Slot(str, result=str)`
- **功能**: 获取或生成学科的学习路径图
- **参数**: 
  - `subject_name` (str): 学科名称
- **返回值**: JSON格式的学习路径数据
- **调用示例**: 
  ```javascript
  const learningPath = JSON.parse(window.pybridge.getOrGenerateLearningPath('数学'));
  ```

#### 8.2 clearLearningPathCache(subject_name)
- **签名**: `@Slot(str, result=str)`
- **功能**: 清除学科的学习路径缓存
- **参数**: 
  - `subject_name` (str): 学科名称
- **返回值**: JSON格式的操作结果

### 9. 知识脑图类 (Knowledge Mindmap)

#### 9.1 getSubjectsWithKnowledgeCount()
- **签名**: `@Slot(result=str)`
- **功能**: 获取学科列表及其知识点数量
- **参数**: 无
- **返回值**: JSON格式的学科统计数据
- **返回格式**: 
  ```json
  [
    {
      "subject_name": "数学",
      "knowledge_count": 156,
      "description": "学科描述"
    }
  ]
  ```

#### 9.2 getOrGenerateMindmap(subject_name)
- **签名**: `@Slot(str, result=str)`
- **功能**: 获取或生成学科的知识脑图
- **参数**: 
  - `subject_name` (str): 学科名称
- **返回值**: JSON格式的脑图数据
- **返回格式**: 
  ```json
  {
    "success": true,
    "mindmap_data": {
      "nodes": [...],
      "links": [...]
    }
  }
  ```

#### 9.3 saveMindmap(subject_name, mindmap_data_json)
- **签名**: `@Slot(str, str, result=bool)`
- **功能**: 保存知识脑图
- **参数**: 
  - `subject_name` (str): 学科名称
  - `mindmap_data_json` (str): 脑图数据JSON
- **返回值**: 布尔值，表示保存是否成功

#### 9.4 clearMindmapCache(subject_name)
- **签名**: `@Slot(str, result=str)`
- **功能**: 清除学科的脑图缓存
- **参数**: 
  - `subject_name` (str): 学科名称
- **返回值**: JSON格式的操作结果

#### 9.5 getKnowledgePointDetail(knowledge_point_id)
- **签名**: `@Slot(str, result=str)`
- **功能**: 获取知识点详情
- **参数**: 
  - `knowledge_point_id` (str): 知识点ID
- **返回值**: JSON格式的知识点详细信息

#### 9.6 getKnowledgePointNotes(knowledge_point_id)
- **签名**: `@Slot(str, result=str)`
- **功能**: 获取知识点关联笔记
- **参数**: 
  - `knowledge_point_id` (str): 知识点ID
- **返回值**: JSON格式的关联笔记列表

#### 9.7 getNoteContent(note_id)
- **签名**: `@Slot(str, result=str)`
- **功能**: 获取笔记的详细内容
- **参数**: 
  - `note_id` (str): 笔记ID
- **返回值**: JSON格式的笔记内容

### 10. 录音与转写类 (Recording & Transcription)

#### 10.1 testAudioSource()
- **签名**: `@Slot(result=str)`
- **功能**: 测试音频源
- **参数**: 无
- **返回值**: JSON格式的测试结果
- **调用示例**: 
  ```javascript
  const testResult = JSON.parse(window.pybridge.testAudioSource());
  ```

#### 10.2 testRecording()
- **签名**: `@Slot(result=str)`
- **功能**: 测试录音功能
- **参数**: 无
- **返回值**: JSON格式的测试结果

#### 10.3 startRecording()
- **签名**: `@Slot(result=str)`
- **功能**: 开始录音
- **参数**: 无
- **返回值**: JSON格式的启动结果
- **返回格式**: 
  ```json
  {
    "success": true,
    "message": "录音已开始",
    "session_id": "recording_session_001"
  }
  ```

#### 10.4 stopRecording()
- **签名**: `@Slot(result=str)`
- **功能**: 停止录音
- **参数**: 无
- **返回值**: JSON格式的停止结果

#### 10.5 pauseRecording(pause)
- **签名**: `@Slot(bool, result=str)`
- **功能**: 暂停/继续录音
- **参数**: 
  - `pause` (bool): true为暂停，false为继续
- **返回值**: JSON格式的操作结果

#### 10.6 summarizeText(text)
- **签名**: `@Slot(str, result=str)`
- **功能**: 对文本进行AI总结
- **参数**: 
  - `text` (str): 要总结的文本
- **返回值**: 总结后的文本
- **调用示例**: 
  ```javascript
  const summary = window.pybridge.summarizeText('要总结的长文本...');
  ```

#### 10.7 takeScreenshot()
- **签名**: `@Slot(result=str)`
- **功能**: 截图功能
- **参数**: 无
- **返回值**: JSON格式的截图结果

### 11. 网课笔记类 (Course Notes)

#### 11.1 switchToRecording()
- **签名**: `@Slot()`
- **功能**: 切换到录音室页面
- **参数**: 无
- **返回值**: 无

#### 11.2 save_course_notes(content, filename)
- **签名**: `@Slot(str, str, result=str)`
- **功能**: 保存网课笔记
- **参数**: 
  - `content` (str): 笔记内容
  - `filename` (str): 文件名
- **返回值**: JSON格式的保存结果

### 12. 测试与调试类 (Testing & Debugging)

#### 12.1 testAPI()
- **签名**: `@Slot(result=str)`
- **功能**: 测试API连接
- **参数**: 无
- **返回值**: JSON格式的测试结果

#### 12.2 testLLMConnection()
- **签名**: `@Slot(result=str)`
- **功能**: 测试LLM连接
- **参数**: 无
- **返回值**: JSON格式的连接测试结果

#### 12.3 getLLMCallLogs()
- **签名**: `@Slot(result=str)`
- **功能**: 获取LLM调用日志
- **参数**: 无
- **返回值**: JSON格式的日志数据

#### 12.4 clearLLMCallLogs()
- **签名**: `@Slot(result=str)`
- **功能**: 清除LLM调用日志
- **参数**: 无
- **返回值**: JSON格式的操作结果

#### 12.5 logFrontendMessage(message)
- **签名**: `@Slot(str)`
- **功能**: 记录前端发送的日志消息
- **参数**: 
  - `message` (str): 日志消息
- **返回值**: 无

## 通用调用模式

### 1. 同步调用
```javascript
// 直接调用并获取结果
const result = window.pybridge.methodName(param1, param2);
```

### 2. 异步调用（对于可能耗时的操作）
```javascript
// 使用Promise包装
function callAsyncMethod(methodName, ...params) {
    return new Promise((resolve, reject) => {
        try {
            const result = window.pybridge[methodName](...params);
            resolve(result);
        } catch (error) {
            reject(error);
        }
    });
}
```

### 3. JSON数据处理
```javascript
// 解析JSON返回值
try {
    const data = JSON.parse(window.pybridge.getFileStructure());
    // 处理数据
} catch (error) {
    console.error('JSON解析失败:', error);
}
```

## 错误处理

### 1. 标准错误格式
大多数方法在出错时返回以下格式的JSON：
```json
{
    "success": false,
    "error": "错误描述信息",
    "error_code": "ERROR_CODE"
}
```

### 2. 错误处理示例
```javascript
function handleApiCall(methodName, ...params) {
    try {
        const result = window.pybridge[methodName](...params);
        
        // 如果返回的是JSON字符串
        if (typeof result === 'string' && result.startsWith('{')) {
            const data = JSON.parse(result);
            if (data.success === false) {
                console.error('API调用失败:', data.error);
                return null;
            }
            return data;
        }
        
        return result;
    } catch (error) {
        console.error('调用异常:', error);
        return null;
    }
}
```

## 最佳实践

### 1. 参数验证
在调用API前验证参数：
```javascript
function safeApiCall(methodName, params) {
    // 参数验证
    if (!methodName || typeof methodName !== 'string') {
        throw new Error('方法名无效');
    }
    
    // 调用API
    return window.pybridge[methodName](...params);
}
```

### 2. 结果缓存
对于不经常变化的数据进行缓存：
```javascript
const cache = new Map();

function getCachedFileStructure() {
    if (cache.has('fileStructure')) {
        return cache.get('fileStructure');
    }
    
    const structure = JSON.parse(window.pybridge.getFileStructure());
    cache.set('fileStructure', structure);
    return structure;
}
```

### 3. 错误重试
对于网络相关的操作实现重试机制：
```javascript
async function retryApiCall(methodName, params, maxRetries = 3) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            return window.pybridge[methodName](...params);
        } catch (error) {
            if (i === maxRetries - 1) throw error;
            await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
        }
    }
}
```

## app_qt.py 核心方法索引

### 1. 主窗口类 (TranscriptionAppQt)

#### 1.1 录音控制方法
- **start_recording()** - 开始录音
  - 创建AudioRecorderWorker线程
  - 初始化音频设备
  - 更新UI状态

- **stop_recording()** - 停止录音
  - 停止AudioRecorderWorker线程
  - 清理音频资源
  - 更新UI状态

- **pause_recording()** - 暂停/继续录音
  - 切换录音状态
  - 保持音频设备连接

#### 1.2 文件操作方法
- **open_file()** - 打开文件
  - 支持多种文件格式
  - 自动检测文件编码
  - 更新编辑器内容

- **save_file()** - 保存文件
  - 保存当前编辑内容
  - 支持另存为功能
  - 更新窗口标题

- **export_file()** - 导出文件
  - 支持多种导出格式
  - 包含格式转换功能

#### 1.3 AI功能方法
- **open_chatbot()** - 打开AI对话面板
  - 创建ChatbotPanel实例
  - 传递选中文本作为上下文
  - 管理对话历史

- **summarize_selected_text()** - 总结选中文本
  - 创建SummarizerWorker线程
  - 调用LLM服务
  - 插入总结结果

### 2. 富文本编辑器类 (RichTextEditor)

#### 2.1 文本操作方法
- **insertPlainText(text)** - 插入纯文本
- **insertImage(image_path)** - 插入图片
- **setMarkdownText(markdown)** - 设置Markdown文本
- **getPlainText()** - 获取纯文本内容
- **getMarkdownText()** - 获取Markdown格式文本

#### 2.2 格式化方法
- **applyBold()** - 应用粗体格式
- **applyItalic()** - 应用斜体格式
- **applyUnderline()** - 应用下划线格式
- **insertList()** - 插入列表
- **insertTable()** - 插入表格

### 3. 工作线程信号槽

#### 3.1 AudioRecorderWorker 信号
```python
segmentReady = Signal(str)      # 音频片段就绪，参数：文件路径
status = Signal(str)            # 状态更新，参数：状态信息
peakLevel = Signal(float)       # 音频电平，参数：0-1的电平值
finished = Signal()             # 录音完成
```

#### 3.2 TranscriberWorker 信号
```python
textReady = Signal(str)         # 转写文本就绪，参数：转写结果
status = Signal(str)            # 状态更新，参数：状态信息
finished = Signal()             # 转写完成
```

#### 3.3 ChatbotWorker 信号
```python
responseReady = Signal(str)     # AI响应就绪，参数：响应内容
finished = Signal()             # 对话完成
```

#### 3.4 SummarizerWorker 信号
```python
summaryReady = Signal(str)      # 总结就绪，参数：总结内容
status = Signal(str)            # 状态更新，参数：状态信息
finished = Signal()             # 总结完成
```

### 4. 对话框类方法

#### 4.1 ChatbotPanel 方法
- **send_message(message)** - 发送消息到AI
- **insert_response()** - 插入AI响应到编辑器
- **clear_conversation()** - 清除对话历史
- **save_conversation()** - 保存对话记录

#### 4.2 SettingsDialog 方法
- **load_settings()** - 加载设置
- **save_settings()** - 保存设置
- **reset_settings()** - 重置设置
- **validate_settings()** - 验证设置

#### 4.3 DeviceLevelDialog 方法
- **refresh_devices()** - 刷新设备列表
- **select_device(device_index)** - 选择音频设备
- **test_device(device_index)** - 测试音频设备
- **get_device_level(device_index)** - 获取设备电平

### 5. 使用示例

#### 5.1 录音转写流程
```python
# 开始录音
app.start_recording()

# 连接信号槽
app.recording_worker.segmentReady.connect(app.on_segment_ready)
app.transcriber_worker.textReady.connect(app.on_text_ready)

# 停止录音
app.stop_recording()
```

#### 5.2 AI对话流程
```python
# 打开对话面板
selected_text = app.editor.textCursor().selectedText()
chatbot_panel = app.open_chatbot(selected_text)

# 发送消息
chatbot_panel.send_message("请总结这段文本")

# 处理响应
chatbot_panel.worker.responseReady.connect(chatbot_panel.on_response_ready)
```

#### 5.3 文件操作流程
```python
# 打开文件
file_path = QFileDialog.getOpenFileName(app, "打开文件", "", "文本文件 (*.txt *.md)")
app.open_file(file_path[0])

# 保存文件
app.save_file()

# 导出文件
export_path = QFileDialog.getSaveFileName(app, "导出文件", "", "PDF文件 (*.pdf)")
app.export_file(export_path[0], "pdf")
```

## 总结

这个API文档涵盖了 LectureLearnLoop 系统两个主要应用程序的所有公开接口：

### overlay_drag_corgi_app.py
- **80+ @Slot方法** - 前后端通信接口
- **12大功能模块** - 完整的学习管理系统
- **Web界面交互** - 现代化用户体验

### app_qt.py  
- **传统Qt架构** - 原生桌面应用体验
- **丰富的信号槽** - 多线程异步处理
- **专业文本处理** - 强大的编辑和AI功能

通过这个文档，开发者可以：

1. **快速查找**需要的API方法
2. **了解参数格式**和返回值结构
3. **掌握调用方式**和最佳实践
4. **处理错误情况**和异常场景
5. **优化性能**通过缓存和重试机制
6. **选择合适的应用程序**进行功能开发

建议在开发过程中将此文档作为参考手册使用。
