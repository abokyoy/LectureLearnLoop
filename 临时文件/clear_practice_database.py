#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
清空练习历史数据库脚本
用于测试练习历史功能
"""

import sqlite3
import os

def clear_practice_database():
    """清空练习历史数据库中的所有数据"""
    db_path = "practice_data.db"
    
    if not os.path.exists(db_path):
        print("❌ 数据库文件不存在")
        return
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 清空练习会话表
            cursor.execute("DELETE FROM practice_sessions")
            sessions_count = cursor.rowcount
            
            # 清空练习提交表
            cursor.execute("DELETE FROM practice_submissions")
            submissions_count = cursor.rowcount
            
            # 重置自增ID
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='practice_sessions'")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='practice_submissions'")
            
            conn.commit()
            
            print("✅ 数据库清空完成")
            print(f"📊 删除了 {sessions_count} 条练习会话记录")
            print(f"📊 删除了 {submissions_count} 条练习提交记录")
            
    except Exception as e:
        print(f"❌ 清空数据库失败: {e}")

def clear_json_files():
    """清空JSON文件目录"""
    practice_dir = "practice_sessions"
    
    if not os.path.exists(practice_dir):
        print("❌ JSON文件目录不存在")
        return
    
    try:
        json_files = [f for f in os.listdir(practice_dir) if f.endswith('.json')]
        
        for json_file in json_files:
            file_path = os.path.join(practice_dir, json_file)
            os.remove(file_path)
            print(f"🗑️ 删除文件: {json_file}")
        
        # 删除迁移标记文件
        migration_marker = os.path.join(practice_dir, ".migration_completed")
        if os.path.exists(migration_marker):
            os.remove(migration_marker)
            print("🗑️ 删除迁移标记文件")
        
        print(f"✅ 清空JSON文件完成，删除了 {len(json_files)} 个文件")
        
    except Exception as e:
        print(f"❌ 清空JSON文件失败: {e}")

if __name__ == "__main__":
    print("🧹 开始清空练习历史数据...")
    print("=" * 50)
    
    # 清空数据库
    clear_practice_database()
    print()
    
    # 清空JSON文件
    clear_json_files()
    print()
    
    print("=" * 50)
    print("🎉 练习历史数据清空完成！")
