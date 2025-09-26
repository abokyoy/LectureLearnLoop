#!/usr/bin/env python3
"""
更新数据库中所有知识点的熟练度为-1（未评估状态）
"""
import sqlite3
import os

def update_mastery_scores():
    """将所有知识点的熟练度更新为-1"""
    db_file = 'knowledge_management.db'
    
    if not os.path.exists(db_file):
        print(f"❌ 数据库文件 {db_file} 不存在")
        return False
    
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # 检查当前熟练度分布
        print("📊 当前熟练度分布：")
        cursor.execute("SELECT mastery_score, COUNT(*) FROM knowledge_points GROUP BY mastery_score ORDER BY mastery_score")
        current_distribution = cursor.fetchall()
        for score, count in current_distribution:
            print(f"   熟练度 {score}: {count} 个知识点")
        
        # 获取总知识点数
        cursor.execute("SELECT COUNT(*) FROM knowledge_points")
        total_count = cursor.fetchone()[0]
        print(f"\n📈 总知识点数: {total_count}")
        
        # 更新所有知识点的熟练度为-1
        print("\n🔄 正在更新所有知识点熟练度为-1...")
        cursor.execute("UPDATE knowledge_points SET mastery_score = -1")
        updated_count = cursor.rowcount
        
        # 提交更改
        conn.commit()
        
        # 验证更新结果
        cursor.execute("SELECT COUNT(*) FROM knowledge_points WHERE mastery_score = -1")
        final_count = cursor.fetchone()[0]
        
        print(f"✅ 更新完成！")
        print(f"   - 更新了 {updated_count} 个知识点")
        print(f"   - 验证：{final_count} 个知识点熟练度为-1")
        
        # 显示更新后的分布
        print("\n📊 更新后熟练度分布：")
        cursor.execute("SELECT mastery_score, COUNT(*) FROM knowledge_points GROUP BY mastery_score ORDER BY mastery_score")
        new_distribution = cursor.fetchall()
        for score, count in new_distribution:
            print(f"   熟练度 {score}: {count} 个知识点")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 更新失败: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🎯 更新知识点熟练度脚本")
    print("=" * 60)
    
    success = update_mastery_scores()
    
    if success:
        print("\n🎉 所有知识点熟练度已更新为-1（未评估状态）")
    else:
        print("\n💥 更新失败，请检查错误信息")
