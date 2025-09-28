# 学习路径Stage节点交互功能实现

## 🎯 **功能需求**

仿照知识脑图功能中点击节点隐藏其他细节的方式，实现点击stage节点突出显示该节点及其子节点。

## ✅ **功能实现**

### 1. **点击交互**

#### 添加点击事件：
```javascript
.style('cursor', d => d.type === 'stage' ? 'pointer' : 'default')
.on('click', function(event, d) {
    if (d.type === 'stage') {
        highlightStageAndChildren(d);
    }
});
```

#### 视觉提示：
- ✅ **鼠标指针**：stage节点显示手型指针
- ✅ **点击响应**：只有stage节点可点击
- ✅ **即时反馈**：点击后立即响应

### 2. **突出显示算法**

#### 子节点查找：
```javascript
// 找到该stage的所有子知识点
const childrenIds = new Set();
const finalEdges = invalidEdges && invalidEdges.length > 0 ? validEdges : edges;

finalEdges.forEach(edge => {
    if (edge.source === stageNode.id || (typeof edge.source === 'object' && edge.source.id === stageNode.id)) {
        const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id;
        childrenIds.add(targetId);
    }
});
```

#### 视觉突出：
```javascript
// 节点透明度控制
.style('opacity', d => {
    if (d.id === stageNode.id || childrenIds.has(d.id)) {
        return 1.0; // 完全不透明
    }
    return 0.2; // 很透明
})

// 边框粗细控制
.attr('stroke-width', d => {
    if (d.id === stageNode.id) {
        return 6; // stage节点边框最粗
    }
    if (childrenIds.has(d.id)) {
        return 4; // 子节点边框较粗
    }
    return 1; // 其他节点边框变细
})
```

### 3. **文字和连线突出**

#### 文字效果：
```javascript
nodeGroups.selectAll('text')
    .style('opacity', d => d.id === stageNode.id || childrenIds.has(d.id) ? 1.0 : 0.3)
    .style('font-weight', d => d.id === stageNode.id || childrenIds.has(d.id) ? 'bold' : 'normal');
```

#### 连线效果：
```javascript
links.style('opacity', d => {
    const sourceId = typeof d.source === 'string' ? d.source : d.source.id;
    const targetId = typeof d.target === 'string' ? d.target : d.target.id;
    
    if (sourceId === stageNode.id || targetId === stageNode.id) {
        return 1.0; // 相关连线突出
    }
    return 0.1; // 其他连线淡化
})
```

### 4. **信息提示框**

#### 动态信息显示：
```javascript
function showStageInfo(stageNode, childrenCount) {
    const infoBox = d3.select('#mindmapSvgContainer')
        .append('div')
        .attr('id', 'stageInfoBox')
        .style('position', 'absolute')
        .style('top', '10px')
        .style('right', '10px')
        .style('background', 'rgba(0,0,0,0.8)')
        .style('color', 'white')
        .html(`
            <div style="font-weight: bold;">📚 ${stageNode.name}</div>
            <div style="font-size: 12px;">包含 ${childrenCount} 个知识点</div>
            <div style="font-size: 11px;">点击其他stage切换 | 再次点击恢复</div>
        `);
}
```

### 5. **状态管理**

#### 全局状态：
```javascript
let currentHighlightedStage = null;
```

#### 切换逻辑：
- **首次点击**：突出显示该stage及其子节点
- **再次点击同一stage**：恢复正常显示
- **点击其他stage**：切换到新的stage
- **点击重置按钮**：恢复正常显示

## 🎨 **视觉效果**

### 突出显示状态：

```
     ○ ○ ○ ○ ○     ○ ○ ○ ○ ○     ● ● ● ● ●     ○ ○ ○ ○ ○
      \ | | | /      \ | | | /      \ | | | /      \ | | | /
       \| | |/        \| | |/        \| | |/        \| | |/
        ○ ○ ○          ○ ○ ○          ● ● ●          ○ ○ ○
         \ /            \ /            \ /            \ /
          |              |              |              |
起点 ——— 阶段1 ——— 阶段2 ——— 【阶段3】——— 阶段4 ——— 终点
          |              |              |              |
         / \            / \            / \            / \
        ○ ○ ○          ○ ○ ○          ● ● ●          ○ ○ ○
       /| | |\        /| | |\        /| | |\        /| | |\
      / | | | \      / | | | \      / | | | \      / | | | \
     ○ ○ ○ ○ ○     ○ ○ ○ ○ ○     ● ● ● ● ●     ○ ○ ○ ○ ○

○ = 淡化节点 (透明度0.2)
● = 突出节点 (透明度1.0, 粗边框)
【】= 当前选中的stage节点 (最粗边框)
```

### 效果特征：
- ✅ **选中stage**：边框最粗(6px)，完全不透明
- ✅ **相关知识点**：边框较粗(4px)，完全不透明，文字加粗
- ✅ **其他节点**：边框变细(1px)，高度透明(0.2)
- ✅ **相关连线**：粗线(4px)，完全不透明
- ✅ **其他连线**：细线(1px)，高度透明(0.1)

## 🔧 **交互流程**

### 1. **点击stage节点**
```
用户点击 → 查找子节点 → 突出显示 → 显示信息框 → 记录状态
```

### 2. **再次点击同一stage**
```
检测重复点击 → 恢复正常显示 → 隐藏信息框 → 清除状态
```

### 3. **点击其他stage**
```
检测不同stage → 切换突出显示 → 更新信息框 → 更新状态
```

### 4. **点击重置按钮**
```
用户点击重置 → 恢复所有显示 → 隐藏信息框 → 清除状态
```

## 🎯 **用户体验**

### 交互特性：
- **直观操作**：点击stage节点即可聚焦
- **视觉清晰**：突出显示相关内容，淡化无关内容
- **状态切换**：支持在不同stage间快速切换
- **恢复机制**：多种方式恢复正常显示

### 信息反馈：
- **实时提示**：右上角显示当前stage信息
- **数量统计**：显示包含的知识点数量
- **操作指引**：提示如何切换和恢复

### 动画效果：
- **平滑过渡**：300ms过渡动画
- **淡入淡出**：透明度渐变效果
- **边框变化**：边框粗细平滑变化

## 💡 **技术亮点**

1. **智能子节点查找**：自动识别stage的所有子知识点
2. **多重视觉突出**：透明度+边框+文字+连线全方位突出
3. **状态管理**：完整的交互状态跟踪和切换
4. **信息提示**：动态信息框显示当前状态
5. **恢复机制**：多种方式恢复正常显示
6. **平滑动画**：所有变化都有过渡动画

## 🚀 **使用场景**

### 学习场景：
- **阶段聚焦**：专注学习某个特定阶段
- **知识点梳理**：查看某阶段包含的所有知识点
- **学习规划**：了解每个阶段的学习内容

### 教学场景：
- **重点讲解**：突出显示当前讲解的阶段
- **内容组织**：清晰展示知识点的归属关系
- **互动教学**：引导学生关注特定内容

---

**学习路径Stage节点交互功能实现完成！现在支持点击stage节点进行聚焦显示！** 🎯✨
