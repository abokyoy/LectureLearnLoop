#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json
import os

def verify_id_mapping():
    """验证ID映射问题"""
    print("🔍 验证脑图节点ID映射问题")
    print("=" * 60)
    
    if not os.path.exists('knowledge_management.db'):
        print("❌ 数据库文件不存在")
        return
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 1. 查看数据库中的知识点数据
        print("📋 步骤1：查看数据库中的知识点数据")
        cursor.execute('''
            SELECT id, point_name, core_description 
            FROM knowledge_points 
            WHERE subject_name = "机器学习" 
            ORDER BY id
        ''')
        db_points = cursor.fetchall()
        
        print(f"数据库中机器学习知识点 ({len(db_points)}个):")
        for point in db_points:
            desc_preview = point[2][:30] + "..." if len(point[2]) > 30 else point[2]
            print(f"  ID:{point[0]:2d} | {point[1]:<35} | {desc_preview}")
        
        # 2. 查看脑图缓存中的节点数据
        print(f"\n📊 步骤2：查看脑图缓存中的节点数据")
        cursor.execute('SELECT mindmap_data FROM knowledge_mindmaps WHERE subject_name = "机器学习"')
        result = cursor.fetchone()
        
        if not result:
            print("⚠️ 没有找到机器学习的脑图缓存")
            return
        
        mindmap_data = json.loads(result[0])
        nodes = mindmap_data.get('nodes', [])
        kp_nodes = [n for n in nodes if n.get('type') == 'knowledge_point']
        
        print(f"脑图中知识点节点 ({len(kp_nodes)}个):")
        for node in kp_nodes:
            mastery = node.get('mastery_score', 'N/A')
            print(f"  ID:{node.get('id'):<8} | {node.get('name'):<35} | 熟练度:{mastery}")
        
        # 3. 分析ID映射问题
        print(f"\n🔍 步骤3：分析ID映射问题")
        
        # 建立名称到数据库ID的映射
        name_to_db_id = {}
        db_id_to_desc = {}
        for point in db_points:
            name_to_db_id[point[1]] = point[0]
            db_id_to_desc[point[0]] = point[2]
        
        print("ID映射分析:")
        mapping_errors = []
        
        for node in kp_nodes:
            node_id = node.get('id', '')
            node_name = node.get('name', '')
            
            # 提取脑图节点的数字ID
            if node_id.startswith('kp_'):
                mindmap_numeric_id = node_id[3:]  # 去掉kp_前缀
                try:
                    mindmap_numeric_id = int(mindmap_numeric_id)
                except ValueError:
                    mindmap_numeric_id = None
            else:
                mindmap_numeric_id = None
            
            # 查找对应的数据库ID
            correct_db_id = name_to_db_id.get(node_name)
            
            if correct_db_id and mindmap_numeric_id:
                if correct_db_id == mindmap_numeric_id:
                    print(f"  ✅ {node_name:<35} | 脑图ID:{mindmap_numeric_id} = 数据库ID:{correct_db_id}")
                else:
                    print(f"  ❌ {node_name:<35} | 脑图ID:{mindmap_numeric_id} ≠ 数据库ID:{correct_db_id}")
                    mapping_errors.append({
                        'name': node_name,
                        'mindmap_id': mindmap_numeric_id,
                        'correct_id': correct_db_id,
                        'wrong_desc': db_id_to_desc.get(mindmap_numeric_id, 'N/A'),
                        'correct_desc': db_id_to_desc.get(correct_db_id, 'N/A')
                    })
            else:
                print(f"  ⚠️ {node_name:<35} | 无法确定映射关系")
        
        # 4. 显示具体的错误映射
        if mapping_errors:
            print(f"\n❌ 发现 {len(mapping_errors)} 个ID映射错误:")
            for error in mapping_errors:
                print(f"\n🔴 节点: {error['name']}")
                print(f"   脑图ID: {error['mindmap_id']} (错误)")
                print(f"   正确ID: {error['correct_id']}")
                print(f"   当前显示描述: {error['wrong_desc'][:50]}...")
                print(f"   应该显示描述: {error['correct_desc'][:50]}...")
        else:
            print("\n✅ 所有ID映射都正确")
        
        # 5. 检查前端获取详情的逻辑
        print(f"\n🔍 步骤4：模拟前端获取详情的过程")
        
        # 模拟前端点击过拟合节点
        overfitting_node = None
        for node in kp_nodes:
            if '过拟合' in node.get('name', ''):
                overfitting_node = node
                break
        
        if overfitting_node:
            node_id = overfitting_node.get('id', '')
            print(f"点击过拟合节点:")
            print(f"  前端节点ID: {node_id}")
            
            # 提取数字ID（模拟前端逻辑）
            if node_id.startswith('kp_'):
                real_id = node_id[3:]  # 去掉kp_前缀
                print(f"  提取的数字ID: {real_id}")
                
                # 查询数据库（模拟后端逻辑）
                cursor.execute(
                    'SELECT point_name, core_description FROM knowledge_points WHERE id = ?',
                    (real_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    print(f"  数据库查询结果:")
                    print(f"    名称: {result[0]}")
                    print(f"    描述: {result[1][:50]}...")
                    
                    if result[0] != overfitting_node.get('name'):
                        print(f"  ❌ 名称不匹配！应该是 '{overfitting_node.get('name')}'")
                    else:
                        print(f"  ✅ 名称匹配")
                else:
                    print(f"  ❌ 数据库中找不到ID={real_id}的记录")
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    verify_id_mapping()
