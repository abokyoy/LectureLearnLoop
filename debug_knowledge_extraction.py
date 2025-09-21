"""
调试知识点提取功能
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from knowledge_management import KnowledgeManagementSystem
import traceback

def test_knowledge_extraction():
    """测试知识点提取功能"""
    
    # 读取配置
    try:
        import json
        with open('app_config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        print("配置文件加载成功")
        print(f"API密钥配置: {'已配置' if config.get('gemini_api_key') else '未配置'}")
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        return
    
    # 测试数据
    subject_name = "机器学习"
    note_content = """
    线性回归是机器学习中的基础算法。它使用梯度下降法来优化参数，
    学习率的选择很重要：学习率过大会导致震荡，过小会收敛很慢。
    线性回归的损失函数通常使用均方误差(MSE)。
    """
    
    print(f"测试学科: {subject_name}")
    print(f"测试内容长度: {len(note_content)}")
    
    try:
        # 创建知识管理系统
        km_system = KnowledgeManagementSystem(config)
        print("知识管理系统创建成功")
        
        # 测试提取知识点
        print("开始提取知识点...")
        result = km_system.extract_knowledge_points(subject_name, note_content)
        
        print("提取成功!")
        print(f"结果类型: {type(result)}")
        print("结果内容:")
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
    except Exception as e:
        print(f"提取失败: {e}")
        print("详细错误信息:")
        traceback.print_exc()

if __name__ == "__main__":
    test_knowledge_extraction()
