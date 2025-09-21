#!/usr/bin/env python3
"""
调试知识点提取功能
"""

import sys
import os
import json
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def debug_knowledge_manager():
    """直接调试KnowledgeManager"""
    print("🔍 调试KnowledgeManager")
    print("=" * 50)
    
    try:
        from knowledge_management import KnowledgeManager
        from config import load_config
        
        # 加载配置
        config = load_config()
        print(f"✅ 配置加载成功: {config.get('llm_provider', 'Unknown')}")
        
        # 创建KnowledgeManager实例
        km = KnowledgeManager(config)
        print("✅ KnowledgeManager创建成功")
        
        # 测试内容
        test_content = """
        # 机器学习基础
        
        机器学习是人工智能的一个重要分支，它使计算机能够从数据中学习并做出预测或决策。
        
        ## 监督学习
        监督学习是一种机器学习方法，它使用标记的训练数据来学习输入和输出之间的映射关系。
        
        ## 无监督学习
        无监督学习是在没有标记数据的情况下发现数据中隐藏模式的方法。
        """
        
        print(f"📄 测试内容长度: {len(test_content)} 字符")
        
        # 调用提取方法
        result = km.extract_knowledge_points("机器学习", test_content)
        
        print(f"🎯 返回结果类型: {type(result)}")
        print(f"🎯 返回结果: {result}")
        
        if isinstance(result, list):
            print(f"✅ 获得知识点列表，包含 {len(result)} 个知识点")
            for i, point in enumerate(result):
                print(f"  {i+1}. {point}")
        elif isinstance(result, dict):
            print(f"✅ 获得字典结果")
            if "success" in result:
                print(f"  成功状态: {result['success']}")
            if "error" in result:
                print(f"  错误信息: {result['error']}")
        else:
            print(f"❌ 未知的返回类型: {type(result)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def debug_knowledge_management_system():
    """调试KnowledgeManagementSystem"""
    print("\n🔍 调试KnowledgeManagementSystem")
    print("=" * 50)
    
    try:
        from knowledge_management import KnowledgeManagementSystem
        from config import load_config
        
        # 加载配置
        config = load_config()
        print(f"✅ 配置加载成功: {config.get('llm_provider', 'Unknown')}")
        
        # 创建KnowledgeManagementSystem实例
        kms = KnowledgeManagementSystem(config)
        print("✅ KnowledgeManagementSystem创建成功")
        
        # 测试内容
        test_content = """
        # 深度学习
        
        深度学习是机器学习的一个子领域，它基于人工神经网络，特别是深层神经网络。
        
        ## 神经网络
        神经网络是由相互连接的节点（神经元）组成的计算模型，模拟生物神经网络的结构和功能。
        
        ## 反向传播
        反向传播是训练神经网络的核心算法，通过计算梯度来更新网络权重。
        """
        
        print(f"📄 测试内容长度: {len(test_content)} 字符")
        
        # 调用提取方法
        result = kms.extract_knowledge_points("深度学习", test_content)
        
        print(f"🎯 返回结果类型: {type(result)}")
        print(f"🎯 返回结果: {result}")
        
        if isinstance(result, dict):
            if result.get("success", False):
                processed_points = result.get("processed_points", [])
                print(f"✅ 成功提取，包含 {len(processed_points)} 个处理后的知识点")
                for i, point_data in enumerate(processed_points):
                    extracted_point = point_data.get("extracted_point", {})
                    print(f"  {i+1}. {extracted_point}")
            else:
                error_msg = result.get("error", "未知错误")
                print(f"❌ 提取失败: {error_msg}")
        elif isinstance(result, list):
            print(f"✅ 直接获得知识点列表，包含 {len(result)} 个知识点")
            for i, point in enumerate(result):
                print(f"  {i+1}. {point}")
        else:
            print(f"❌ 未知的返回类型: {type(result)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主调试函数"""
    print("🚀 开始调试知识点提取功能")
    print("=" * 60)
    
    # 调试KnowledgeManager
    km_success = debug_knowledge_manager()
    
    # 调试KnowledgeManagementSystem
    kms_success = debug_knowledge_management_system()
    
    # 总结
    print("\n📊 调试结果总结")
    print("=" * 60)
    print(f"KnowledgeManager: {'✅ 正常' if km_success else '❌ 异常'}")
    print(f"KnowledgeManagementSystem: {'✅ 正常' if kms_success else '❌ 异常'}")

if __name__ == "__main__":
    main()
