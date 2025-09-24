#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复practice_service.py中的保存逻辑
添加对answer_history字段的支持
"""

import re

def fix_practice_service():
    """修复practice_service.py文件"""
    
    # 读取原文件
    with open('services/practice_service.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 修复更新语句 - 添加answer_history字段
    update_pattern = r'UPDATE practice_sessions\s+SET selected_text = \?, questions = \?, user_answers = \?,\s+evaluation_result = \?, status = \?, updated_at = CURRENT_TIMESTAMP\s+WHERE practice_id = \?'
    
    new_update = '''UPDATE practice_sessions
                        SET selected_text = ?, questions = ?, user_answers = ?,
                            evaluation_result = ?, answer_history = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE practice_id = ?'''
    
    content = re.sub(update_pattern, new_update, content, flags=re.MULTILINE | re.DOTALL)
    
    # 修复插入语句 - 添加answer_history字段
    insert_pattern = r'INSERT INTO practice_sessions\s+\(practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, status\)\s+VALUES \(\?, \?, \?, \?, \?, \?, \?\)'
    
    new_insert = '''INSERT INTO practice_sessions 
                        (practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)'''
    
    content = re.sub(insert_pattern, new_insert, content, flags=re.MULTILINE | re.DOTALL)
    
    # 修复更新语句的参数传递
    update_params_pattern = r'\(\s+data\.get\(\'selected_text\', \'\'\),\s+data\.get\(\'questions\', \'\'\),\s+data\.get\(\'user_answers\', \'\'\),\s+data\.get\(\'evaluation_result\', \'\'\),\s+\'evaluated\',\s+practice_id\s+\)'
    
    new_update_params = '''(
                        data.get('selected_text', ''),
                        data.get('questions', ''),
                        data.get('user_answers', ''),
                        data.get('evaluation_result', ''),
                        data.get('answer_history', ''),
                        'evaluated',
                        practice_id
                    )'''
    
    content = re.sub(update_params_pattern, new_update_params, content, flags=re.MULTILINE | re.DOTALL)
    
    # 修复插入语句的参数传递
    insert_params_pattern = r'\(\s+practice_id,\s+datetime\.now\(\)\.isoformat\(\),\s+data\.get\(\'selected_text\', \'\'\),\s+data\.get\(\'questions\', \'\'\),\s+data\.get\(\'user_answers\', \'\'\),\s+data\.get\(\'evaluation_result\', \'\'\),\s+\'evaluated\'\s+\)'
    
    new_insert_params = '''(
                        practice_id,
                        datetime.now().isoformat(),
                        data.get('selected_text', ''),
                        data.get('questions', ''),
                        data.get('user_answers', ''),
                        data.get('evaluation_result', ''),
                        data.get('answer_history', ''),
                        'evaluated'
                    )'''
    
    content = re.sub(insert_params_pattern, new_insert_params, content, flags=re.MULTILINE | re.DOTALL)
    
    # 写入修复后的文件
    with open('services/practice_service.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ practice_service.py 修复完成")

if __name__ == "__main__":
    print("🔧 开始修复practice_service.py...")
    fix_practice_service()
    print("🎉 修复完成！")
