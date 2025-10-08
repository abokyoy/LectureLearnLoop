#!/usr/bin/env python3
import sqlite3
import json
import os

print("=== 验证修复效果 ===")

# 查找数据库文件
db_file = 'knowledge_management.db'
if not os.path.exists(db_file):
    print(f"❌ 数据库文件 {db_file} 不存在")
    exit(1)

try:
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # 验证关键的知识点ID映射
    test_cases = [
        ("过拟合 (Overfitting)", 6),
        ("优化算法 (Optimization Algorithm)", 5),
        ("模型容量/弹性 (Model Capacity)", 7)
    ]
    
    print("\n1. 验证数据库中的知识点:")
    for name, expected_id in test_cases:
        cursor.execute(
            "SELECT id, point_name, core_description FROM knowledge_points WHERE id = ?",
            (expected_id,)
        )
        result = cursor.fetchone()
        if result:
            db_id, db_name, description = result
            print(f"✅ ID {db_id}: {db_name}")
            print(f"   描述: {description[:50]}...")
        else:
            print(f"❌ 未找到ID {expected_id}")
    
    # 验证脑图中的映射
    print("\n2. 验证脑图中的节点映射:")
    cursor.execute(
        """SELECT mindmap_data FROM knowledge_mindmaps 
           WHERE subject_name = '机器学习' 
           ORDER BY created_time DESC LIMIT 1"""
    )
    mindmap_result = cursor.fetchone()
    
    if mindmap_result:
        mindmap_data = json.loads(mindmap_result[0])
        nodes = mindmap_data.get('nodes', [])
        
        for name, expected_id in test_cases:
            found = False
            for node in nodes:
                if node.get('name') == name and node.get('type') == 'knowledge_point':
                    node_id = node.get('id', '')
                    expected_node_id = f"kp_{expected_id}"
                    if node_id == expected_node_id:
                        print(f"✅ 脑图: '{name}' -> {node_id} (正确)")
                    else:
                        print(f"❌ 脑图: '{name}' -> {node_id} (应为 {expected_node_id})")
                    found = True
                    break
            
            if not found:
                print(f"❌ 脑图中未找到: '{name}'")
    
    # 测试API调用
    print("\n3. 模拟API调用测试:")
    for name, expected_id in test_cases:
        print(f"\n测试知识点ID {expected_id} ({name}):")
        
        # 基本信息查询
        cursor.execute(
            """SELECT id, point_name, core_description, mastery_score, subject_name, created_time
               FROM knowledge_points WHERE id = ?""",
            (expected_id,)
        )
        result = cursor.fetchone()
        
        if result:
            print(f"  ✅ 基本信息: {result[1]}")
            print(f"     描述: {result[2][:50]}...")
            
            # 练习记录查询
            cursor.execute(
                "SELECT COUNT(*) FROM practice_records WHERE knowledge_point_id = ?",
                (expected_id,)
            )
            practice_count = cursor.fetchone()[0]
            print(f"  ✅ 练习记录: {practice_count} 条")
            
            # 收藏题目查询
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM favorite_questions WHERE knowledge_point_id = ?",
                    (expected_id,)
                )
                favorite_count = cursor.fetchone()[0]
                print(f"  ✅ 收藏题目: {favorite_count} 条")
            except Exception as e:
                print(f"  ⚠️ 收藏题目查询失败: {e}")
            
            # 笔记查询
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM notes WHERE title LIKE ?",
                    (f'%{result[1]}%',)
                )
                notes_count = cursor.fetchone()[0]
                print(f"  ✅ 关联笔记: {notes_count} 条")
            except Exception as e:
                print(f"  ⚠️ 笔记查询失败: {e}")
        else:
            print(f"  ❌ 未找到知识点ID {expected_id}")
    
    conn.close()
    print("\n✅ 验证完成")
    
except Exception as e:
    print(f"❌ 验证失败: {e}")
    import traceback
    traceback.print_exc()
