# Obsidian图片格式支持说明

## 功能概述
为网课笔记系统添加了Obsidian兼容的图片插入和显示功能，支持`![[filename]]`格式。

## 修改内容

### 1. 图片插入格式修改
**位置**: `templates/pages/online_course_notes.html` - `insertScreenshotToDocument`函数

**修改前**:
```javascript
const imageText = '\n\n![截图](' + imagePath + ')\n\n';
```

**修改后**:
```javascript
// 使用Obsidian兼容的图片格式，只使用文件名，不包含路径
const fileName = imagePath.split('/').pop(); // 提取文件名
const imageText = '\n\n![[' + fileName + ']]\n\n';
```

### 2. Markdown渲染支持
**位置**: `templates/pages/online_course_notes.html` - `renderMarkdownContent`函数

**新增预处理**:
```javascript
// 预处理：支持Obsidian格式的图片 ![[filename]]
content = content.replace(/!\[\[([^\]]+)\]\]/g, function(match, filename) {
    // 构建图片路径：假设图片在attachments目录中
    const imagePath = 'attachments/' + filename;
    return `![${filename}](${imagePath})`;
});
```

## 工作原理

### 插入阶段
1. **截图保存**: 图片保存到 `attachments/screenshot_YYYYMMDD_HHMMSS.png`
2. **路径提取**: 从完整路径中提取文件名 `screenshot_YYYYMMDD_HHMMSS.png`
3. **格式插入**: 插入Obsidian格式 `![[screenshot_YYYYMMDD_HHMMSS.png]]`

### 渲染阶段
1. **格式识别**: 识别 `![[filename]]` 模式
2. **路径构建**: 转换为标准Markdown格式 `![filename](attachments/filename)`
3. **图片显示**: 通过现有的图片路径处理逻辑显示图片

## 格式对比

### 标准Markdown格式
```markdown
![截图](attachments/screenshot_20250926_091553.png)
```

### Obsidian格式
```markdown
![[screenshot_20250926_091553.png]]
```

## 优势

### Obsidian兼容性
- **简洁格式**: 只需文件名，无需路径
- **自动链接**: Obsidian会自动查找同名文件
- **重构友好**: 移动文件时链接不会断开

### 系统兼容性
- **向下兼容**: 现有的标准Markdown图片仍然支持
- **双格式支持**: 同时支持两种格式
- **无缝转换**: Obsidian格式在渲染时转换为标准格式

## 测试用例

### 测试1: 截图插入
1. 打开笔记文档
2. 点击截图按钮
3. 选择截图区域
4. **预期结果**: 插入 `![[screenshot_YYYYMMDD_HHMMSS.png]]`

### 测试2: 预览显示
1. 编辑器中包含 `![[screenshot_20250926_091553.png]]`
2. 切换到预览模式
3. **预期结果**: 图片正常显示

### 测试3: 混合格式
编辑器内容:
```markdown
# 测试文档

标准格式图片:
![截图1](attachments/image1.png)

Obsidian格式图片:
![[image2.png]]
```

**预期结果**: 两种格式的图片都能正常显示

## 文件结构示例

```
vault/
├── 笔记文档.md                     # 包含 ![[screenshot.png]]
├── attachments/                    # 图片存储目录
│   ├── screenshot_20250926_091553.png
│   └── screenshot_20250926_092145.png
└── 其他文档.md
```

## 技术细节

### 正则表达式
- **Obsidian格式匹配**: `/!\[\[([^\]]+)\]\]/g`
- **文件名提取**: `imagePath.split('/').pop()`
- **路径构建**: `'attachments/' + filename`

### 处理流程
1. **预处理阶段**: Obsidian格式 → 标准Markdown格式
2. **Marked渲染**: 标准Markdown → HTML
3. **后处理阶段**: 相对路径 → 绝对路径

### 错误处理
- 如果文件不存在，显示占位符
- 如果路径解析失败，保持原始格式
- 兼容不同的文件名格式

## 总结
通过添加Obsidian格式支持，网课笔记系统现在可以：
- 使用更简洁的图片插入格式
- 与Obsidian软件保持兼容
- 支持双格式并存
- 保持现有功能的完整性

用户可以享受到更好的笔记体验，同时保持与Obsidian生态系统的兼容性。
