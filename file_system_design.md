# 文件系统架构设计方案

## 方案对比分析

### 当前问题
- 文件系统 + 数据库双重管理，容易不同步
- 复杂的文件追踪逻辑，维护成本高
- 重命名文件导致知识点丢失

## 推荐方案：改进的纯文件系统

### 核心设计原则
1. **文件名即索引** - 通过编号管理文件
2. **知识点内嵌** - 知识点直接存储在文件中
3. **轻量元数据** - 最小化的配置文件

### 文件命名规范
```
vault/
├── 0001_机器学习基础概念.md
├── 0002_深度学习原理详解.md
├── 0003_神经网络架构设计.md
├── 未编号_临时笔记.md
└── .vault_config.json
```

### 知识点存储格式
```markdown
# 机器学习基础概念

<!-- META_START -->
file_id: 0001
created: 2025-10-16
knowledge_points: 5
<!-- META_END -->

<!-- KNOWLEDGE_POINTS_START -->
1. 监督学习 (Supervised Learning) - 使用标记数据训练模型
2. 无监督学习 (Unsupervised Learning) - 从无标记数据中发现模式
3. 强化学习 (Reinforcement Learning) - 通过奖励机制学习最优策略
4. 过拟合 (Overfitting) - 模型在训练数据上表现好但泛化能力差
5. 交叉验证 (Cross Validation) - 评估模型性能的统计方法
<!-- KNOWLEDGE_POINTS_END -->

## 正文内容
...
```

### 元数据配置文件
```json
{
  "version": "1.0",
  "next_file_id": 4,
  "files": {
    "0001": {
      "filename": "机器学习基础概念.md",
      "title": "机器学习基础概念",
      "created": "2025-10-16T10:00:00Z",
      "knowledge_points_count": 5,
      "last_modified": "2025-10-16T15:30:00Z"
    },
    "0002": {
      "filename": "深度学习原理详解.md", 
      "title": "深度学习原理详解",
      "created": "2025-10-16T11:00:00Z",
      "knowledge_points_count": 8,
      "last_modified": "2025-10-16T16:00:00Z"
    }
  },
  "settings": {
    "auto_assign_id": true,
    "backup_enabled": true,
    "knowledge_points_format": "markdown_comments"
  }
}
```

## 实现优势

### 1. 简单性
- 无需复杂的数据库追踪逻辑
- 文件重命名不会丢失知识点
- 备份就是复制文件夹

### 2. 可靠性  
- 知识点随文件保存，永不丢失
- 即使元数据文件损坏，主要内容仍然完整
- 可以用任何文本编辑器查看和编辑

### 3. 可扩展性
- 可以轻松添加新的元数据字段
- 支持不同的知识点存储格式
- 便于实现导入导出功能

### 4. 用户友好
- 文件名直接显示编号状态
- 知识点在文件中可见可编辑
- 支持传统的文件管理操作

## 技术实现要点

### 文件操作API
```python
class FileSystemManager:
    def assign_file_id(self, filepath):
        """为文件分配编号并重命名"""
        
    def extract_knowledge_points(self, filepath):
        """从文件中提取知识点"""
        
    def update_knowledge_points(self, filepath, points):
        """更新文件中的知识点"""
        
    def get_file_metadata(self, file_id):
        """获取文件元数据"""
```

### 前端显示逻辑
- 编号文件显示特殊图标
- 知识点数量显示在文件名旁
- 支持按编号排序和筛选

## 迁移策略

### 从当前系统迁移
1. 导出现有知识点数据
2. 为有知识点的文件分配编号
3. 将知识点写入文件内容
4. 生成元数据配置文件
5. 清理数据库依赖

### 渐进式实施
1. 先实现新文件的编号系统
2. 逐步迁移现有文件
3. 保持向后兼容性
4. 最后移除数据库依赖
