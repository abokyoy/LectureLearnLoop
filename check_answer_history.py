#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
检查练习历史中的用户提交记录
"""

import sqlite3
import json
from datetime import datetime

def check_answer_history():
    """检查答案历史记录"""
    print("=" * 60)
    print("检查练习历史中的用户提交记录")
    print("=" * 60)
    
    try:
        conn = sqlite3.connect('practice_data.db')
        cursor = conn.cursor()
        
        # 查询最新的几条练习记录
        cursor.execute("""
            SELECT practice_id, timestamp, selected_text, questions, user_answers, 
                   evaluation_result, status, answer_history 
            FROM practice_sessions 
            ORDER BY timestamp DESC 
            LIMIT 5
        """)
        
        records = cursor.fetchall()
        print(f"📊 找到 {len(records)} 条最新练习记录\n")
        
        for i, record in enumerate(records):
            practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, status, answer_history = record
            
            print(f"{'='*50}")
            print(f"📋 记录 {i+1}: {practice_id}")
            print(f"{'='*50}")
            print(f"🕒 时间: {timestamp}")
            print(f"📝 状态: {status}")
            print(f"📄 题目长度: {len(questions or '')}")
            print(f"✍️ 用户答案长度: {len(user_answers or '')}")
            print(f"📊 评估结果长度: {len(evaluation_result or '')}")
            print(f"📚 答案历史长度: {len(answer_history or '')}")
            
            # 详细检查用户答案
            if user_answers:
                print(f"\n✍️ 用户答案内容:")
                print(f"   {user_answers[:200]}...")
            else:
                print(f"\n❌ 用户答案为空")
            
            # 详细检查答案历史
            if answer_history:
                print(f"\n📚 答案历史内容:")
                try:
                    history_data = json.loads(answer_history)
                    if isinstance(history_data, list):
                        print(f"   📊 历史记录数量: {len(history_data)}")
                        for j, entry in enumerate(history_data):
                            if isinstance(entry, dict):
                                entry_id = entry.get('id', 'N/A')
                                timestamp = entry.get('timestamp', 'N/A')
                                answer = entry.get('answer', '')
                                score = entry.get('score', 'N/A')
                                print(f"   📝 记录 {j+1}: ID={entry_id}, 时间={timestamp}, 分数={score}")
                                print(f"      答案: {answer[:100]}...")
                            else:
                                print(f"   📝 记录 {j+1}: {str(entry)[:100]}...")
                    else:
                        print(f"   📄 历史数据: {str(history_data)[:200]}...")
                except json.JSONDecodeError as e:
                    print(f"   ❌ JSON解析失败: {e}")
                    print(f"   📄 原始数据: {answer_history[:200]}...")
            else:
                print(f"\n❌ 答案历史为空")
            
            # 详细检查评估结果
            if evaluation_result:
                print(f"\n📊 评估结果内容:")
                try:
                    eval_data = json.loads(evaluation_result)
                    if isinstance(eval_data, dict):
                        score = eval_data.get('score', 'N/A')
                        feedback = eval_data.get('feedback', '')
                        print(f"   🎯 分数: {score}")
                        print(f"   💬 反馈: {feedback[:100]}...")
                    else:
                        print(f"   📄 评估数据: {str(eval_data)[:200]}...")
                except json.JSONDecodeError as e:
                    print(f"   ❌ JSON解析失败: {e}")
                    print(f"   📄 原始数据: {evaluation_result[:200]}...")
            else:
                print(f"\n❌ 评估结果为空")
            
            print(f"\n")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        import traceback
        traceback.print_exc()

def simulate_frontend_data():
    """模拟前端会收到的数据格式"""
    print("=" * 60)
    print("模拟前端API调用返回的数据格式")
    print("=" * 60)
    
    try:
        conn = sqlite3.connect('practice_data.db')
        cursor = conn.cursor()
        
        # 模拟getPracticeHistory API调用
        cursor.execute("""
            SELECT practice_id as id, timestamp, selected_text, questions, user_answers, 
                   evaluation_result, status, answer_history 
            FROM practice_sessions 
            ORDER BY timestamp DESC 
            LIMIT 3
        """)
        
        records = cursor.fetchall()
        practices = []
        
        for record in records:
            practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, status, answer_history = record
            
            practice_data = {
                'id': practice_id,
                'practice_id': practice_id,
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
            practices.append(practice_data)
        
        api_response = {
            'success': True,
            'practices': practices
        }
        
        print("🔄 API响应格式:")
        print(json.dumps(api_response, ensure_ascii=False, indent=2))
        
        conn.close()
        
    except Exception as e:
        print(f"❌ 模拟API调用失败: {e}")

if __name__ == "__main__":
    check_answer_history()
    print("\n")
    simulate_frontend_data()
