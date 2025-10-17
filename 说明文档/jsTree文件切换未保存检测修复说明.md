# jsTree文件切换未保存检测修复说明

## 问题分析

根据用户提供的日志，发现问题在于网课笔记页面使用的是jsTree组件来处理文件选择，而不是之前修改的`handleFileClick`函数。

### 日志分析
```
[3:37:40 PM] 🖱️ jsTree文件被选中
[3:37:40 PM] 📊 文件路径: vault\柯基学习法.md
[3:37:40 PM] 📁 文件切换: vault\test222.md -> vault/柯基学习法.md
[3:37:40 PM] 📋 当前文件路径已更新: vault/柯基学习法.md
[3:37:40 PM] ✅ 未保存状态已重置
```

从日志可以看出：
1. **jsTree事件触发**：`🖱️ jsTree文件被选中`
2. **直接文件切换**：没有未保存内容检测
3. **状态直接重置**：`✅ 未保存状态已重置`

## 问题根源

### 事件处理流程
1. **jsTree选择事件** → `select_node.jstree`
2. **调用selectFile函数** → 直接加载文件
3. **调用onFileSwitch函数** → 使用旧的hasUnsavedChanges变量
4. **状态重置** → 绕过了新的UnsavedChangesGuard系统

### 关键问题
- `selectFile`函数没有集成未保存内容检测
- `onFileSwitch`函数使用旧的状态管理系统
- jsTree事件处理绕过了我们之前添加的守卫逻辑

## 修复方案

### 1. 修改selectFile函数

**位置**：`templates/pages/online_course_notes.html` 第4881行

**修改前**：
```javascript
function selectFile(filePath) {
    // 直接处理文件加载，没有未保存检测
    debugLog('选择文件: ' + filePath);
    // ... 直接加载文件逻辑
}
```

**修改后**：
```javascript
function selectFile(filePath) {
    debugLog('选择文件: ' + filePath);
    
    // 标准化文件路径
    let normalizedPath = filePath.replace(/\\/g, '/');
    
    // 检查是否切换到不同文件，如果是则进行未保存内容检测
    if (window.UnsavedChangesGuard && currentFilePath && currentFilePath !== normalizedPath) {
        console.log('🛡️ jsTree文件切换检测未保存内容');
        console.log('📁 从文件:', currentFilePath, '切换到:', normalizedPath);
        
        // 使用守卫系统检查是否可以导航
        window.UnsavedChangesGuard.canNavigate(function() {
            console.log('✅ 用户确认文件切换，继续加载: ' + normalizedPath);
            
            // 重置守卫状态
            if (window.UnsavedChangesGuard) {
                window.UnsavedChangesGuard.reset();
            }
            
            // 继续执行文件加载
            loadFileInSelectFile(normalizedPath);
        });
        return; // 等待用户确认，不继续执行
    }
    
    // 无未保存内容或同一文件，直接加载
    console.log('✅ 无未保存内容或同一文件，直接加载: ' + normalizedPath);
    loadFileInSelectFile(normalizedPath);
}
```

### 2. 提取文件加载逻辑

**新增函数**：`loadFileInSelectFile(normalizedPath)`

将原来`selectFile`函数中的文件加载逻辑提取到独立函数中，确保：
- 检测通过后可以继续加载
- 无未保存内容时直接加载
- 保持原有的文件加载功能不变

### 3. 文件加载后重新注册编辑器

**位置**：在文件加载完成回调中添加

```javascript
// 重新注册编辑器到未保存内容守卫系统
setTimeout(function() {
    const editContent = document.getElementById('edit-content');
    if (editContent && window.UnsavedChangesGuard) {
        // 取消之前的监控
        window.UnsavedChangesGuard.reset();
        
        // 重新注册当前文件的编辑器
        window.UnsavedChangesGuard.registerEditor(editContent, normalizedPath, function() {
            return new Promise((resolve, reject) => {
                if (normalizedPath && editContent.value) {
                    console.log('💾 执行网课笔记保存 (jsTree文件切换后)');
                    
                    if (window.pybridge && window.pybridge.save_file) {
                        window.pybridge.save_file(normalizedPath, editContent.value, function(result) {
                            // 处理保存结果
                            try {
                                const response = typeof result === 'string' ? JSON.parse(result) : result;
                                if (response.success) {
                                    console.log('✅ 网课笔记保存成功 (jsTree文件切换后)');
                                    originalContent = editContent.value;
                                    hasUnsavedChanges = false;
                                    hideUnsavedIndicator();
                                    resolve();
                                } else {
                                    console.error('❌ 网课笔记保存失败 (jsTree文件切换后):', response.error);
                                    reject(new Error(response.error));
                                }
                            } catch (e) {
                                console.error('❌ 解析保存响应失败 (jsTree文件切换后):', e);
                                reject(e);
                            }
                        });
                    } else {
                        reject(new Error('保存功能不可用'));
                    }
                } else {
                    reject(new Error('没有文件路径或内容'));
                }
            });
        });
        
        console.log('✅ jsTree文件切换后重新注册编辑器到未保存内容守卫');
    }
}, 500);
```

## 修复效果

### 预期行为
1. **编辑文件A** → 修改内容但不保存
2. **点击jsTree中的文件B** → 弹出保存提示对话框
3. **用户选择**：
   - **保存**：保存文件A后切换到文件B
   - **不保存**：直接切换到文件B，丢弃更改
   - **取消**：停留在文件A，继续编辑

### 日志输出
修复后的日志应该显示：
```
[时间] 🛡️ jsTree文件切换检测未保存内容
[时间] 📁 从文件: vault/test222.md 切换到: vault/柯基学习法.md
[时间] 📋 显示保存提示对话框
[时间] ✅ 用户确认文件切换，继续加载: vault/柯基学习法.md
[时间] ✅ jsTree文件切换后重新注册编辑器到未保存内容守卫
```

## 技术要点

### 关键检查条件
```javascript
if (window.UnsavedChangesGuard && currentFilePath && currentFilePath !== normalizedPath)
```

### 异步处理
- 使用`canNavigate`方法处理用户选择
- 通过回调函数继续文件加载流程
- `return`语句阻止直接执行，等待用户确认

### 状态管理
- 切换前重置守卫状态：`window.UnsavedChangesGuard.reset()`
- 加载后重新注册编辑器：`registerEditor()`
- 延迟注册确保DOM完全加载：`setTimeout(..., 500)`

### 兼容性
- 保持原有`selectFile`函数接口不变
- 向后兼容现有的文件加载逻辑
- 渐进增强，不影响基础功能

## 测试验证

### 测试场景
1. **基础功能**：编辑文件A → 点击文件B → 应弹出保存提示
2. **保存选择**：选择"保存" → 应保存文件A并切换到文件B
3. **不保存选择**：选择"不保存" → 应直接切换到文件B
4. **取消选择**：选择"取消" → 应停留在文件A
5. **无更改切换**：无编辑内容时切换 → 应直接切换，不弹提示
6. **同文件点击**：点击当前文件 → 应直接加载，不弹提示

### 验证要点
- ✅ jsTree文件选择触发未保存检测
- ✅ 保存提示对话框正确显示
- ✅ 用户选择后正确处理
- ✅ 文件切换后编辑器重新注册
- ✅ 控制台日志显示正确的调试信息

## 页面差异

### 网课笔记页面
- **使用jsTree**：需要修改`selectFile`函数
- **事件流程**：`select_node.jstree` → `selectFile` → 未保存检测

### 从资料学习页面
- **使用handleFileClick**：已在之前修复
- **事件流程**：文件点击 → `handleFileClick` → 未保存检测

## 总结

通过修改`selectFile`函数，现在网课笔记页面的jsTree文件切换也具备了完整的未保存内容检测功能。结合之前的修复，整个系统现在在所有文件切换场景下都能正确保护用户的编辑内容：

1. **页面级导航**：侧边栏菜单切换
2. **文件级导航**：文件树中的文件切换（jsTree和普通点击）
3. **浏览器级导航**：页面刷新、关闭、切换标签页

这确保了用户在任何情况下都不会意外丢失编辑内容。
