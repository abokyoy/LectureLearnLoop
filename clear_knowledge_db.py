#!/usr/bin/env python3
"""
清空知识点数据库的脚本
"""

import sys
import os
import sqlite3

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knowledge_management import DatabaseManager

def clear_knowledge_database():
    """清空知识点数据库中的所有数据"""
    print("开始清空知识点数据库...")
    
    try:
        # 创建数据库管理器
        db_manager = DatabaseManager()
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # 获取当前数据统计
        cursor.execute("SELECT COUNT(*) FROM knowledge_points")
        knowledge_count = cursor.fetchone()[0]
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_records'")
        has_practice = cursor.fetchone() is not None
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='error_questions'")
        has_error = cursor.fetchone() is not None
        
        practice_count = 0
        error_count = 0
        
        if has_practice:
            cursor.execute("SELECT COUNT(*) FROM practice_records")
            practice_count = cursor.fetchone()[0]
            
        if has_error:
            cursor.execute("SELECT COUNT(*) FROM error_questions")
            error_count = cursor.fetchone()[0]
        
        print(f"当前数据库统计:")
        print(f"  - 知识点: {knowledge_count} 个")
        print(f"  - 练习记录: {practice_count} 个")
        print(f"  - 错题记录: {error_count} 个")
        
        if knowledge_count == 0:
            print("知识点数据库已经是空的，无需清空。")
            return
        
        # 清空所有表
        print("\n开始清空数据...")
        
        # 清空错题记录
        if has_error:
            cursor.execute("DELETE FROM error_questions")
            print("✅ 已清空错题记录")
        
        # 清空练习记录
        if has_practice:
            cursor.execute("DELETE FROM practice_records")
            print("✅ 已清空练习记录")
        
        # 清空知识点
        cursor.execute("DELETE FROM knowledge_points")
        print("✅ 已清空知识点")
        
        # 重置自增ID
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('knowledge_points', 'practice_records', 'error_questions')")
        print("✅ 已重置自增ID")
        
        # 提交更改
        conn.commit()
        conn.close()
        
        print("\n🎉 数据库清空完成！")
        print("现在可以重新开始提取核心概念了。")
        
    except Exception as e:
        print(f"❌ 清空数据库失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    clear_knowledge_database()
