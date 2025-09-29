#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def direct_fix_mindmap_ids():
    """直接修复脑图中的ID映射问题"""
    print("🔧 直接修复脑图ID映射问题")
    print("=" * 50)
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 1. 获取数据库中的知识点数据
        cursor.execute('''
            SELECT id, point_name, core_description, mastery_score 
            FROM knowledge_points 
            WHERE subject_name = "机器学习" 
            ORDER BY id
        ''')
        db_points = cursor.fetchall()
        
        # 建立名称到真实ID的映射
        name_to_db_data = {}
        for point in db_points:
            name_to_db_data[point[1]] = {
                'id': point[0],
                'description': point[2],
                'mastery_score': point[3] or -1
            }
        
        print(f"📋 数据库知识点: {len(db_points)} 个")
        
        # 2. 获取脑图缓存数据
        cursor.execute('SELECT mindmap_data FROM knowledge_mindmaps WHERE subject_name = "机器学习"')
        result = cursor.fetchone()
        
        if not result:
            print("⚠️ 没有找到脑图缓存，请先生成脑图")
            return
        
        mindmap_data = json.loads(result[0])
        nodes = mindmap_data.get('nodes', [])
        edges = mindmap_data.get('edges', [])
        
        print(f"📊 脑图节点: {len(nodes)} 个")
        print(f"🔗 脑图边: {len(edges)} 条")
        
        # 3. 修复节点ID映射
        old_to_new_id_map = {}
        fixed_nodes = 0
        
        for node in nodes:
            if node.get('type') == 'knowledge_point':
                node_name = node.get('name', '')
                old_id = node.get('id', '')
                
                if node_name in name_to_db_data:
                    db_data = name_to_db_data[node_name]
                    correct_id = db_data['id']
                    new_id = f"kp_{correct_id}"
                    
                    if old_id != new_id:
                        print(f"🔧 修复: {node_name}")
                        print(f"   {old_id} → {new_id}")
                        
                        old_to_new_id_map[old_id] = new_id
                        node['id'] = new_id
                        node['mastery_score'] = db_data['mastery_score']
                        fixed_nodes += 1
                    else:
                        print(f"✅ 正确: {node_name} ({new_id})")
                else:
                    print(f"⚠️ 未找到: {node_name}")
        
        # 4. 修复边的引用
        fixed_edges = 0
        for edge in edges:
            source_updated = False
            target_updated = False
            
            if edge.get('source') in old_to_new_id_map:
                old_source = edge['source']
                edge['source'] = old_to_new_id_map[old_source]
                source_updated = True
                
            if edge.get('target') in old_to_new_id_map:
                old_target = edge['target']
                edge['target'] = old_to_new_id_map[old_target]
                target_updated = True
                
            if source_updated or target_updated:
                fixed_edges += 1
        
        # 5. 保存修复后的数据
        if fixed_nodes > 0 or fixed_edges > 0:
            updated_json = json.dumps(mindmap_data, ensure_ascii=False)
            cursor.execute('''
                UPDATE knowledge_mindmaps 
                SET mindmap_data = ?, updated_time = datetime('now', 'localtime')
                WHERE subject_name = "机器学习"
            ''', (updated_json,))
            
            conn.commit()
            
            print(f"\n✅ 修复完成:")
            print(f"   📊 修复节点: {fixed_nodes} 个")
            print(f"   🔗 修复边: {fixed_edges} 条")
            print(f"   💾 已保存到数据库")
        else:
            print("\n✅ 所有ID映射都正确，无需修复")
        
        # 6. 验证修复结果
        print(f"\n🔍 验证修复结果:")
        
        # 检查几个关键节点
        key_nodes = ["过拟合 (Overfitting)", "优化算法 (Optimization Algorithm)", "监督学习"]
        for node_name in key_nodes:
            node = next((n for n in nodes if n.get('name') == node_name), None)
            if node and node_name in name_to_db_data:
                node_id = node.get('id', '')
                expected_id = f"kp_{name_to_db_data[node_name]['id']}"
                
                if node_id == expected_id:
                    print(f"   ✅ {node_name}: {node_id}")
                else:
                    print(f"   ❌ {node_name}: {node_id} (应该是 {expected_id})")
            else:
                print(f"   ⚠️ {node_name}: 未找到")
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    direct_fix_mindmap_ids()
