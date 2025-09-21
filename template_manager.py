#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模板管理器
负责管理和渲染Jinja2模板
"""

import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

class TemplateManager:
    """模板管理器类"""
    
    def __init__(self, template_dir="templates"):
        """
        初始化模板管理器
        
        Args:
            template_dir: 模板文件目录路径
        """
        self.template_dir = Path(template_dir)
        
        # 确保模板目录存在
        if not self.template_dir.exists():
            raise FileNotFoundError(f"模板目录不存在: {self.template_dir}")
        
        # 初始化Jinja2环境
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        print(f"📁 模板管理器初始化完成，模板目录: {self.template_dir}")
    
    def render_spa_layout(self, **context):
        """
        渲染SPA主布局
        
        Args:
            **context: 模板上下文变量
            
        Returns:
            str: 渲染后的HTML内容
        """
        try:
            template = self.env.get_template('spa_layout.html')
            return template.render(**context)
        except Exception as e:
            print(f"❌ 渲染SPA布局失败: {e}")
            return self._get_error_html(f"渲染SPA布局失败: {e}")
    
    def render_page_content(self, page_name, **context):
        """
        渲染页面内容
        
        Args:
            page_name: 页面名称（不含.html后缀）
            **context: 模板上下文变量
            
        Returns:
            str: 渲染后的HTML内容
        """
        try:
            template_path = f'pages/{page_name}.html'
            template = self.env.get_template(template_path)
            return template.render(**context)
        except Exception as e:
            print(f"❌ 渲染页面内容失败 ({page_name}): {e}")
            return self._get_placeholder_content(page_name)
    
    def render_component(self, component_name, **context):
        """
        渲染组件
        
        Args:
            component_name: 组件名称（不含.html后缀）
            **context: 模板上下文变量
            
        Returns:
            str: 渲染后的HTML内容
        """
        try:
            template_path = f'components/{component_name}.html'
            template = self.env.get_template(template_path)
            return template.render(**context)
        except Exception as e:
            print(f"❌ 渲染组件失败 ({component_name}): {e}")
            return f'<!-- 组件渲染失败: {component_name} -->'
    
    def _get_error_html(self, error_message):
        """
        获取错误页面HTML
        
        Args:
            error_message: 错误信息
            
        Returns:
            str: 错误页面HTML
        """
        return f'''
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>模板错误 - 柯基学习小助手</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-red-50 flex items-center justify-center min-h-screen">
            <div class="bg-white p-8 rounded-lg shadow-lg max-w-md">
                <div class="text-red-600 text-center">
                    <h1 class="text-2xl font-bold mb-4">模板渲染错误</h1>
                    <p class="text-gray-700">{error_message}</p>
                </div>
            </div>
        </body>
        </html>
        '''
    
    def _get_placeholder_content(self, page_name):
        """
        获取占位符内容
        
        Args:
            page_name: 页面名称
            
        Returns:
            str: 占位符HTML内容
        """
        page_titles = {
            "dashboard": "工作台",
            "learn_from_materials": "从资料学习",
            "learn_from_audio": "从音视频学习", 
            "online_course_notes": "网课笔记",
            "practice_materials": "基于学习资料练习",
            "practice_knowledge": "基于知识点练习",
            "practice_errors": "基于错题练习",
            "memory_knowledge": "基于知识点记忆",
            "memory_errors": "基于错题记忆",
            "knowledge_base": "知识库管理",
            "settings": "设置",
            "llm_logs": "LLM调用日志"
        }
        
        title = page_titles.get(page_name, page_name)
        
        return f'''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">construction</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">{title}</h3>
                <p class="text-text-gray mb-6">该页面模板正在开发中...</p>
                <div class="text-sm text-gray-500">
                    <p>模板文件: pages/{page_name}.html</p>
                </div>
            </div>
        </div>
        '''
    
    def list_templates(self):
        """
        列出所有可用的模板文件
        
        Returns:
            dict: 模板文件信息
        """
        templates = {
            "layouts": [],
            "components": [],
            "pages": []
        }
        
        # 扫描模板目录
        for root, dirs, files in os.walk(self.template_dir):
            for file in files:
                if file.endswith('.html'):
                    rel_path = os.path.relpath(os.path.join(root, file), self.template_dir)
                    
                    if rel_path.startswith('components/'):
                        templates["components"].append(rel_path)
                    elif rel_path.startswith('pages/'):
                        templates["pages"].append(rel_path)
                    else:
                        templates["layouts"].append(rel_path)
        
        return templates
    
    def get_template_info(self):
        """
        获取模板系统信息
        
        Returns:
            dict: 模板系统信息
        """
        templates = self.list_templates()
        
        return {
            "template_dir": str(self.template_dir),
            "total_templates": sum(len(v) for v in templates.values()),
            "templates": templates,
            "jinja2_version": self.env.environment_class.__module__
        }
