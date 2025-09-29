#!/usr/bin/env python3
"""
清空练习历史数据脚本
清空数据库中的练习历史记录和JSON文件
"""

import os
import sqlite3
import shutil
import json
from datetime import datetime

def clear_database():
    """清空数据库中的练习历史数据"""
    try:
        # 连接数据库
        db_path = "practice_database.db"
        if not os.path.exists(db_path):
            print("❌ 数据库文件不存在")
            return False
            
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 清空所有相关表
            tables_to_clear = [
                "practice_sessions",
                "practice_submissions", 
                "practice_evaluations",
                "practice_statistics"
            ]
            
            total_deleted = 0
            for table in tables_to_clear:
                try:
                    # 检查表是否存在
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if cursor.fetchone():
                        # 清空表
                        cursor.execute(f"DELETE FROM {table}")
                        deleted_count = cursor.rowcount
                        total_deleted += deleted_count
                        print(f"✅ 清空表 {table}: {deleted_count} 条记录")
                    else:
                        print(f"ℹ️ 表 {table} 不存在，跳过")
                except Exception as e:
                    print(f"❌ 清空表 {table} 失败: {e}")
            
            conn.commit()
            print(f"✅ 数据库清空完成，共删除 {total_deleted} 条记录")
            return True
            
    except Exception as e:
        print(f"❌ 数据库清空失败: {e}")
        return False

def clear_json_files():
    """清空JSON文件目录"""
    try:
        practice_dir = "practice_sessions"
        
        if not os.path.exists(practice_dir):
            print("ℹ️ practice_sessions 目录不存在，无需清空")
            return True
            
        # 统计文件数量
        files = [f for f in os.listdir(practice_dir) if f.endswith('.json')]
        file_count = len(files)
        
        if file_count == 0:
            print("ℹ️ practice_sessions 目录为空，无需清空")
            return True
            
        # 删除整个目录并重新创建
        shutil.rmtree(practice_dir)
        os.makedirs(practice_dir, exist_ok=True)
        
        print(f"✅ JSON文件清空完成，删除 {file_count} 个文件")
        return True
        
    except Exception as e:
        print(f"❌ JSON文件清空失败: {e}")
        return False

def backup_before_clear():
    """清空前创建备份"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"backup_practice_history_{timestamp}"
        
        # 备份数据库
        db_path = "practice_database.db"
        if os.path.exists(db_path):
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(db_path, os.path.join(backup_dir, "practice_database.db"))
            print(f"✅ 数据库备份到: {backup_dir}/practice_database.db")
        
        # 备份JSON文件
        practice_dir = "practice_sessions"
        if os.path.exists(practice_dir):
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            shutil.copytree(practice_dir, os.path.join(backup_dir, "practice_sessions"))
            print(f"✅ JSON文件备份到: {backup_dir}/practice_sessions")
            
        return backup_dir if os.path.exists(backup_dir) else None
        
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return None

def main():
    """主函数"""
    print("🧹 开始清空练习历史数据...")
    print("=" * 50)
    
    # 询问是否需要备份
    backup_choice = input("是否在清空前创建备份？(y/N): ").strip().lower()
    
    if backup_choice in ['y', 'yes']:
        print("\n📦 创建备份...")
        backup_dir = backup_before_clear()
        if backup_dir:
            print(f"✅ 备份完成: {backup_dir}")
        else:
            print("❌ 备份失败")
            return
    
    # 最终确认
    print("\n⚠️ 警告：此操作将永久删除所有练习历史数据！")
    confirm = input("确认清空练习历史数据？(yes/N): ").strip()
    
    if confirm != "yes":
        print("❌ 操作已取消")
        return
    
    print("\n🧹 开始清空数据...")
    
    # 清空数据库
    print("\n1️⃣ 清空数据库...")
    db_success = clear_database()
    
    # 清空JSON文件
    print("\n2️⃣ 清空JSON文件...")
    json_success = clear_json_files()
    
    # 总结
    print("\n" + "=" * 50)
    if db_success and json_success:
        print("🎉 练习历史数据清空完成！")
        print("✅ 数据库已清空")
        print("✅ JSON文件已清空")
        print("\n现在可以进行全新的练习测试了！")
    else:
        print("❌ 清空过程中出现错误，请检查上述日志")

if __name__ == "__main__":
    main()
