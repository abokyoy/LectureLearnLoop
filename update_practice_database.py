#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
更新练习历史数据库结构脚本
添加answer_history字段来存储完整的答案历史
"""

import sqlite3
import os

def update_database_structure():
    """更新数据库结构，添加answer_history字段"""
    db_path = "practice_data.db"
    
    if not os.path.exists(db_path):
        print("❌ 数据库文件不存在")
        return
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 检查当前表结构
            cursor.execute("PRAGMA table_info(practice_sessions)")
            columns = [column[1] for column in cursor.fetchall()]
            
            print("📊 当前表字段:", columns)
            
            # 检查是否已有answer_history字段
            if 'answer_history' not in columns:
                # 添加answer_history字段
                cursor.execute('ALTER TABLE practice_sessions ADD COLUMN answer_history TEXT')
                print("✅ 已添加answer_history字段")
            else:
                print("ℹ️ answer_history字段已存在")
            
            conn.commit()
            
            # 验证更新后的表结构
            cursor.execute("PRAGMA table_info(practice_sessions)")
            updated_columns = [column[1] for column in cursor.fetchall()]
            print("📊 更新后表字段:", updated_columns)
            
            print("✅ 数据库结构更新完成")
            
    except Exception as e:
        print(f"❌ 更新数据库结构失败: {e}")

if __name__ == "__main__":
    print("🔧 开始更新练习历史数据库结构...")
    print("=" * 50)
    
    update_database_structure()
    
    print("=" * 50)
    print("🎉 数据库结构更新完成！")
