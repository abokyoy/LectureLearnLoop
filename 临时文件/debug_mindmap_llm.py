#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脑图LLM生成问题
"""

import json
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from knowledge_management import KnowledgeManagementSystem
from config import load_config

def debug_llm_mindmap_generation():
    """调试LLM脑图生成"""
    print("=" * 60)
    print("🔍 调试LLM脑图生成")
    print("=" * 60)
    
    config = load_config()
    km_system = KnowledgeManagementSystem(config)
    
    # 选择数据结构学科（有11个知识点）
    subject_name = "数据结构"
    
    print(f"📚 测试学科: {subject_name}")
    
    # 1. 获取知识点
    knowledge_points = km_system.get_knowledge_points_by_subject(subject_name)
    print(f"📊 知识点数量: {len(knowledge_points)}")
    
    if not knowledge_points:
        print("❌ 没有知识点数据")
        return
    
    # 显示知识点
    print("\n知识点列表:")
    for i, kp in enumerate(knowledge_points):
        print(f"  {i+1}. ID:{kp['id']} - {kp['point_name']}")
    
    # 2. 测试LLM调用
    print(f"\n🧠 测试LLM脑图生成...")
    
    try:
        # 直接调用MindmapManager的方法
        mindmap_manager = km_system.mindmap_manager
        mindmap_data = mindmap_manager.generate_mindmap_with_llm(subject_name, knowledge_points)
        
        if mindmap_data:
            print("✅ LLM脑图生成成功!")
            
            # 检查数据结构
            nodes = mindmap_data.get('nodes', [])
            edges = mindmap_data.get('edges', [])
            
            print(f"📊 节点数量: {len(nodes)}")
            print(f"🔗 连线数量: {len(edges)}")
            
            # 显示节点
            if nodes:
                print("\n节点详情:")
                for i, node in enumerate(nodes):
                    print(f"  {i+1}. ID:{node.get('id', 'unknown')} - {node.get('name', 'unnamed')} ({node.get('type', 'unknown')})")
            
            # 显示连线
            if edges:
                print("\n连线详情:")
                for i, edge in enumerate(edges):
                    print(f"  {i+1}. {edge.get('source', 'unknown')} -> {edge.get('target', 'unknown')}")
            
            # 保存原始LLM响应
            output_file = "llm_mindmap_raw.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(mindmap_data, f, ensure_ascii=False, indent=2)
            print(f"\n💾 LLM生成的脑图数据已保存到: {output_file}")
            
            return mindmap_data
            
        else:
            print("❌ LLM脑图生成失败")
            return None
            
    except Exception as e:
        print(f"❌ LLM调用出错: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_llm_provider():
    """测试LLM提供者"""
    print("\n" + "=" * 60)
    print("🤖 测试LLM提供者")
    print("=" * 60)
    
    try:
        config = load_config()
        print(f"📋 配置文件加载成功")
        
        # 检查LLM配置
        llm_config = config.get('llm', {})
        print(f"🔧 LLM配置: {llm_config}")
        
        from llm_provider_factory import LLMProviderFactory
        
        factory = LLMProviderFactory()
        llm_provider = factory.get_provider()
        
        print(f"✅ LLM提供者创建成功: {type(llm_provider).__name__}")
        
        # 测试简单调用
        test_prompt = "请回答：1+1等于几？"
        print(f"🧪 测试提示词: {test_prompt}")
        
        response = llm_provider.call(test_prompt)
        print(f"📝 LLM响应: {response[:100]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ LLM提供者测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        # 测试LLM提供者
        llm_ok = test_llm_provider()
        
        if llm_ok:
            # 测试脑图生成
            debug_llm_mindmap_generation()
        else:
            print("❌ LLM提供者不可用，跳过脑图生成测试")
        
        print("\n" + "=" * 60)
        print("🎉 调试完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()
