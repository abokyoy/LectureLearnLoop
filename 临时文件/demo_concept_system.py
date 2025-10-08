#!/usr/bin/env python3
"""
核心概念提取系统演示
展示新系统相比旧系统的优势
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from knowledge_management import KnowledgeManagementSystem

def demo_concept_extraction():
    """演示核心概念提取功能"""
    print("=" * 60)
    print("🎯 学科核心概念提取系统演示")
    print("=" * 60)
    
    # 加载配置
    config = load_config()
    km_system = KnowledgeManagementSystem(config)
    
    # 测试案例：不同学科的学习材料
    test_cases = [
        {
            "subject": "机器学习",
            "content": """
# 机器学习中的过拟合问题

## 什么是过拟合
过拟合是指机器学习模型在训练数据上表现很好，但在新的、未见过的测试数据上表现较差的现象。这通常发生在模型过于复杂，学习了训练数据中的噪声和特殊情况。

## 检测过拟合的方法
1. 使用验证集：将数据分为训练集、验证集和测试集
2. 学习曲线分析：观察训练误差和验证误差的变化
3. 交叉验证：使用k折交叉验证评估模型性能

## 防止过拟合的技术
### 正则化
正则化是在损失函数中添加惩罚项，约束模型复杂度的技术。
- L1正则化：添加参数绝对值的惩罚
- L2正则化：添加参数平方和的惩罚

### 早停法
在验证误差开始上升时停止训练，防止模型过度学习训练数据。

### Dropout
随机丢弃一部分神经元，减少模型对特定神经元的依赖。
""",
            "expected_concepts": ["过拟合", "交叉验证", "正则化", "L1正则化", "L2正则化", "早停法", "Dropout"]
        },
        {
            "subject": "物理学", 
            "content": """
# 经典力学基础

## 牛顿运动定律
牛顿运动定律是经典力学的基础，包括三个基本定律：

### 牛顿第一定律（惯性定律）
物体在不受外力或所受合外力为零时，保持静止状态或匀速直线运动状态。
这个定律揭示了惯性的概念。

### 牛顿第二定律
物体的加速度与作用在物体上的合外力成正比，与物体的质量成反比。
数学表达式：F = ma

### 牛顿第三定律（作用与反作用定律）  
两个物体之间的作用力和反作用力大小相等、方向相反、作用在不同物体上。

## 动量和动量守恒
动量是物体质量和速度的乘积：p = mv
在没有外力作用的封闭系统中，系统的总动量保持不变。

## 能量守恒定律
在一个孤立系统中，能量既不能创造也不能消灭，只能从一种形式转化为另一种形式。
""",
            "expected_concepts": ["牛顿第一定律", "牛顿第二定律", "牛顿第三定律", "惯性定律", "动量", "动量守恒", "能量守恒定律"]
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📚 测试案例 {i}: {test_case['subject']}")
        print("-" * 40)
        
        try:
            # 提取核心概念
            result = km_system.extract_knowledge_points(test_case['subject'], test_case['content'])
            
            if result.get('success', False):
                processed_points = result.get('processed_points', [])
                
                print(f"✅ 成功提取 {len(processed_points)} 个核心概念：")
                print()
                
                extracted_concepts = []
                for j, point_data in enumerate(processed_points, 1):
                    extracted_point = point_data.get('extracted_point', {})
                    concept_name = extracted_point.get('point_name', '')
                    core_definition = extracted_point.get('core_description', '')
                    
                    print(f"{j}. 📖 {concept_name}")
                    print(f"   💡 {core_definition}")
                    print()
                    
                    extracted_concepts.append(concept_name)
                
                # 分析提取质量
                print("🔍 提取质量分析：")
                expected = set(test_case['expected_concepts'])
                extracted = set(extracted_concepts)
                
                # 计算匹配度（考虑部分匹配）
                matches = 0
                for exp in expected:
                    for ext in extracted:
                        if exp.lower() in ext.lower() or ext.lower() in exp.lower():
                            matches += 1
                            break
                
                coverage = matches / len(expected) * 100 if expected else 0
                precision = matches / len(extracted) * 100 if extracted else 0
                
                print(f"   📊 概念覆盖率: {coverage:.1f}% ({matches}/{len(expected)})")
                print(f"   🎯 提取精度: {precision:.1f}%")
                print(f"   📝 数量控制: {len(extracted_concepts)} 个 (目标: 1-7个)")
                
                if coverage >= 60:
                    print("   ✅ 提取效果良好")
                else:
                    print("   ⚠️  可能需要优化提示词")
                    
            else:
                error_msg = result.get('error', '未知错误')
                print(f"❌ 提取失败: {error_msg}")
                
        except Exception as e:
            print(f"❌ 测试失败: {e}")
    
    print("\n" + "=" * 60)
    print("🎉 核心概念提取系统演示完成")
    print("=" * 60)
    print("\n💡 新系统优势：")
    print("   • 专注学科核心概念，避免通用知识点泛滥")
    print("   • 严格数量控制，保持知识库可管理性") 
    print("   • 精准定义，每个概念都有1-2句核心描述")
    print("   • 学科导向，根据不同领域特点提取相应概念")
    print("   • 排除案例和推导，只保留最本质的概念术语")

if __name__ == "__main__":
    demo_concept_extraction()
