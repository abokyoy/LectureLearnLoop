#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def complete_id_mapping_fix():
    """彻底修复ID映射问题"""
    print("🚀 彻底修复脑图ID映射问题")
    print("=" * 60)
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 1. 获取数据库中的真实知识点数据
        print("📋 步骤1：获取数据库真实数据")
        cursor.execute('''
            SELECT id, point_name, core_description, mastery_score 
            FROM knowledge_points 
            WHERE subject_name = "机器学习" 
            ORDER BY id
        ''')
        db_points = cursor.fetchall()
        
        # 建立名称到真实数据的完整映射
        name_to_real_data = {}
        for point in db_points:
            name_to_real_data[point[1]] = {
                'real_id': point[0],
                'name': point[1],
                'description': point[2],
                'mastery_score': point[3] or -1
            }
        
        print(f"✅ 获取到 {len(db_points)} 个真实知识点")
        
        # 2. 检查当前脑图缓存
        print("\n📊 步骤2：检查脑图缓存")
        cursor.execute('SELECT mindmap_data FROM knowledge_mindmaps WHERE subject_name = "机器学习"')
        result = cursor.fetchone()
        
        if not result:
            print("⚠️ 没有脑图缓存，需要先生成脑图")
            return False
        
        mindmap_data = json.loads(result[0])
        nodes = mindmap_data.get('nodes', [])
        edges = mindmap_data.get('edges', [])
        
        # 3. 分析当前的错误映射
        print("\n🔍 步骤3：分析错误映射")
        kp_nodes = [n for n in nodes if n.get('type') == 'knowledge_point']
        
        mapping_errors = []
        for node in kp_nodes:
            node_name = node.get('name', '')
            current_id = node.get('id', '')
            
            if node_name in name_to_real_data:
                real_data = name_to_real_data[node_name]
                correct_id = f"kp_{real_data['real_id']}"
                
                if current_id != correct_id:
                    # 提取当前ID的数字部分
                    current_numeric = current_id.replace('kp_', '') if current_id.startswith('kp_') else current_id
                    
                    # 查询当前错误ID对应的真实数据
                    cursor.execute('SELECT point_name, core_description FROM knowledge_points WHERE id = ?', (current_numeric,))
                    wrong_data = cursor.fetchone()
                    
                    mapping_errors.append({
                        'node_name': node_name,
                        'current_id': current_id,
                        'correct_id': correct_id,
                        'real_id': real_data['real_id'],
                        'wrong_name': wrong_data[0] if wrong_data else 'N/A',
                        'wrong_desc': wrong_data[1] if wrong_data else 'N/A',
                        'correct_desc': real_data['description']
                    })
        
        if mapping_errors:
            print(f"❌ 发现 {len(mapping_errors)} 个错误映射:")
            for error in mapping_errors:
                print(f"\n🔴 节点: {error['node_name']}")
                print(f"   当前ID: {error['current_id']} (错误)")
                print(f"   正确ID: {error['correct_id']}")
                print(f"   当前显示: {error['wrong_name']} - {error['wrong_desc'][:50]}...")
                print(f"   应该显示: {error['node_name']} - {error['correct_desc'][:50]}...")
        else:
            print("✅ 所有映射都正确")
            return True
        
        # 4. 执行修复
        print(f"\n🔧 步骤4：执行修复")
        
        # 记录ID变更映射
        old_to_new_id_map = {}
        
        # 修复节点ID
        for node in nodes:
            if node.get('type') == 'knowledge_point':
                node_name = node.get('name', '')
                if node_name in name_to_real_data:
                    real_data = name_to_real_data[node_name]
                    old_id = node.get('id', '')
                    new_id = f"kp_{real_data['real_id']}"
                    
                    if old_id != new_id:
                        old_to_new_id_map[old_id] = new_id
                        node['id'] = new_id
                        node['mastery_score'] = real_data['mastery_score']
                        print(f"🔧 修复节点: {node_name} | {old_id} → {new_id}")
        
        # 修复边引用
        edges_fixed = 0
        for edge in edges:
            if edge.get('source') in old_to_new_id_map:
                edge['source'] = old_to_new_id_map[edge['source']]
                edges_fixed += 1
            if edge.get('target') in old_to_new_id_map:
                edge['target'] = old_to_new_id_map[edge['target']]
                edges_fixed += 1
        
        # 5. 保存修复结果
        print(f"\n💾 步骤5：保存修复结果")
        updated_json = json.dumps(mindmap_data, ensure_ascii=False)
        cursor.execute('''
            UPDATE knowledge_mindmaps 
            SET mindmap_data = ?, updated_time = datetime('now', 'localtime')
            WHERE subject_name = "机器学习"
        ''', (updated_json,))
        
        conn.commit()
        
        print(f"✅ 修复完成:")
        print(f"   📊 修复节点: {len(old_to_new_id_map)} 个")
        print(f"   🔗 修复边引用: {edges_fixed} 次")
        
        # 6. 验证修复结果
        print(f"\n🔍 步骤6：验证修复结果")
        
        # 重新检查关键节点
        test_cases = [
            ("过拟合 (Overfitting)", 6),
            ("优化算法 (Optimization Algorithm)", 5),
            ("监督学习", 17)
        ]
        
        all_correct = True
        for node_name, expected_id in test_cases:
            node = next((n for n in nodes if n.get('name') == node_name), None)
            if node:
                actual_id = node.get('id', '')
                expected_full_id = f"kp_{expected_id}"
                
                if actual_id == expected_full_id:
                    print(f"   ✅ {node_name}: {actual_id}")
                else:
                    print(f"   ❌ {node_name}: {actual_id} (应该是 {expected_full_id})")
                    all_correct = False
            else:
                print(f"   ⚠️ {node_name}: 节点未找到")
                all_correct = False
        
        if all_correct:
            print(f"\n🎉 所有关键节点ID映射正确！")
            print(f"现在点击节点应该显示正确的描述和错题了。")
        else:
            print(f"\n⚠️ 仍有部分节点映射不正确")
        
        return all_correct
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = complete_id_mapping_fix()
    
    if success:
        print(f"\n🚀 修复成功！请刷新脑图页面测试效果。")
        print(f"预期结果:")
        print(f"- 点击'过拟合'节点 → 显示过拟合的描述和相关错题")
        print(f"- 点击'优化算法'节点 → 显示优化算法的描述和相关错题")
        print(f"- 点击'监督学习'节点 → 显示监督学习的描述和相关错题")
    else:
        print(f"\n❌ 修复失败，请检查错误信息并重试。")
