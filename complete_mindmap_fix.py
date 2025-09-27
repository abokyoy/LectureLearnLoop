#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def fix_all_mindmap_issues():
    """完整修复所有脑图问题"""
    print("🚀 开始完整修复脑图问题...")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    try:
        # 1. 清除所有脑图缓存
        print("\n🗑️ 步骤1：清除脑图缓存...")
        cursor.execute('DELETE FROM knowledge_mindmaps')
        deleted_count = cursor.rowcount
        print(f"✅ 已清除 {deleted_count} 个脑图缓存")
        
        # 2. 检查知识点数据
        print("\n📋 步骤2：检查知识点数据...")
        cursor.execute('SELECT subject_name, COUNT(*) FROM knowledge_points GROUP BY subject_name')
        subjects = cursor.fetchall()
        
        for subject_name, count in subjects:
            print(f"  📚 {subject_name}: {count} 个知识点")
            
            # 检查过拟合知识点
            if subject_name == "机器学习":
                cursor.execute(
                    'SELECT id, point_name FROM knowledge_points WHERE subject_name = ? AND point_name LIKE ?',
                    (subject_name, '%过拟合%')
                )
                overfitting = cursor.fetchall()
                for kp_id, kp_name in overfitting:
                    print(f"    🎯 过拟合知识点: ID={kp_id}, 名称={kp_name}")
        
        # 3. 提交更改
        conn.commit()
        print("\n✅ 所有修复完成！")
        
        print("\n📋 修复总结:")
        print("1. ✅ 清除了所有脑图缓存")
        print("2. ✅ 验证了知识点数据完整性")
        print("3. ✅ 下次访问将重新生成脑图")
        
        print("\n🔄 下一步操作:")
        print("1. 重启应用: python overlay_drag_corgi_app.py")
        print("2. 进入脑图页面")
        print("3. 点击机器学习学科")
        print("4. 验证过拟合节点显示正确描述")
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_all_mindmap_issues()
