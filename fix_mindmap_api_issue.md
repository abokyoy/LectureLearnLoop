# 脑图API调用问题修复指南

## 问题现象 🔍
- 点击学科卡片后显示模拟脑图，而不是真实的LLM生成脑图
- 终端日志显示WebChannel连接成功，但没有API调用记录

## 可能原因分析 📊

### 1. WebChannel方法注册问题
- `getOrGenerateMindmap`方法可能没有正确注册到WebChannel
- 前端无法访问到后端方法

### 2. 异步调用问题
- JavaScript异步调用可能被阻塞
- Promise没有正确处理

### 3. 方法名称不匹配
- 前端调用的方法名与后端注册的不一致

## 立即修复步骤 🔧

### 步骤1：重启应用并测试
```bash
# 关闭当前应用
# 重新启动
python overlay_drag_corgi_app.py
```

### 步骤2：检查调试日志
点击机器学习学科，观察前端日志输出：
- 是否显示"WebChannel连接状态"信息
- 是否显示"bridge 方法列表"
- 是否有API调用记录

### 步骤3：手动测试WebChannel
在浏览器控制台执行：
```javascript
// 检查bridge对象
console.log('bridge存在:', !!window.bridge);
console.log('方法列表:', window.bridge ? Object.keys(window.bridge) : 'N/A');

// 手动调用API
if (window.bridge && window.bridge.getOrGenerateMindmap) {
    window.bridge.getOrGenerateMindmap('机器学习').then(response => {
        console.log('API响应:', response);
    }).catch(error => {
        console.error('API错误:', error);
    });
}
```

### 步骤4：如果仍然失败，清除缓存
```python
# 运行清除缓存脚本
python -c "
import sqlite3
conn = sqlite3.connect('knowledge_management.db')
cursor = conn.cursor()
cursor.execute('DELETE FROM knowledge_mindmaps WHERE subject_name = ?', ('机器学习',))
conn.commit()
conn.close()
print('✅ 已清除机器学习脑图缓存')
"
```

## 预期结果 ✅

修复成功后，点击学科应该看到：
```
🧠 开始生成 机器学习 的知识脑图
🔍 检查WebChannel连接状态:
  - window.bridge 存在: true
  - getOrGenerateMindmap 方法存在: true
📡 调用后端API获取脑图数据...
📤 请求参数: 学科="机器学习"
📡 API响应长度: [数字]
📡 API响应预览: {"success":true,"mindmap":{"data":...
💾 使用缓存的脑图数据 (或 🆕 使用新生成的脑图数据)
📊 节点数: [数字]
🔗 连线数: [数字]
✅ 脑图渲染完成，节点数: [数字]
```

## 如果问题持续存在 🚨

### 检查后端方法注册
确认`overlay_drag_corgi_app.py`中的方法装饰器：
```python
@Slot(str, result=str)
def getOrGenerateMindmap(self, subject_name):
    # 方法实现
```

### 检查WebChannel设置
确认WebChannel正确设置到页面：
```python
# 在页面加载完成后
self.web_view.page().setWebChannel(self.channel)
```

### 检查方法可见性
确认方法在WebChannel中可见：
```python
# 检查是否正确暴露给前端
self.channel.registerObject("bridge", self)
```

## 临时解决方案 🔄

如果API调用仍然失败，可以临时修改前端代码强制使用真实数据：
```javascript
// 在generateMindmap函数中，临时跳过API调用
// 直接使用缓存数据或生成新数据
```

但这只是临时方案，根本问题还是需要修复WebChannel连接。
