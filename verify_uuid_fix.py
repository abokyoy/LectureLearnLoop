#!/usr/bin/env python3
"""
UUID修复验证脚本
检查知识点合并功能是否正确使用UUID系统
"""

import re

def check_merge_function_fix():
    """检查mergeKnowledgePoint函数是否已修复"""
    print("🔍 检查mergeKnowledgePoint函数...")
    
    try:
        with open('overlay_drag_corgi_app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 查找mergeKnowledgePoint函数
        merge_function_match = re.search(
            r'def mergeKnowledgePoint\(self, merge_data\):(.*?)(?=def|\Z)', 
            content, 
            re.DOTALL
        )
        
        if not merge_function_match:
            print("❌ 未找到mergeKnowledgePoint函数")
            return False
        
        merge_function_code = merge_function_match.group(1)
        
        # 检查是否使用了note_uuid而不是note_id
        if 'if note_uuid:' in merge_function_code:
            print("✅ mergeKnowledgePoint函数正确使用note_uuid")
        else:
            print("❌ mergeKnowledgePoint函数未使用note_uuid")
            return False
        
        # 检查是否还有错误的note_id使用
        if 'if note_id:' in merge_function_code:
            print("❌ mergeKnowledgePoint函数仍在使用note_id")
            return False
        
        # 检查link_knowledge_point_to_note调用
        if 'link_knowledge_point_to_note(target_knowledge_id, note_uuid)' in merge_function_code:
            print("✅ link_knowledge_point_to_note正确使用note_uuid参数")
        else:
            print("❌ link_knowledge_point_to_note未正确使用note_uuid参数")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 检查过程中出现错误: {e}")
        return False

def check_create_function():
    """检查createNewKnowledgePoint函数"""
    print("\n🔍 检查createNewKnowledgePoint函数...")
    
    try:
        with open('overlay_drag_corgi_app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 查找createNewKnowledgePoint函数
        create_function_match = re.search(
            r'def createNewKnowledgePoint\(self, create_data\):(.*?)(?=def|\Z)', 
            content, 
            re.DOTALL
        )
        
        if not create_function_match:
            print("❌ 未找到createNewKnowledgePoint函数")
            return False
        
        create_function_code = create_function_match.group(1)
        
        # 检查是否正确使用UUID
        if 'note_uuid = self._findOrCreateNoteRecord' in create_function_code:
            print("✅ createNewKnowledgePoint函数正确获取note_uuid")
        else:
            print("❌ createNewKnowledgePoint函数未正确获取note_uuid")
            return False
        
        if 'link_knowledge_point_to_note(new_knowledge_id, note_uuid)' in create_function_code:
            print("✅ createNewKnowledgePoint函数正确使用note_uuid参数")
        else:
            print("❌ createNewKnowledgePoint函数未正确使用note_uuid参数")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 检查过程中出现错误: {e}")
        return False

def check_database_queries():
    """检查数据库查询是否使用UUID"""
    print("\n🔍 检查数据库查询...")
    
    try:
        with open('overlay_drag_corgi_app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否还有使用note_id的JOIN查询
        problematic_joins = [
            'JOIN notes n ON kps.note_id = n.id',
            'JOIN notes n ON n.id = kps.note_id'
        ]
        
        issues_found = []
        for join_pattern in problematic_joins:
            if join_pattern in content:
                issues_found.append(join_pattern)
        
        if issues_found:
            print("❌ 发现使用note_id的JOIN查询:")
            for issue in issues_found:
                print(f"   - {issue}")
            return False
        
        # 检查是否正确使用UUID的JOIN查询
        correct_joins = [
            'JOIN notes n ON kps.note_uuid = n.note_uuid',
            'JOIN notes n ON n.note_uuid = kps.note_uuid'
        ]
        
        uuid_joins_found = 0
        for join_pattern in correct_joins:
            if join_pattern in content:
                uuid_joins_found += 1
        
        if uuid_joins_found > 0:
            print(f"✅ 发现 {uuid_joins_found} 个正确的UUID JOIN查询")
        else:
            print("⚠️ 未发现UUID JOIN查询（可能不需要或已在其他地方处理）")
        
        return True
        
    except Exception as e:
        print(f"❌ 检查过程中出现错误: {e}")
        return False

def check_knowledge_management_file():
    """检查knowledge_management.py文件的修复"""
    print("\n🔍 检查knowledge_management.py文件...")
    
    try:
        with open('knowledge_management.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查get_knowledge_point_sources方法
        if 'JOIN notes n ON n.note_uuid = kps.note_uuid' in content:
            print("✅ get_knowledge_point_sources方法正确使用UUID关联")
        else:
            print("❌ get_knowledge_point_sources方法未正确使用UUID关联")
            return False
        
        # 检查是否还有错误的关联
        if 'JOIN notes n ON n.id = kps.note_id' in content:
            print("❌ 仍有使用note_id的关联查询")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 检查过程中出现错误: {e}")
        return False

def main():
    """主验证函数"""
    print("🚀 开始UUID修复验证...")
    
    all_checks_passed = True
    
    # 检查1: mergeKnowledgePoint函数
    if not check_merge_function_fix():
        all_checks_passed = False
    
    # 检查2: createNewKnowledgePoint函数
    if not check_create_function():
        all_checks_passed = False
    
    # 检查3: 数据库查询
    if not check_database_queries():
        all_checks_passed = False
    
    # 检查4: knowledge_management.py文件
    if not check_knowledge_management_file():
        all_checks_passed = False
    
    print("\n" + "="*60)
    
    if all_checks_passed:
        print("🎉 所有检查通过！UUID修复已完成。")
        print("\n📋 修复总结:")
        print("✅ mergeKnowledgePoint函数已修复为使用note_uuid")
        print("✅ createNewKnowledgePoint函数正确使用UUID系统")
        print("✅ 数据库查询已更新为UUID关联")
        print("✅ knowledge_management.py文件已修复")
        print("\n🔧 现在知识点合并功能应该不再出现'name note id is not defined'错误。")
    else:
        print("❌ 部分检查未通过，请检查上述问题。")

if __name__ == "__main__":
    main()
