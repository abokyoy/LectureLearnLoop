#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
调试练习历史数据结构
"""

import sqlite3
import json

def debug_practice_data():
    """调试练习数据结构"""
    print("=" * 50)
    print("调试练习历史数据结构")
    print("=" * 50)
    
    try:
        conn = sqlite3.connect('practice_data.db')
        cursor = conn.cursor()
        
        # 查询一条具体的练习记录
        cursor.execute("""
            SELECT practice_id, timestamp, selected_text, questions, user_answers, 
                   evaluation_result, status, answer_history 
            FROM practice_sessions 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        record = cursor.fetchone()
        if record:
            practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, status, answer_history = record
            
            print("📊 练习记录详细信息:")
            print(f"practice_id: {practice_id}")
            print(f"timestamp: {timestamp}")
            print(f"selected_text: {selected_text[:100] if selected_text else 'None'}...")
            print(f"questions: {questions[:100] if questions else 'None'}...")
            print(f"user_answers: {user_answers[:100] if user_answers else 'None'}...")
            print(f"evaluation_result: {evaluation_result[:100] if evaluation_result else 'None'}...")
            print(f"status: {status}")
            print(f"answer_history: {answer_history[:100] if answer_history else 'None'}...")
            
            # 模拟前端会收到的数据格式
            practice_data = {
                'practice_id': practice_id,
                'id': practice_id,  # 兼容字段
                'timestamp': timestamp,
                'selected_text': selected_text,
                'questions': questions,
                'question': questions,  # 兼容字段
                'user_answers': user_answers,
                'answer': user_answers,  # 兼容字段
                'evaluation_result': evaluation_result,
                'evaluation': evaluation_result,  # 兼容字段
                'status': status,
                'answer_history': answer_history
            }
            
            print("\n📋 前端会收到的数据格式:")
            print(json.dumps(practice_data, ensure_ascii=False, indent=2))
            
        conn.close()
        
    except Exception as e:
        print(f"❌ 查询失败: {e}")

if __name__ == "__main__":
    debug_practice_data()
