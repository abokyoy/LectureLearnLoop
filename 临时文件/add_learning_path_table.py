#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
添加学习路径表到数据库
"""

import sqlite3

def add_learning_path_table():
    """添加学习路径表"""
    print("🔧 添加学习路径表到数据库")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 学习路径图表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS learning_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                path_data TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, subject_name)
            )
        ''')
        
        conn.commit()
        print("✅ 学习路径表创建成功")
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_paths'")
        result = cursor.fetchone()
        if result:
            print("✅ 验证：learning_paths表已存在")
        else:
            print("❌ 验证失败：learning_paths表不存在")
            
    except Exception as e:
        print(f"❌ 创建学习路径表失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    add_learning_path_table()
