#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def fix_mindmap_node_ids():
    """修复脑图节点ID映射问题"""
    print("🔧 开始修复脑图节点ID映射问题...")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 获取所有脑图数据
        cursor.execute('SELECT subject_name, mindmap_data FROM knowledge_mindmaps')
        mindmaps = cursor.fetchall()
        
        for subject_name, mindmap_json in mindmaps:
            print(f"\n📊 处理学科: {subject_name}")
            
            # 解析脑图数据
            mindmap_data = json.loads(mindmap_json)
            nodes = mindmap_data.get('nodes', [])
            
            # 获取该学科的知识点数据
            cursor.execute('''
                SELECT id, point_name, mastery_score 
                FROM knowledge_points 
                WHERE subject_name = ?
            ''', (subject_name,))
            knowledge_points = cursor.fetchall()
            
            # 建立名称到ID的映射
            name_to_id = {}
            id_to_mastery = {}
            for kp_id, kp_name, mastery_score in knowledge_points:
                name_to_id[kp_name] = kp_id
                id_to_mastery[kp_id] = mastery_score or -1
            
            print(f"📋 知识点映射: {len(name_to_id)} 个")
            
            # 修复节点ID和熟练度
            nodes_fixed = 0
            for node in nodes:
                if node.get('type') == 'knowledge_point':
                    node_name = node.get('name', '')
                    
                    # 通过名称查找真实ID
                    if node_name in name_to_id:
                        real_id = name_to_id[node_name]
                        old_id = node.get('id', '')
                        
                        # 更新节点ID为真实ID
                        node['id'] = f"kp_{real_id}"
                        node['mastery_score'] = id_to_mastery.get(real_id, -1)
                        
                        nodes_fixed += 1
                        print(f"  🔧 修复: {node_name} | {old_id} -> kp_{real_id} | 熟练度: {node['mastery_score']}")
                    else:
                        print(f"  ⚠️ 未找到匹配: {node_name}")
            
            # 更新边的连接
            edges = mindmap_data.get('edges', [])
            for edge in edges:
                source = edge.get('source', '')
                target = edge.get('target', '')
                
                # 更新边的source和target引用
                for node in nodes:
                    if node.get('name') and source.startswith('kp_') and node.get('type') == 'knowledge_point':
                        if node.get('name') in name_to_id:
                            real_id = name_to_id[node.get('name')]
                            if source == f"kp_{node.get('name').split()[0]}":  # 简单匹配
                                edge['source'] = f"kp_{real_id}"
                            if target == f"kp_{node.get('name').split()[0]}":
                                edge['target'] = f"kp_{real_id}"
            
            # 保存修复后的脑图数据
            if nodes_fixed > 0:
                updated_json = json.dumps(mindmap_data, ensure_ascii=False)
                cursor.execute('''
                    UPDATE knowledge_mindmaps 
                    SET mindmap_data = ?, updated_time = datetime('now', 'localtime')
                    WHERE subject_name = ?
                ''', (updated_json, subject_name))
                
                print(f"✅ 已修复 {nodes_fixed} 个节点，更新数据库")
            else:
                print("ℹ️ 无需修复")
        
        conn.commit()
        print(f"\n🎉 脑图节点ID修复完成！")
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        conn.rollback()
    finally:
        conn.close()

def clear_all_mindmap_cache():
    """清除所有脑图缓存，强制重新生成"""
    print("🗑️ 清除所有脑图缓存...")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT COUNT(*) FROM knowledge_mindmaps')
        count = cursor.fetchone()[0]
        
        cursor.execute('DELETE FROM knowledge_mindmaps')
        conn.commit()
        
        print(f"✅ 已清除 {count} 个脑图缓存")
        
    except Exception as e:
        print(f"❌ 清除失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 脑图问题修复工具")
    print("1. 修复节点ID映射")
    print("2. 清除所有缓存（强制重新生成）")
    
    choice = input("请选择操作 (1/2): ").strip()
    
    if choice == "1":
        fix_mindmap_node_ids()
    elif choice == "2":
        clear_all_mindmap_cache()
    else:
        print("无效选择")
