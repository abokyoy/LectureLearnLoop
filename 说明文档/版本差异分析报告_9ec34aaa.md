# 版本差异分析报告

**对比版本**: `9ec34aaa6a9583095c9f65f500e0793eefdf725a` vs 当前版本  
**分析时间**: 2025-10-01 19:15  
**问题**: 练习历史显示为空，无法正确载入提交记录  

## 📋 总体差异概览

通过Git差异分析，发现以下关键文件存在差异：

1. **overlay_drag_corgi_app.py** - 后端API新增
2. **services/practice_service.py** - 数据库服务增强  
3. **templates/base.html** - 前端功能大幅改进

## 🔧 详细差异分析

### 1. 后端API差异 (overlay_drag_corgi_app.py)

#### 新增功能
- **`savePracticeHistory(practice_data)`** - 保存练习历史API
- **`updatePracticeEvaluation(practice_id, evaluation_data)`** - 更新练习评估API

#### 关键代码差异
```python
# 新增：保存练习历史方法
@Slot(str, result=str)
def savePracticeHistory(self, practice_data):
    """保存练习历史（用户提交答案时调用）"""
    try:
        data = json.loads(practice_data)
        from services.practice_service import PracticeService
        practice_service = PracticeService()
        result = practice_service.save_practice_history(data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

# 新增：更新练习评估方法  
@Slot(str, str, result=str)
def updatePracticeEvaluation(self, practice_id, evaluation_data):
    """更新练习评估结果（AI评估完成时调用）"""
    try:
        data = json.loads(evaluation_data)
        from services.practice_service import PracticeService
        practice_service = PracticeService()
        result = practice_service.update_practice_evaluation(practice_id, data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
```

#### 影响分析
- ✅ **正面影响**: 提供了完整的练习历史保存和更新机制
- ❌ **潜在问题**: 旧版本缺少这些API，无法正确保存练习历史

### 2. 数据库服务差异 (services/practice_service.py)

#### 字段增强
```python
# 旧版本查询
SELECT practice_id, timestamp, selected_text, status, has_evaluation

# 新版本查询  
SELECT practice_id, timestamp, selected_text, questions, status, has_evaluation
```

#### 新增方法
```python
def save_practice_history(self, practice_data: Dict[str, Any]) -> Dict[str, Any]:
    """保存练习历史到数据库"""
    with sqlite3.connect(self.db_path) as conn:
        cursor = conn.cursor()
        # 检查练习是否已存在，更新或插入
        if existing:
            cursor.execute('''UPDATE practice_sessions SET ...''')
        else:
            cursor.execute('''INSERT INTO practice_sessions ...''')

def update_practice_evaluation(self, practice_id: str, evaluation_data: Dict[str, Any]):
    """更新练习评估状态"""
    with sqlite3.connect(self.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''UPDATE practice_sessions SET evaluation_result = ?, status = 'evaluated' ...''')
```

#### 字段处理改进
```python
# 新增：优先使用questions字段
question_content = questions if questions else selected_text

# 新增：预览文本长度增加
text_preview = question_content[:120] if len(question_content) > 120 else question_content
```

#### 影响分析
- ✅ **正面影响**: 支持`questions`字段，提供完整的数据持久化
- ❌ **潜在问题**: 旧版本只支持`selected_text`，字段映射不完整

### 3. 前端功能差异 (templates/base.html)

#### UI改进

**练习历史弹窗增强**:
```html
<!-- 新增：独立的练习历史弹窗 -->
<div class="ai-history-modal" id="practiceHistoryModal">
    <div class="ai-history-content" style="width: 800px; max-width: 90vw; max-height: 85vh;">
        <!-- 完整的练习历史界面，包含搜索、筛选、分页等功能 -->
    </div>
</div>
```

**尺寸优化**:
- 弹窗宽度: 600px → 800px
- 最大高度: 80vh → 85vh  
- 列表高度: 400px → 500px

#### 功能增强

**1. 练习历史加载机制**:
```javascript
// 旧版本：简单的按钮点击
practiceHistoryBtn.click();

// 新版本：独立的弹窗系统
showPracticeHistoryModal(practices); // 直接调用独立弹窗
```

**2. 数据保存机制**:
```javascript
// 新增：自动保存练习历史
function savePracticeHistoryToDatabase() {
    const practiceData = {
        practice_id: currentPracticeId,
        timestamp: new Date().toISOString(),
        selected_text: currentPracticeData ? (currentPracticeData.selected_text || '') : '',
        questions: currentPracticeQuestions || '',
        user_answers: currentPracticeAnswer || '',
        answer_history: JSON.stringify(practiceAnswerHistory || []),
        evaluation_result: currentEvaluationResult || '',
        status: 'submitted'
    };
    
    if (window.bridge && window.bridge.savePracticeHistory) {
        const response = window.bridge.savePracticeHistory(JSON.stringify(practiceData));
        // 处理响应...
    }
}

// 新增：自动更新评估状态
function updatePracticeEvaluationInDatabase(evaluationData) {
    const evalData = {
        evaluation_result: JSON.stringify(evaluationData),
        score: evaluationData.score || 0,
        feedback: evaluationData.feedback || '',
        answer_history: JSON.stringify(practiceAnswerHistory || []),
        timestamp: new Date().toISOString()
    };
    
    if (window.bridge && window.bridge.updatePracticeEvaluation) {
        const response = window.bridge.updatePracticeEvaluation(currentPracticeId, JSON.stringify(evalData));
        // 处理响应...
    }
}
```

**3. Promise处理改进**:
```javascript
// 旧版本：直接报错
if (response && typeof response.then === 'function') {
    globalDebugError('❌ 检测到Promise对象，WebChannel异步问题');
    alert('获取练习历史失败');
}

// 新版本：正确处理Promise
if (response && typeof response.then === 'function') {
    globalDebugLog('🔄 检测到Promise对象，等待异步响应...');
    response.then(function(actualResponse) {
        handlePracticeHistoryResponse(actualResponse);
    }).catch(function(error) {
        globalDebugError('❌ Promise rejected: ' + error.message);
    });
}
```

**4. 练习数据加载逻辑差异**:
```javascript
// 旧版本：简单的数据加载和清空（适合新练习）
function loadPracticeData(practiceData) {
    currentPracticeId = practiceData.id;
    currentPracticeQuestions = practiceData.question || practiceData.questions;
    
    // 清空答案历史
    const answerHistoryArea = document.getElementById('answerHistoryArea');
    if (answerHistoryArea) {
        answerHistoryArea.innerHTML = '';
    }
    
    // 重置状态
    currentPracticeAnswer = '';
    currentEvaluationResult = null;
    practiceAnswerHistory = [];
}

// 新版本：复杂的数据恢复逻辑（适合历史练习加载）
function loadPracticeData(practiceData) {
    currentPracticeId = practiceData.practice_id || practiceData.id || '';
    currentPracticeQuestions = practiceData.questions || practiceData.question || practiceData.selected_text || '';
    currentPracticeAnswer = practiceData.user_answers || practiceData.answer || '';
    currentEvaluationResult = practiceData.evaluation_result || practiceData.evaluation || null;
    
    // 重置答案历史（从加载的数据中恢复）
    practiceAnswerHistory = [];
    
    // 尝试从保存的answer_history恢复完整的答案历史
    if (practiceData.answer_history) {
        try {
            const savedHistory = JSON.parse(practiceData.answer_history);
            if (Array.isArray(savedHistory) && savedHistory.length > 0) {
                practiceAnswerHistory = savedHistory;
            }
        } catch (e) {
            globalDebugError('❌ 解析答案历史失败: ' + e.message);
        }
    }
    
    // 如果没有保存的历史，但有当前答案，则创建一条记录
    if (practiceAnswerHistory.length === 0 && currentPracticeAnswer) {
        // 创建默认记录...
    }
    
    updateAnswerHistory();
}
```

**5. 自动保存触发点**:
```javascript
// 在答案提交时自动保存
function submitPracticeAnswer() {
    // ... 提交逻辑
    
    // 新增：自动保存练习历史（状态：未评估）
    savePracticeHistoryToDatabase();
}

// 在AI评估完成时自动更新状态
function handleEvaluationResult(evaluationData) {
    // ... 评估处理逻辑
    
    // 新增：自动更新练习历史状态为已评估
    updatePracticeEvaluationInDatabase(evaluationData);
}
```

## 🎯 关键问题分析

### 核心问题：练习历史显示为空的根本原因

#### 1. 数据保存链路断裂
- ❌ **旧版本**: 缺少`savePracticeHistory`和`updatePracticeEvaluation` API
- ❌ **当前版本**: 有API但前端调用可能有问题

#### 2. 数据加载逻辑差异  
- ❌ **旧版本**: 简单清空，适合新练习
- ❌ **当前版本**: 复杂恢复，但可能解析失败

#### 3. 字段映射不一致
- ❌ **数据库**: 同时支持`questions`和`selected_text`
- ❌ **前端**: 字段优先级可能不正确

#### 4. 函数定义位置变化
- ❌ **旧版本**: 有两个`loadPracticeData`函数（新练习 + 历史练习）
- ❌ **当前版本**: 只有一个复杂的`loadPracticeData`函数

## 🛠️ 修复建议

### 立即修复项

1. **确保API调用正常**:
   - 验证`savePracticeHistory`在答案提交时被调用
   - 验证`updatePracticeEvaluation`在评估完成时被调用
   - 检查WebChannel通信是否正常

2. **简化数据加载逻辑**:
   - 回到旧版本的简单清空逻辑用于新练习
   - 保留复杂恢复逻辑用于历史练习加载
   - 考虑分离两种场景的处理函数

3. **修复字段映射**:
   - 确保`questions`字段优先级高于`selected_text`
   - 统一前后端字段命名
   - 添加字段兼容性处理

4. **调试信息优化**:
   - 添加更详细的数据保存和加载日志
   - 确保错误信息能准确定位问题

### 验证步骤

1. **检查数据库**: 确认练习记录是否正确保存
2. **检查API调用**: 确认前端是否正确调用保存API  
3. **检查数据加载**: 确认历史记录加载时数据解析是否正确
4. **检查字段映射**: 确认前后端字段名称一致性

## 📊 结论

这份分析报告揭示了练习历史显示问题的根本原因在于**数据保存和加载链路的不完整**。新版本虽然添加了完整的数据持久化功能，但可能在实际调用和数据解析环节存在问题。

**关键修复方向**:
1. 确保前端正确调用后端保存API
2. 简化并修复数据加载逻辑  
3. 统一前后端字段映射
4. 分离新练习和历史练习的处理逻辑

通过系统性修复这些差异，应该能够恢复练习历史的正常显示功能。
