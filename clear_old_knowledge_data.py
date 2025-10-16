#!/usr/bin/env python3
"""
清空老的知识点数据脚本
解决UUID升级后的存量数据问题
"""

import sqlite3
from pathlib import Path

def clear_old_knowledge_data():
    """清空老的知识点数据"""
    print("🧹 开始清空老的知识点数据...")
    
    db_path = "knowledge_management.db"
    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    # 备份提醒
    print("⚠️  重要提醒：此操作将删除所有知识点数据，建议先备份数据库文件")
    print(f"📁 数据库位置: {Path(db_path).absolute()}")
    
    confirm = input("是否继续清空知识点数据？(输入 'YES' 确认): ")
    if confirm != 'YES':
        print("❌ 操作已取消")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 统计清空前的数据
        cursor.execute("SELECT COUNT(*) FROM knowledge_points")
        kp_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources")
        sources_count = cursor.fetchone()[0]
        
        print(f"📊 清空前统计:")
        print(f"   知识点数量: {kp_count}")
        print(f"   关联记录数量: {sources_count}")
        
        # 清空关联表
        print("🗑️  清空知识点来源关联表...")
        cursor.execute("DELETE FROM knowledge_point_sources")
        deleted_sources = cursor.rowcount
        
        # 清空知识点表
        print("🗑️  清空知识点表...")
        cursor.execute("DELETE FROM knowledge_points")
        deleted_kps = cursor.rowcount
        
        # 重置自增ID
        print("🔄 重置自增ID...")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='knowledge_points'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='knowledge_point_sources'")
        
        conn.commit()
        
        print(f"✅ 清空完成:")
        print(f"   删除知识点: {deleted_kps} 个")
        print(f"   删除关联记录: {deleted_sources} 个")
        print(f"   自增ID已重置")
        
        # 验证清空结果
        cursor.execute("SELECT COUNT(*) FROM knowledge_points")
        remaining_kps = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources")
        remaining_sources = cursor.fetchone()[0]
        
        print(f"📊 清空后验证:")
        print(f"   剩余知识点: {remaining_kps}")
        print(f"   剩余关联记录: {remaining_sources}")
        
        conn.close()
        
        if remaining_kps == 0 and remaining_sources == 0:
            print("🎉 知识点数据清空成功！现在可以重新提取知识点，将使用新的UUID系统。")
            return True
        else:
            print("⚠️  清空可能不完整，请检查")
            return False
            
    except Exception as e:
        print(f"❌ 清空过程中出现错误: {e}")
        return False

def backup_database():
    """备份数据库文件"""
    import shutil
    from datetime import datetime
    
    db_path = "knowledge_management.db"
    if not Path(db_path).exists():
        print("❌ 数据库文件不存在，无需备份")
        return False
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"knowledge_management_backup_{timestamp}.db"
    
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✅ 数据库已备份到: {backup_path}")
        return True
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return False

def main():
    """主函数"""
    print("🚀 知识点数据清理工具")
    print("="*50)
    
    # 询问是否需要备份
    backup_choice = input("是否先备份数据库？(y/n): ").lower()
    if backup_choice == 'y':
        if not backup_database():
            print("❌ 备份失败，建议手动备份后再继续")
            return
    
    # 清空数据
    if clear_old_knowledge_data():
        print("\n🎯 下一步操作建议:")
        print("1. 重启应用程序")
        print("2. 打开需要的笔记文件")
        print("3. 重新提取知识点")
        print("4. 新的知识点将使用UUID系统，显示正常")
    else:
        print("\n❌ 清空失败，请检查错误信息")

if __name__ == "__main__":
    main()
