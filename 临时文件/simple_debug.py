#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import json

def check_knowledge_points():
    """检查知识点数据"""
    print("📋 检查知识点数据...")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    # 检查机器学习学科的知识点
    cursor.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE subject_name = ?",
        ("机器学习",)
    )
    count = cursor.fetchone()[0]
    print(f"机器学习知识点数量: {count}")
    
    if count > 0:
        cursor.execute(
            "SELECT id, point_name, mastery_score FROM knowledge_points WHERE subject_name = ? LIMIT 5",
            ("机器学习",)
        )
        points = cursor.fetchall()
        print("前5个知识点:")
        for point in points:
            print(f"  ID:{point[0]} | {point[1]} | 熟练度:{point[2]}")
    
    conn.close()

def check_mindmap_cache():
    """检查脑图缓存"""
    print("\n💾 检查脑图缓存...")
    
    conn = sqlite3.connect('knowledge_management.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT subject_name, updated_time FROM knowledge_mindmaps")
    caches = cursor.fetchall()
    
    print(f"缓存数量: {len(caches)}")
    for cache in caches:
        print(f"  学科: {cache[0]} | 更新时间: {cache[1]}")
    
    conn.close()

def test_webchannel_connection():
    """测试WebChannel连接"""
    print("\n🔗 WebChannel连接测试...")
    
    # 这个需要在实际的Qt应用环境中测试
    print("⚠️ WebChannel连接需要在Qt应用环境中测试")
    print("请检查终端日志中是否有以下信息:")
    print("  - '🔗 WebChannel设置到页面完成'")
    print("  - '📄 页面加载完成，状态: True'")

if __name__ == "__main__":
    print("🔍 简单调试脚本")
    print("=" * 40)
    
    check_knowledge_points()
    check_mindmap_cache()
    test_webchannel_connection()
    
    print("\n💡 如果知识点数据正常但脑图不显示，可能的原因:")
    print("1. WebChannel连接问题")
    print("2. LLM服务不可用")
    print("3. 前端JavaScript错误")
    print("4. 数据格式验证失败")
    
    print("\n🔧 建议的修复步骤:")
    print("1. 检查浏览器控制台是否有JavaScript错误")
    print("2. 查看终端日志中的API调用记录")
    print("3. 尝试清除脑图缓存重新生成")
