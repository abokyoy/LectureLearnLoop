#!/usr/bin/env python3
"""快速清空练习历史数据"""

import sqlite3
import os
import shutil

def clear_databases():
    """清空练习相关数据库"""
    databases = ['practice_data.db', 'practice_history.db']
    
    for db_name in databases:
        if os.path.exists(db_name):
            print(f'📊 处理数据库: {db_name}')
            try:
                with sqlite3.connect(db_name) as conn:
                    cursor = conn.cursor()
                    
                    # 获取所有表名
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                    total_deleted = 0
                    for table in tables:
                        try:
                            cursor.execute(f'SELECT COUNT(*) FROM {table}')
                            count_before = cursor.fetchone()[0]
                            
                            cursor.execute(f'DELETE FROM {table}')
                            deleted = cursor.rowcount
                            total_deleted += deleted
                            
                            print(f'  ✅ 表 {table}: 删除 {deleted} 条记录 (原有 {count_before} 条)')
                        except Exception as e:
                            print(f'  ❌ 清空表 {table} 失败: {e}')
                    
                    conn.commit()
                    print(f'  ✅ {db_name} 清空完成，共删除 {total_deleted} 条记录')
            except Exception as e:
                print(f'❌ 处理 {db_name} 失败: {e}')
        else:
            print(f'ℹ️ 数据库 {db_name} 不存在')

def clear_json_files():
    """清空JSON文件"""
    practice_dir = 'practice_sessions'
    if os.path.exists(practice_dir):
        files = [f for f in os.listdir(practice_dir) if f.endswith('.json')]
        if files:
            for f in files:
                os.remove(os.path.join(practice_dir, f))
            print(f'✅ 删除 {len(files)} 个JSON文件')
        else:
            print('ℹ️ practice_sessions 目录为空')
    else:
        print('ℹ️ practice_sessions 目录不存在')

if __name__ == "__main__":
    print('🧹 开始清空练习历史数据...')
    clear_databases()
    clear_json_files()
    print('🎉 练习历史数据清空完成！现在可以进行全新的测试了！')
