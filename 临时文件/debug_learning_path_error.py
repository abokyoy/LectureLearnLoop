#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
调试学习路径错误
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def debug_learning_path_error():
    """调试学习路径错误"""
    print("🔍 调试学习路径错误")
    print("=" * 50)
    
    try:
        # 1. 测试导入
        print("1. 测试模块导入...")
        from knowledge_management import KnowledgeManagementSystem
        print("✅ KnowledgeManagementSystem 导入成功")
        
        # 2. 测试配置
        print("\n2. 测试配置...")
        config = {
            "llm_provider": "DeepSeek",
            "deepseek_api_key": "sk-test",
            "deepseek_model": "deepseek-chat"
        }
        km_system = KnowledgeManagementSystem(config)
        print("✅ KnowledgeManagementSystem 创建成功")
        
        # 3. 测试知识点获取
        print("\n3. 测试知识点获取...")
        subject_name = "机器学习"
        knowledge_points = km_system.get_knowledge_points_by_subject(subject_name)
        print(f"✅ 获取到 {len(knowledge_points)} 个知识点")
        
        # 4. 测试方法存在性
        print("\n4. 测试方法存在性...")
        if hasattr(km_system, 'get_or_generate_learning_path'):
            print("✅ get_or_generate_learning_path 方法存在")
        else:
            print("❌ get_or_generate_learning_path 方法不存在")
            return
            
        if hasattr(km_system.mindmap_manager, 'get_or_generate_learning_path'):
            print("✅ mindmap_manager.get_or_generate_learning_path 方法存在")
        else:
            print("❌ mindmap_manager.get_or_generate_learning_path 方法不存在")
            return
        
        # 5. 测试缓存查询
        print("\n5. 测试缓存查询...")
        try:
            cached_path = km_system.mindmap_manager._get_cached_learning_path(subject_name)
            if cached_path:
                print(f"✅ 找到缓存学习路径")
            else:
                print(f"ℹ️ 没有缓存学习路径")
        except Exception as cache_error:
            print(f"❌ 缓存查询失败: {cache_error}")
        
        # 6. 测试知识点获取（内部方法）
        print("\n6. 测试内部知识点获取...")
        try:
            internal_kps = km_system.mindmap_manager._get_knowledge_points_by_subject(subject_name)
            print(f"✅ 内部方法获取到 {len(internal_kps)} 个知识点")
        except Exception as internal_error:
            print(f"❌ 内部方法失败: {internal_error}")
            import traceback
            traceback.print_exc()
        
        # 7. 测试LLM提供者工厂导入
        print("\n7. 测试LLM提供者工厂...")
        try:
            from llm_provider_factory import LLMProviderFactory
            llm_factory = LLMProviderFactory(config)
            print("✅ LLMProviderFactory 创建成功")
        except Exception as llm_error:
            print(f"❌ LLMProviderFactory 失败: {llm_error}")
        
        print(f"\n✅ 基础测试完成")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_learning_path_error()
