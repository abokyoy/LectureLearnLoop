#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复加载逻辑，添加对answer_history字段的支持
"""

import re

def fix_load_logic():
    """修复加载逻辑"""
    
    # 读取原文件
    with open('services/practice_service.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 修复SELECT语句 - 添加answer_history字段
    select_pattern = r'SELECT practice_id, timestamp, selected_text, questions,\s+user_answers, evaluation_result, status'
    
    new_select = '''SELECT practice_id, timestamp, selected_text, questions,
                           user_answers, evaluation_result, answer_history, status'''
    
    content = re.sub(select_pattern, new_select, content, flags=re.MULTILINE | re.DOTALL)
    
    # 修复row解包 - 添加answer_history字段
    unpack_pattern = r'practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, status = row'
    
    new_unpack = 'practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status = row'
    
    content = re.sub(unpack_pattern, new_unpack, content)
    
    # 修复practice_detail字典 - 添加answer_history字段
    detail_pattern = r'practice_detail = \{\s+"practice_id": practice_id,\s+"timestamp": timestamp,\s+"selected_text": selected_text or "",\s+"questions": questions or "",\s+"user_answers": user_answers or "",\s+"evaluation_result": evaluation_result or "",\s+"status": status or "unknown"\s+\}'
    
    new_detail = '''practice_detail = {
                        "practice_id": practice_id,
                        "timestamp": timestamp,
                        "selected_text": selected_text or "",
                        "questions": questions or "",
                        "user_answers": user_answers or "",
                        "evaluation_result": evaluation_result or "",
                        "answer_history": answer_history or "",
                        "status": status or "unknown"
                    }'''
    
    content = re.sub(detail_pattern, new_detail, content, flags=re.MULTILINE | re.DOTALL)
    
    # 写入修复后的文件
    with open('services/practice_service.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ 加载逻辑修复完成")

if __name__ == "__main__":
    print("🔧 开始修复加载逻辑...")
    fix_load_logic()
    print("🎉 修复完成！")
