#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def check_mindmap_nodes():
    """检查脑图节点的ID映射"""
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    # 获取脑图数据
    cursor.execute('SELECT mindmap_data FROM knowledge_mindmaps WHERE subject_name = ? LIMIT 1', ('机器学习',))
    result = cursor.fetchone()
    
    if result:
        data = json.loads(result[0])
        nodes = data.get('nodes', [])
        kp_nodes = [n for n in nodes if n.get('type') == 'knowledge_point']
        
        print("脑图中的知识点节点:")
        for i, node in enumerate(kp_nodes[:10]):  # 只显示前10个
            print(f"{i+1}. ID: {node.get('id')}, Name: {node.get('name')}")
        
        # 查找过拟合节点
        overfitting_nodes = [n for n in kp_nodes if '过拟合' in n.get('name', '')]
        print(f"\n过拟合相关节点:")
        for node in overfitting_nodes:
            print(f"ID: {node.get('id')}, Name: {node.get('name')}")
    
    # 检查数据库中的知识点
    cursor.execute('SELECT id, point_name FROM knowledge_points WHERE point_name LIKE ?', ('%过拟合%',))
    db_results = cursor.fetchall()
    print(f"\n数据库中的过拟合知识点:")
    for row in db_results:
        print(f"ID: {row[0]}, Name: {row[1]}")
    
    conn.close()

if __name__ == "__main__":
    check_mindmap_nodes()
