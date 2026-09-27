#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LectureLearnLoop Flask Web Application
基于原有Qt应用改造的Web版本

主要改造点：
1. Qt WebEngine → Flask Web Server
2. QWebChannel → RESTful API
3. @Slot装饰器 → @app.route装饰器
4. 业务逻辑层完全复用
"""

import os
import sys
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_cors import CORS
from flask_session import Session
from datetime import timedelta
import logging
from logging.handlers import RotatingFileHandler

# 导入配置和业务逻辑（完全复用现有代码）
from config import load_config, save_config
from knowledge_management import KnowledgeManagementSystem
from llm_provider_factory import LLMProviderFactory, call_llm
from llm_call_logger import get_llm_call_records, get_llm_call_statistics

# 创建Flask应用
app = Flask(__name__)

# 基础配置
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB最大上传

# 启用CORS（开发阶段，生产环境需要配置具体域名）
CORS(app, supports_credentials=True)

# 启用Session
Session(app)

# 配置日志
if not os.path.exists('logs'):
    os.makedirs('logs')

file_handler = RotatingFileHandler(
    'logs/app.log',
    maxBytes=10240000,  # 10MB
    backupCount=10
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('LectureLearnLoop Flask启动')

# 初始化业务对象（复用现有代码）
config = load_config()
km_system = KnowledgeManagementSystem(config)  # 传入config参数
llm_factory = LLMProviderFactory()

# ==================== 模板上下文处理器 ====================

@app.context_processor
def inject_common_variables():
    """为所有模板注入通用变量"""
    return {
        'config': config,
        'stats': {
            'learning_materials': 0,
            'practice_accuracy': '0%',
            'knowledge_points': 0,
            'study_hours': 0
        }
    }

# ==================== 页面路由 ====================

@app.route('/')
def index():
    """首页 - 工作台"""
    return render_template('pages/dashboard.html', title='工作台')

@app.route('/learn_materials')
def learn_materials():
    """资料学习页面"""
    return render_template('pages/learn_from_materials.html', title='从资料学习')

@app.route('/online_course')
def online_course():
    """网课笔记页面"""
    return render_template('pages/online_course_notes.html', title='网课笔记')

@app.route('/practice')
def practice():
    """练习脑图页面"""
    return render_template('pages/practice_materials.html', title='练习脑图')

@app.route('/knowledge_base')
def knowledge_base():
    """知识库管理页面"""
    return render_template('pages/knowledge_base.html', title='知识库管理')

@app.route('/settings')
def settings():
    """设置页面"""
    return render_template('pages/settings.html', title='设置')

@app.route('/llm_logs')
def llm_logs():
    """LLM调用日志页面"""
    return render_template('pages/llm_logs.html', title='LLM调用日志')

# ==================== API路由 ====================

# 知识管理API
@app.route('/api/knowledge/extract', methods=['POST'])
def api_extract_knowledge():
    """提取知识点（复用原有业务逻辑）"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        app.logger.info(f'提取知识点请求，文本长度: {len(text)}')
        
        # 直接调用原有业务逻辑
        result = km_system.extract_knowledge_points(text)
        
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        app.logger.error(f'提取知识点失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/knowledge/list', methods=['GET'])
def api_get_knowledge_points():
    """获取知识点列表"""
    try:
        subject = request.args.get('subject')
        points = km_system.get_knowledge_points(subject)
        
        return jsonify({
            'success': True,
            'data': points
        })
    except Exception as e:
        app.logger.error(f'获取知识点列表失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/knowledge/create', methods=['POST'])
def api_create_knowledge_point():
    """创建知识点"""
    try:
        data = request.get_json()
        result = km_system.create_knowledge_point(
            subject=data.get('subject'),
            point_name=data.get('point_name'),
            description=data.get('description')
        )
        
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        app.logger.error(f'创建知识点失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# LLM调用API
@app.route('/api/llm/call', methods=['POST'])
def api_call_llm():
    """调用LLM（复用原有逻辑）"""
    try:
        data = request.get_json()
        prompt = data.get('prompt', '')
        provider = data.get('provider')
        
        app.logger.info(f'LLM调用请求，提供商: {provider}')
        
        # 调用原有的LLM工厂
        result = call_llm(prompt, provider)
        
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        app.logger.error(f'LLM调用失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/llm/logs', methods=['GET'])
def api_get_llm_logs():
    """获取LLM调用日志"""
    try:
        limit = int(request.args.get('limit', 50))
        logs = get_llm_call_records(limit)
        
        return jsonify({
            'success': True,
            'data': logs
        })
    except Exception as e:
        app.logger.error(f'获取LLM日志失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/llm/stats', methods=['GET'])
def api_get_llm_stats():
    """获取LLM调用统计"""
    try:
        stats = get_llm_call_statistics()
        
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        app.logger.error(f'获取LLM统计失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# 配置管理API
@app.route('/api/config/get', methods=['GET'])
def api_get_config():
    """获取配置"""
    try:
        return jsonify({
            'success': True,
            'data': config
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/config/save', methods=['POST'])
def api_save_config():
    """保存配置"""
    try:
        data = request.get_json()
        global config
        config.update(data)
        save_config(config)
        
        return jsonify({
            'success': True,
            'message': '配置保存成功'
        })
    except Exception as e:
        app.logger.error(f'保存配置失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# 文件操作API
@app.route('/api/file/save', methods=['POST'])
def api_save_file():
    """保存文件"""
    try:
        data = request.get_json()
        file_path = data.get('path')
        content = data.get('content')
        
        # 安全检查：确保路径在允许的目录内
        base_dir = os.path.join(app.root_path, 'data')
        full_path = os.path.join(base_dir, file_path)
        
        if not full_path.startswith(base_dir):
            return jsonify({
                'success': False,
                'error': '非法路径'
            }), 403
        
        # 确保目录存在
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # 保存文件
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({
            'success': True,
            'message': '文件保存成功'
        })
    except Exception as e:
        app.logger.error(f'保存文件失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/file/load', methods=['GET'])
def api_load_file():
    """加载文件"""
    try:
        file_path = request.args.get('path')
        
        # 安全检查
        base_dir = os.path.join(app.root_path, 'data')
        full_path = os.path.join(base_dir, file_path)
        
        if not full_path.startswith(base_dir):
            return jsonify({
                'success': False,
                'error': '非法路径'
            }), 403
        
        # 读取文件
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            'success': True,
            'data': content
        })
    except Exception as e:
        app.logger.error(f'加载文件失败: {str(e)}')
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    """404错误处理"""
    return jsonify({
        'success': False,
        'error': 'Not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """500错误处理"""
    app.logger.error(f'Internal error: {str(error)}')
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    """文件过大错误"""
    return jsonify({
        'success': False,
        'error': '文件过大，最大支持50MB'
    }), 413

# ==================== 启动应用 ====================

if __name__ == '__main__':
    # 开发模式
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        threaded=True
    )
    
    # 生产模式使用：
    # gunicorn -w 4 -b 0.0.0.0:5000 app_flask:app
