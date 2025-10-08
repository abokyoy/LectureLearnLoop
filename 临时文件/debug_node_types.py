#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试学习路径节点类型
"""

import sqlite3
import json

def debug_learning_path_nodes():
    """调试学习路径节点类型"""
    print("🔍 调试学习路径节点类型")
    print("=" * 50)
    
    # 连接数据库
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 查询最新的学习路径数据
        cursor.execute("""
            SELECT subject_name, path_data 
            FROM learning_paths 
            WHERE subject_name = '机器学习'
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        if not result:
            print("❌ 未找到机器学习的学习路径数据")
            return
        
        subject_name, path_data_str = result
        path_data = json.loads(path_data_str)
        
        print(f"📚 学科: {subject_name}")
        print(f"📊 节点总数: {len(path_data.get('nodes', []))}")
        print()
        
        # 检查问题节点
        problem_nodes = [
            "账户登录与切换", "模型配置", "云环境管理", 
            "系统状态查看", "成本监控"
        ]
        
        print("🎯 检查问题节点:")
        print("-" * 30)
        
        for node in path_data.get('nodes', []):
            node_name = node.get('name', '')
            node_type = node.get('type', '')
            node_id = node.get('id', '')
            mastery_score = node.get('mastery_score', 'N/A')
            original_kp_id = node.get('original_kp_id', 'N/A')
            is_llm_supplement = node.get('is_llm_supplement', False)
            
            # 检查是否是问题节点
            if any(problem_name in node_name for problem_name in problem_nodes):
                print(f"🔍 节点: {node_name}")
                print(f"  - ID: {node_id}")
                print(f"  - 类型: {node_type}")
                print(f"  - 熟练度: {mastery_score}")
                print(f"  - 原始知识点ID: {original_kp_id}")
                print(f"  - LLM补充标记: {is_llm_supplement}")
                print()
        
        print("📋 所有知识点节点类型统计:")
        print("-" * 30)
        
        type_counts = {}
        for node in path_data.get('nodes', []):
            node_type = node.get('type', 'unknown')
            if node_type in ['existing_kp', 'supplement_kp', 'knowledge_point']:
                type_counts[node_type] = type_counts.get(node_type, 0) + 1
                
                # 打印所有知识点节点的详细信息
                node_name = node.get('name', '')
                node_id = node.get('id', '')
                mastery_score = node.get('mastery_score', 'N/A')
                is_llm_supplement = node.get('is_llm_supplement', False)
                
                print(f"  {node_type}: {node_name} (ID: {node_id}, 熟练度: {mastery_score}, LLM补充: {is_llm_supplement})")
        
        print()
        print("📊 类型统计:")
        for node_type, count in type_counts.items():
            print(f"  {node_type}: {count} 个")
            
    except Exception as e:
        print(f"❌ 调试失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    debug_learning_path_nodes()
