#!/usr/bin/env python3
"""
知识点数据UUID迁移脚本
将老的note_id关联迁移到UUID系统
"""

import sqlite3
from pathlib import Path

def migrate_knowledge_to_uuid():
    """迁移知识点关联到UUID系统"""
    print("🔄 开始知识点UUID迁移...")
    
    db_path = "knowledge_management.db"
    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 统计迁移前的数据
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources WHERE note_uuid IS NULL OR note_uuid = ''")
        need_migration = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources WHERE note_uuid IS NOT NULL AND note_uuid != ''")
        already_migrated = cursor.fetchone()[0]
        
        print(f"📊 迁移前统计:")
        print(f"   需要迁移的记录: {need_migration}")
        print(f"   已迁移的记录: {already_migrated}")
        
        if need_migration == 0:
            print("✅ 所有记录已使用UUID系统，无需迁移")
            return True
        
        # 查找需要迁移的记录
        cursor.execute("""
            SELECT kps.id, kps.knowledge_point_id, kps.note_id, n.note_uuid, kp.point_name
            FROM knowledge_point_sources kps
            LEFT JOIN notes n ON kps.note_id = n.id
            LEFT JOIN knowledge_points kp ON kps.knowledge_point_id = kp.id
            WHERE (kps.note_uuid IS NULL OR kps.note_uuid = '') AND kps.note_id IS NOT NULL
        """)
        
        migration_records = cursor.fetchall()
        
        print(f"🔍 找到 {len(migration_records)} 条需要迁移的记录:")
        
        migrated_count = 0
        failed_count = 0
        
        for record in migration_records:
            kps_id, kp_id, note_id, note_uuid, kp_name = record
            
            if note_uuid:
                # 有对应的UUID，可以迁移
                try:
                    cursor.execute(
                        "UPDATE knowledge_point_sources SET note_uuid = ? WHERE id = ?",
                        (note_uuid, kps_id)
                    )
                    migrated_count += 1
                    print(f"   ✅ 迁移: {kp_name} -> UUID:{note_uuid[:8]}...")
                except Exception as e:
                    print(f"   ❌ 迁移失败: {kp_name} - {e}")
                    failed_count += 1
            else:
                # 没有对应的UUID，记录无法迁移
                print(f"   ⚠️  无法迁移: {kp_name} (note_id:{note_id} 无对应UUID)")
                failed_count += 1
        
        conn.commit()
        
        print(f"\n📊 迁移结果:")
        print(f"   成功迁移: {migrated_count} 条")
        print(f"   迁移失败: {failed_count} 条")
        
        # 验证迁移结果
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources WHERE note_uuid IS NOT NULL AND note_uuid != ''")
        final_uuid_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources WHERE note_uuid IS NULL OR note_uuid = ''")
        final_no_uuid_count = cursor.fetchone()[0]
        
        print(f"\n📊 迁移后统计:")
        print(f"   使用UUID的记录: {final_uuid_count}")
        print(f"   未使用UUID的记录: {final_no_uuid_count}")
        
        conn.close()
        
        if final_no_uuid_count > 0:
            print(f"\n⚠️  仍有 {final_no_uuid_count} 条记录未使用UUID")
            print("建议:")
            print("1. 删除这些无法关联的记录，或")
            print("2. 使用清空脚本重新开始")
            
            delete_choice = input("是否删除无法迁移的记录？(y/n): ").lower()
            if delete_choice == 'y':
                return delete_unmigrated_records()
        
        return migrated_count > 0
        
    except Exception as e:
        print(f"❌ 迁移过程中出现错误: {e}")
        return False

def delete_unmigrated_records():
    """删除无法迁移的记录"""
    print("🗑️  删除无法迁移的记录...")
    
    try:
        conn = sqlite3.connect("knowledge_management.db")
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM knowledge_point_sources WHERE note_uuid IS NULL OR note_uuid = ''")
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        print(f"✅ 删除了 {deleted_count} 条无法迁移的记录")
        return True
        
    except Exception as e:
        print(f"❌ 删除失败: {e}")
        return False

def main():
    """主函数"""
    print("🚀 知识点UUID迁移工具")
    print("="*50)
    
    if migrate_knowledge_to_uuid():
        print("\n🎉 迁移完成！")
        print("🎯 下一步操作:")
        print("1. 重启应用程序")
        print("2. 打开之前的笔记文件")
        print("3. 知识点应该能正常显示了")
    else:
        print("\n❌ 迁移失败")
        print("建议使用清空脚本重新开始")

if __name__ == "__main__":
    main()
