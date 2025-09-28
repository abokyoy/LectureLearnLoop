# Stage节点交互问题修复

## 🚨 **问题现象**

- ✅ **第一次点击stage节点**：正常工作
- ❌ **点击其他stage切换**：不工作
- ❌ **再次点击恢复**：不工作

## 🔍 **问题分析**

### 可能的原因：
1. **事件绑定失效**：在修改节点样式后，点击事件可能失效
2. **节点ID比较问题**：currentHighlightedStage的ID比较可能有问题
3. **D3.js数据绑定变化**：在transition过程中数据绑定可能发生变化

## ✅ **修复方案**

### 1. **改进事件绑定**
```javascript
// 将点击事件绑定到节点组而不是circle
const nodeGroups = g.selectAll('.learning-node')
    .data(nodes)
    .enter().append('g')
    .attr('class', 'learning-node')
    .style('cursor', d => d.type === 'stage' ? 'pointer' : 'default')
    .on('click', function(event, d) {
        if (d.type === 'stage') {
            event.stopPropagation(); // 防止事件冒泡
            highlightStageAndChildren(d);
        }
    })
```

### 2. **添加详细调试信息**
```javascript
function highlightStageAndChildren(stageNode) {
    log(`🎯 点击stage节点: ${stageNode.name} (${stageNode.id})`);
    log(`🔍 当前突出显示状态: ${currentHighlightedStage ? currentHighlightedStage.id : 'null'}`);
    log(`✅ 全局变量检查通过: nodes=${globalNodes.length}, edges=${globalEdges.length}`);
    
    // 节点ID比较调试
    if (currentHighlightedStage && currentHighlightedStage.id === stageNode.id) {
        log(`🔄 检测到重复点击同一节点: ${stageNode.id}，执行恢复操作`);
        resetHighlight();
        return;
    }
    
    // 切换调试
    if (currentHighlightedStage) {
        log(`🔀 从 ${currentHighlightedStage.id} 切换到 ${stageNode.id}`);
    }
}
```

### 3. **添加背景点击恢复**
```javascript
// 点击空白区域恢复正常显示
svg.on('click', function(event) {
    if (event.target === this && currentHighlightedStage) {
        log('🖱️ 点击背景，恢复正常显示');
        resetHighlight();
    }
});
```

## 🧪 **测试步骤**

### 1. **重启应用并测试**
```
1. 重启应用程序
2. 进入学习路径页面
3. 打开浏览器开发者工具查看控制台日志
```

### 2. **第一次点击测试**
```
1. 点击任意stage节点（如"数学基础阶段"）
2. 观察控制台日志：
   🎯 点击stage节点: 数学基础阶段 (stage1)
   🔍 当前突出显示状态: null
   ✅ 全局变量检查通过: nodes=40, edges=52
   📋 找到5个子节点: kp_linear_algebra, kp_calculus...
   ✅ 突出显示效果正常
```

### 3. **切换节点测试**
```
1. 在第一个节点突出显示状态下，点击另一个stage节点
2. 观察控制台日志：
   🎯 点击stage节点: 编程基础阶段 (stage2)
   🔍 当前突出显示状态: stage1
   ✅ 全局变量检查通过: nodes=40, edges=52
   🔀 从 stage1 切换到 stage2
   📋 找到3个子节点: kp_python_basics, kp_pandas_numpy...
```

### 4. **恢复显示测试**
```
1. 在突出显示状态下，再次点击同一个stage节点
2. 观察控制台日志：
   🎯 点击stage节点: 编程基础阶段 (stage2)
   🔍 当前突出显示状态: stage2
   🔄 检测到重复点击同一节点: stage2，执行恢复操作
   🔄 恢复正常显示
```

### 5. **背景点击测试**
```
1. 在突出显示状态下，点击空白区域
2. 观察控制台日志：
   🖱️ 点击背景，恢复正常显示
   🔄 恢复正常显示
```

## 🔧 **调试指南**

### 如果第一次点击不工作：
```
检查日志中是否有：
❌ 全局变量未初始化，无法执行突出显示
→ 说明渲染过程有问题，需要检查renderLearningPath函数
```

### 如果切换不工作：
```
检查日志中是否显示：
🔀 从 stageX 切换到 stageY
→ 如果没有这条日志，说明点击事件没有触发
→ 检查节点组的事件绑定
```

### 如果恢复不工作：
```
检查日志中是否显示：
🔄 检测到重复点击同一节点: stageX，执行恢复操作
→ 如果没有这条日志，说明节点ID比较有问题
→ 检查currentHighlightedStage的保存和比较逻辑
```

## 🎯 **预期修复效果**

### 完整的交互流程：
```
1. 点击stage1 → 突出显示stage1及其子节点
2. 点击stage2 → 切换到突出显示stage2及其子节点
3. 再次点击stage2 → 恢复正常显示
4. 点击空白区域 → 恢复正常显示（如果有突出显示）
5. 点击重置按钮 → 恢复正常显示
```

### 控制台日志示例：
```
🎯 点击stage节点: 数学基础阶段 (stage1)
🔍 当前突出显示状态: null
✅ 全局变量检查通过: nodes=40, edges=52
📋 找到5个子节点: kp_linear_algebra, kp_calculus, kp_probability, kp_python_basics, kp_pandas_numpy

🎯 点击stage节点: 编程基础阶段 (stage2)  
🔍 当前突出显示状态: stage1
✅ 全局变量检查通过: nodes=40, edges=52
🔀 从 stage1 切换到 stage2
📋 找到3个子节点: kp_missing_value_handling, kp_scaling_normalization, kp_feature_encoding

🎯 点击stage节点: 编程基础阶段 (stage2)
🔍 当前突出显示状态: stage2  
🔄 检测到重复点击同一节点: stage2，执行恢复操作
🔄 恢复正常显示
```

## 💡 **如果问题仍然存在**

### 可能需要进一步检查：
1. **D3.js版本兼容性**：确认D3.js版本支持当前的事件处理方式
2. **CSS样式冲突**：检查是否有CSS样式影响了点击事件
3. **浏览器兼容性**：在不同浏览器中测试
4. **事件传播**：检查是否有其他元素阻止了事件传播

### 备用解决方案：
1. **使用委托事件**：将事件绑定到父容器上
2. **重新绑定事件**：在每次样式修改后重新绑定点击事件
3. **使用原生事件**：改用原生JavaScript事件而不是D3.js事件

---

**请按照测试步骤验证修复效果，并查看控制台日志来诊断具体问题！** 🔧🧪
