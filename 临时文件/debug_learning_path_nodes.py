#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
调试学习路径节点问题
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def debug_learning_path_nodes():
    """调试学习路径节点和边的数据结构"""
    print("🔍 调试学习路径节点问题")
    print("=" * 50)
    
    try:
        from knowledge_management import KnowledgeManagementSystem
        
        # 使用真实配置
        config = {
            "llm_provider": "DeepSeek",
            "deepseek_api_key": "sk-test",  # 需要真实API密钥
            "deepseek_model": "deepseek-chat"
        }
        
        # 创建知识管理系统
        km_system = KnowledgeManagementSystem(config)
        print("✅ KnowledgeManagementSystem 创建成功")
        
        # 获取学习路径数据
        subject_name = "机器学习"
        print(f"\n🎯 获取 '{subject_name}' 的学习路径数据...")
        
        try:
            learning_path_result = km_system.get_or_generate_learning_path(subject_name)
            
            if learning_path_result and learning_path_result.get('success'):
                data = learning_path_result.get('data', {})
                nodes = data.get('nodes', [])
                edges = data.get('edges', [])
                
                print(f"\n📊 数据结构分析：")
                print(f"   总节点数: {len(nodes)}")
                print(f"   总边数: {len(edges)}")
                
                # 分析节点
                print(f"\n🔍 节点详细信息：")
                node_ids = set()
                for i, node in enumerate(nodes, 1):
                    node_id = node.get('id', 'N/A')
                    node_name = node.get('name', 'N/A')
                    node_type = node.get('type', 'N/A')
                    node_level = node.get('level', 'N/A')
                    
                    node_ids.add(node_id)
                    print(f"   {i:2d}. ID: {node_id:15s} | 名称: {node_name:20s} | 类型: {node_type:12s} | 级别: {node_level}")
                
                # 分析边
                print(f"\n🔗 边详细信息：")
                valid_edges = []
                invalid_edges = []
                
                for i, edge in enumerate(edges, 1):
                    source = edge.get('source', 'N/A')
                    target = edge.get('target', 'N/A')
                    relationship = edge.get('relationship', 'N/A')
                    
                    # 检查边的有效性
                    source_exists = source in node_ids
                    target_exists = target in node_ids
                    is_valid = source_exists and target_exists
                    
                    if is_valid:
                        valid_edges.append(edge)
                        status = "✅"
                    else:
                        invalid_edges.append(edge)
                        status = "❌"
                    
                    print(f"   {i:2d}. {status} {source:15s} → {target:15s} | 关系: {relationship}")
                    if not source_exists:
                        print(f"       ⚠️  源节点 '{source}' 不存在")
                    if not target_exists:
                        print(f"       ⚠️  目标节点 '{target}' 不存在")
                
                print(f"\n📈 边有效性统计：")
                print(f"   有效边: {len(valid_edges)} 条")
                print(f"   无效边: {len(invalid_edges)} 条")
                print(f"   有效率: {len(valid_edges)/len(edges)*100:.1f}%")
                
                if invalid_edges:
                    print(f"\n❌ 无效边详情：")
                    for edge in invalid_edges:
                        print(f"   - {edge.get('source')} → {edge.get('target')}")
                
                # 分析节点类型分布
                print(f"\n📊 节点类型分布：")
                type_counts = {}
                for node in nodes:
                    node_type = node.get('type', 'unknown')
                    type_counts[node_type] = type_counts.get(node_type, 0) + 1
                
                for node_type, count in sorted(type_counts.items()):
                    print(f"   {node_type:15s}: {count:2d} 个")
                
                # 检查主线结构
                print(f"\n🐟 主线结构分析：")
                main_nodes = [n for n in nodes if n.get('type') in ['start', 'stage', 'end']]
                main_nodes.sort(key=lambda x: x.get('level', 0))
                
                print(f"   主线节点数: {len(main_nodes)}")
                print(f"   主线序列:")
                for i, node in enumerate(main_nodes):
                    arrow = " → " if i > 0 else "   "
                    print(f"   {arrow}{node.get('name', 'N/A')} (level: {node.get('level', 'N/A')})")
                
                # 生成修复建议
                print(f"\n💡 修复建议：")
                if invalid_edges:
                    print(f"   1. 前端需要过滤无效边，只使用有效边进行渲染")
                    print(f"   2. 后端LLM生成的数据可能存在节点ID不一致问题")
                    print(f"   3. 建议在前端添加数据验证和清理逻辑")
                else:
                    print(f"   ✅ 所有边都有效，问题可能在前端渲染逻辑")
                
            else:
                print(f"❌ 学习路径数据获取失败")
                if learning_path_result:
                    print(f"   错误信息: {learning_path_result.get('error', 'N/A')}")
                
        except Exception as e:
            print(f"❌ 获取学习路径数据异常: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"\n✅ 调试完成")
        
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_learning_path_nodes()
