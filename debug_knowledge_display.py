#!/usr/bin/env python3
"""
调试知识点显示问题
检查数据库中的知识点关联数据
"""

import sqlite3
import json
from pathlib import Path

def debug_knowledge_display():
    """调试知识点显示问题"""
    print("🔍 开始调试知识点显示问题...")
    
    # 连接数据库
    db_path = "knowledge_management.db"
    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("\n📊 数据库统计信息:")
    
    # 1. 检查知识点总数
    cursor.execute("SELECT COUNT(*) FROM knowledge_points")
    kp_count = cursor.fetchone()[0]
    print(f"📈 知识点总数: {kp_count}")
    
    # 2. 检查笔记总数
    cursor.execute("SELECT COUNT(*) FROM notes")
    notes_count = cursor.fetchone()[0]
    print(f"📈 笔记总数: {notes_count}")
    
    # 3. 检查关联记录总数
    cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources")
    sources_count = cursor.fetchone()[0]
    print(f"📈 知识点来源关联总数: {sources_count}")
    
    # 4. 检查有UUID的关联记录
    cursor.execute("SELECT COUNT(*) FROM knowledge_point_sources WHERE note_uuid IS NOT NULL AND note_uuid != ''")
    uuid_sources_count = cursor.fetchone()[0]
    print(f"📈 使用UUID的关联记录: {uuid_sources_count}")
    
    print("\n📝 最近的知识点记录:")
    
    # 5. 显示最近创建的知识点
    cursor.execute("""
        SELECT id, point_name, subject_name, created_time
        FROM knowledge_points
        ORDER BY created_time DESC
        LIMIT 5
    """)
    
    recent_kps = cursor.fetchall()
    for kp in recent_kps:
        print(f"   🧠 ID:{kp[0]} - {kp[1]} ({kp[2]}) - {kp[3]}")
    
    print("\n📄 最近的笔记记录:")
    
    # 6. 显示最近的笔记记录
    cursor.execute("""
        SELECT id, note_uuid, file_name, file_path, created_time
        FROM notes
        ORDER BY created_time DESC
        LIMIT 5
    """)
    
    recent_notes = cursor.fetchall()
    for note in recent_notes:
        uuid_short = note[1][:8] + "..." if note[1] else "无UUID"
        print(f"   📄 ID:{note[0]} - {note[2]} (UUID:{uuid_short}) - {note[4]}")
    
    print("\n🔗 最近的关联记录:")
    
    # 7. 显示最近的关联记录
    cursor.execute("""
        SELECT kps.id, kps.knowledge_point_id, kps.note_uuid, kps.extraction_time,
               kp.point_name, n.file_name
        FROM knowledge_point_sources kps
        LEFT JOIN knowledge_points kp ON kps.knowledge_point_id = kp.id
        LEFT JOIN notes n ON kps.note_uuid = n.note_uuid
        ORDER BY kps.extraction_time DESC
        LIMIT 10
    """)
    
    recent_sources = cursor.fetchall()
    for source in recent_sources:
        uuid_short = source[2][:8] + "..." if source[2] else "无UUID"
        kp_name = source[4] or "未知知识点"
        file_name = source[5] or "未找到文件"
        print(f"   🔗 关联ID:{source[0]} - {kp_name} -> {file_name} (UUID:{uuid_short}) - {source[3]}")
    
    print("\n🔍 检查特定文件的关联:")
    
    # 8. 检查可能的问题文件
    cursor.execute("""
        SELECT DISTINCT n.file_path, n.note_uuid, COUNT(kps.id) as kp_count
        FROM notes n
        LEFT JOIN knowledge_point_sources kps ON n.note_uuid = kps.note_uuid
        GROUP BY n.file_path, n.note_uuid
        HAVING kp_count > 0
        ORDER BY n.updated_time DESC
        LIMIT 5
    """)
    
    files_with_kps = cursor.fetchall()
    for file_info in files_with_kps:
        uuid_short = file_info[1][:8] + "..." if file_info[1] else "无UUID"
        print(f"   📁 {file_info[0]} (UUID:{uuid_short}) - {file_info[2]}个知识点")
        
        # 显示该文件的具体知识点
        cursor.execute("""
            SELECT kp.point_name, kp.subject_name
            FROM knowledge_points kp
            JOIN knowledge_point_sources kps ON kp.id = kps.knowledge_point_id
            WHERE kps.note_uuid = ?
        """, (file_info[1],))
        
        kps_for_file = cursor.fetchall()
        for kp in kps_for_file:
            print(f"      🧠 {kp[0]} ({kp[1]})")
    
    conn.close()

def test_specific_file_lookup(file_path):
    """测试特定文件的知识点查找"""
    print(f"\n🎯 测试文件知识点查找: {file_path}")
    
    # 模拟_findOrCreateNoteRecord的逻辑
    def normalize_path(path):
        normalized = path.replace('\\', '/')
        if normalized.startswith('./'):
            normalized = normalized[2:]
        return normalized
    
    normalized_path = normalize_path(file_path)
    print(f"📍 标准化路径: {normalized_path}")
    
    conn = sqlite3.connect("knowledge_management.db")
    cursor = conn.cursor()
    
    # 1. 精确路径匹配
    cursor.execute("SELECT id, note_uuid, file_name FROM notes WHERE file_path = ?", (normalized_path,))
    exact_match = cursor.fetchone()
    
    if exact_match:
        print(f"✅ 精确匹配找到: ID:{exact_match[0]}, UUID:{exact_match[1][:8]}..., 文件名:{exact_match[2]}")
        
        # 查找关联的知识点
        cursor.execute("""
            SELECT kp.id, kp.point_name, kp.subject_name
            FROM knowledge_points kp
            JOIN knowledge_point_sources kps ON kp.id = kps.knowledge_point_id
            WHERE kps.note_uuid = ?
        """, (exact_match[1],))
        
        related_kps = cursor.fetchall()
        print(f"🔗 关联的知识点数量: {len(related_kps)}")
        for kp in related_kps:
            print(f"   🧠 {kp[1]} ({kp[2]})")
    else:
        print("❌ 精确匹配未找到")
        
        # 2. 模糊匹配
        cursor.execute("SELECT id, note_uuid, file_name, file_path FROM notes WHERE file_path LIKE ?", (f'%{Path(normalized_path).name}%',))
        fuzzy_matches = cursor.fetchall()
        
        if fuzzy_matches:
            print(f"🔍 模糊匹配找到 {len(fuzzy_matches)} 个结果:")
            for match in fuzzy_matches:
                print(f"   📄 ID:{match[0]}, UUID:{match[1][:8]}..., 文件名:{match[2]}, 路径:{match[3]}")
        else:
            print("❌ 模糊匹配也未找到")
    
    conn.close()

def main():
    """主函数"""
    debug_knowledge_display()
    
    # 如果用户提供了具体的文件路径，可以测试该文件
    print("\n" + "="*60)
    print("💡 如果您想测试特定文件，请提供文件路径")
    print("例如: vault/某个笔记.md")
    
    # 这里可以根据需要添加具体的文件路径测试
    # test_specific_file_lookup("vault/example.md")

if __name__ == "__main__":
    main()
