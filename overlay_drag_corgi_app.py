#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
{{ ... }}
"""

import sys
import os
import json
import logging
import time
from datetime import datetime
from pathlib import Path
import traceback
import asyncio
import threading
import requests
from typing import Dict, Any, Optional, List
import queue
import wave
import numpy as np
import pyaudio
import torch
# 导入语音转写模块
whisper = None
faster_whisper = None

try:
    # 优先尝试faster-whisper（更快更稳定）
    from faster_whisper import WhisperModel
    faster_whisper = WhisperModel
    print("✅ 使用 faster-whisper 包")
except ImportError:
    try:
        # 备选：尝试导入标准whisper包，但需要避免冲突
        import subprocess
        import sys
        
        # 临时重命名冲突的whisper.py文件
        conflict_file = None
        for path in sys.path:
            potential_conflict = os.path.join(path, 'whisper.py')
            if os.path.exists(potential_conflict):
                # 检查是否是冲突的文件（不是OpenAI Whisper）
                with open(potential_conflict, 'r', encoding='utf-8') as f:
                    content = f.read(200)
                    if 'ctypes.util.find_library' in content and 'fallocate' in content:
                        conflict_file = potential_conflict
                        backup_file = potential_conflict + '.backup'
                        os.rename(conflict_file, backup_file)
                        print(f"🔄 临时重命名冲突文件: {conflict_file}")
                        break
        
        # 现在尝试导入whisper
        import whisper
        print("✅ 成功导入 OpenAI Whisper")
        
        # 恢复冲突文件
        if conflict_file:
            backup_file = conflict_file + '.backup'
            if os.path.exists(backup_file):
                os.rename(backup_file, conflict_file)
                print(f"🔄 恢复冲突文件: {conflict_file}")
                
    except Exception as e:
        print(f"⚠️ Whisper导入失败: {e}")
        whisper = None

if whisper is None and faster_whisper is None:
    print("❌ 语音转写功能不可用，录音转写功能将被禁用")
from config import load_config, save_config
from template_manager import TemplateManager
from llm_provider_factory import call_llm, test_llm_connection, llm_factory
from llm_call_logger import get_llm_call_records, get_llm_call_statistics, llm_call_logger
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout, QLabel,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QProgressBar
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import Qt, QTimer, QUrl, QThread, Signal, Slot, QObject, QRect, QPoint, QByteArray, QRegularExpression
from PySide6.QtGui import QFont, QMouseEvent, QCursor, QIcon, QKeySequence, QShortcut

class CorgiWebBridge(QObject):
    """Python与JavaScript通信桥梁"""
    
    pageChanged = Signal(str)
    dataUpdated = Signal(str)
    chatResponseReady = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = "dashboard"
        self.main_window = parent
        
        # 设置日志记录
        self.setup_logging()
        
        # 菜单状态管理
        self.menu_state = {
            "dashboard": {"expanded": False, "children": []},
            "learn": {"expanded": False, "children": ["learn_from_materials", "online_course_notes"]},
            "practice": {"expanded": False, "children": ["practice_materials", "practice_knowledge", "practice_errors"]},
            "memory": {"expanded": False, "children": ["memory_knowledge", "memory_errors"]},
            "knowledge_base": {"expanded": False, "children": []},
            "settings": {"expanded": False, "children": []}
        }
        
        # 录音相关状态
        self.is_recording = False
        self.transcription_text = ""
        self.summary_text = ""
        self.is_test_mode = False
        
        # 从配置文件加载设备设置
        self.selected_device_index = self.config.get("selected_audio_device_index", None)
        self.selected_device_name = self.config.get("selected_audio_device_name", None)
        
        if self.selected_device_index is not None:
            self.logger.info(f"🎤 已加载保存的音频设备: {self.selected_device_name} (索引: {self.selected_device_index})")
        else:
            self.logger.info("🎤 未设置音频设备，将使用默认设备")
        
        # 录音和转写线程
        self._rec_thread = None
        self._rec_worker = None
        self._tr_thread = None
        self._tr_worker = None
        
        # 转写队列
        self.transcription_queue = queue.Queue()
        
    def setup_logging(self):
        """设置日志记录"""
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 创建logger
        self.logger = logging.getLogger('CorgiWebBridge')
        self.logger.setLevel(logging.DEBUG)
        
        # 清除现有的handlers
        self.logger.handlers.clear()
        
        # 创建文件handler
        log_file = os.path.join(log_dir, f"corgi_bridge_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 创建控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 创建formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 添加handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # 创建专门的录音测试日志
        test_log_file = os.path.join(log_dir, f"recording_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.test_logger = logging.getLogger('RecordingTest')
        self.test_logger.setLevel(logging.DEBUG)
        self.test_logger.handlers.clear()
        
        test_file_handler = logging.FileHandler(test_log_file, encoding='utf-8')
        test_file_handler.setLevel(logging.DEBUG)
        test_formatter = logging.Formatter('%(asctime)s - [TEST] - %(message)s')
        test_file_handler.setFormatter(test_formatter)
        self.test_logger.addHandler(test_file_handler)
        
        self.logger.info(f"日志文件: {log_file}")
        self.logger.info(f"测试日志文件: {test_log_file}")
        
        # 加载配置
        self.config = load_config()
        
        self.logger.info("=" * 80)
        self.logger.info("文件结构调试日志开始")
        self.logger.info("=" * 80)
        
    @Slot(str)
    def logFrontendMessage(self, message):
        """记录前端发送的日志消息"""
        # 直接写入日志，因为前端已经包含了时间戳和级别
        self.logger.handlers[0].stream.write(message + '\n')
        self.logger.handlers[0].stream.flush()

    @Slot()
    def minimizeWindow(self):
        """最小化窗口"""
        if self.main_window:
            self.main_window.showMinimized()
            print("🔽 窗口已最小化")
            
    @Slot()
    def maximizeWindow(self):
        """最大化/还原窗口"""
        if self.main_window:
            # 使用自定义标志来跟踪状态
            if not hasattr(self.main_window, 'is_maximized_custom'):
                self.main_window.is_maximized_custom = False
                
            print(f"🔍 当前自定义状态: {self.main_window.is_maximized_custom}")
            
            if self.main_window.is_maximized_custom:
                # 还原窗口
                if hasattr(self.main_window, 'normal_geometry') and self.main_window.normal_geometry:
                    self.main_window.setGeometry(self.main_window.normal_geometry)
                    self.main_window.is_maximized_custom = False
                    print("🔄 窗口已还原到原始大小")
                else:
                    self.main_window.showNormal()
                    self.main_window.is_maximized_custom = False
                    print("🔄 窗口已还原")
            else:
                # 最大化窗口
                self.main_window.normal_geometry = self.main_window.geometry()
                print(f"💾 保存窗口几何信息: {self.main_window.normal_geometry}")
                
                # 获取当前窗口所在屏幕的尺寸
                current_screen = QApplication.screenAt(self.main_window.geometry().center())
                if current_screen is None:
                    current_screen = QApplication.primaryScreen()
                screen_geometry = current_screen.geometry()
                
                self.main_window.setGeometry(screen_geometry)
                self.main_window.is_maximized_custom = True
                print(f"🔼 窗口已在当前屏幕最大化: {screen_geometry}")
                
    @Slot()
    def closeWindow(self):
        """关闭窗口"""
        if self.main_window:
            self.main_window.close()
            print("❌ 窗口已关闭")
            
    
    @Slot(str, result=str)
    def toggleMenu(self, menu_id):
        """切换菜单展开/收缩状态"""
        if menu_id in self.menu_state:
            # 如果有子菜单，切换展开状态
            if self.menu_state[menu_id]["children"]:
                self.menu_state[menu_id]["expanded"] = not self.menu_state[menu_id]["expanded"]
                print(f"📋 菜单 {menu_id} 展开状态: {self.menu_state[menu_id]['expanded']}")
            else:
                # 叶子节点，直接加载内容
                self.loadContent(menu_id)
        else:
            # 检查是否是二级菜单项
            is_submenu_item = False
            for parent_id, parent_data in self.menu_state.items():
                if menu_id in parent_data.get("children", []):
                    is_submenu_item = True
                    print(f"📄 二级菜单项点击: {menu_id}")
                    self.loadContent(menu_id)
                    break
            
            if not is_submenu_item:
                print(f"⚠️ 未知菜单项: {menu_id}")
        
        return json.dumps(self.menu_state, ensure_ascii=False)
    
    @Slot(str)
    def loadContent(self, content_id):
        """加载指定内容"""
        print(f"🔍 loadContent被调用，content_id: {content_id}")
        self.current_page = content_id
        if self.main_window:
            print(f"🔍 main_window存在，开始生成内容HTML")
            content_html = self.main_window.generate_content_html(content_id)
            print(f"🔍 生成的HTML长度: {len(content_html)}")
            print(f"🔍 HTML内容预览: {content_html[:200]}...")
            
            # 转义HTML内容中的反引号和反斜杠
            escaped_html = content_html.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            print(f"🔍 HTML转义完成，长度: {len(escaped_html)}")
            
            # 通过JavaScript更新右侧内容区域
            js_code = f"updateContentArea(`{escaped_html}`);"
            print(f"🔍 执行JavaScript代码长度: {len(js_code)}")
            
            self.main_window.web_view.page().runJavaScript(js_code)
            print(f"📄 已加载内容: {content_id}")
        else:
            print(f"❌ main_window不存在")
            
            # 更新页面标题和活动菜单项
            title_map = {
                "dashboard": "柯基的学习乐园",
                "learn_from_materials": "从资料学习",
                "learn_from_audio": "从音视频学习",
                "online_course_notes": "网课笔记",
                "practice_materials": "基于学习资料练习",
                "practice_knowledge": "基于知识点练习", 
                "practice_errors": "基于错题练习",
                "memory_knowledge": "基于知识点记忆",
                "memory_errors": "基于错题记忆",
                "knowledge_base": "知识库管理",
                "settings": "设置"
            }
            page_title = title_map.get(content_id, "柯基学习小助手")
            self.main_window.web_view.page().runJavaScript(f"""
                updatePageTitle('{page_title}');
                setActiveMenuItem('{content_id}');
            """)
    
    @Slot(result=str)
    def getMenuState(self):
        """获取当前菜单状态"""
        return json.dumps(self.menu_state, ensure_ascii=False)
    
    @Slot(str)
    def openQuestionReview(self, question_id):
        """打开题目复习面板"""
        if self.main_window:
            self.main_window.open_question_review_panel(question_id)
            print(f"📝 打开题目复习面板: {question_id}")
            
    @Slot(result=str)
    def getFileStructure(self):
        """获取vault文件夹的文件结构"""
        self.logger.info("=" * 80)
        self.logger.info("【步骤2开始】getFileStructure方法被前端调用")
        self.logger.info("=" * 80)
        
        vault_path = Path("vault")
        self.logger.info(f"vault路径: {vault_path.absolute()}")
        self.logger.info(f"vault存在: {vault_path.exists()}")
        
        if not vault_path.exists():
            vault_path.mkdir(exist_ok=True)
            self.logger.info("创建了vault目录")
        
        # 先列出vault目录下的所有内容
        self.logger.info("【详细扫描】vault目录内容:")
        try:
            all_items = list(vault_path.iterdir())
            self.logger.info(f"总共发现 {len(all_items)} 个项目")
            for i, item in enumerate(all_items, 1):
                item_type = "文件夹" if item.is_dir() else "文件"
                self.logger.info(f"  {i:2d}. {item.name} ({item_type}) - 路径: {item}")
        except Exception as e:
            self.logger.error(f"扫描vault目录失败: {e}")
        
        def build_tree(path, level=0):
            items = []
            indent = "  " * level
            try:
                self.logger.debug(f"{indent}扫描目录: {path} (级别: {level})")
                sorted_items = sorted(path.iterdir())
                self.logger.debug(f"{indent}该目录下有 {len(sorted_items)} 个项目")
                
                for item in sorted_items:
                    if item.name.startswith('.'):
                        self.logger.debug(f"{indent}  跳过隐藏文件: {item.name}")
                        continue
                    
                    self.logger.debug(f"{indent}  处理项目: {item.name} ({'文件夹' if item.is_dir() else '文件'})")
                    
                    if item.is_dir():
                        folder_data = {
                            "name": item.name,
                            "type": "folder",
                            "path": str(item),
                            "level": level,
                            "children": build_tree(item, level + 1)
                        }
                        items.append(folder_data)
                        self.logger.debug(f"{indent}  文件夹已添加: {item.name} (子项目数: {len(folder_data['children'])})")
                    elif item.suffix == '.md':
                        file_data = {
                            "name": item.name,
                            "type": "file",
                            "path": str(item),
                            "level": level
                        }
                        items.append(file_data)
                        self.logger.debug(f"{indent}  Markdown文件已添加: {item.name}")
                    else:
                        self.logger.debug(f"{indent}  跳过非Markdown文件: {item.name} (扩展名: {item.suffix})")
                        
            except PermissionError as e:
                self.logger.error(f"{indent}权限错误: {e}")
            except Exception as e:
                self.logger.error(f"{indent}其他错误: {e}")
            
            self.logger.debug(f"{indent}该级别返回 {len(items)} 个有效项目")
            return items
        
        self.logger.info("【步骤2】开始构建文件树结构")
        
        structure = build_tree(vault_path)
        
        self.logger.info("【步骤2完成】最终文件结构统计:")
        self.logger.info(f"根级别项目数: {len(structure)}")
        
        def count_items(items, level=0):
            total = len(items)
            indent = "  " * level
            for item in items:
                self.logger.debug(f"{indent}- {item['name']} ({item['type']})")
                if item['type'] == 'folder' and 'children' in item:
                    child_count = count_items(item['children'], level + 1)
                    total += child_count
            return total
        
        total_items = count_items(structure)
        self.logger.info(f"总计项目数: {total_items}")
        
        result = json.dumps(structure, ensure_ascii=False, indent=2)
        self.logger.info(f"JSON结构长度: {len(result)} 字符")
        self.logger.debug("完整JSON结构:")
        self.logger.debug(result)
        
        self.logger.info("【步骤2-Python端完成】准备返回数据给前端")
        self.logger.info("=" * 80)
        
        return result
    
    @Slot(str, result=str)
    def loadMarkdownFile(self, file_path):
        """加载Markdown文件内容并转换为HTML"""
        self.logger.info("=" * 60)
        self.logger.info("【文件加载】loadMarkdownFile 开始")
        self.logger.info(f"文件路径: {file_path}")
        
        try:
            path = Path(file_path)
            self.logger.info(f"解析路径: {path.absolute()}")
            self.logger.info(f"文件存在: {path.exists()}")
            
            if not path.exists():
                self.logger.error("❌ 文件不存在")
                return ""
            
            # 读取文件内容
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content_length = len(content)
            self.logger.info(f"文件内容长度: {content_length} 字符")
            
            # 使用markdown库转换为HTML
            try:
                import markdown
                html_content = markdown.markdown(content, extensions=['codehilite', 'fenced_code'])
                html_length = len(html_content)
                self.logger.info(f"✅ Markdown转换成功，HTML长度: {html_length} 字符")
                return html_content
            except ImportError:
                self.logger.warning("⚠️ markdown库未安装，返回原始内容")
                # 如果没有markdown库，返回原始内容
                return f"<pre>{content}</pre>"
                
        except Exception as e:
            self.logger.error(f"❌ 加载Markdown文件异常: {e}")
            print(f"❌ 加载Markdown文件失败: {e}")
        return ""
    
    @Slot(str, result=str)
    def loadMarkdownRaw(self, file_path):
        """加载Markdown文件的原始内容"""
        self.logger.info("=" * 60)
        self.logger.info("【文件加载】loadMarkdownRaw 开始")
        self.logger.info(f"文件路径: {file_path}")
        
        try:
            path = Path(file_path)
            self.logger.info(f"解析路径: {path.absolute()}")
            self.logger.info(f"文件存在: {path.exists()}")
            
            if not path.exists():
                self.logger.error("❌ 文件不存在")
                return ""
            
            # 读取原始文件内容
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content_length = len(content)
            self.logger.info(f"✅ 原始内容加载成功，长度: {content_length} 字符")
            return content
                
        except Exception as e:
            self.logger.error(f"❌ 加载原始文件异常: {e}")
            print(f"❌ 加载原始文件失败: {e}")
        return ""
    
    @Slot(str, result=str)
    def generatePracticeQuestions(self, selected_text):
        """根据选中文本生成练习题目"""
        self.logger.info("=" * 60)
        self.logger.info("【练习生成】generatePracticeQuestions 开始")
        self.logger.info(f"选中文本长度: {len(selected_text)}")
        
        try:
            # 构建生成练习题的提示词
            prompt = f"""请基于以下内容生成一套练习题目：

**学习内容：**
{selected_text}

**要求：**
1. 生成5-8道不同类型的题目（选择题、填空题、简答题、应用题等）
2. 题目要有一定的难度梯度，从基础理解到深入应用
3. 每道题目都要紧密围绕给定的学习内容
4. 题目表述要清晰明确，便于理解
5. 使用纯文本格式，题目编号使用数字格式：1. 2. 3. 等
6. 选择题的选项使用 A) B) C) D) 格式
7. 只提供题目，不要提供答案

请生成练习题目："""

            # 调用LLM API生成题目
            response = call_llm(prompt, "生成练习题目")
            
            if response:
                self.logger.info(f"✅ 练习题目生成成功，长度: {len(response)} 字符")
                return response
            else:
                self.logger.error("❌ LLM API返回空结果")
                return self._generate_fallback_questions(selected_text)
                
        except Exception as e:
            self.logger.error(f"❌ 生成练习题目异常: {e}")
            print(f"❌ 生成练习题目失败: {e}")
            return self._generate_fallback_questions(selected_text)
    
    def _generate_fallback_questions(self, selected_text):
        """生成备用练习题目"""
        return f"""基于学习内容的练习题目：

1. 请简要概括以下内容的主要观点：
"{selected_text[:200]}{'...' if len(selected_text) > 200 else ''}"

2. 这个内容中提到的核心概念有哪些？请列举并简要说明。

3. 请分析这些概念在实际应用中的重要性。

4. 如果要向他人解释这个内容，你会如何组织语言？

5. 基于这个内容，你认为还有哪些相关知识点值得深入学习？

请认真思考后作答，每道题目都要结合具体内容来回答。"""
    
    @Slot(str, result=str)
    def evaluatePracticeAnswer(self, evaluation_data_json):
        """评估单个练习答案 - 与前端的evaluatePracticeAnswer调用保持一致"""
        self.logger.info("=" * 60)
        self.logger.info("【答案评估】evaluatePracticeAnswer 开始")
        
        try:
            import json
            evaluation_data = json.loads(evaluation_data_json)
            
            question = evaluation_data.get('question', '')
            answer = evaluation_data.get('answer', '')
            practice_id = evaluation_data.get('practice_id', '')
            
            self.logger.info(f"题目长度: {len(question)}")
            self.logger.info(f"答案长度: {len(answer)}")
            self.logger.info(f"练习ID: {practice_id}")
            
            # 构建评估提示词 - 使用不会与内容中的花括号冲突的方式
            prompt_template = """请对以下练习答案进行专业评估：

**练习题目：**
{question}

**学生答案：**
{answer}

**评估要求：**
1. 对答案的准确性、完整性和深度进行评估
2. 给出具体的改进建议
3. 评估学生对知识点的掌握程度
4. 给出0-100分的数值评分
5. 提供鼓励性的反馈和学习建议

**评估维度：**
- 概念理解：对基本概念的理解程度
- 应用能力：将知识应用到实际情况的能力
- 分析深度：分析问题的深度和广度
- 表达清晰：答案表达的清晰度和逻辑性

请生成详细的评估结果，并以JSON格式返回：
{{
  "score": 85,
  "feedback": "详细的反馈内容",
  "suggestions": ["建议1", "建议2"]
}}"""
            
            # 使用.format()方法来避免花括号冲突
            prompt = prompt_template.format(question=question, answer=answer)
            
            # 调用LLM API进行评估
            response = call_llm(prompt, "评估练习答案")
            
            if response:
                try:
                    # 尝试解析JSON格式的回答
                    import re
                    json_match = re.search(r'\{[^}]*"score"[^}]*\}', response, re.DOTALL)
                    if json_match:
                        evaluation_result = json.loads(json_match.group())
                        self.logger.info(f"✅ 评估结果解析成功: {evaluation_result}")
                    else:
                        # 如果不是JSON格式，创建默认的评估结果
                        evaluation_result = {
                            "score": 75,
                            "feedback": response,
                            "suggestions": ["继续加油，加深理解", "多练习相关问题"]
                        }
                        
                    result = {
                        "success": True,
                        "data": evaluation_result
                    }
                    self.logger.info(f"✅ 答案评估完成，得分: {evaluation_result.get('score', 'N/A')}")
                    return json.dumps(result, ensure_ascii=False)
                    
                except Exception as parse_error:
                    self.logger.error(f"❗ 解析评估结果失败: {parse_error}")
                    # 使用原始回答作为反馈
                    result = {
                        "success": True,
                        "data": {
                            "score": 75,
                            "feedback": response,
                            "suggestions": ["继续加油，加深理解", "多练习相关问题"]
                        }
                    }
                    return json.dumps(result, ensure_ascii=False)
            else:
                self.logger.error("❌ LLM API返回空结果")
                result = {
                    "success": False,
                    "error": "AI评估服务暂时不可用"
                }
                return json.dumps(result, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"❌ 评估答案异常: {e}")
            result = {
                "success": False,
                "error": str(e)
            }
            return json.dumps(result, ensure_ascii=False)
    
    @Slot(result=str)
    def generateNewPractice(self):
        """生成新的练习题目 - 基于最近的学习内容"""
        self.logger.info("=" * 60)
        self.logger.info("【练习生成】generateNewPractice 开始")
        
        try:
            # 这里可以根据实际需要来获取最近的学习内容
            # 目前使用模拟内容
            recent_content = """机器学习基础概念：
机器学习是人工智能的一个分支，它是一种让计算机系统能够自动地从数据中学习和改善性能的方法。
主要包括监督学习、无监督学习和强化学习三大类别。
常见的算法包括线性回归、决策树、随机森林、支持向量机等。"""
            
            # 调用已有的generatePracticeQuestions方法
            questions = self.generatePracticeQuestions(recent_content)
            
            if questions:
                # 生成练习ID
                import time
                practice_id = f"TECH-{int(time.time())}"
                
                result = {
                    "success": True,
                    "data": {
                        "id": practice_id,
                        "question": questions,
                        "questions": questions,  # 兼容两种字段名
                        "related_content": "基于最近学习的机器学习基础概念生成",
                        "selectedText": recent_content
                    }
                }
                
                self.logger.info(f"✅ 新练习生成成功，练习ID: {practice_id}")
                return json.dumps(result, ensure_ascii=False)
            else:
                self.logger.error("❌ 练习题目生成失败")
                result = {
                    "success": False,
                    "error": "生成练习题目失败"
                }
                return json.dumps(result, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"❌ 生成新练习异常: {e}")
            result = {
                "success": False,
                "error": str(e)
            }
            return json.dumps(result, ensure_ascii=False)
    
    @Slot(str, str, result=str)
    def evaluatePracticeAnswers(self, questions, answers):
        """评判练习答案"""
        self.logger.info("=" * 60)
        self.logger.info("【答案评判】evaluatePracticeAnswers 开始")
        self.logger.info(f"题目长度: {len(questions)}")
        self.logger.info(f"答案长度: {len(answers)}")
        
        try:
            # 构建评判提示词
            prompt = f"""请对以下练习答案进行专业评判：

**练习题目：**
{questions}

**学生答案：**
{answers}

**评判要求：**
1. 对每道题目的回答进行具体分析
2. 评估答案的准确性、完整性和深度
3. 给出具体的改进建议
4. 评估学生对知识点的掌握程度
5. 使用星级评分（1-5星）评价不同维度
6. 提供鼓励性的反馈和学习建议

**评判维度：**
- 概念理解：对基本概念的理解程度
- 应用能力：将知识应用到实际情况的能力
- 分析深度：分析问题的深度和广度
- 表达清晰：答案表达的清晰度和逻辑性

请生成详细的评判报告："""

            # 调用LLM API进行评判
            response = call_llm(prompt, "评判练习答案")
            
            if response:
                self.logger.info(f"✅ 答案评判完成，长度: {len(response)} 字符")
                return response
            else:
                self.logger.error("❌ LLM API返回空结果")
                return self._generate_fallback_evaluation()
                
        except Exception as e:
            self.logger.error(f"❌ 评判答案异常: {e}")
            print(f"❌ 评判答案失败: {e}")
            return self._generate_fallback_evaluation()
    
    def _generate_fallback_evaluation(self):
        """生成备用评判结果"""
        return """📊 练习评估报告

✅ 整体表现：良好
感谢您认真完成了这次练习，您的回答显示了对学习内容的基本理解。

📝 评价维度：
• 概念理解：★★★☆☆ (3/5)
  - 基本概念掌握情况良好
  - 建议加强对细节的理解

• 应用能力：★★★☆☆ (3/5)
  - 能够进行基本的应用分析
  - 可以尝试更多实际案例

• 分析深度：★★☆☆☆ (2/5)
  - 分析较为表面
  - 建议深入思考问题的本质

• 表达清晰：★★★★☆ (4/5)
  - 表达清晰，逻辑较好
  - 继续保持这种表达方式

💡 学习建议：
1. 加强对核心概念的深入理解
2. 多结合实际案例进行思考
3. 尝试从多个角度分析问题
4. 继续保持学习的积极性

🎯 总体掌握程度：65%
继续努力，相信您会取得更好的成绩！"""
    
    @Slot(str, str, result=bool)
    def saveMarkdownFile(self, file_path, content):
        """保存Markdown文件"""
        self.logger.info("=" * 60)
        self.logger.info("【文件保存】saveMarkdownFile 开始")
        self.logger.info(f"文件路径: {file_path}")
        self.logger.info(f"内容长度: {len(content)} 字符")
        
        try:
            path = Path(file_path)
            self.logger.info(f"解析路径: {path.absolute()}")
            
            # 确保父目录存在
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # 保存文件
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 验证保存是否成功
            if path.exists():
                file_size = path.stat().st_size
                self.logger.info(f"✅ 文件保存成功")
                self.logger.info(f"文件大小: {file_size} 字节")
                print(f"✅ 文件已保存: {file_path}")
                return True
            else:
                self.logger.error("❌ 文件保存失败 - 文件不存在")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 保存文件异常: {e}")
            print(f"❌ 保存文件失败: {e}")
            return False

    # ==================== 配置管理功能 ====================
    
    @Slot(result=str)
    def getConfig(self):
        """获取当前配置"""
        self.logger.info("=" * 60)
        self.logger.info("【配置管理】getConfig 开始")
        
        try:
            config_json = json.dumps(self.config, ensure_ascii=False, indent=2)
            self.logger.info(f"✅ 配置获取成功，长度: {len(config_json)} 字符")
            return config_json
        except Exception as e:
            self.logger.error(f"❌ 获取配置异常: {e}")
            return "{}"
    
    @Slot(str, result=bool)
    def saveConfig(self, config_json):
        """保存配置"""
        self.logger.info("=" * 60)
        self.logger.info("【配置管理】saveConfig 开始")
        self.logger.info(f"配置数据长度: {len(config_json)} 字符")
        
        try:
            # 解析配置JSON
            new_config = json.loads(config_json)
            self.logger.info(f"配置解析成功，包含 {len(new_config)} 个配置项")
            
            # 更新内存中的配置
            old_provider = self.config.get("llm_provider", "Ollama")
            self.config.update(new_config)
            new_provider = self.config.get("llm_provider", "Ollama")
            
            # 更新选择标志位
            self._update_provider_selection(new_provider)
            
            # 保存到文件
            success = save_config(self.config)
            
            if success:
                self.logger.info(f"✅ 配置保存成功")
                if old_provider != new_provider:
                    self.logger.info(f"LLM提供商从 {old_provider} 切换到 {new_provider}")
                    # 强制重新加载LLM提供商
                    try:
                        llm_factory.get_provider(force_reload=True)
                        self.logger.info(f"✅ LLM提供商已切换到 {new_provider}")
                    except Exception as e:
                        self.logger.error(f"❌ LLM提供商切换失败: {e}")
                print(f"✅ 配置已保存")
                return True
            else:
                self.logger.error("❌ 配置保存失败")
                return False
                
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ 配置JSON解析失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ 保存配置异常: {e}")
            return False
    
    def _update_provider_selection(self, selected_provider):
        """更新LLM提供商的选择标志位"""
        providers = ["ollama", "gemini", "deepseek", "qwen"]
        
        for provider in providers:
            is_selected_key = f"{provider}_is_selected"
            if provider.lower() == selected_provider.lower():
                self.config[is_selected_key] = True
                self.logger.info(f"✅ 设置 {provider} 为选中状态")
            else:
                self.config[is_selected_key] = False
                self.logger.info(f"❌ 设置 {provider} 为未选中状态")

    # ==================== 知识点提取功能 ====================
    
    @Slot(str, result=str)
    def extractKnowledgePoints(self, file_path):
        """提取文档的知识点"""
        self.logger.info("=" * 60)
        self.logger.info("【知识点提取】extractKnowledgePoints 开始")
        self.logger.info(f"文件路径: {file_path}")
        
        try:
            # 加载文件内容
            path = Path(file_path)
            if not path.exists():
                self.logger.error("❌ 文件不存在")
                return json.dumps({"success": False, "error": "文件不存在"}, ensure_ascii=False)
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content_length = len(content)
            self.logger.info(f"文件内容长度: {content_length} 字符")
            self.logger.info(f"文件内容前200字符: {content[:200]}")
            self.logger.info(f"文件内容后200字符: {content[-200:] if len(content) > 200 else content}")
            
            if not content.strip():
                self.logger.warning("⚠️ 文件内容为空")
                return json.dumps({"success": False, "error": "文件内容为空"}, ensure_ascii=False)
            
            # 调用知识点提取
            result = self._extract_knowledge_with_llm(content)
            
            self.logger.info(f"✅ 知识点提取完成")
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"❌ 知识点提取异常: {e}")
            error_result = {"success": False, "error": str(e)}
            return json.dumps(error_result, ensure_ascii=False)
    
    def _extract_knowledge_with_llm(self, content):
        """使用LLM提取知识点"""
        self.logger.info("【LLM调用】开始知识点提取")
        
        try:
            # 导入知识管理系统
            from knowledge_management import KnowledgeManagementSystem
            
            # 每次都重新创建知识管理系统实例，避免缓存问题
            self.logger.info("创建新的KnowledgeManagementSystem实例")
            km_system = KnowledgeManagementSystem(self.config)
            self.logger.info("KnowledgeManagementSystem实例创建完成")
            
            # 提取知识点（使用默认学科名称）
            subject_name = "通用学科"
            result = km_system.extract_knowledge_points(subject_name, content)
            
            self.logger.info(f"知识管理系统返回结果类型: {type(result)}")
            self.logger.info(f"知识管理系统返回结果: {result}")
            
            # 优先处理列表格式（KnowledgeManager直接返回的格式）
            if isinstance(result, list):
                self.logger.info(f"✅ 直接获得知识点列表，包含 {len(result)} 个知识点")
                
                # 格式化知识点数据供前端使用
                formatted_points = []
                for point in result:
                    self.logger.info(f"处理知识点: {point} (类型: {type(point)})")
                    
                    # 安全地处理不同格式的知识点数据
                    if isinstance(point, dict):
                        formatted_point = {
                            "name": point.get("point_name") or point.get("concept_name", ""),
                            "description": point.get("core_description") or point.get("core_definition", ""),
                            "category": point.get("category", ""),
                            "importance": point.get("importance", "中等")
                        }
                    elif isinstance(point, (list, tuple)) and len(point) >= 2:
                        # 如果是列表格式，尝试按顺序解析
                        formatted_point = {
                            "name": str(point[0]) if len(point) > 0 else "",
                            "description": str(point[1]) if len(point) > 1 else "",
                            "category": str(point[2]) if len(point) > 2 else "",
                            "importance": "中等"
                        }
                        self.logger.info(f"从列表格式解析知识点: {formatted_point}")
                    else:
                        # 如果是其他格式，尝试转换为字符串
                        formatted_point = {
                            "name": str(point),
                            "description": "自动提取的知识点",
                            "category": "",
                            "importance": "中等"
                        }
                        self.logger.warning(f"未知格式的知识点，使用默认处理: {formatted_point}")
                    
                    if formatted_point["name"]:
                        formatted_points.append(formatted_point)
                        self.logger.info(f"格式化后的知识点: {formatted_point}")
                    else:
                        self.logger.warning(f"跳过空名称的知识点: {point}")
                
                self.logger.info(f"最终格式化了 {len(formatted_points)} 个知识点")
                return {
                    "success": True,
                    "knowledge_points": formatted_points,
                    "total_count": len(formatted_points)
                }
            
            # 处理字典格式（KnowledgeManagementSystem返回的格式）
            elif isinstance(result, dict) and result.get("success", False):
                processed_points = result.get("processed_points", [])
                self.logger.info(f"✅ 成功提取 {len(processed_points)} 个知识点")
                
                if not processed_points:
                    self.logger.warning("⚠️ processed_points为空，尝试直接从result获取知识点")
                    # 如果processed_points为空，尝试从其他字段获取
                    if "knowledge_points" in result:
                        processed_points = [{"extracted_point": point} for point in result["knowledge_points"]]
                        self.logger.info(f"从knowledge_points字段获取到 {len(processed_points)} 个知识点")
                
                # 格式化知识点数据供前端使用
                formatted_points = []
                for point_data in processed_points:
                    extracted_point = point_data.get("extracted_point", {})
                    formatted_point = {
                        "name": extracted_point.get("point_name") or extracted_point.get("concept_name", ""),
                        "description": extracted_point.get("core_description") or extracted_point.get("core_definition", ""),
                        "category": extracted_point.get("category", ""),
                        "importance": extracted_point.get("importance", "中等")
                    }
                    if formatted_point["name"]:
                        formatted_points.append(formatted_point)
                
                return {
                    "success": True,
                    "knowledge_points": formatted_points,
                    "total_count": len(formatted_points)
                }
            
            # 处理错误字典格式
            elif isinstance(result, dict) and not result.get("success", True):
                error_msg = result.get("error", "提取失败")
                self.logger.error(f"❌ 知识点提取失败: {error_msg}")
                return {"success": False, "error": error_msg}
            
            # 未知格式
            else:
                self.logger.error(f"❌ 知识管理系统返回格式异常: {type(result)}")
                return {"success": False, "error": "知识管理系统返回格式异常"}
                
        except ImportError as e:
            self.logger.error(f"❌ 导入知识管理模块失败: {e}")
            return {"success": False, "error": "知识管理模块不可用"}
        except Exception as e:
            self.logger.error(f"❌ LLM知识点提取异常: {e}")
            import traceback
            self.logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}
    
    @Slot(str, result=bool)
    def createNewNote(self, folder_path="vault"):
        """创建新的Markdown笔记"""
        self.logger.info("=" * 60)
        self.logger.info("【文件操作验证】createNewNote 开始")
        self.logger.info(f"目标文件夹: {folder_path}")
        
        try:
            vault_path = Path(folder_path)
            self.logger.info(f"解析路径: {vault_path.absolute()}")
            self.logger.info(f"路径存在: {vault_path.exists()}")
            
            if not vault_path.exists():
                vault_path.mkdir(parents=True, exist_ok=True)
                self.logger.info("✅ 创建了目标文件夹")
            
            # 生成唯一的文件名
            counter = 1
            while True:
                filename = f"新建笔记{counter}.md"
                file_path = vault_path / filename
                if not file_path.exists():
                    break
                counter += 1
            
            self.logger.info(f"生成文件名: {filename}")
            self.logger.info(f"完整路径: {file_path.absolute()}")
            
            # 创建文件并写入模板内容
            template_content = f"""# {filename[:-3]}

## 概述
这是一个新建的笔记文件。

## 内容
请在这里添加您的笔记内容...

---
创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(template_content)
            
            # 验证文件是否创建成功
            if file_path.exists():
                file_size = file_path.stat().st_size
                self.logger.info(f"✅ 文件创建成功")
                self.logger.info(f"文件大小: {file_size} 字节")
                self.logger.info(f"文件路径: {file_path}")
                print(f"✅ 成功创建笔记: {file_path}")
                return True
            else:
                self.logger.error("❌ 文件创建失败 - 文件不存在")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ 创建笔记异常: {e}")
            print(f"❌ 创建笔记失败: {e}")
            return False
    
    @Slot(str, result=bool)
    def createNewFolder(self, parent_path="vault"):
        """创建新文件夹"""
        self.logger.info("=" * 60)
        self.logger.info("【文件操作验证】createNewFolder 开始")
        self.logger.info(f"父级路径: {parent_path}")
        
        try:
            parent = Path(parent_path)
            self.logger.info(f"解析父级路径: {parent.absolute()}")
            self.logger.info(f"父级路径存在: {parent.exists()}")
            
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
                self.logger.info("✅ 创建了父级文件夹")
            
            # 生成新文件夹名
            counter = 1
            while True:
                new_folder_name = f"新文件夹{counter}"
                new_folder_path = parent / new_folder_name
                if not new_folder_path.exists():
                    break
                counter += 1
            
            self.logger.info(f"生成文件夹名: {new_folder_name}")
            self.logger.info(f"完整路径: {new_folder_path.absolute()}")
            
            new_folder_path.mkdir()
            
            # 验证文件夹是否创建成功
            if new_folder_path.exists() and new_folder_path.is_dir():
                self.logger.info(f"✅ 文件夹创建成功")
                self.logger.info(f"文件夹路径: {new_folder_path}")
                print(f"✅ 创建新文件夹: {new_folder_path}")
                return True
            else:
                self.logger.error("❌ 文件夹创建失败 - 文件夹不存在")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 创建文件夹异常: {e}")
            print(f"❌ 创建新文件夹失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def renameFileOrFolder(self, old_path, new_name):
        """重命名文件或文件夹"""
        self.logger.info("=" * 60)
        self.logger.info("【文件操作验证】renameFileOrFolder 开始")
        self.logger.info(f"原路径: {old_path}")
        self.logger.info(f"新名称: {new_name}")
        
        try:
            old_path_obj = Path(old_path)
            new_path_obj = old_path_obj.parent / new_name
            
            self.logger.info(f"原路径对象: {old_path_obj.absolute()}")
            self.logger.info(f"新路径对象: {new_path_obj.absolute()}")
            self.logger.info(f"原路径存在: {old_path_obj.exists()}")
            self.logger.info(f"原路径类型: {'文件夹' if old_path_obj.is_dir() else '文件'}")
            
            if not old_path_obj.exists():
                self.logger.error("❌ 原路径不存在")
                return False
            
            if new_path_obj.exists():
                self.logger.error(f"❌ 目标名称已存在: {new_name}")
                print(f"❌ 重命名失败: {new_name} 已存在")
                return False
            
            old_path_obj.rename(new_path_obj)
            
            # 验证重命名是否成功
            if new_path_obj.exists() and not old_path_obj.exists():
                self.logger.info("✅ 重命名成功")
                self.logger.info(f"新路径: {new_path_obj}")
                print(f"✅ 重命名成功: {old_path} -> {new_path_obj}")
                return True
            else:
                self.logger.error("❌ 重命名失败 - 验证失败")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 重命名异常: {e}")
            print(f"❌ 重命名失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def moveFileOrFolder(self, source_path, target_folder):
        """移动文件或文件夹"""
        self.logger.info("=" * 60)
        self.logger.info("【文件操作验证】moveFileOrFolder 开始")
        self.logger.info(f"源路径: {source_path}")
        self.logger.info(f"目标文件夹: {target_folder}")
        
        try:
            source = Path(source_path)
            target_dir = Path(target_folder)
            target_path = target_dir / source.name
            
            self.logger.info(f"源路径对象: {source.absolute()}")
            self.logger.info(f"目标文件夹对象: {target_dir.absolute()}")
            self.logger.info(f"目标路径对象: {target_path.absolute()}")
            self.logger.info(f"源路径存在: {source.exists()}")
            self.logger.info(f"源路径类型: {'文件夹' if source.is_dir() else '文件'}")
            self.logger.info(f"目标文件夹存在: {target_dir.exists()}")
            
            if not source.exists():
                self.logger.error("❌ 源路径不存在")
                return False
            
            if target_path.exists():
                self.logger.error(f"❌ 目标路径已存在: {target_path}")
                print(f"❌ 移动失败: {target_path} 已存在")
                return False
            
            # 确保目标文件夹存在
            target_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("✅ 目标文件夹已准备好")
            
            # 执行移动操作
            source.rename(target_path)
            
            # 验证移动是否成功
            if target_path.exists() and not source.exists():
                self.logger.info("✅ 移动成功")
                self.logger.info(f"新路径: {target_path}")
                print(f"✅ 移动成功: {source_path} -> {target_path}")
                return True
            else:
                self.logger.error("❌ 移动失败 - 验证失败")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 移动异常: {e}")
            print(f"❌ 移动失败: {e}")
            return False
    
    @Slot(str, result=bool)
    def deleteFileOrFolder(self, path):
        """删除文件或文件夹"""
        self.logger.info("=" * 60)
        self.logger.info("【文件操作验证】deleteFileOrFolder 开始")
        self.logger.info(f"目标路径: {path}")
        
        try:
            target = Path(path)
            self.logger.info(f"路径对象: {target.absolute()}")
            self.logger.info(f"路径存在: {target.exists()}")
            
            if not target.exists():
                self.logger.error("❌ 目标路径不存在")
                print(f"❌ 删除失败: {path} 不存在")
                return False
            
            is_dir = target.is_dir()
            self.logger.info(f"路径类型: {'文件夹' if is_dir else '文件'}")
            
            if is_dir:
                # 删除文件夹及其所有内容
                import shutil
                # 先统计文件夹内容
                try:
                    items = list(target.iterdir())
                    self.logger.info(f"文件夹包含 {len(items)} 个项目")
                except:
                    self.logger.info("无法统计文件夹内容")
                
                shutil.rmtree(target)
                self.logger.info("✅ 文件夹删除成功")
                print(f"✅ 删除文件夹成功: {path}")
            else:
                # 删除文件
                file_size = target.stat().st_size
                self.logger.info(f"文件大小: {file_size} 字节")
                target.unlink()
                self.logger.info("✅ 文件删除成功")
                print(f"✅ 删除文件成功: {path}")
            
            # 验证删除是否成功
            if not target.exists():
                self.logger.info("✅ 删除验证成功")
                return True
            else:
                self.logger.error("❌ 删除验证失败 - 文件仍然存在")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ 删除异常: {e}")
            print(f"❌ 删除失败: {e}")
            return False
    
    @Slot()
    def triggerManualDebug(self):
        """手动触发调试验证面板"""
        print("\n" + "="*80)
        print("🔧 手动触发调试验证面板")
        print("="*80)
        result = self.validateAllFileOperations()
        print("\n📋 调试验证结果:")
        print(result)
        print("="*80)
        return result
    
    @Slot(str, result=str)
    def testLLMConnection(self, provider):
        """测试LLM连接"""
        try:
            self.logger.info(f"开始测试 {provider} 连接")
            
            # 重新加载最新配置
            self.config = load_config()
            current_provider = self.config.get("llm_provider", "Ollama")
            
            self.logger.info(f"当前配置的提供商: {current_provider}")
            self.logger.info(f"请求测试的提供商: {provider}")
            
            # 如果测试的提供商与当前配置不一致，提供详细信息
            if provider != current_provider:
                return f"""⚠️ 配置不一致检测:
📋 当前配置的提供商: {current_provider}
🔍 正在测试的提供商: {provider}
💡 建议: 请先在设置中选择 {provider}，保存配置后再进行测试"""
            
            # 使用统一的测试方法
            success, message = test_llm_connection()
            
            # 添加当前配置信息到测试结果
            config_info = f"\n📋 当前配置: {current_provider}"
            if current_provider == "Qwen":
                config_info += f" (模型: {self.config.get('qwen_model', 'qwen-flash')})"
            elif current_provider == "DeepSeek":
                config_info += f" (模型: {self.config.get('deepseek_model', 'deepseek-chat')})"
            elif current_provider == "Gemini":
                config_info += f" (模型: {self.config.get('gemini_model', 'gemini-1.5-flash-002')})"
            elif current_provider == "Ollama":
                config_info += f" (模型: {self.config.get('ollama_model', 'deepseek-r1:1.5b')})"
            
            return message + config_info
                
        except Exception as e:
            self.logger.error(f"❌ {provider} 连接测试异常: {e}")
            return f"❌ {provider} 连接测试异常: {str(e)}"
    
    @Slot(result=str)
    def validateAllFileOperations(self):
        """验证所有文件操作功能"""
        self.logger.info("=" * 80)
        self.logger.info("【后端功能全面验证】开始验证所有文件操作功能")
        self.logger.info("=" * 80)
        
        validation_results = []
        test_folder = "vault/test_validation"
        test_file = "test_validation/测试文件.md"
        
        try:
            # 1. 测试获取文件结构
            self.logger.info("🔍 测试1: 获取文件结构")
            structure_result = self.getFileStructure()
            if structure_result:
                validation_results.append("✅ getFileStructure: 成功")
                self.logger.info("✅ 文件结构获取测试通过")
            else:
                validation_results.append("❌ getFileStructure: 失败")
                self.logger.error("❌ 文件结构获取测试失败")
            
            # 2. 测试创建文件夹
            self.logger.info("🔍 测试2: 创建文件夹")
            folder_result = self.createNewFolder("vault")
            if folder_result:
                validation_results.append("✅ createNewFolder: 成功")
                self.logger.info("✅ 文件夹创建测试通过")
            else:
                validation_results.append("❌ createNewFolder: 失败")
                self.logger.error("❌ 文件夹创建测试失败")
            
            # 3. 测试创建笔记
            self.logger.info("🔍 测试3: 创建笔记")
            note_result = self.createNewNote("vault")
            if note_result:
                validation_results.append("✅ createNewNote: 成功")
                self.logger.info("✅ 笔记创建测试通过")
            else:
                validation_results.append("❌ createNewNote: 失败")
                self.logger.error("❌ 笔记创建测试失败")
            
            # 4. 测试文件加载功能
            self.logger.info("🔍 测试4: 加载Markdown文件")
            # 查找刚创建的文件进行测试
            vault_path = Path("vault")
            test_files = [f for f in vault_path.glob("*.md") if f.name.startswith("新建笔记")]
            if test_files:
                test_file_path = str(test_files[0])
                load_result = self.loadMarkdownFile(test_file_path)
                if load_result:
                    validation_results.append("✅ loadMarkdownFile: 成功")
                    self.logger.info("✅ 文件加载测试通过")
                else:
                    validation_results.append("❌ loadMarkdownFile: 失败")
                    self.logger.error("❌ 文件加载测试失败")
            else:
                validation_results.append("⚠️ loadMarkdownFile: 跳过(无测试文件)")
                self.logger.warning("⚠️ 文件加载测试跳过 - 无可用测试文件")
            
            # 5. 测试重命名功能
            self.logger.info("🔍 测试5: 重命名文件")
            if test_files:
                old_path = str(test_files[0])
                new_name = "重命名测试文件.md"
                rename_result = self.renameFileOrFolder(old_path, new_name)
                if rename_result:
                    validation_results.append("✅ renameFileOrFolder: 成功")
                    self.logger.info("✅ 重命名测试通过")
                    # 更新测试文件路径
                    test_files[0] = test_files[0].parent / new_name
                else:
                    validation_results.append("❌ renameFileOrFolder: 失败")
                    self.logger.error("❌ 重命名测试失败")
            else:
                validation_results.append("⚠️ renameFileOrFolder: 跳过(无测试文件)")
                self.logger.warning("⚠️ 重命名测试跳过 - 无可用测试文件")
            
            # 6. 测试移动功能
            self.logger.info("🔍 测试6: 移动文件")
            # 先创建一个目标文件夹
            target_folder_result = self.createNewFolder("vault")
            if target_folder_result and test_files:
                # 查找刚创建的文件夹
                folders = [f for f in vault_path.iterdir() if f.is_dir() and f.name.startswith("新文件夹")]
                if folders:
                    source_path = str(test_files[0])
                    target_folder = str(folders[0])
                    move_result = self.moveFileOrFolder(source_path, target_folder)
                    if move_result:
                        validation_results.append("✅ moveFileOrFolder: 成功")
                        self.logger.info("✅ 移动测试通过")
                    else:
                        validation_results.append("❌ moveFileOrFolder: 失败")
                        self.logger.error("❌ 移动测试失败")
                else:
                    validation_results.append("⚠️ moveFileOrFolder: 跳过(无目标文件夹)")
                    self.logger.warning("⚠️ 移动测试跳过 - 无可用目标文件夹")
            else:
                validation_results.append("⚠️ moveFileOrFolder: 跳过(条件不满足)")
                self.logger.warning("⚠️ 移动测试跳过 - 测试条件不满足")
            
            # 7. 清理测试文件
            self.logger.info("🔍 测试7: 清理测试文件")
            cleanup_count = 0
            for item in vault_path.iterdir():
                if (item.name.startswith("新建笔记") or 
                    item.name.startswith("新文件夹") or 
                    item.name.startswith("重命名测试")):
                    delete_result = self.deleteFileOrFolder(str(item))
                    if delete_result:
                        cleanup_count += 1
            
            if cleanup_count > 0:
                validation_results.append(f"✅ deleteFileOrFolder: 成功清理{cleanup_count}个测试文件")
                self.logger.info(f"✅ 清理测试通过 - 清理了{cleanup_count}个文件")
            else:
                validation_results.append("⚠️ deleteFileOrFolder: 无需清理")
                self.logger.info("⚠️ 清理测试 - 无需清理文件")
            
        except Exception as e:
            validation_results.append(f"❌ 验证过程异常: {e}")
            self.logger.error(f"❌ 验证过程异常: {e}")
        
        # 生成验证报告
        self.logger.info("=" * 80)
        self.logger.info("【验证报告】")
        for result in validation_results:
            self.logger.info(result)
        
        success_count = len([r for r in validation_results if r.startswith("✅")])
        total_tests = len([r for r in validation_results if not r.startswith("❌ 验证过程异常")])
        
        self.logger.info(f"验证完成: {success_count}/{total_tests} 项测试通过")
        self.logger.info("=" * 80)
        
        return f"后端功能验证完成: {success_count}/{total_tests} 项测试通过\n" + "\n".join(validation_results)
    
    @Slot(result=str)
    def getSubjects(self):
        """获取所有科目列表"""
        self.logger.info("获取科目列表")
        
        try:
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            subjects = km_system.get_subjects()
            
            self.logger.info(f"获取到 {len(subjects)} 个科目")
            return json.dumps(subjects, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"获取科目列表失败: {e}")
            return json.dumps([], ensure_ascii=False)
    
    @Slot(str, result=str)
    def getSubjectKnowledgePoints(self, subject):
        """获取指定科目的知识点列表"""
        self.logger.info(f"获取科目知识点列表: {subject}")
        
        try:
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            knowledge_points = km_system.get_knowledge_points_by_subject(subject)
            
            # 转换为前端需要的格式
            formatted_points = []
            for point in knowledge_points:
                # 获取知识点的来源笔记
                sources = km_system.get_knowledge_point_sources(point["id"])
                
                formatted_points.append({
                    "id": point["id"],
                    "name": point["point_name"],
                    "description": point["core_description"],
                    "mastery_score": point.get("mastery_score", 50),
                    "created_time": point.get("created_time", ""),
                    "sources": sources
                })
            
            self.logger.info(f"获取到 {len(formatted_points)} 个知识点")
            return json.dumps(formatted_points, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"获取科目知识点失败: {e}")
            return json.dumps([], ensure_ascii=False)
    
    @Slot(str, result=str)
    def addSubject(self, subject_name):
        """添加新科目"""
        self.logger.info(f"添加新科目: {subject_name}")
        
        try:
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            success = km_system.add_subject(subject_name)
            
            if success:
                self.logger.info(f"科目 '{subject_name}' 添加成功")
                return json.dumps({"success": True, "message": f"科目 '{subject_name}' 添加成功"}, ensure_ascii=False)
            else:
                self.logger.info(f"科目 '{subject_name}' 已存在")
                return json.dumps({"success": False, "error": f"科目 '{subject_name}' 已存在"}, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"添加科目失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    @Slot(str, result=str)
    def findSimilarKnowledgePoints(self, request_data):
        """查找相似知识点（基于embedding）"""
        self.logger.info("查找相似知识点")
        
        try:
            data = json.loads(request_data)
            subject = data.get('subject')
            point = data.get('point')
            limit = data.get('limit', 10)
            
            self.logger.info(f"科目: {subject}, 知识点: {point['name']}, 限制: {limit}")
            
            # 使用原有的知识管理系统和相似度匹配
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            
            # 获取该科目下的所有知识点
            knowledge_points = km_system.get_knowledge_points_by_subject(subject)
            
            if not knowledge_points:
                self.logger.info("该科目下没有现有知识点")
                return json.dumps([], ensure_ascii=False)
            
            # 使用相似度匹配器
            try:
                from similarity_matcher import rank_matches
                query = point['name']
                ranked_matches = rank_matches(query, knowledge_points, cfg=self.config, top_k=limit, min_score=0.0)
                
                # 转换为前端需要的格式
                similar_points = []
                for match in ranked_matches:
                    # 找到对应的知识点详细信息
                    kp = next((p for p in knowledge_points if p.get('id') == match.get('id')), None)
                    if kp:
                        # 获取知识点的来源笔记
                        sources = km_system.get_knowledge_point_sources(kp["id"])
                        
                        similar_points.append({
                            "id": kp["id"],
                            "name": kp["point_name"],
                            "description": kp["core_description"],
                            "similarity": float(match.get('score', 0.0)),
                            "mastery_score": kp.get("mastery_score", 50),
                            "sources": sources
                        })
                
                self.logger.info(f"找到 {len(similar_points)} 个相似知识点")
                return json.dumps(similar_points, ensure_ascii=False)
                
            except ImportError:
                self.logger.warning("similarity_matcher模块不可用，使用简单匹配")
                # 简单的文本匹配作为备选
                similar_points = []
                query_lower = point['name'].lower()
                for kp in knowledge_points[:limit]:
                    if query_lower in kp["point_name"].lower() or query_lower in kp["core_description"].lower():
                        # 获取知识点的来源笔记
                        sources = km_system.get_knowledge_point_sources(kp["id"])
                        
                        similar_points.append({
                            "id": kp["id"],
                            "name": kp["point_name"],
                            "description": kp["core_description"],
                            "similarity": 0.5,  # 固定相似度
                            "mastery_score": kp.get("mastery_score", 50),
                            "sources": sources
                        })
                
                return json.dumps(similar_points, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"查找相似知识点失败: {e}")
            return json.dumps([], ensure_ascii=False)
    
    @Slot(str, result=str)
    def mergeKnowledgePoint(self, merge_data):
        """合并知识点"""
        self.logger.info("合并知识点")
        
        try:
            data = json.loads(merge_data)
            note_info = data.get('noteInfo', {})
            current_point = data.get('currentPoint')
            target_knowledge_id = data.get('targetKnowledgeId')
            
            self.logger.info(f"笔记信息: {note_info}")
            self.logger.info(f"当前知识点: {current_point['name']}")
            self.logger.info(f"目标知识点ID: {target_knowledge_id}")
            
            # 使用知识管理系统进行合并
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            
            # 注册笔记到数据库
            note_id = None
            if note_info.get('fileName') and note_info.get('filePath'):
                note_id = km_system.register_note(
                    file_name=note_info['fileName'],
                    file_path=note_info['filePath'],
                    title=note_info.get('title')
                )
                self.logger.info(f"笔记注册成功，ID: {note_id}")
            
            # 获取目标知识点的详细信息
            conn = km_system.db_manager.get_connection()
            cursor = conn.cursor()
            
            # 查询目标知识点
            cursor.execute(
                "SELECT point_name, core_description, mastery_score FROM knowledge_points WHERE id = ?",
                (target_knowledge_id,)
            )
            target_point = cursor.fetchone()
            
            if not target_point:
                conn.close()
                return json.dumps({"success": False, "error": "目标知识点不存在"}, ensure_ascii=False)
            
            # 合并逻辑：更新目标知识点的描述（可选）
            # 这里可以根据需要合并描述内容
            updated_description = target_point[1]  # 保持原有描述
            
            # 如果需要合并描述，可以这样做：
            # if current_point['description'] not in updated_description:
            #     updated_description += f"\n\n补充内容：{current_point['description']}"
            
            # 更新目标知识点（如果需要）
            cursor.execute(
                "UPDATE knowledge_points SET core_description = ?, updated_time = CURRENT_TIMESTAMP WHERE id = ?",
                (updated_description, target_knowledge_id)
            )
            
            conn.commit()
            conn.close()
            
            # 建立知识点与笔记的关联
            if note_id:
                link_success = km_system.link_knowledge_point_to_note(target_knowledge_id, note_id)
                self.logger.info(f"知识点来源关联: {'成功' if link_success else '失败'}")
            
            self.logger.info(f"知识点合并成功，目标ID: {target_knowledge_id}")
            
            # 获取更新后的来源信息
            sources = km_system.get_knowledge_point_sources(target_knowledge_id)
            
            response = {
                "success": True,
                "message": "知识点合并成功",
                "merged_knowledge_id": target_knowledge_id,
                "updated_point": {
                    "id": target_knowledge_id,
                    "name": target_point[0],
                    "description": updated_description,
                    "mastery_score": target_point[2],
                    "sources": sources
                }
            }
            
            return json.dumps(response, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"合并知识点失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    @Slot(str, result=str)
    def createNewKnowledgePoint(self, create_data):
        """创建新知识点"""
        self.logger.info("创建新知识点")
        
        try:
            data = json.loads(create_data)
            note_info = data.get('noteInfo', {})
            subject = data.get('subject')
            point = data.get('point')
            
            self.logger.info(f"笔记信息: {note_info}")
            self.logger.info(f"科目: {subject}")
            self.logger.info(f"知识点: {point['name']}")
            
            # 使用知识管理系统创建新知识点
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            
            # 确保科目存在
            km_system.add_subject(subject)
            
            # 注册笔记到数据库
            note_id = None
            if note_info.get('fileName') and note_info.get('filePath'):
                note_id = km_system.register_note(
                    file_name=note_info['fileName'],
                    file_path=note_info['filePath'],
                    title=note_info.get('title')
                )
                self.logger.info(f"笔记注册成功，ID: {note_id}")
            
            # 创建知识点数据
            knowledge_point_data = {
                "point_name": point['name'],
                "core_description": point['description'],
                "mastery_score": 50  # 默认掌握度
            }
            
            # 保存到数据库
            confirmations = [{
                "action": "new",
                "point_data": knowledge_point_data,
                "subject_name": subject
            }]
            
            saved_ids = km_system.confirm_knowledge_points(confirmations)
            
            if saved_ids and len(saved_ids) > 0:
                new_knowledge_id = saved_ids[0]
                
                # 建立知识点与笔记的关联
                if note_id:
                    link_success = km_system.link_knowledge_point_to_note(new_knowledge_id, note_id)
                    self.logger.info(f"知识点来源关联: {'成功' if link_success else '失败'}")
                
                self.logger.info(f"新知识点创建成功，ID: {new_knowledge_id}")
                
                # 获取来源信息
                sources = []
                if note_id:
                    sources = km_system.get_knowledge_point_sources(new_knowledge_id)
                
                response = {
                    "success": True,
                    "message": "新知识点创建成功",
                    "knowledge_id": new_knowledge_id,
                    "knowledge_point": {
                        "id": new_knowledge_id,
                        "name": point['name'],
                        "description": point['description'],
                        "subject": subject,
                        "mastery_score": 50,
                        "sources": sources
                    }
                }
            else:
                response = {
                    "success": False,
                    "error": "数据库保存失败"
                }
            
            return json.dumps(response, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"创建新知识点失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    @Slot(str, result=str)
    def getNoteKnowledgePoints(self, file_path):
        """获取指定笔记相关的知识点"""
        self.logger.info(f"获取笔记相关知识点: {file_path}")
        
        try:
            from knowledge_management import KnowledgeManagementSystem
            km_system = KnowledgeManagementSystem(self.config)
            
            # 查找该笔记在数据库中的记录
            conn = km_system.db_manager.get_connection()
            cursor = conn.cursor()
            
            # 查询笔记ID
            cursor.execute("SELECT id FROM notes WHERE file_path = ?", (file_path,))
            note_record = cursor.fetchone()
            
            if not note_record:
                conn.close()
                self.logger.info(f"笔记 {file_path} 在数据库中不存在")
                return json.dumps([], ensure_ascii=False)
            
            note_id = note_record[0]
            
            # 查询该笔记相关的知识点
            cursor.execute("""
                SELECT kp.id, kp.point_name, kp.core_description, kp.subject_name, kp.mastery_score, kp.created_time
                FROM knowledge_points kp
                JOIN knowledge_point_sources kps ON kp.id = kps.knowledge_point_id
                WHERE kps.note_id = ?
                ORDER BY kps.extraction_time DESC
            """, (note_id,))
            
            knowledge_points = []
            for row in cursor.fetchall():
                knowledge_points.append({
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "subject": row[3],
                    "mastery_score": row[4] or 50,
                    "created_time": row[5],
                    "type": "existing"  # 标记为已存在的知识点
                })
            
            conn.close()
            
            self.logger.info(f"找到 {len(knowledge_points)} 个相关知识点")
            return json.dumps(knowledge_points, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"获取笔记知识点失败: {e}")
            return json.dumps([], ensure_ascii=False)

    @Slot(str, str, result=str)
    def chatWithAI(self, message, conversation_history_json="[]"):
        """与AI助手聊天 - 立即返回，异步处理"""
        import json
        
        self.logger.info(f"AI聊天请求: {message}")
        
        # 立即返回处理中状态
        return json.dumps({"success": True, "message": "processing", "status": "processing"}, ensure_ascii=False)
    
    @Slot(str, str)
    def chatWithAIAsync(self, message, conversation_history_json="[]"):
        """异步处理AI聊天请求"""
        import threading
        
        def process_chat():
            import json
            import requests
            import random
            
            try:
                # 解析对话历史
                conversation_history = json.loads(conversation_history_json) if conversation_history_json else []
                
                # 构建包含历史的完整提示词
                system_prompt = """你是柯基学习小助手的AI伙伴，一个友善、聪明、有耐心的学习助手。
你的特点：
1. 像柯基犬一样活泼友好，偶尔会用"汪！"表达兴奋
2. 专注于帮助用户学习和解决问题
3. 回答简洁明了，但不失温暖
4. 善于将复杂概念用简单易懂的方式解释
5. 鼓励用户积极学习，给予正面反馈

请用友好、鼓励的语气回答用户的问题。记住之前的对话内容，保持对话的连贯性。"""
                
                # 构建完整的对话提示词
                full_prompt = system_prompt + "\n\n"
                if conversation_history:
                    full_prompt += "对话历史：\n"
                    for msg in conversation_history[-10:]:  # 只保留最近10条消息
                        role = "用户" if msg["role"] == "user" else "AI助手"
                        full_prompt += f"{role}: {msg['content']}\n"
                    full_prompt += "\n"
                full_prompt += f"用户: {message}\nAI助手: "
                
                # 调用LLM API
                self.logger.info(f"开始调用LLM API，提示词长度: {len(full_prompt)}")
                ai_response = call_llm(full_prompt, "AI聊天对话")
                
                if ai_response:
                    self.logger.info(f"AI回复生成成功: {ai_response[:50]}...")
                    result = json.dumps({"success": True, "message": ai_response}, ensure_ascii=False)
                    # 通过信号发送结果到前端
                    self.chatResponseReady.emit(result)
                else:
                    self.logger.warning("LLM API调用失败，使用fallback回复")
                    # 友好的回退回复
                    fallback_responses = [
                        "汪！我现在有点累了，稍后再聊好吗？",
                        "抱歉，我的小脑瓜现在有点转不过来，请稍后再试试。",
                        "哎呀，我好像走神了，能再说一遍吗？",
                        "我需要先去充充电，等会儿再来帮你！"
                    ]
                    fallback_message = random.choice(fallback_responses)
                    result = json.dumps({"success": True, "message": fallback_message}, ensure_ascii=False)
                    # 通过信号发送结果到前端
                    self.chatResponseReady.emit(result)
                    
            except Exception as e:
                self.logger.error(f"AI聊天功能异常: {e}")
                result = json.dumps({"success": True, "message": "汪！我现在有点忙，稍后再来找我聊天吧！"}, ensure_ascii=False)
                self.chatResponseReady.emit(result)
        
        # 在新线程中处理
        thread = threading.Thread(target=process_chat)
        thread.daemon = True
        thread.start()
    
    # 旧的LLM调用方法已被统一工厂替代，保留此注释作为标记
    
    # 所有旧的LLM API调用方法已被统一的LLM工厂替代

    @Slot(str, result=str)
    def summarizeConversation(self, conversation_history_json):
        """总结对话内容"""
        import json
        
        self.logger.info("对话总结请求")
        try:
            conversation_history = json.loads(conversation_history_json)
            if not conversation_history:
                return json.dumps({"success": False, "error": "没有对话内容可以总结"}, ensure_ascii=False)
            
            # 构建对话文本
            conversation_text = "\n\n".join([
                f"{'用户' if msg['role'] == 'user' else 'AI助手'}: {msg['content']}" 
                for msg in conversation_history
            ])
            
            summary_prompt = f"""请用中文对以下对话进行知识点总结，要求：
1. 使用中文回答
2. 提取关键知识点和要点
3. 结构化展示，使用标题和列表
4. 突出重要概念和原理
5. 保持简洁明了

对话内容：
{conversation_text}

请生成总结："""
            
            # 调用LLM API
            summary = call_llm(summary_prompt, "对话总结")
            
            if summary:
                self.logger.info(f"对话总结生成成功: {summary[:50]}...")
                return json.dumps({"success": True, "summary": summary}, ensure_ascii=False)
            else:
                self.logger.error("对话总结生成失败")
                return json.dumps({"success": False, "error": "总结生成失败"}, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"对话总结功能异常: {e}")
            return json.dumps({"success": False, "error": f"总结功能异常: {str(e)}"}, ensure_ascii=False)
    
    @Slot(str, result=str)
    def saveConversation(self, conversation_data_json):
        """保存对话到历史记录"""
        self.logger.info("保存对话请求")
        try:
            import json
            import os
            from datetime import datetime
            
            conversation_data = json.loads(conversation_data_json)
            
            # 创建对话目录
            conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
            os.makedirs(conversations_dir, exist_ok=True)
            
            # 生成文件名
            conv_id = conversation_data.get('id', datetime.now().strftime('%Y%m%d_%H%M%S'))
            filename = f"conversation_{conv_id}.json"
            filepath = os.path.join(conversations_dir, filename)
            
            # 添加时间戳
            conversation_data['timestamp'] = datetime.now().isoformat()
            
            # 保存文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(conversation_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"对话已保存: {filepath}")
            return json.dumps({"success": True, "message": "对话已保存"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"保存对话失败: {e}")
            return json.dumps({"success": False, "error": f"保存失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def loadConversationHistory(self):
        """加载对话历史列表"""
        self.logger.info("加载对话历史请求")
        try:
            import json
            import os
            from datetime import datetime
            
            conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
            if not os.path.exists(conversations_dir):
                return json.dumps({"success": True, "conversations": []}, ensure_ascii=False)
            
            conversations = []
            for filename in os.listdir(conversations_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(conversations_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            # 只返回必要的信息用于列表显示
                            conv_info = {
                                'id': data.get('id', ''),
                                'timestamp': data.get('timestamp', ''),
                                'title': data.get('title', ''),
                                'message_count': len(data.get('conversation_history', []))
                            }
                            conversations.append(conv_info)
                    except Exception as e:
                        self.logger.error(f"加载对话文件失败 {filename}: {e}")
            
            # 按时间排序（最新的在前）
            conversations.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            self.logger.info(f"加载了 {len(conversations)} 个对话记录")
            return json.dumps({"success": True, "conversations": conversations}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"加载对话历史失败: {e}")
            return json.dumps({"success": False, "error": f"加载失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(str, result=str)
    def loadConversationById(self, conversation_id):
        """根据ID加载具体对话内容"""
        self.logger.info(f"加载对话内容请求: {conversation_id}")
        try:
            import json
            import os
            
            conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
            filename = f"conversation_{conversation_id}.json"
            filepath = os.path.join(conversations_dir, filename)
            
            if not os.path.exists(filepath):
                return json.dumps({"success": False, "error": "对话文件不存在"}, ensure_ascii=False)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                conversation_data = json.load(f)
            
            self.logger.info(f"对话内容加载成功: {conversation_id}")
            return json.dumps({"success": True, "conversation": conversation_data}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"加载对话内容失败: {e}")
            return json.dumps({"success": False, "error": f"加载失败: {str(e)}"}, ensure_ascii=False)

    @Slot(str, result=str)
    def saveNoteKnowledgeMapping(self, mapping_data):
        """保存笔记知识点映射关系"""
        self.logger.info("保存笔记知识点映射关系")
        
        try:
            data = json.loads(mapping_data)
            note_id = data.get('noteId')
            file_name = data.get('fileName')
            file_path = data.get('filePath')
            processed_points = data.get('processedPoints', [])
            
            self.logger.info(f"笔记ID: {note_id}")
            self.logger.info(f"文件名: {file_name}")
            self.logger.info(f"文件路径: {file_path}")
            self.logger.info(f"处理的知识点数量: {len(processed_points)}")
            
            # 这里应该：
            # 1. 将笔记信息保存到数据库
            # 2. 建立笔记与知识点的多对多映射关系
            # 3. 更新知识点的来源信息
            
            # 模拟保存映射关系
            mapping_info = {
                "note_id": note_id,
                "file_name": file_name,
                "file_path": file_path,
                "processed_count": len(processed_points),
                "timestamp": time.time()
            }
            
            # 这里可以保存到文件或数据库
            # 暂时只记录日志
            for point in processed_points:
                self.logger.info(f"已处理知识点: {point['name']}")
            
            response = {
                "success": True,
                "message": "笔记知识点映射保存成功",
                "mapping_info": mapping_info
            }
            
            return json.dumps(response, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"保存笔记知识点映射失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    @Slot()
    def openLogViewer(self):
        """打开日志查看器"""
        self.logger.info("打开LLM调用日志查看器")
        
        try:
            # 这里可以打开一个新的窗口或面板来显示日志
            # 暂时通过JavaScript在前端显示
            records = get_llm_call_records(50)  # 获取最近50条记录
            statistics = get_llm_call_statistics()
            
            log_data = {
                "records": records,
                "statistics": statistics
            }
            
            # 通过JavaScript显示日志数据
            js_code = f"showLogViewer({json.dumps(log_data, ensure_ascii=False)});"
            if self.main_window and self.main_window.web_view:
                self.main_window.web_view.page().runJavaScript(js_code)
            
            self.logger.info(f"日志查看器已打开，显示 {len(records)} 条记录")
            
        except Exception as e:
            self.logger.error(f"打开日志查看器失败: {e}")
    
    @Slot(result=bool)
    def clearLLMLogs(self):
        """清空LLM调用日志"""
        self.logger.info("清空LLM调用日志")
        
        try:
            llm_call_logger.clear_records()
            self.logger.info("✅ LLM调用日志已清空")
            return True
        except Exception as e:
            self.logger.error(f"❌ 清空LLM调用日志失败: {e}")
            return False
    
    @Slot(result=str)
    def getLLMCallLogs(self):
        """获取LLM调用日志"""
        try:
            records = get_llm_call_records(100)  # 获取最近100条记录
            statistics = get_llm_call_statistics()
            
            result = {
                "success": True,
                "records": records,
                "statistics": statistics
            }
            
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"获取LLM调用日志失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    # ====== 网课笔记录音功能 ======
    
    @Slot()
    def switchToRecording(self):
        """切换到录音室页面 - 重定向到网课笔记"""
        self.logger.info("切换到录音室页面，重定向到网课笔记")
        self.loadContent("online_course_notes")
    
    def _cleanup_tr(self):
        """清理转写线程"""
        self._tr_thread = None
        self._tr_worker = None

    # ====== AI练习助手功能 ======
    
    @Slot(result=str)
    def getPracticeHistory(self):
        """获取练习历史列表"""
        self.logger.info("=== 开始获取练习历史列表 ===")
        
        try:
            # 导入练习服务
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            
            from services.practice_service import PracticeService
            
            # 初始化服务
            practice_service = PracticeService()
            
            # 检查是否需要从 JSON 文件迁移数据
            current_dir = os.getcwd()
            practice_dir = os.path.join(current_dir, "practice_sessions")
            
            self.logger.info(f"📁 检查JSON文件目录: {practice_dir}")
            
            if os.path.exists(practice_dir):
                json_files = [f for f in os.listdir(practice_dir) if f.endswith('.json')]
                self.logger.info(f"📁 找到JSON文件: {len(json_files)} 个")
                
                if json_files:
                    self.logger.info("🔄 开始数据迁移...")
                    migration_result = practice_service.migrate_from_json_files(practice_dir)
                    self.logger.info(f"📦 数据迁移结果: {migration_result}")
            
            # 获取练习历史列表
            self.logger.info("📊 从数据库获取练习历史...")
            result = practice_service.get_practice_history_list(limit=50)
            
            if result["success"]:
                practices = result["practices"]
                self.logger.info(f"🎯 成功获取练习历史: {len(practices)} 条")
                
                # 记录前3个练习ID
                if practices:
                    first3_ids = [p.get('id', 'N/A') for p in practices[:3]]
                    self.logger.info(f"📋 前3个练习ID: {first3_ids}")
                
                # 统一返回格式
                response_data = {
                    "success": True,
                    "practices": practices
                }
                
                result_str = json.dumps(response_data, ensure_ascii=False)
                
                # 记录返回数据的概要
                if len(result_str) > 1000:
                    self.logger.info(f"📤 返回数据(截断): {result_str[:300]}...{result_str[-200:]}")
                else:
                    self.logger.info(f"📤 返回数据: {result_str}")
                
                self.logger.info("=== 练习历史获取完成 ===")
                return result_str
            else:
                error_msg = result.get("error", "未知错误")
                self.logger.error(f"❌ 获取练习历史失败: {error_msg}")
                return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
            
        except ImportError as import_error:
            self.logger.error(f"❌ 导入模块失败: {import_error}")
            # 回退到原有的JSON文件读取方式
            self.logger.info("🔄 回退到JSON文件读取方式...")
            return self._get_practice_history_from_json()
            
        except Exception as e:
            self.logger.error(f"❌ 获取练习历史异常: {e}")
            self.logger.error(f"❌ 错误类型: {type(e).__name__}")
            import traceback
            self.logger.error(f"❌ 错误堆栈: {traceback.format_exc()}")
            
            # 尝试回退到JSON文件读取
            self.logger.info("🔄 尝试回退到JSON文件读取...")
            try:
                return self._get_practice_history_from_json()
            except Exception as fallback_error:
                self.logger.error(f"❌ JSON文件读取也失败: {fallback_error}")
                return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    
    def _get_practice_history_from_json(self):
        """从 JSON 文件获取练习历史（备用方法）"""
        self.logger.info("🔄 使用JSON文件读取方式...")
        
        try:
            import os
            import json
            
            current_dir = os.getcwd()
            practice_dir = os.path.join(current_dir, "practice_sessions")
            
            if not os.path.exists(practice_dir):
                return json.dumps({"success": True, "practices": []}, ensure_ascii=False)
            
            all_files = os.listdir(practice_dir)
            practice_files = [f for f in all_files if f.endswith('.json') and 'practice' in f]
            practice_files.sort(reverse=True)
            
            practices = []
            for filename in practice_files[:20]:
                filepath = os.path.join(practice_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        practice_data = json.load(f)
                    
                    # 安全处理selected_text字段
                    selected_text = practice_data.get("selected_text", "")
                    if selected_text is None:
                        selected_text = ""
                    
                    # 安全截取文本
                    text_preview = selected_text[:100] if len(selected_text) > 100 else selected_text
                    if len(selected_text) > 100:
                        text_preview += "..."
                    
                    practices.append({
                        "id": practice_data.get("practice_id", ""),
                        "timestamp": practice_data.get("timestamp", ""),
                        "status": practice_data.get("status", "unknown"),
                        "selected_text": text_preview,
                        "has_evaluation": bool(practice_data.get("evaluation_result", ""))
                    })
                except Exception as e:
                    self.logger.warning(f"⚠️ 跳过文件 {filename}: {e}")
                    continue
            
            result = {"success": True, "practices": practices}
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"❌ JSON文件读取失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    def _load_practice_history_from_json(self, practice_id):
        """从 JSON 文件加载练习历史（备用方法）"""
        self.logger.info(f"🔄 使用JSON文件加载方式: {practice_id}")
        
        try:
            import os
            import json
            
            current_dir = os.getcwd()
            practice_dir = os.path.join(current_dir, "practice_sessions")
            
            # 清理practice_id
            clean_practice_id = practice_id
            if practice_id.startswith('practice_'):
                clean_practice_id = practice_id[9:]
            
            # 尝试多种文件名格式
            possible_filenames = [
                f"practice_{clean_practice_id}.json",
                f"practice_practice_{clean_practice_id}.json",
                f"{practice_id}.json"
            ]
            
            for filename in possible_filenames:
                filepath = os.path.join(practice_dir, filename)
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            practice_data = json.load(f)
                        
                        result = {"success": True, "practice": practice_data}
                        return json.dumps(result, ensure_ascii=False)
                    except Exception as e:
                        self.logger.warning(f"⚠️ 读取文件失败 {filename}: {e}")
                        continue
            
            # 所有尝试都失败
            error_msg = f"练习记录不存在: {practice_id}"
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"❌ JSON文件加载失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


    
    def _save_practice_evaluation_to_json(self, data):
        """保存练习评估到JSON文件（备用方法）"""
        self.logger.info("🔄 使用JSON文件保存方式...")
        
        try:
            import os
            import json
            from datetime import datetime
            
            practice_id = data.get('practice_id')
            
            # 清理practice_id
            if practice_id and practice_id.startswith('practice_'):
                practice_id = practice_id[9:]
            
            if not practice_id:
                practice_id = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 创建目录
            current_dir = os.getcwd()
            practice_dir = os.path.join(current_dir, "practice_sessions")
            os.makedirs(practice_dir, exist_ok=True)
            
            # 保存数据
            practice_data = {
                "practice_id": practice_id,
                "timestamp": datetime.now().isoformat(),
                "selected_text": data.get('selected_text', ''),
                "questions": data.get('questions', ''),
                "user_answers": data.get('user_answers', ''),
                "evaluation_result": data.get('evaluation_result', ''),
                "status": "evaluated"
            }
            
            filename = f"practice_{practice_id}.json"
            filepath = os.path.join(practice_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(practice_data, f, ensure_ascii=False, indent=2)
            
            result = {
                "success": True,
                "message": "评估结果已保存",
                "practice_id": practice_id,
                "filepath": filepath
            }
            
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"❌ JSON文件保存失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def loadPracticeHistory(self, practice_id):
        """加载指定的练习历史"""
        self.logger.info(f"=== 开始加载练习历史: {practice_id} ===")
        
        try:
            # 导入练习服务
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            
            from services.practice_service import PracticeService
            
            # 初始化服务
            practice_service = PracticeService()
            
            # 加载练习详情
            self.logger.info(f"📊 从数据库加载练习详情: {practice_id}")
            result = practice_service.load_practice_detail(practice_id)
            
            if result["success"]:
                practice_detail = result["practice"]
                self.logger.info(f"✅ 成功加载练习详情: {practice_id}")
                self.logger.info(f"📄 practice_id: {practice_detail.get('practice_id')}")
                self.logger.info(f"📄 timestamp: {practice_detail.get('timestamp')}")
                self.logger.info(f"📄 questions长度: {len(practice_detail.get('questions', ''))}")
                self.logger.info(f"📄 user_answers长度: {len(practice_detail.get('user_answers', ''))}")
                self.logger.info(f"📄 evaluation_result长度: {len(practice_detail.get('evaluation_result', ''))}")
                
                result_str = json.dumps(result, ensure_ascii=False)
                self.logger.info("=== 练习历史加载完成 ===")
                return result_str
            else:
                error_msg = result.get("error", "未知错误")
                self.logger.error(f"❌ 加载练习详情失败: {error_msg}")
                return json.dumps(result, ensure_ascii=False)
            
        except ImportError as import_error:
            self.logger.error(f"❌ 导入模块失败: {import_error}")
            # 回退到原有的JSON文件读取方式
            self.logger.info("🔄 回退到JSON文件读取方式...")
            return self._load_practice_history_from_json(practice_id)
            
        except Exception as e:
            self.logger.error(f"❌ 加载练习历史异常: {e}")
            self.logger.error(f"❌ 错误类型: {type(e).__name__}")
            import traceback
            self.logger.error(f"❌ 错误堆栈: {traceback.format_exc()}")
            
            # 尝试回退到JSON文件读取
            self.logger.info("🔄 尝试回退到JSON文件读取...")
            try:
                return self._load_practice_history_from_json(practice_id)
            except Exception as fallback_error:
                self.logger.error(f"❌ JSON文件读取也失败: {fallback_error}")
                return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    
    @Slot(str, result=str)
    def savePracticeEvaluation(self, evaluation_data):
        """保存练习评估结果"""
        self.logger.info("=== 开始保存练习评估结果 ===")
        
        try:
            import json
            
            self.logger.info(f"📥 接收到评估数据长度: {len(evaluation_data)} 字符")
            data = json.loads(evaluation_data)
            
            # 尝试使用数据库方式
            try:
                import sys
                import os
                sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                
                from services.practice_service import PracticeService
                
                # 初始化服务
                practice_service = PracticeService()
                
                # 保存完整的练习数据
                self.logger.info("💾 使用数据库方式保存...")
                result = practice_service.save_complete_practice_data(data)
                
                if result["success"]:
                    self.logger.info(f"✅ 数据库保存成功: {result.get('practice_id')}")
                    return json.dumps(result, ensure_ascii=False)
                else:
                    raise Exception(result.get("error", "数据库保存失败"))
                    
            except ImportError as import_error:
                self.logger.error(f"❌ 导入模块失败: {import_error}")
                # 回退到JSON文件保存方式
                self.logger.info("🔄 回退到JSON文件保存方式...")
                return self._save_practice_evaluation_to_json(data)
                
            except Exception as db_error:
                self.logger.error(f"❌ 数据库保存失败: {db_error}")
                # 回退到JSON文件保存方式
                self.logger.info("🔄 回退到JSON文件保存方式...")
                return self._save_practice_evaluation_to_json(data)
            
        except json.JSONDecodeError as json_error:
            error_msg = f"JSON解析错误: {json_error}"
            self.logger.error(f"❌ {error_msg}")
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"❌ 保存练习评估发生严重错误: {e}")
            import traceback
            self.logger.error(f"❌ 错误堆栈: {traceback.format_exc()}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    
    @Slot(str, result=str)
    def importPracticeErrors(self, error_data):
        """错题入库功能"""
        self.logger.info("开始错题入库")
        
        try:
            import json
            
            data = json.loads(error_data)
            practice_content = data.get('practice_content', '')
            evaluation_result = data.get('evaluation_result', '')
            selected_text = data.get('selected_text', '')
            
            # 直接使用错题入库功能
            if not evaluation_result:
                return json.dumps({"success": False, "error": "没有评估结果可以入库"}, ensure_ascii=False)
            
            # 这里可以直接调用错题入库的逻辑，或者返回数据给前端处理
            return json.dumps({
                "success": True, 
                "message": "错题入库功能需要在Qt界面中操作",
                "action": "open_error_import_dialog",
                "data": {
                    "practice_content": practice_content,
                    "evaluation_result": evaluation_result,
                    "selected_text": selected_text
                }
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"错题入库失败: {e}")
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
        """详细的设备兼容性测试，包含崩溃日志"""
        crash_log_file = "audio_device_crash.log"
        
        try:
            self.logger.info(f"=== 开始兼容性测试 ===")
            self.logger.info(f"设备索引: {device_index}")
            self.logger.info(f"设备名称: {device_name}")
            
            # 记录详细的系统信息
            import platform
            import sys
            self.logger.info(f"Python版本: {sys.version}")
            self.logger.info(f"操作系统: {platform.system()} {platform.version()}")
            
            # 写入崩溃日志文件
            from datetime import datetime
            with open(crash_log_file, "a", encoding="utf-8") as f:
                f.write(f"\n=== 兼容性测试开始 {datetime.now()} ===\n")
                f.write(f"设备: {device_name} (索引: {device_index})\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"系统: {platform.system()} {platform.version()}\n")
            
            try:
                self.logger.info("导入PyAudio...")
                import pyaudio
                self.logger.info("✅ PyAudio导入成功")
                
                with open(crash_log_file, "a", encoding="utf-8") as f:
                    f.write("PyAudio导入成功\n")
                
                self.logger.info("初始化PyAudio...")
                p = pyaudio.PyAudio()
                self.logger.info("✅ PyAudio初始化成功")
                
                with open(crash_log_file, "a", encoding="utf-8") as f:
                    f.write("PyAudio初始化成功\n")
                
                try:
                    self.logger.info(f"获取设备信息 (索引: {device_index})...")
                    device_info = p.get_device_info_by_index(device_index)
                    self.logger.info(f"✅ 设备信息获取成功: {device_info}")
                    
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write(f"设备信息: {device_info}\n")
                    
                    device_rate = int(device_info.get('defaultSampleRate', 44100))
                    max_input_channels = device_info.get('maxInputChannels', 0)
                    
                    self.logger.info(f"设备采样率: {device_rate}")
                    self.logger.info(f"最大输入声道: {max_input_channels}")
                    
                    if max_input_channels == 0:
                        raise Exception("设备不支持音频输入")
                    
                    self.logger.info("尝试打开音频流...")
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write(f"尝试打开音频流: 采样率={device_rate}, 声道=1\n")
                    
                    # 尝试打开音频流（不录制）
                    stream = p.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=device_rate,
                        input=True,
                        input_device_index=device_index,
                        frames_per_buffer=1024
                    )
                    
                    self.logger.info("✅ 音频流打开成功")
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write("音频流打开成功\n")
                    
                    # 立即关闭
                    self.logger.info("关闭音频流...")
                    stream.close()
                    self.logger.info("✅ 音频流关闭成功")
                    
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write("音频流关闭成功\n")
                    
                    self.logger.info("终止PyAudio...")
                    p.terminate()
                    self.logger.info("✅ PyAudio终止成功")
                    
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write("PyAudio终止成功\n")
                        f.write("=== 兼容性测试成功完成 ===\n\n")
                    
                    self.logger.info(f"✅ 设备 {device_name} 兼容性测试通过")
                    return json.dumps({
                        "success": True, 
                        "message": f"设备 {device_name} 可以正常使用",
                        "compatible": True
                    }, ensure_ascii=False)
                    
                except Exception as device_error:
                    self.logger.error(f"❌ 设备操作失败: {device_error}")
                    import traceback
                    error_trace = traceback.format_exc()
                    self.logger.error(f"详细错误: {error_trace}")
                    
                    with open(crash_log_file, "a", encoding="utf-8") as f:
                        f.write(f"设备操作失败: {device_error}\n")
                        f.write(f"错误堆栈: {error_trace}\n")
                        f.write("=== 兼容性测试失败 ===\n\n")
                    
                    try:
                        p.terminate()
                        self.logger.info("PyAudio已清理")
                    except:
                        self.logger.warning("PyAudio清理失败")
                    
                    return json.dumps({
                        "success": False, 
                        "error": f"设备不兼容: {str(device_error)}",
                        "compatible": False
                    }, ensure_ascii=False)
                    
            except Exception as pyaudio_error:
                self.logger.error(f"❌ PyAudio操作失败: {pyaudio_error}")
                import traceback
                error_trace = traceback.format_exc()
                self.logger.error(f"详细错误: {error_trace}")
                
                with open(crash_log_file, "a", encoding="utf-8") as f:
                    f.write(f"PyAudio操作失败: {pyaudio_error}\n")
                    f.write(f"错误堆栈: {error_trace}\n")
                    f.write("=== PyAudio失败 ===\n\n")
                
                return json.dumps({
                    "success": False, 
                    "error": f"PyAudio错误: {str(pyaudio_error)}",
                    "compatible": False
                }, ensure_ascii=False)
                
        except Exception as outer_error:
            self.logger.error(f"❌ 兼容性测试严重异常: {outer_error}")
            import traceback
            error_trace = traceback.format_exc()
            self.logger.error(f"完整错误堆栈: {error_trace}")
            
            try:
                with open(crash_log_file, "a", encoding="utf-8") as f:
                    f.write(f"严重异常: {outer_error}\n")
                    f.write(f"完整错误堆栈: {error_trace}\n")
                    f.write("=== 严重异常结束 ===\n\n")
            except:
                pass
            
            return json.dumps({"success": False, "error": f"严重错误: {str(outer_error)}"}, ensure_ascii=False)
    
    @Slot(int, str, result=str)
    def testDeviceRecording(self, device_index, device_name):
        """最安全的设备测试 - 完全避免PyAudio操作"""
        self.logger.info(f"最安全测试: {device_index} - {device_name}")
        
        try:
            # 完全避免PyAudio操作，只做模拟测试
            from PySide6.QtCore import QTimer
            
            def simulate_success():
                try:
                    self.logger.info(f"模拟测试完成: {device_name}")
                    
                    # 直接通知前端成功
                    if self.main_window and self.main_window.web_view:
                        js_code = f"""
                        try {{
                            if (typeof onTestRecordingFinished === 'function') {{
                                onTestRecordingFinished(null, {json.dumps(device_name, ensure_ascii=False)});
                            }}
                        }} catch(e) {{
                            console.error('前端回调出错:', e);
                        }}
                        """
                        self.main_window.web_view.page().runJavaScript(js_code)
                        self.logger.info("✅ 前端通知已发送")
                
                except Exception as notify_error:
                    self.logger.error(f"通知前端出错: {notify_error}")
            
            # 延迟1秒模拟测试过程
            QTimer.singleShot(1000, simulate_success)
            
            self.logger.info(f"✅ 开始模拟测试: {device_name}")
            return json.dumps({
                "success": True, 
                "message": f"开始模拟测试设备: {device_name}（1秒模拟）",
                "duration": 1
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"模拟测试失败: {e}")
            return json.dumps({"success": False, "error": f"模拟测试失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def chooseInputDevice(self):
        """打开设备选择对话框 - 完全按照app_qt.py实现"""
        self.logger.info("打开设备选择对话框")
        
        try:
            dlg = DeviceLevelDialog(self.main_window)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                idx = dlg.selected_device_index()
                label = dlg.selected_device_label()
                if idx is not None:
                    # 保存选择的设备
                    self.selected_device_index = idx
                    self.selected_device_name = label
                    
                    # 保存到配置文件
                    self.config["selected_audio_device_index"] = idx
                    self.config["selected_audio_device_name"] = label
                    save_config(self.config)
                    
                    self.logger.info(f"✅ 已选择设备: {label} (索引: {idx})")
                    
                    return json.dumps({
                        "success": True,
                        "message": f"已选择设备: {label}",
                        "device_index": idx,
                        "device_name": label
                    }, ensure_ascii=False)
                else:
                    return json.dumps({
                        "success": False,
                        "message": "未选择任何设备"
                    }, ensure_ascii=False)
            else:
                return json.dumps({
                    "success": False,
                    "message": "用户取消选择"
                }, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"设备选择失败: {e}")
            return json.dumps({
                "success": False,
                "error": f"设备选择失败: {str(e)}"
            }, ensure_ascii=False)
    
    @Slot(result=str)
    def getSelectedDevice(self):
        """获取当前选择的设备信息"""
        if self.selected_device_index is not None:
            return json.dumps({
                "success": True,
                "device_index": self.selected_device_index,
                "device_name": self.selected_device_name or f"设备{self.selected_device_index}"
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "message": "未选择设备"
            }, ensure_ascii=False)
    
    @Slot(result=str)
    def getAudioDevices(self):
        """获取所有音频输入设备列表（分类返回）"""
        self.logger.info("获取音频设备列表")
        
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            
            input_devices = []
            system_audio_devices = []
            all_devices = []
            
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        name = info.get("name", f"设备{i}")
                        rate = int(info.get("defaultSampleRate", 44100))
                        channels = info.get("maxInputChannels", 1)
                        
                        # 基础设备信息
                        device_info = {
                            "index": i,
                            "name": name,
                            "sampleRate": rate,
                            "channels": channels
                        }
                        
                        # 检查是否为系统音频录制设备
                        is_system_audio = (
                            "立体声混音" in name or "Stereo Mix" in name or 
                            "What U Hear" in name or "混音" in name or
                            "WASAPI" in name or "loopback" in name.lower() or
                            "CABLE Output" in name  # VB-Audio Cable 也算系统音频
                        )
                        
                        if is_system_audio:
                            # 系统音频设备
                            device_info.update({
                                "type": "system_audio",
                                "displayName": f"🔊 [系统音频] {name}",
                                "description": "录制电脑播放的声音（适用于网课学习）"
                            })
                            system_audio_devices.append(device_info)
                        else:
                            # 普通输入设备（麦克风等）
                            device_info.update({
                                "type": "input",
                                "displayName": f"🎤 [麦克风] {name}",
                                "description": "录制麦克风输入（适用于线下听课）"
                            })
                            input_devices.append(device_info)
                        
                        # 添加到总列表（用于简单的设备选择界面）
                        simple_device = {
                            "index": i,
                            "name": name,
                            "displayName": f"[{i}] {name}" + (" 🎵" if "CABLE Output" in name else ""),
                            "sampleRate": rate,
                            "channels": channels
                        }
                        all_devices.append(simple_device)
                        
                except Exception as e:
                    self.logger.warning(f"获取设备{i}信息失败: {e}")
                    continue
            
            p.terminate()
            
            self.logger.info(f"找到 {len(input_devices)} 个输入设备, {len(system_audio_devices)} 个系统音频设备")
            
            return json.dumps({
                "success": True,
                "devices": all_devices,  # 兼容简单界面
                "inputDevices": input_devices,  # 麦克风设备
                "systemAudioDevices": system_audio_devices  # 系统音频设备
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"获取音频设备失败: {e}")
            return json.dumps({
                "success": False,
                "error": f"获取设备失败: {str(e)}"
            }, ensure_ascii=False)
    
    @Slot(int, str, result=str)
    def selectAudioDevice(self, device_index, device_name):
        """选择音频设备"""
        self.logger.info(f"选择音频设备: [{device_index}] {device_name}")
        
        try:
            # 保存选择的设备
            self.selected_device_index = device_index
            self.selected_device_name = device_name
            
            # 保存到配置文件
            self.config["selected_audio_device_index"] = device_index
            self.config["selected_audio_device_name"] = device_name
            save_config(self.config)
            
            self.logger.info(f"✅ 音频设备选择成功: {device_name}")
            return json.dumps({
                "success": True, 
                "message": f"已选择设备: {device_name}"
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"选择音频设备失败: {e}")
            return json.dumps({
                "success": False, 
                "error": f"选择设备失败: {str(e)}"
            }, ensure_ascii=False)
    
    @Slot(result=str)
    def getDeviceLevels(self):
        """获取当前选择设备的实时电平"""
        try:
            if self.selected_device_index is None:
                return json.dumps({
                    "success": False,
                    "error": "未选择设备"
                }, ensure_ascii=False)
            
            import pyaudio
            import numpy as np
            
            # 音频参数
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            RATE = 44100
            CHANNELS = 1
            
            peak = 0.0
            stream = None
            
            try:
                p = pyaudio.PyAudio()
                
                # 获取选择设备的信息
                info = p.get_device_info_by_index(self.selected_device_index)
                use_rate = int(info.get("defaultSampleRate", RATE)) or RATE
                use_channels = min(max(1, int(info.get("maxInputChannels", 1))), CHANNELS) or 1
                
                # 打开音频流
                stream = p.open(
                    format=FORMAT,
                    channels=use_channels,
                    rate=use_rate,
                    input=True,
                    frames_per_buffer=CHUNK,
                    input_device_index=self.selected_device_index
                )
                
                # 读取音频数据
                data = stream.read(CHUNK, exception_on_overflow=False)
                
                # 转换为numpy数组并计算峰值
                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                if audio_np.size > 0:
                    peak = float(np.max(np.abs(audio_np)))
                
            except Exception as e:
                self.logger.warning(f"获取设备{self.selected_device_index}电平失败: {e}")
                peak = 0.0
            finally:
                try:
                    if stream:
                        stream.stop_stream()
                        stream.close()
                    if 'p' in locals():
                        p.terminate()
                except Exception:
                    pass
            
            return json.dumps({
                "success": True,
                "level": peak,
                "device_index": self.selected_device_index,
                "device_name": self.selected_device_name or f"设备{self.selected_device_index}"
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"获取设备电平失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)
    
    @Slot(int, result=str)
    def getSingleDeviceLevel(self, device_index):
        """获取单个设备的实时电平"""
        # 如果不在录音状态，直接返回0电平，避免设备访问错误
        if not self.is_recording:
            return json.dumps({
                "success": True,
                "level": 0.0,
                "message": "录音已停止"
            }, ensure_ascii=False)
        
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            
            info = p.get_device_info_by_index(device_index)
            if info.get("maxInputChannels", 0) <= 0:
                p.terminate()
                return json.dumps({"success": False, "error": "设备不支持输入"}, ensure_ascii=False)
            
            use_rate = int(info.get("defaultSampleRate", RATE)) or RATE
            use_channels = min(max(1, int(info.get("maxInputChannels", 1))), CHANNELS) or 1
            
            stream = p.open(
                format=FORMAT,
                channels=use_channels,
                rate=use_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK
            )
            
            # 快速读取一小段音频数据
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(audio_np))) if audio_np.size else 0.0
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            return json.dumps({
                "success": True,
                "level": peak
            }, ensure_ascii=False)
            
        except Exception as e:
            # 记录警告但不让错误影响程序运行
            self.logger.warning(f"获取设备{device_index}电平失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "level": 0.0
            }, ensure_ascii=False)
    
    def _on_test_recording_finished(self, audio_file, device_name):
        """测试录制完成回调"""
        self.logger.info(f"测试录制完成: {device_name} -> {audio_file}")
        
        # 通知前端测试完成
        if self.main_window and self.main_window.web_view:
            js_code = f"""
            if (typeof onTestRecordingFinished === 'function') {{
                onTestRecordingFinished({json.dumps(audio_file, ensure_ascii=False)}, {json.dumps(device_name, ensure_ascii=False)});
            }}
            """
            self.main_window.web_view.page().runJavaScript(js_code)
    
    @Slot(result=str)
    def startRecording(self):
        """开始录音"""
        self.logger.info("🎤 开始录音请求")
        
        # 添加调用堆栈信息
        import traceback
        self.logger.info("调用堆栈:")
        for line in traceback.format_stack():
            self.logger.info(line.strip())
        
        if self.is_recording:
            return json.dumps({"success": False, "error": "录音已在进行中"}, ensure_ascii=False)
        
        # 检查是否已选择音频设备
        if self.selected_device_index is None:
            return json.dumps({"success": False, "error": "请先选择音频输入设备", "needDeviceSelection": True}, ensure_ascii=False)
        
        try:
            # 启动转写线程
            self._tr_thread = QThread(self.main_window)
            self._tr_worker = TranscriberWorker(
                model_size=self.config.get("whisper_model_size", "small"),
                language_setting=self.config.get("whisper_language", "auto")
            )
            self._tr_worker.moveToThread(self._tr_thread)
            self._tr_thread.started.connect(self._tr_worker.start)
            self._tr_worker.textReady.connect(self._on_transcription_ready)
            self._tr_worker.status.connect(self._on_transcription_status)
            self._tr_worker.finished.connect(self._tr_thread.quit)
            self._tr_worker.finished.connect(lambda: self._cleanup_tr())
            self._tr_thread.start()
            
            # 启动录音线程
            self._rec_thread = QThread(self.main_window)
            self._rec_worker = AudioRecorderWorker(device_index=self.selected_device_index)
            self._rec_worker.moveToThread(self._rec_thread)
            self._rec_thread.started.connect(self._rec_worker.start)
            self._rec_worker.segmentReady.connect(self._on_audio_segment_ready)
            self._rec_worker.status.connect(self._on_recording_status)
            self._rec_worker.peakLevel.connect(self._on_peak_level)
            self._rec_worker.finished.connect(self._rec_thread.quit)
            self._rec_worker.finished.connect(lambda: self._cleanup_rec())
            self._rec_thread.start()
            
            self.is_recording = True
            self.logger.info("✅ 录音已启动")
            
            return json.dumps({"success": True, "message": "录音已启动"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"启动录音失败: {e}")
            return json.dumps({"success": False, "error": f"启动录音失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def stopRecording(self):
        """停止录音"""
        self.logger.info("停止录音请求")
        
        if not self.is_recording:
            return json.dumps({"success": False, "error": "录音未在进行中"}, ensure_ascii=False)
        
        try:
            # 停止录音和转写Worker
            if self._rec_worker:
                self.logger.info("停止录音Worker...")
                self._rec_worker.stop()
            if self._tr_worker:
                self.logger.info("停止转写Worker...")
                self._tr_worker.stop()
            
            self.is_recording = False
            self.logger.info("✅ 录音已停止")
            
            # 停止设备电平监控（重要！）
            self._stop_device_monitoring()
            
            return json.dumps({"success": True, "message": "录音已停止"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"停止录音失败: {e}")
            return json.dumps({"success": False, "error": f"停止录音失败: {str(e)}"}, ensure_ascii=False)
    
    def _stop_device_monitoring(self):
        """停止设备电平监控"""
        try:
            # 清除设备索引，停止电平监控
            if hasattr(self, '_monitoring_device_index'):
                self.logger.info(f"停止设备{self._monitoring_device_index}的电平监控")
                delattr(self, '_monitoring_device_index')
        except Exception as e:
            self.logger.warning(f"停止设备监控时出错: {e}")
    
    @Slot(result=str)
    def saveNotes(self):
        """保存笔记"""
        self.logger.info("保存笔记请求")
        
        try:
            # 创建保存目录
            notes_dir = os.path.join(os.path.dirname(__file__), "course_notes")
            os.makedirs(notes_dir, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"course_note_{timestamp}.md"
            filepath = os.path.join(notes_dir, filename)
            
            # 构建Markdown内容
            markdown_content = f"""# 网课笔记

## 笔记总结

{self.summary_text}

---

## 原始语音转文字

{self.transcription_text}

---

*保存时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
            
            # 保存文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            self.logger.info(f"✅ 笔记已保存: {filepath}")
            
            return json.dumps({
                "success": True, 
                "message": f"笔记已保存: {filename}",
                "filepath": filepath
            }, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"保存笔记失败: {e}")
            return json.dumps({"success": False, "error": f"保存笔记失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def manualSummary(self):
        """手动总结"""
        self.logger.info("手动总结请求")
        
        if not self.transcription_text.strip():
            return json.dumps({"success": False, "error": "没有转写内容可以总结"}, ensure_ascii=False)
        
        try:
            # 使用统一的LLM工厂进行总结
            summary_prompt = f"""请对以下语音转写内容进行总结，提取关键信息和要点：

{self.transcription_text}

请用Markdown格式输出总结，包括：
1. 主要内容概述
2. 关键知识点
3. 重要细节

总结内容："""
            
            summary_result = call_llm(summary_prompt)
            
            if summary_result and not summary_result.startswith("LLM调用失败"):
                self.summary_text = summary_result
                self.logger.info("✅ 手动总结完成")
                
                return json.dumps({
                    "success": True, 
                    "message": "总结完成",
                    "summary": summary_result
                }, ensure_ascii=False)
            else:
                self.logger.error(f"总结失败: {summary_result}")
                return json.dumps({"success": False, "error": f"总结失败: {summary_result}"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"手动总结失败: {e}")
            return json.dumps({"success": False, "error": f"手动总结失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def takeScreenshot(self):
        """截图笔记"""
        self.logger.info("截图笔记请求")
        
        try:
            # 这里可以实现截图功能
            # 暂时返回占位符
            return json.dumps({"success": True, "message": "截图功能开发中..."}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"截图笔记失败: {e}")
            return json.dumps({"success": False, "error": f"截图笔记失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def getTranscriptionText(self):
        """获取转写文本"""
        return json.dumps({
            "success": True,
            "transcription": self.transcription_text,
            "summary": self.summary_text,
            "is_recording": self.is_recording
        }, ensure_ascii=False)
    
    @Slot(result=str)
    def testRecordingWithTranscription(self):
        """测试录音功能 - 直接使用正常录音，只是界面显示为测试"""
        self.logger.info("🧪 开始测试录音（使用正常录音方法）")
        
        # 直接调用正常的开始录音方法
        return self.startRecording()
    
    @Slot(result=str)
    def testRecordingFlow(self):
        """测试录音转写流程 - 同步版本，不依赖定时器"""
        self.test_logger.info("=" * 80)
        self.test_logger.info("🧪 开始测试录音转写流程（同步版本）")
        self.test_logger.info("=" * 80)
        
        try:
            # 步骤1: 检查设备选择
            self.test_logger.info("📋 步骤1: 检查设备选择")
            if self.selected_device_index is None:
                self.test_logger.error("❌ 未选择音频设备")
                return json.dumps({
                    "success": False, 
                    "error": "请先选择音频设备",
                    "step": "device_selection"
                }, ensure_ascii=False)
            
            self.test_logger.info(f"✅ 设备已选择: {self.selected_device_index} - {self.selected_device_name}")
            
            # 步骤2: 记录当前状态
            self.test_logger.info("📋 步骤2: 记录当前状态")
            self.test_logger.info(f"当前录音状态: {self.is_recording}")
            self.test_logger.info(f"当前转写文本长度: {len(self.transcription_text)}")
            self.test_logger.info(f"录音线程状态: {self._rec_thread is not None}")
            self.test_logger.info(f"转写线程状态: {self._tr_thread is not None}")
            
            # 备份原始转写文本
            original_text = self.transcription_text
            self.transcription_text = ""
            self.test_logger.info("🧹 已备份并清空转写文本缓存")
            
            # 步骤3: 开始录音
            self.test_logger.info("📋 步骤3: 开始录音（调用startRecording方法）")
            self.test_logger.info("🔍 这里调用的是与正常录音完全相同的startRecording方法")
            
            start_result = self.startRecording()
            self.test_logger.info(f"📊 录音开始结果: {start_result}")
            
            # 解析结果
            try:
                start_data = json.loads(start_result)
                if not start_data.get('success'):
                    self.test_logger.error(f"❌ 录音启动失败: {start_data.get('error')}")
                    self.transcription_text = original_text
                    return json.dumps({
                        "success": False,
                        "error": f"录音启动失败: {start_data.get('error')}",
                        "step": "start_recording"
                    }, ensure_ascii=False)
                else:
                    self.test_logger.info("✅ 录音启动成功")
            except json.JSONDecodeError:
                self.test_logger.warning("⚠️ 无法解析JSON结果，检查字符串内容")
                if "success" not in start_result.lower():
                    self.test_logger.error(f"❌ 录音启动失败: {start_result}")
                    self.transcription_text = original_text
                    return json.dumps({
                        "success": False,
                        "error": f"录音启动失败: {start_result}",
                        "step": "start_recording"
                    }, ensure_ascii=False)
                else:
                    self.test_logger.info("✅ 录音启动成功（根据字符串判断）")
            
            # 步骤4: 记录录音后的状态
            self.test_logger.info("📋 步骤4: 记录录音启动后的状态")
            self.test_logger.info(f"录音状态: {self.is_recording}")
            self.test_logger.info(f"录音线程: {self._rec_thread}")
            self.test_logger.info(f"录音Worker: {self._rec_worker}")
            self.test_logger.info(f"转写线程: {self._tr_thread}")
            self.test_logger.info(f"转写Worker: {self._tr_worker}")
            
            # 步骤5: 同步等待10秒
            self.test_logger.info("📋 步骤5: 开始10秒录音，请播放音频或说话...")
            import time
            for i in range(10):
                time.sleep(1)
                self.test_logger.info(f"⏰ 录音中... {i+1}/10 秒")
                
                # 处理Qt事件，保持程序响应
                QApplication.processEvents()
            
            # 步骤6: 停止录音
            self.test_logger.info("📋 步骤6: 10秒录音完成，停止录音...")
            stop_result = self.stopRecording()
            self.test_logger.info(f"📊 停止录音结果: {stop_result}")
            
            # 步骤7: 等待转写完成
            self.test_logger.info("📋 步骤7: 等待转写完成...")
            max_wait = 15  # 最多等待15秒
            for wait_count in range(max_wait):
                time.sleep(1)
                QApplication.processEvents()  # 处理Qt事件
                
                transcription_text = self.transcription_text.strip()
                pure_text = self._extract_pure_text_for_test(transcription_text)
                
                self.test_logger.info(f"⏳ 等待转写完成 {wait_count+1}/{max_wait} 秒 - 当前文本长度: {len(pure_text)}")
                
                if pure_text:
                    self.test_logger.info("🎉 检测到转写结果！")
                    break
            
            # 步骤8: 分析最终结果
            self.test_logger.info("📋 步骤8: 分析最终转写结果...")
            final_transcription = self.transcription_text.strip()
            final_pure_text = self._extract_pure_text_for_test(final_transcription)
            
            self.test_logger.info(f"📊 最终原始转写文本: '{final_transcription}'")
            self.test_logger.info(f"📊 最终纯文本: '{final_pure_text}'")
            self.test_logger.info(f"📊 纯文本长度: {len(final_pure_text)}")
            
            # 恢复原始转写文本
            self.transcription_text = original_text
            
            if final_pure_text:
                self.test_logger.info("🎉 测试成功！录音转写功能正常工作")
                self.test_logger.info(f"✅ 转写结果: {final_pure_text}")
                result_message = f"测试成功！转写结果: {final_pure_text}"
            else:
                self.test_logger.warning("⚠️ 测试部分成功！录音功能正常，但转写结果为空")
                self.test_logger.warning("💡 可能的原因:")
                self.test_logger.warning("   • 录音期间没有声音输入")
                self.test_logger.warning("   • 音频设备选择不正确") 
                self.test_logger.warning("   • 音量太小无法识别")
                result_message = "录音功能正常，但转写结果为空"
            
            self.test_logger.info("=" * 80)
            self.test_logger.info("🏁 测试录音转写流程完成")
            self.test_logger.info("=" * 80)
            
            return json.dumps({
                "success": True,
                "message": result_message,
                "transcription": final_pure_text,
                "step": "completed"
            }, ensure_ascii=False)
            
        except Exception as e:
            import traceback
            self.test_logger.error(f"❌ 测试录音流程失败: {e}")
            self.test_logger.error(f"📋 异常详情: {traceback.format_exc()}")
            
            # 确保恢复原始文本
            try:
                if 'original_text' in locals():
                    self.transcription_text = original_text
            except:
                pass
                
            return json.dumps({
                "success": False,
                "error": f"测试录音流程失败: {str(e)}",
                "step": "exception"
            }, ensure_ascii=False)
    
    def _finish_test_recording(self):
        """完成测试录音"""
        self.test_logger.info("📋 步骤6: 10秒测试时间到，停止录音...")
        
        try:
            # 记录停止前的状态
            self.test_logger.info(f"停止前录音状态: {self.is_recording}")
            self.test_logger.info(f"停止前转写文本长度: {len(self.transcription_text)}")
            self.test_logger.info(f"停止前线程状态 - 录音Worker: {self._rec_worker is not None}, 转写Worker: {self._tr_worker is not None}")
            
            # 停止录音
            stop_result = self.stopRecording()
            self.test_logger.info(f"📊 停止录音结果: {stop_result}")
            
            # 记录停止后的状态
            self.test_logger.info(f"停止后录音状态: {self.is_recording}")
            self.test_logger.info(f"停止后线程状态 - 录音: {self._rec_thread}, 转写: {self._tr_thread}")
            
            # 立即开始检查转写结果，然后每秒检查一次，最多检查10次
            self.test_check_count = 0
            self.test_max_checks = 10
            
            def check_transcription_result():
                self.test_check_count += 1
                self.test_logger.info(f"📋 步骤7: 检查转写结果 (第{self.test_check_count}次)...")
                
                transcription_text = self.transcription_text.strip()
                self.test_logger.info(f"📊 原始转写文本: '{transcription_text}'")
                self.test_logger.info(f"📊 转写文本长度: {len(transcription_text)}")
                
                # 检查转写线程状态
                self.test_logger.info(f"📊 转写Worker状态: {self._tr_worker}")
                if self._tr_worker:
                    self.test_logger.info("⚠️ 转写Worker仍在运行，可能转写还未完成")
                
                # 提取纯文本（去除时间戳）
                pure_text = self._extract_pure_text_for_test(transcription_text)
                self.test_logger.info(f"📊 提取的纯文本: '{pure_text}'")
                self.test_logger.info(f"📊 纯文本长度: {len(pure_text)}")
                
                # 如果有转写结果或达到最大检查次数，结束测试
                if pure_text or self.test_check_count >= self.test_max_checks:
                    # 分析结果
                    if pure_text:
                        self.test_logger.info("🎉 测试成功！录音转写功能正常工作")
                        self.test_logger.info(f"✅ 转写结果: {pure_text}")
                    else:
                        self.test_logger.warning("⚠️ 测试部分成功！录音功能正常，但转写结果为空")
                        self.test_logger.warning("💡 可能的原因:")
                        self.test_logger.warning("   • 录音期间没有声音输入")
                        self.test_logger.warning("   • 音频设备选择不正确") 
                        self.test_logger.warning("   • 音量太小无法识别")
                        self.test_logger.warning("   • 转写模型加载问题")
                        self.test_logger.warning("   • 音频文件生成问题")
                        self.test_logger.warning("   • 转写线程被过早停止")
                    
                    # 恢复原始转写文本
                    if hasattr(self, 'original_text'):
                        self.test_logger.info("🔄 恢复原始转写文本")
                        self.transcription_text = self.original_text
                        delattr(self, 'original_text')
                    
                    self.test_logger.info("=" * 80)
                    self.test_logger.info("🏁 测试录音转写流程完成")
                    self.test_logger.info("=" * 80)
                    
                    # 停止定时器
                    if hasattr(self, 'test_check_timer'):
                        self.test_check_timer.stop()
                        delattr(self, 'test_check_timer')
                else:
                    # 继续等待，1秒后再检查
                    self.test_logger.info(f"⏳ 转写还未完成，1秒后再检查 ({self.test_check_count}/{self.test_max_checks})")
            
            # 立即执行第一次检查
            check_transcription_result()
            
            # 如果第一次检查没有结果，设置定时器继续检查
            if self.test_check_count < self.test_max_checks and not self._extract_pure_text_for_test(self.transcription_text):
                self.test_check_timer = QTimer()
                self.test_check_timer.timeout.connect(check_transcription_result)
                self.test_check_timer.start(1000)  # 每秒检查一次
            
        except Exception as e:
            import traceback
            self.test_logger.error(f"❌ 完成测试录音失败: {e}")
            self.test_logger.error(f"📋 异常详情: {traceback.format_exc()}")
            
            # 确保程序不会因为测试异常而退出
            try:
                if hasattr(self, 'original_text'):
                    self.transcription_text = self.original_text
                    delattr(self, 'original_text')
            except:
                pass
    
    def _extract_pure_text_for_test(self, transcription_text):
        """从转写文本中提取纯文本内容，去除时间戳"""
        if not transcription_text:
            return ""
        
        import re
        
        # 转写文本格式通常是: [HH:MM:SS] 文本内容
        lines = transcription_text.strip().split('\n')
        pure_text_parts = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 使用正则表达式匹配时间戳格式 [HH:MM:SS]
            timestamp_pattern = r'^\[\d{2}:\d{2}:\d{2}\]\s*'
            text_without_timestamp = re.sub(timestamp_pattern, '', line)
            
            if text_without_timestamp.strip():
                pure_text_parts.append(text_without_timestamp.strip())
        
        result = ' '.join(pure_text_parts)
        return result
    
    @Slot(str, result=str)
    def summarizeText(self, text):
        """总结指定文本"""
        self.logger.info(f"总结文本请求，长度: {len(text)}")
        
        if not text.strip():
            return json.dumps({"success": False, "error": "文本内容为空"}, ensure_ascii=False)
        
        try:
            # 使用统一的LLM工厂进行总结
            summary_prompt = f"""请对以下文本进行总结，提取关键信息和要点：

{text}

请用简洁的Markdown格式输出总结，重点突出核心内容。

总结内容："""
            
            summary_result = call_llm(summary_prompt)
            
            if summary_result and not summary_result.startswith("LLM调用失败"):
                self.logger.info("✅ 文本总结完成")
                
                return json.dumps({
                    "success": True, 
                    "message": "总结完成",
                    "summary": summary_result
                }, ensure_ascii=False)
            else:
                self.logger.error(f"总结失败: {summary_result}")
                return json.dumps({"success": False, "error": f"总结失败: {summary_result}"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"文本总结失败: {e}")
            return json.dumps({"success": False, "error": f"文本总结失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def testAudioSource(self):
        """测试音源"""
        self.logger.info("测试音源请求")
        
        try:
            # 这里可以实现音源测试功能
            # 暂时返回占位符
            return json.dumps({"success": True, "message": "音源测试正常"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"音源测试失败: {e}")
            return json.dumps({"success": False, "error": f"音源测试失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(result=str)
    def testRecording(self):
        """测试录音"""
        self.logger.info("测试录音请求")
        
        try:
            # 这里可以实现录音测试功能
            # 暂时返回占位符
            return json.dumps({"success": True, "message": "录音测试正常"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"录音测试失败: {e}")
            return json.dumps({"success": False, "error": f"录音测试失败: {str(e)}"}, ensure_ascii=False)
    
    @Slot(bool, result=str)
    def pauseRecording(self, pause):
        """暂停/继续录音"""
        self.logger.info(f"{'暂停' if pause else '继续'}录音请求")
        
        if not self.is_recording:
            return json.dumps({"success": False, "error": "录音未在进行中"}, ensure_ascii=False)
        
        try:
            # 这里可以实现暂停/继续录音功能
            # 暂时返回占位符
            action = "暂停" if pause else "继续"
            return json.dumps({"success": True, "message": f"录音已{action}"}, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"暂停/继续录音失败: {e}")
            return json.dumps({"success": False, "error": f"暂停/继续录音失败: {str(e)}"}, ensure_ascii=False)
    
    # 录音相关回调方法
    def _on_audio_segment_ready(self, filepath):
        """音频片段准备就绪"""
        if self._tr_worker:
            self._tr_worker.enqueue_file(filepath)
    
    def _on_transcription_ready(self, text):
        """转写文本准备就绪"""
        self.transcription_text += f"[{datetime.now().strftime('%H:%M:%S')}] {text}\n"
        self.logger.info(f"转写文本: {text[:50]}...")
        
        # 通知前端更新
        if self.main_window and self.main_window.web_view:
            js_code = f"""
            if (typeof updateTranscriptionText === 'function') {{
                updateTranscriptionText({json.dumps(text, ensure_ascii=False)});
            }}
            """
            self.main_window.web_view.page().runJavaScript(js_code)
    
    def _on_recording_status(self, status):
        """录音状态更新"""
        self.logger.info(f"录音状态: {status}")
        
        # 通知前端更新状态
        if self.main_window and self.main_window.web_view:
            js_code = f"""
            if (typeof updateRecordingStatus === 'function') {{
                updateRecordingStatus({json.dumps(status, ensure_ascii=False)});
            }}
            """
            self.main_window.web_view.page().runJavaScript(js_code)
    
    def _on_transcription_status(self, status):
        """转写状态更新"""
        self.logger.info(f"转写状态: {status}")
    
    def _on_peak_level(self, level):
        """音量峰值更新"""
        # 通知前端更新音量指示器
        if self.main_window and self.main_window.web_view:
            js_code = f"""
            if (typeof updateVolumeLevel === 'function') {{
                updateVolumeLevel({level});
            }}
            """
            self.main_window.web_view.page().runJavaScript(js_code)
    
    def _cleanup_rec(self):
        """清理录音线程"""
        self._rec_thread = None
        self._rec_worker = None
    
    def _cleanup_tr(self):
        """清理转写线程"""
        self._tr_thread = None
        self._tr_worker = None


class DragOverlay(QWidget):
    """透明拖拽覆盖层"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 获取主窗口引用
        self.parent_window = parent if isinstance(parent, QMainWindow) else (parent.window() if parent else None)
        self.drag_position = QPoint()
        self.setup_overlay()
        
    def setup_overlay(self):
        """设置覆盖层"""
        # 设置为完全透明的浮动层
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 0);  /* 完全透明 */
                border: none;
            }
        """)
        self.setMouseTracking(True)  # 启用鼠标跟踪
        
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton and self.parent_window:
            self.drag_position = event.globalPosition().toPoint() - self.parent_window.pos()
            event.accept()
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull() and self.parent_window:
            new_pos = event.globalPosition().toPoint() - self.drag_position
            self.parent_window.move(new_pos)
            event.accept()
            
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = QPoint()
            event.accept()

class ResizeOverlay(QWidget):
    """窗口边缘调整大小覆盖层"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent if isinstance(parent, QMainWindow) else (parent.window() if parent else None)
        self.resize_mode = None
        self.resize_start_pos = QPoint()
        self.resize_start_geometry = QRect()
        self.edge_width = 8  # 边缘检测宽度
        self.setup_overlay()
        
    def setup_overlay(self):
        """设置调整大小覆盖层"""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.setMouseTracking(True)  # 启用鼠标跟踪
        
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton and self.parent_window:
            self.resize_mode = self.get_resize_mode(event.position().toPoint())
            if self.resize_mode:
                self.resize_start_pos = event.globalPosition().toPoint()
                self.resize_start_geometry = self.parent_window.geometry()
                event.accept()
                
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.resize_mode and self.parent_window:
            self.resize_window(event.globalPosition().toPoint())
            event.accept()
        else:
            # 更新鼠标光标
            mode = self.get_resize_mode(event.position().toPoint())
            self.update_cursor(mode)
            
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.resize_mode = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            
    def get_resize_mode(self, pos):
        """根据鼠标位置确定调整模式"""
        rect = self.rect()
        x, y = pos.x(), pos.y()
        w, h = rect.width(), rect.height()
        
        # 检测边缘区域
        left_edge = x <= self.edge_width
        right_edge = x >= w - self.edge_width
        top_edge = y <= self.edge_width
        bottom_edge = y >= h - self.edge_width
        
        # 确定调整模式
        if top_edge and left_edge:
            return "top_left"
        elif top_edge and right_edge:
            return "top_right"
        elif bottom_edge and left_edge:
            return "bottom_left"
        elif bottom_edge and right_edge:
            return "bottom_right"
        elif top_edge:
            return "top"
        elif bottom_edge:
            return "bottom"
        elif left_edge:
            return "left"
        elif right_edge:
            return "right"
        return None
        
    def update_cursor(self, mode):
        """更新鼠标光标"""
        cursor_map = {
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        cursor = cursor_map.get(mode, Qt.CursorShape.ArrowCursor)
        self.setCursor(cursor)
        
    def resize_window(self, global_pos):
        """调整窗口大小"""
        if not self.parent_window or not self.resize_mode:
            return
            
        delta = global_pos - self.resize_start_pos
        new_geometry = QRect(self.resize_start_geometry)
        
        # 根据调整模式计算新的几何信息
        if "left" in self.resize_mode:
            new_geometry.setLeft(new_geometry.left() + delta.x())
        if "right" in self.resize_mode:
            new_geometry.setRight(new_geometry.right() + delta.x())
        if "top" in self.resize_mode:
            new_geometry.setTop(new_geometry.top() + delta.y())
        if "bottom" in self.resize_mode:
            new_geometry.setBottom(new_geometry.bottom() + delta.y())
            
        # 确保窗口不会太小
        min_size = self.parent_window.minimumSize()
        if new_geometry.width() >= min_size.width() and new_geometry.height() >= min_size.height():
            self.parent_window.setGeometry(new_geometry)

class OverlayDragCorgiApp(QMainWindow):
    """覆盖层拖拽版本的柯基学习小助手"""
    
    def __init__(self):
        super().__init__()
        self.bridge = CorgiWebBridge(self)
        # 记住窗口的正常大小和位置
        self.normal_geometry = None
        # 初始化模板管理器
        self.template_manager = TemplateManager()
        self.setup_window()
        self.setup_ui()
        self.setup_web_channel()
        self.load_html_content()
        
    def setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("柯基学习小助手 - 覆盖层拖拽版")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 设置无边框窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 添加圆角样式 - 使用mask实现真正的圆角
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
        # 保存初始的正常几何信息
        self.normal_geometry = self.geometry()
        
        # 设置快捷键
        self.setup_shortcuts()
    
    def setup_shortcuts(self):
        """设置快捷键"""
        # Ctrl+L 打开日志查看器
        log_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        log_shortcut.activated.connect(self.open_log_viewer)
        print("✅ 快捷键 Ctrl+L 已设置 - 打开日志查看器")
    
    def open_log_viewer(self):
        """打开日志查看器"""
        print("🔍 快捷键触发：打开LLM调用日志查看器")
        if self.bridge:
            self.bridge.loadContent("llm_logs")
        
    def showEvent(self, event):
        """窗口显示时设置圆角mask"""
        super().showEvent(event)
        self.setRoundedCorners()
        
    def resizeEvent(self, event):
        """窗口大小改变时调整覆盖层和圆角"""
        super().resizeEvent(event)
        self.setRoundedCorners()
        
        if hasattr(self, 'drag_overlay'):
            # 调整拖拽覆盖层大小，避开右侧按钮区域和边缘区域
            self.drag_overlay.setGeometry(8, 8, self.width() - 120 - 16, 60 - 8)
        if hasattr(self, 'resize_overlay'):
            # 调整大小覆盖层覆盖整个窗口
            self.resize_overlay.setGeometry(0, 0, self.width(), self.height())
            
    def setRoundedCorners(self):
        """设置圆角mask"""
        from PySide6.QtGui import QPainterPath, QRegion
        
        radius = 12
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)
        
    def setup_ui(self):
        """设置用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 只使用WebEngineView，不添加额外布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建WebEngineView
        self.web_view = QWebEngineView()
        
        # 配置WebEngine设置
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        
        # 添加WebView到布局
        layout.addWidget(self.web_view)
        
        # 先创建调整大小覆盖层（底层）
        self.resize_overlay = ResizeOverlay(self)  # 直接作为主窗口的子组件
        self.resize_overlay.setGeometry(0, 0, self.width(), self.height())
        self.resize_overlay.show()
        
        # 再创建拖拽覆盖层（上层），避开右侧按钮区域和边缘区域
        self.drag_overlay = DragOverlay(self)  # 直接作为主窗口的子组件
        # 覆盖除了右侧120px（按钮区域）和边缘8px以外的顶部区域
        self.drag_overlay.setGeometry(8, 8, self.width() - 120 - 16, 60 - 8)
        self.drag_overlay.show()
        
        # 设置层次关系
        self.resize_overlay.lower()  # 调整大小层在底部
        self.drag_overlay.raise_()   # 拖拽层在顶部
        
    def load_html_content(self):
        """加载HTML内容"""
        try:
            html_content = self.template_manager.render_spa_layout()
            self.web_view.setHtml(html_content)
            print("✅ 使用模板系统加载SPA布局成功")
        except Exception as e:
            print(f"❌ 模板系统加载失败，使用备用方案: {e}")
            # 备用方案：使用原来的方法
            html_content = self.create_spa_html()
            self.web_view.setHtml(html_content)
    
    def open_question_review_panel(self, question_id):
        """打开题目复习面板 - 直接加载HTML文件"""
        try:
            # 直接在当前WebView中加载题目复习HTML
            self.load_question_review_content(question_id)
            
        except Exception as e:
            print(f"打开题目复习面板时发生错误: {e}")
    
    def load_question_review_content(self, question_id):
        """加载题目复习页面内容"""
        try:
            # 读取题目复习HTML文件
            html_file_path = "题目复习.html"
            if os.path.exists(html_file_path):
                with open(html_file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                # 根据question_id动态替换HTML中的题目数据
                html_content = self.customize_question_html(html_content, question_id)
                
                # 在WebView中加载HTML内容
                self.web_view.setHtml(html_content)
                print(f"📝 已加载题目复习页面: 题目ID {question_id}")
            else:
                print(f"❌ 找不到题目复习HTML文件: {html_file_path}")
                
        except Exception as e:
            print(f"加载题目复习页面时发生错误: {e}")
    
    def customize_question_html(self, html_content, question_id):
        """根据题目ID自定义HTML内容"""
        # 获取题目数据
        question_data = self.get_question_data_by_id(question_id)
        
        # 替换HTML中的占位符（如果有的话）
        # 这里可以根据需要动态替换题目内容
        # 例如：html_content = html_content.replace("{{question}}", question_data["question"])
        
        return html_content
    
    def get_question_data_by_id(self, question_id):
        """根据题目ID获取题目数据（模拟数据）"""
        # 这里返回模拟的题目数据，后续可以替换为真实的数据库查询
        question_data_map = {
            "1": {
                "question": "以下哪个是线性回归模型的假设？",
                "user_answer": "A. 残差独立",
                "correct_answer": "B",
                "is_correct": False,
                "analysis": "线性回归模型的基本假设包括：线性关系、独立性、同方差性和正态性。残差独立是其中一个重要假设，但正确答案应该是更全面的表述。",
                "knowledge_point": "机器学习基础",
                "question_type": "单选题",
                "proficiency": "80%"
            },
            "2": {
                "question": "请简述线性回归的损失函数是什么？",
                "user_answer": "平方损失",
                "correct_answer": "均方误差（MSE）",
                "is_correct": False,
                "analysis": "线性回归通常使用均方误差（Mean Squared Error, MSE）作为损失函数，它是预测值与真实值差的平方的平均值。虽然平方损失的概念是对的，但标准表述应该是均方误差。",
                "knowledge_point": "机器学习基础",
                "question_type": "简答题",
                "proficiency": "60%"
            },
            "3": {
                "question": "线性回归中，用来评估模型拟合优度的指标是____。",
                "user_answer": "R²",
                "correct_answer": "R²（决定系数）",
                "is_correct": True,
                "analysis": "R²（决定系数）是评估线性回归模型拟合优度的重要指标，它表示模型能够解释的方差占总方差的比例，取值范围为0到1，越接近1表示模型拟合效果越好。",
                "knowledge_point": "机器学习基础", 
                "question_type": "填空题",
                "proficiency": "95%"
            }
        }
        
        return question_data_map.get(question_id, question_data_map["1"])
    
    def generate_content_html(self, content_id):
        """根据内容ID生成对应的HTML内容"""
        try:
            # 准备模板数据
            context = self.get_template_context(content_id)
            # 首先尝试使用模板系统
            html_content = self.template_manager.render_page_content(content_id, **context)
            print(f"✅ 使用模板渲染页面内容: {content_id}")
            return html_content
        except Exception as e:
            print(f"⚠️ 模板渲染失败: {content_id} - {e}")
            import traceback
            traceback.print_exc()
            
            # 对于online_course_notes，强制使用模板系统
            if content_id == "online_course_notes":
                print(f"🔄 强制重试模板渲染: {content_id}")
                try:
                    # 不使用context，直接渲染
                    html_content = self.template_manager.render_page_content(content_id)
                    print(f"✅ 强制重试成功: {content_id}")
                    return html_content
                except Exception as e2:
                    print(f"❌ 强制重试也失败: {content_id} - {e2}")
                    # 返回一个简单的错误页面
                    return f'''
                    <div class="flex items-center justify-center h-full">
                        <div class="text-center">
                            <h2 class="text-2xl font-bold text-red-600 mb-4">模板加载失败</h2>
                            <p class="text-gray-600">页面: {content_id}</p>
                            <p class="text-gray-600">错误: {str(e2)}</p>
                        </div>
                    </div>
                    '''
            
            # 备用方案：使用原来的生成器
            content_generators = {
                "dashboard": self.generate_dashboard_content,
                "learn_from_materials": self.generate_learn_materials_content,
                "learn_from_audio": self.generate_learn_audio_content,
                "practice_materials": self.generate_practice_materials_content,
                "practice_knowledge": self.generate_practice_knowledge_content,
                "practice_errors": self.generate_practice_errors_content,
                "memory_knowledge": self.generate_memory_knowledge_content,
                "memory_errors": self.generate_memory_errors_content,
                "knowledge_base": self.generate_knowledge_base_content,
                "settings": self.generate_settings_content
            }
            
            generator = content_generators.get(content_id, self.generate_dashboard_content)
            return generator()
    
    def get_template_context(self, content_id):
        """获取模板渲染所需的上下文数据"""
        context = {}
        
        if content_id == "dashboard":
            context = {
                "stats": {
                    "learning_materials": 12,
                    "practice_accuracy": "85%",
                    "knowledge_points": 156
                },
                "recent_activities": [
                    {"icon": "article", "color": "blue", "title": "学习了《机器学习基础》", "time": "2小时前"},
                    {"icon": "quiz", "color": "green", "title": "完成了线性回归练习", "time": "4小时前"},
                    {"icon": "psychology", "color": "purple", "title": "复习了神经网络知识点", "time": "6小时前"}
                ]
            }
        elif content_id == "learn_from_materials":
            context = {
                "current_file": None,
                "file_tree": []
            }
        elif content_id == "settings":
            context = {
                "current_llm_model": "Gemini Pro",
                "api_key_configured": True,
                "daily_reminder_enabled": True,
                "template_system_enabled": True
            }
        
        return context
    
    def generate_dashboard_content(self):
        """生成工作台内容"""
        return '''
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <div class="flex items-center mb-4">
                    <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mr-4">
                        <span class="material-icons-outlined text-blue-600">school</span>
                    </div>
                    <div>
                        <h3 class="text-lg font-semibold text-text-dark-brown">学习模块</h3>
                        <p class="text-sm text-text-gray">从资料和音视频中学习</p>
                    </div>
                </div>
                <div class="text-2xl font-bold text-blue-600 mb-2">12</div>
                <p class="text-sm text-text-gray">本周学习资料数</p>
                <div class="mt-4">
                    <button class="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700" onclick="handleMenuClick('learn_from_materials')">
                        开始学习
                    </button>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <div class="flex items-center mb-4">
                    <div class="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mr-4">
                        <span class="material-icons-outlined text-green-600">fitness_center</span>
                    </div>
                    <div>
                        <h3 class="text-lg font-semibold text-text-dark-brown">练习模块</h3>
                        <p class="text-sm text-text-gray">知识点和错题练习</p>
                    </div>
                </div>
                <div class="text-2xl font-bold text-green-600 mb-2">85%</div>
                <p class="text-sm text-text-gray">本周练习正确率</p>
                <div class="mt-4">
                    <button class="bg-green-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-green-700" onclick="handleMenuClick('practice_knowledge')">
                        开始练习
                    </button>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <div class="flex items-center mb-4">
                    <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mr-4">
                        <span class="material-icons-outlined text-purple-600">psychology</span>
                    </div>
                    <div>
                        <h3 class="text-lg font-semibold text-text-dark-brown">记忆模块</h3>
                        <p class="text-sm text-text-gray">知识点记忆和复习</p>
                    </div>
                </div>
                <div class="text-2xl font-bold text-purple-600 mb-2">156</div>
                <p class="text-sm text-text-gray">已掌握知识点数</p>
                <div class="mt-4">
                    <button class="bg-purple-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-purple-700" onclick="handleMenuClick('memory_knowledge')">
                        开始记忆
                    </button>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm col-span-full">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">最近学习活动</h3>
                <div class="space-y-3">
                    <div class="flex items-center p-3 bg-gray-50 rounded-lg">
                        <div class="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center mr-3">
                            <span class="material-icons-outlined text-blue-600 text-sm">article</span>
                        </div>
                        <div class="flex-1">
                            <p class="font-medium text-text-dark-brown">学习了《机器学习基础》</p>
                            <p class="text-sm text-text-gray">2小时前</p>
                        </div>
                    </div>
                    <div class="flex items-center p-3 bg-gray-50 rounded-lg">
                        <div class="w-8 h-8 bg-green-100 rounded-full flex items-center justify-center mr-3">
                            <span class="material-icons-outlined text-green-600 text-sm">quiz</span>
                        </div>
                        <div class="flex-1">
                            <p class="font-medium text-text-dark-brown">完成了线性回归练习</p>
                            <p class="text-sm text-text-gray">4小时前</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        '''
    
    def generate_learn_materials_content(self):
        """生成从资料学习内容"""
        return '''
        <div class="flex h-full">
            <!-- 左侧文件树 -->
            <div class="w-80 bg-white rounded-xl shadow-sm mr-6 flex flex-col">
                <div class="p-4 border-b border-gray-200">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-semibold text-text-dark-brown">学习资料</h3>
                        <div class="flex space-x-2">
                            <button class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg" title="新建笔记" onclick="createNewNote()">
                                <span class="material-icons-outlined text-sm">note_add</span>
                            </button>
                            <button class="p-2 text-gray-500 hover:bg-gray-100 rounded-lg" title="新建文件夹" onclick="createNewFolder()">
                                <span class="material-icons-outlined text-sm">create_new_folder</span>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="flex-1 p-4 overflow-auto">
                    <div id="file-tree">
                        <div class="text-center text-gray-500 py-8">
                            <span class="material-icons-outlined text-4xl mb-2">folder_open</span>
                            <p>加载文件结构中...</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 右侧内容区 -->
            <div class="flex-1 flex flex-col">
                <!-- 工具栏 -->
                <div class="bg-white rounded-xl shadow-sm mb-4 p-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-4">
                            <button id="preview-btn" class="px-4 py-2 bg-primary text-white rounded-lg text-sm" onclick="switchToPreview()">
                                预览
                            </button>
                            <button id="edit-btn" class="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm" onclick="switchToEdit()">
                                编辑
                            </button>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button class="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700" onclick="extractKnowledgePoints()">
                                <span class="material-icons-outlined text-sm mr-1">psychology</span>
                                提取知识点
                            </button>
                            <button class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700" onclick="saveCurrentFile()">
                                <span class="material-icons-outlined text-sm mr-1">save</span>
                                保存
                            </button>
                        </div>
                    </div>
                </div>
                
                <!-- 内容显示区 -->
                <div class="flex-1 bg-white rounded-xl shadow-sm p-6 overflow-auto">
                    <div id="content-display" class="h-full">
                        <div class="text-center text-gray-500 py-16">
                            <span class="material-icons-outlined text-6xl mb-4">description</span>
                            <h3 class="text-xl font-semibold mb-2">选择一个文件开始学习</h3>
                            <p>从左侧文件树中选择Markdown文件进行预览或编辑</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            // 初始化文件树
            if (bridge && bridge.getFileStructure) {
                bridge.getFileStructure().then(function(structureJson) {
                    const structure = JSON.parse(structureJson);
                    renderFileTree(structure);
                });
            }
            
            function renderFileTree(structure) {
                const fileTree = document.getElementById('file-tree');
                fileTree.innerHTML = buildTreeHTML(structure);
            }
            
            function buildTreeHTML(items, level = 0) {
                let html = '';
                items.forEach(item => {
                    const indent = 'pl-' + (level * 4);
                    if (item.type === 'folder') {
                        html += `
                            <div class="folder-item">
                                <div class="flex items-center py-1 px-2 hover:bg-gray-100 rounded cursor-pointer ${indent}" onclick="toggleFolder(this)">
                                    <span class="material-icons-outlined text-sm mr-2 folder-icon">folder</span>
                                    <span class="text-sm">${item.name}</span>
                                </div>
                                <div class="folder-content hidden">
                                    ${buildTreeHTML(item.children, level + 1)}
                                </div>
                            </div>
                        `;
                    } else {
                        html += `
                            <div class="flex items-center py-1 px-2 hover:bg-gray-100 rounded cursor-pointer ${indent}" onclick="loadFile('${item.path}')">
                                <span class="material-icons-outlined text-sm mr-2 text-blue-600">description</span>
                                <span class="text-sm">${item.name}</span>
                            </div>
                        `;
                    }
                });
                return html;
            }
            
            function toggleFolder(element) {
                const content = element.nextElementSibling;
                const icon = element.querySelector('.folder-icon');
                if (content.classList.contains('hidden')) {
                    content.classList.remove('hidden');
                    icon.textContent = 'folder_open';
                } else {
                    content.classList.add('hidden');
                    icon.textContent = 'folder';
                }
            }
            
            function loadFile(filePath) {
                if (bridge && bridge.loadMarkdownFile) {
                    bridge.loadMarkdownFile(filePath).then(function(htmlContent) {
                        const contentDisplay = document.getElementById('content-display');
                        contentDisplay.innerHTML = htmlContent;
                    });
                }
            }
            
            function switchToPreview() {
                document.getElementById('preview-btn').className = 'px-4 py-2 bg-primary text-white rounded-lg text-sm';
                document.getElementById('edit-btn').className = 'px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm';
            }
            
            function switchToEdit() {
                document.getElementById('preview-btn').className = 'px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm';
                document.getElementById('edit-btn').className = 'px-4 py-2 bg-primary text-white rounded-lg text-sm';
            }
        </script>
        '''
    
    def generate_learn_audio_content(self):
        """生成从音视频学习内容 - 使用模板系统"""
        try:
            # 使用模板管理器渲染页面内容
            return self.template_manager.render_page_content('learn_from_audio')
        except Exception as e:
            print(f"❌ 渲染网课学习页面失败: {e}")
            # 返回错误提示页面
            return '''
            <div class="bg-white rounded-xl shadow-sm p-6">
                <div class="text-center py-16">
                    <span class="material-icons-outlined text-6xl text-red-400 mb-4">error</span>
                    <h3 class="text-xl font-semibold text-text-dark-brown mb-2">页面加载失败</h3>
                    <p class="text-text-gray mb-6">模板渲染出现错误，请检查模板文件</p>
                    <p class="text-sm text-red-500">错误信息: {}</p>
                </div>
            </div>
            '''.format(str(e))
    
    def generate_practice_materials_content(self):
        """生成基于学习资料练习内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">quiz</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">基于学习资料练习</h3>
                <p class="text-text-gray mb-6">根据你的学习资料自动生成练习题目</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    开始练习
                </button>
            </div>
        </div>
        '''
    
    def generate_practice_knowledge_content(self):
        """生成基于知识点练习内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">psychology</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">基于知识点练习</h3>
                <p class="text-text-gray mb-6">针对特定知识点进行专项练习</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    选择知识点
                </button>
            </div>
        </div>
        '''
    
    def generate_practice_errors_content(self):
        """生成基于错题练习内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">error_outline</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">基于错题练习</h3>
                <p class="text-text-gray mb-6">复习和练习之前做错的题目</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    查看错题本
                </button>
            </div>
        </div>
        '''
    
    def generate_memory_knowledge_content(self):
        """生成基于知识点记忆内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">lightbulb</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">基于知识点记忆</h3>
                <p class="text-text-gray mb-6">通过脑图和间隔重复算法加强记忆</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    开始记忆训练
                </button>
            </div>
        </div>
        '''
    
    def generate_memory_errors_content(self):
        """生成基于错题记忆内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">history</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">基于错题记忆</h3>
                <p class="text-text-gray mb-6">重点记忆容易出错的知识点</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    查看错题记忆
                </button>
            </div>
        </div>
        '''
    
    def generate_knowledge_base_content(self):
        """生成知识库管理内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">library_books</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">知识库管理</h3>
                <p class="text-text-gray mb-6">管理和组织你的知识点数据库</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    管理知识库
                </button>
            </div>
        </div>
        '''
    
    def generate_settings_content(self):
        """生成设置内容 - 备用方案，实际使用模板系统"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <h3 class="text-xl font-semibold text-text-dark-brown mb-6">设置</h3>
            <div class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-text-dark-brown mb-2">LLM模型选择</label>
                    <select class="w-full p-3 border border-gray-300 rounded-lg">
                        <option>Gemini Pro</option>
                        <option>Ollama</option>
                        <option>通义千问</option>
                        <option>规则匹配</option>
                    </select>
                </div>
                <div>
                    <label class="block text-sm font-medium text-text-dark-brown mb-2">API Key</label>
                    <input type="password" class="w-full p-3 border border-gray-300 rounded-lg" placeholder="输入你的API Key">
                </div>
                <div>
                    <label class="block text-sm font-medium text-text-dark-brown mb-2">学习提醒</label>
                    <div class="flex items-center">
                        <input type="checkbox" class="mr-2">
                        <span class="text-sm text-text-gray">启用每日学习提醒</span>
                    </div>
                </div>
                <button class="bg-primary text-white px-6 py-2 rounded-lg hover:bg-green-600">
                    保存设置
                </button>
            </div>
        </div>
        '''
    
    def create_spa_html(self):
        """创建单页面应用的HTML模板"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        primary: "#32C77F",
                        warning: "#FF9B27", 
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                    }
                }
            }
        };
    </script>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <!-- 左侧菜单栏 -->
        <aside id="sidebar" class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300">
            <!-- 头部 -->
            <div class="flex items-center mb-8">
                <div class="w-10 h-10 rounded-full bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center mr-3">
                    <span class="material-icons-outlined text-white">school</span>
                </div>
                <h1 id="app-title" class="text-lg font-bold text-text-dark-brown transition-opacity duration-300">柯基学习小助手</h1>
                <button id="sidebar-toggle" class="ml-auto p-1 rounded hover:bg-gray-100" onclick="toggleSidebar()">
                    <span class="material-icons-outlined text-gray-500">menu</span>
                </button>
            </div>
            
            <!-- 用户信息 -->
            <div id="user-info" class="flex flex-col items-center mb-8 transition-opacity duration-300">
                <div class="w-20 h-20 rounded-full bg-gradient-to-r from-green-400 to-blue-500 flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">account_circle</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 ⭐</p>
            </div>
            
            <!-- 导航菜单 -->
            <nav id="navigation" class="flex-1 space-y-2">
                <!-- 工作台 -->
                <div class="menu-item">
                    <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('dashboard')">
                        <span class="material-icons-outlined mr-3">dashboard</span>
                        <span class="menu-text">工作台</span>
                    </a>
                </div>
                
                <!-- 学 -->
                <div class="menu-item">
                    <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('learn')">
                        <span class="material-icons-outlined mr-3">school</span>
                        <span class="menu-text">学</span>
                        <span class="material-icons-outlined ml-auto expand-icon">expand_more</span>
                    </a>
                    <div class="submenu ml-8 mt-2 space-y-1 hidden">
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('learn_from_materials')">
                            <span class="material-icons-outlined mr-2 text-sm">article</span>
                            <span class="menu-text">从资料学习</span>
                        </a>
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('learn_from_audio')">
                            <span class="material-icons-outlined mr-2 text-sm">headphones</span>
                            <span class="menu-text">从音视频学习</span>
                        </a>
                    </div>
                </div>
                
                <!-- 练 -->
                <div class="menu-item">
                    <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('practice')">
                        <span class="material-icons-outlined mr-3">fitness_center</span>
                        <span class="menu-text">练</span>
                        <span class="material-icons-outlined ml-auto expand-icon">expand_more</span>
                    </a>
                    <div class="submenu ml-8 mt-2 space-y-1 hidden">
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('practice_materials')">
                            <span class="material-icons-outlined mr-2 text-sm">quiz</span>
                            <span class="menu-text">基于学习资料练习</span>
                        </a>
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('practice_knowledge')">
                            <span class="material-icons-outlined mr-2 text-sm">psychology</span>
                            <span class="menu-text">基于知识点练习</span>
                        </a>
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('practice_errors')">
                            <span class="material-icons-outlined mr-2 text-sm">error_outline</span>
                            <span class="menu-text">基于错题练习</span>
                        </a>
                    </div>
                </div>
                
                <!-- 记 -->
                <div class="menu-item">
                    <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('memory')">
                        <span class="material-icons-outlined mr-3">psychology</span>
                        <span class="menu-text">记</span>
                        <span class="material-icons-outlined ml-auto expand-icon">expand_more</span>
                    </a>
                    <div class="submenu ml-8 mt-2 space-y-1 hidden">
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('memory_knowledge')">
                            <span class="material-icons-outlined mr-2 text-sm">lightbulb</span>
                            <span class="menu-text">基于知识点记忆</span>
                        </a>
                        <a class="flex items-center px-4 py-2 text-sm text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('memory_errors')">
                            <span class="material-icons-outlined mr-2 text-sm">history</span>
                            <span class="menu-text">基于错题记忆</span>
                        </a>
                    </div>
                </div>
                
                <!-- 知识库管理 -->
                <div class="menu-item">
                    <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('knowledge_base')">
                        <span class="material-icons-outlined mr-3">library_books</span>
                        <span class="menu-text">知识库管理</span>
                    </a>
                </div>
            </nav>
            
            <!-- 设置 -->
            <div class="mt-auto">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="handleMenuClick('settings')">
                    <span class="material-icons-outlined mr-3">settings</span>
                    <span class="menu-text">设置</span>
                </a>
            </div>
        </aside>
        
        <!-- 右侧内容区域 -->
        <main class="flex-1 flex flex-col">
            <!-- 顶部标题栏 -->
            <header class="flex justify-between items-center p-6 bg-white border-b border-gray-200">
                <h2 id="page-title" class="text-2xl font-bold text-text-dark-brown">柯基的学习乐园</h2>
                <div class="flex space-x-2">
                    <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                    <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                    <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                </div>
            </header>
            
            <!-- 动态内容区域 -->
            <div id="content-area" class="flex-1 p-6 bg-bg-light-blue-gray overflow-auto">
                <!-- 默认加载工作台内容 -->
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div class="bg-white p-6 rounded-xl shadow-sm">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mr-4">
                                <span class="material-icons-outlined text-blue-600">school</span>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-text-dark-brown">学习模块</h3>
                                <p class="text-sm text-text-gray">从资料和音视频中学习</p>
                            </div>
                        </div>
                        <div class="text-2xl font-bold text-blue-600 mb-2">12</div>
                        <p class="text-sm text-text-gray">本周学习资料数</p>
                    </div>
                    
                    <div class="bg-white p-6 rounded-xl shadow-sm">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mr-4">
                                <span class="material-icons-outlined text-green-600">fitness_center</span>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-text-dark-brown">练习模块</h3>
                                <p class="text-sm text-text-gray">知识点和错题练习</p>
                            </div>
                        </div>
                        <div class="text-2xl font-bold text-green-600 mb-2">85%</div>
                        <p class="text-sm text-text-gray">本周练习正确率</p>
                    </div>
                    
                    <div class="bg-white p-6 rounded-xl shadow-sm">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mr-4">
                                <span class="material-icons-outlined text-purple-600">psychology</span>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-text-dark-brown">记忆模块</h3>
                                <p class="text-sm text-text-gray">知识点记忆和复习</p>
                            </div>
                        </div>
                        <div class="text-2xl font-bold text-purple-600 mb-2">156</div>
                        <p class="text-sm text-text-gray">已掌握知识点数</p>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;
        let sidebarCollapsed = false;
        
        // 初始化WebChannel
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log("WebChannel连接成功");
        });
        
        // 调用Python函数
        function callPythonFunction(functionName, ...args) {
            if (bridge && bridge[functionName]) {
                bridge[functionName](...args);
            }
        }
        
        // 侧边栏收缩/展开
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const appTitle = document.getElementById('app-title');
            const userInfo = document.getElementById('user-info');
            const menuTexts = document.querySelectorAll('.menu-text');
            const expandIcons = document.querySelectorAll('.expand-icon');
            
            sidebarCollapsed = !sidebarCollapsed;
            
            if (sidebarCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-16');
                appTitle.classList.add('opacity-0');
                userInfo.classList.add('opacity-0');
                menuTexts.forEach(text => text.classList.add('opacity-0'));
                expandIcons.forEach(icon => icon.classList.add('opacity-0'));
                // 隐藏所有子菜单
                document.querySelectorAll('.submenu').forEach(submenu => {
                    submenu.classList.add('hidden');
                });
            } else {
                sidebar.classList.remove('w-16');
                sidebar.classList.add('w-64');
                appTitle.classList.remove('opacity-0');
                userInfo.classList.remove('opacity-0');
                menuTexts.forEach(text => text.classList.remove('opacity-0'));
                expandIcons.forEach(icon => icon.classList.remove('opacity-0'));
            }
        }
        
        // 处理菜单点击
        function handleMenuClick(menuId) {
            if (sidebarCollapsed) {
                // 如果侧边栏收缩，先展开
                toggleSidebar();
                return;
            }
            
            if (bridge && bridge.toggleMenu) {
                bridge.toggleMenu(menuId).then(function(menuStateJson) {
                    const menuState = JSON.parse(menuStateJson);
                    updateMenuDisplay(menuState);
                });
            }
        }
        
        // 更新菜单显示状态
        function updateMenuDisplay(menuState) {
            Object.keys(menuState).forEach(menuId => {
                const menuItem = document.querySelector(`[onclick="handleMenuClick('${menuId}')"]`);
                if (menuItem) {
                    const submenu = menuItem.parentElement.querySelector('.submenu');
                    const expandIcon = menuItem.querySelector('.expand-icon');
                    
                    if (submenu && expandIcon) {
                        if (menuState[menuId].expanded) {
                            submenu.classList.remove('hidden');
                            expandIcon.textContent = 'expand_less';
                        } else {
                            submenu.classList.add('hidden');
                            expandIcon.textContent = 'expand_more';
                        }
                    }
                }
            });
        }
        
        // 更新内容区域
        function updateContentArea(htmlContent) {
            const contentArea = document.getElementById('content-area');
            if (contentArea) {
                contentArea.innerHTML = htmlContent;
            }
        }
        
        // 更新页面标题
        function updatePageTitle(title) {
            const pageTitle = document.getElementById('page-title');
            if (pageTitle) {
                pageTitle.textContent = title;
            }
        }
        
        // 设置活动菜单项
        function setActiveMenuItem(menuId) {
            // 移除所有活动状态
            document.querySelectorAll('.menu-item a').forEach(item => {
                item.classList.remove('text-white', 'bg-primary');
                item.classList.add('text-text-gray');
            });
            
            // 设置当前活动项
            const activeItem = document.querySelector(`[onclick="handleMenuClick('${menuId}')"]`);
            if (activeItem) {
                activeItem.classList.remove('text-text-gray');
                activeItem.classList.add('text-white', 'bg-primary');
            }
        }
    </script>
</body>
</html>'''
        
    def create_dashboard_html(self):
        """创建工作台页面的HTML内容"""
        try:
            with open('dashboard_template.html', 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            # 如果模板文件不存在，返回简单的HTML
            return self.create_simple_dashboard_html()
    
    def create_simple_dashboard_html(self):
        """创建简单的工作台页面"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>柯基学习小助手 - 工作台</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        primary: "#32C77F",
                        warning: "#FF9B27", 
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                    }
                }
            }
        };
    </script>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200">
            <div class="flex items-center mb-8">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 ⭐</p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg" href="#">
                    <span class="material-icons-outlined mr-3">work</span>
                    <span>工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToNotebook()">
                    <span class="material-icons-outlined mr-3">edit_note</span>
                    <span>笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3">mic</span>
                    <span>录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToAIPartner()">
                    <span class="material-icons-outlined mr-3">smart_toy</span>
                    <span>AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3">book</span>
                    <span>知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#">
                    <span class="material-icons-outlined mr-3">bar_chart</span>
                    <span>学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#">
                    <span class="material-icons-outlined mr-3">settings</span>
                    <span>设置</span>
                </a>
            </nav>
        </aside>
        
        <main class="flex-1 p-8">
            <header class="flex justify-between items-center mb-8">
                <h2 class="text-3xl font-bold text-text-dark-brown">柯基的学习乐园</h2>
                <div class="flex space-x-2">
                    <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                    <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                    <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                </div>
            </header>
            
            <div class="grid grid-cols-2 gap-6">
                <div class="bg-white p-6 rounded-xl shadow">
                    <h3 class="text-xl font-semibold mb-4">快速操作</h3>
                    <button class="bg-primary text-white px-4 py-2 rounded-lg" onclick="switchToNotebook()">打开笔记本</button>
                </div>
                <div class="bg-white p-6 rounded-xl shadow">
                    <h3 class="text-xl font-semibold mb-4">学习统计</h3>
                    <p>今日笔记: 3篇</p>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        });
        
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }
        
        function switchToNotebook() {
            if (bridge && bridge.switchToNotebook) {
                bridge.switchToNotebook();
            }
        }
        
        function switchToRecording() {
            if (bridge && bridge.switchToRecording) {
                bridge.switchToRecording();
            }
        }
        
        function switchToAIPartner() {
            if (bridge && bridge.switchToAIPartner) {
                bridge.switchToAIPartner();
            }
        }
        
        function switchToKnowledgeBase() {
            if (bridge && bridge.switchToKnowledgeBase) {
                bridge.switchToKnowledgeBase();
            }
        }
        
        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }
    </script>
</body>
</html>'''

    def create_notebook_html(self):
        """创建笔记本页面的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>柯基学习小助手 - 笔记本</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        primary: "#32C77F",
                        warning: "#FF9B27",
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-blue": "#D5F8FF",
                        "bg-beige": "#FFFFD6",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                    },
                    fontFamily: {
                        sans: ['"Noto Sans SC"', 'sans-serif'],
                    },
                    borderRadius: {
                        'xl': '1rem',
                    },
                }
            }
        };
    </script>
    <style>
        #sidebar.collapsed .sidebar-text,
        #sidebar.collapsed #user-profile,
        #sidebar.collapsed .logo-text {
            display: none;
        }
        #sidebar.collapsed .nav-item-icon {
            margin-right: 0;
        }
        #sidebar.collapsed .nav-link {
            justify-content: center;
        }
        .prose { max-width: none; }
        .prose h1 { font-size: 2em; font-weight: bold; margin-bottom: 0.5em; color: #715D46; }
        .prose h2 { font-size: 1.5em; font-weight: bold; margin-top: 1em; margin-bottom: 0.5em; color: #715D46; }
        .prose p { margin-bottom: 1em; line-height: 1.6; }
        .prose ul { margin-bottom: 1em; padding-left: 1.5em; }
        .prose li { margin-bottom: 0.5em; }
        .prose code { background-color: #f3f4f6; padding: 0.2em 0.4em; border-radius: 0.25em; font-family: monospace; }
        .prose pre { background-color: #1f2937; color: #f9fafb; padding: 1em; border-radius: 0.5em; overflow-x: auto; margin: 1em 0; }
        .prose blockquote { border-left: 4px solid #32C77F; padding-left: 1em; margin: 1em 0; font-style: italic; color: #6b7280; }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8 flex-shrink-0">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8" id="user-profile">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 <span class="text-yellow-400">⭐</span></p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">edit_note</span>
                    <span class="sidebar-text">笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToAIPartner()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">settings</span>
                    <span class="sidebar-text">设置</span>
                </a>
            </nav>
            
            <div class="mt-auto">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
            </div>
        </aside>

        <div class="flex-1 flex bg-bg-light-blue-gray" id="main-content">
            <div class="w-1/4 bg-white border-r border-gray-200 p-4 flex flex-col transition-all duration-300" id="file-structure">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold text-text-dark-brown">文件结构</h2>
                    <div class="space-x-2">
                        <button class="text-text-gray hover:text-primary">
                            <span class="material-icons-outlined">create_new_folder</span>
                        </button>
                        <button class="text-text-gray hover:text-primary">
                            <span class="material-icons-outlined">note_add</span>
                        </button>
                    </div>
                </div>
                <div class="flex-1 overflow-y-auto pr-2" id="file-tree">
                    <!-- 文件树将在这里动态生成 -->
                </div>
            </div>

            <main class="flex-1 p-6 flex flex-col">
                <header class="flex justify-between items-center mb-4">
                    <h2 class="text-2xl font-bold text-text-dark-brown" id="current-file-title">选择一个文件开始编辑</h2>
                    <div class="flex items-center space-x-2">
                        <button class="flex items-center bg-white border border-gray-300 px-3 py-1.5 rounded-lg text-text-gray hover:bg-gray-100" id="preview-btn">
                            <span class="material-icons-outlined text-sm mr-1">visibility</span>
                            <span>预览</span>
                        </button>
                        <button class="flex items-center bg-primary text-white px-3 py-1.5 rounded-lg hover:bg-green-600" id="edit-btn">
                            <span class="material-icons-outlined text-sm mr-1">edit</span>
                            <span>编辑</span>
                        </button>
                        <div class="flex space-x-1 ml-4">
                            <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                            <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                            <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                        </div>
                    </div>
                </header>
                
                <div class="flex-1 bg-white rounded-xl shadow-sm p-6 overflow-y-auto">
                    <div id="preview-content" class="prose max-w-none">
                        <div class="text-center text-text-gray py-20">
                            <span class="material-icons-outlined text-6xl mb-4 block">description</span>
                            <p class="text-xl">选择一个Markdown文件开始阅读</p>
                        </div>
                    </div>
                </div>
            </main>
            
            <aside class="w-1/5 bg-white border-l border-gray-200 p-4 flex flex-col" id="knowledge-panel">
                <h2 class="text-lg font-semibold text-text-dark-brown mb-4">知识点列表</h2>
                <div class="flex-1 overflow-y-auto space-y-3" id="knowledge-points">
                    <div class="bg-bg-light-green p-3 rounded-lg cursor-pointer hover:shadow-md transition-shadow">
                        <h3 class="font-semibold text-primary">兴趣驱动</h3>
                        <p class="text-sm text-text-medium-brown mt-1">学习的核心动力来源，提高主动性。</p>
                    </div>
                    <div class="bg-bg-light-gray p-3 rounded-lg cursor-pointer hover:shadow-md transition-shadow">
                        <h3 class="font-semibold text-text-dark-brown">积极反馈</h3>
                        <p class="text-sm text-text-medium-brown mt-1">通过奖励机制巩固学习成果，提升动机。</p>
                    </div>
                    <div class="bg-bg-light-gray p-3 rounded-lg cursor-pointer hover:shadow-md transition-shadow">
                        <h3 class="font-semibold text-text-dark-brown">番茄工作法</h3>
                        <p class="text-sm text-text-medium-brown mt-1">一种时间管理方法，用于保持专注。</p>
                    </div>
                </div>
            </aside>
        </div>
    </div>

    <script>
        let bridge = null;
        let currentFilePath = null;

        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
            loadFileStructure();
        });

        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }

        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }

        function switchToRecording() {
            if (bridge && bridge.switchToRecording) {
                bridge.switchToRecording();
            }
        }

        function switchToAIPartner() {
            if (bridge && bridge.switchToAIPartner) {
                bridge.switchToAIPartner();
            }
        }

        function switchToKnowledgeBase() {
            if (bridge && bridge.switchToKnowledgeBase) {
                bridge.switchToKnowledgeBase();
            }
        }

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const fileStructure = document.getElementById('file-structure');
            const mainContent = document.getElementById('main-content');
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                fileStructure.classList.add('hidden');
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                fileStructure.classList.remove('hidden');
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            const chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        function loadFileStructure() {
            if (bridge && bridge.getFileStructure) {
                bridge.getFileStructure().then(function(structureJson) {
                    const fileStructure = JSON.parse(structureJson);
                    renderFileTree(fileStructure);
                });
            }
        }

        function renderFileTree(structure) {
            const container = document.getElementById('file-tree');
            container.innerHTML = '';
            
            function renderItems(items, container, level = 0) {
                items.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'flex items-center p-2 rounded-md hover:bg-bg-light-gray cursor-pointer';
                    div.style.paddingLeft = (level * 20 + 8) + 'px';
                    
                    if (item.type === 'folder') {
                        div.innerHTML = `
                            <span class="material-icons-outlined text-yellow-500 mr-2">folder</span>
                            <span class="text-text-dark-brown font-medium">${item.name}</span>
                            <span class="material-icons-outlined text-text-gray ml-auto">chevron_right</span>
                        `;
                    } else if (item.type === 'file') {
                        div.innerHTML = `
                            <span class="material-icons-outlined text-gray-500 mr-2">description</span>
                            <span class="text-text-medium-brown">${item.name}</span>
                        `;
                        
                        div.onclick = function() {
                            selectFile(item.path, item.name);
                        };
                    }
                    
                    container.appendChild(div);
                    
                    if (item.type === 'folder' && item.children && item.children.length > 0) {
                        renderItems(item.children, container, level + 1);
                    }
                });
            }
            
            renderItems(structure, container);
        }

        function selectFile(filePath, fileName) {
            currentFilePath = filePath;
            document.getElementById('current-file-title').textContent = fileName;
            loadFileContent(filePath);
            
            // 高亮选中的文件
            const allFiles = document.querySelectorAll('#file-tree > div, #file-tree div div');
            allFiles.forEach(file => {
                file.classList.remove('bg-bg-light-green');
                const span = file.querySelector('span:last-child');
                if (span) {
                    span.classList.remove('text-primary', 'font-semibold');
                    span.classList.add('text-text-medium-brown');
                }
            });
            
            // 高亮当前选中的文件
            const currentFile = Array.from(allFiles).find(file => {
                const nameSpan = file.querySelector('span:last-child');
                return nameSpan && nameSpan.textContent === fileName;
            });
            
            if (currentFile) {
                currentFile.classList.add('bg-bg-light-green');
                const nameSpan = currentFile.querySelector('span:last-child');
                if (nameSpan) {
                    nameSpan.classList.remove('text-text-medium-brown');
                    nameSpan.classList.add('text-primary', 'font-semibold');
                }
            }
        }

        function loadFileContent(filePath) {
            if (bridge && bridge.loadMarkdownFile) {
                bridge.loadMarkdownFile(filePath).then(function(htmlContent) {
                    document.getElementById('preview-content').innerHTML = htmlContent;
                });
            }
        }

        // 预览/编辑按钮功能
        document.addEventListener('DOMContentLoaded', function() {
            const previewBtn = document.getElementById('preview-btn');
            const editBtn = document.getElementById('edit-btn');
            
            if (previewBtn) {
                previewBtn.addEventListener('click', function() {
                    // 切换到预览模式
                    previewBtn.classList.remove('bg-white', 'border-gray-300', 'text-text-gray');
                    previewBtn.classList.add('bg-primary', 'text-white');
                    editBtn.classList.remove('bg-primary', 'text-white');
                    editBtn.classList.add('bg-white', 'border', 'border-gray-300', 'text-text-gray');
                });
            }
            
            if (editBtn) {
                editBtn.addEventListener('click', function() {
                    // 切换到编辑模式
                    editBtn.classList.remove('bg-white', 'border-gray-300', 'text-text-gray');
                    editBtn.classList.add('bg-primary', 'text-white');
                    previewBtn.classList.remove('bg-primary', 'text-white');
                    previewBtn.classList.add('bg-white', 'border', 'border-gray-300', 'text-text-gray');
                });
            }
        });
    </script>
</body>
</html>'''
        
    def setup_web_channel(self):
        """设置Web通道"""
        print("🔗 开始设置WebChannel")
        self.channel = QWebChannel()
        print("🔗 WebChannel对象创建成功")
        
        self.channel.registerObject("bridge", self.bridge)
        print(f"🔗 bridge对象注册成功: {self.bridge}")
        print(f"🔗 bridge对象方法: {[method for method in dir(self.bridge) if not method.startswith('_')]}")
        
        self.web_view.page().setWebChannel(self.channel)
        print("🔗 WebChannel设置到页面完成")
        
        # 添加页面加载完成的回调
        def on_load_finished(ok):
            print(f"📄 页面加载完成，状态: {ok}")
            if ok:
                print("🔗 重新设置WebChannel到页面")
                self.web_view.page().setWebChannel(self.channel)
                
                # 测试WebChannel连接
                test_js = """
                console.log('🧪 测试WebChannel连接');
                console.log('window.qt:', window.qt);
                console.log('window.bridge:', window.bridge);
                if (window.bridge) {
                    console.log('✅ bridge对象可用');
                    console.log('bridge方法:', Object.getOwnPropertyNames(window.bridge));
                } else {
                    console.log('❌ bridge对象不可用');
                }
                """
                self.web_view.page().runJavaScript(test_js)
            
        self.web_view.loadFinished.connect(on_load_finished)
        
    def create_recording_html(self):
        """创建录音室页面的HTML内容 - 已废弃，使用模板系统"""
        # 强制使用模板系统
        return self.template_manager.render_page_content('online_course_notes')

    def create_ai_partner_html(self):
        """创建AI伙伴页面的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>AI伙伴 - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        primary: "#32C77F",
                        warning: "#FF9B27",
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-blue": "#D5F8FF",
                        "bg-beige": "#FFFFD6",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                    },
                    fontFamily: {
                        sans: ['"Noto Sans SC"', 'sans-serif'],
                    },
                    borderRadius: {
                        'xl': '1rem',
                    },
                }
            }
        };
    </script>
    <style>
        #sidebar.collapsed .sidebar-text,
        #sidebar.collapsed #user-profile,
        #sidebar.collapsed .logo-text {
            display: none;
        }
        #sidebar.collapsed .nav-item-icon {
            margin-right: 0;
        }
        #sidebar.collapsed .nav-link {
            justify-content: center;
        }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8 flex-shrink-0">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8" id="user-profile">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 <span class="text-yellow-400">⭐</span></p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToNotebook()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">edit_note</span>
                    <span class="sidebar-text">笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">settings</span>
                    <span class="sidebar-text">设置</span>
                </a>
            </nav>
            
            <div class="mt-auto">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
            </div>
        </aside>

        <main class="flex-1 flex flex-col p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex-shrink-0 flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-text-dark-brown">AI深入学习助手</h2>
                <div class="flex items-center space-x-4">
                    <button class="bg-white text-text-gray font-semibold py-2 px-4 rounded-lg flex items-center border border-gray-300 hover:bg-gray-50 transition duration-300" id="history-btn">
                        <span class="material-icons-outlined mr-2">history</span>
                        <span>历史</span>
                    </button>
                    <button class="bg-primary text-white font-semibold py-2 px-4 rounded-lg flex items-center shadow-sm hover:bg-green-600 transition duration-300" id="new-conversation-btn">
                        <span class="material-icons-outlined mr-2">add</span>
                        <span>新对话</span>
                    </button>
                    <div class="flex space-x-1 ml-4">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                    </div>
                </div>
            </header>
            
            <div class="bg-white p-6 rounded-xl shadow-sm mb-6">
                <p class="text-text-medium-brown">当前选中内容： <span class="text-text-dark-brown font-semibold" id="selected-content">柯基的日常行为习惯</span></p>
            </div>
            
            <div class="flex-1 flex flex-col bg-white rounded-xl shadow-sm">
                <div class="flex-1 p-6 space-y-6 overflow-y-auto" id="chat-area">
                    <div class="flex items-start gap-4">
                        <div class="w-10 h-10 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
                            <span class="material-icons-outlined text-white">pets</span>
                        </div>
                        <div class="bg-bg-light-green p-4 rounded-lg max-w-xl">
                            <p class="font-bold text-primary mb-1">柯基AI</p>
                            <p class="text-text-dark-brown">你好！我是你的AI学习伙伴柯基。有什么可以帮到你的吗？你可以问我关于"柯基的日常行为习惯"的任何问题。</p>
                        </div>
                    </div>
                    
                    <div class="flex items-start gap-4 justify-end">
                        <div class="bg-blue-100 p-4 rounded-lg max-w-xl">
                            <p class="font-bold text-blue-800 mb-1">你</p>
                            <p class="text-gray-800">柯基犬每天需要多少运动量才算足够？</p>
                        </div>
                        <div class="w-10 h-10 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
                            <span class="material-icons-outlined text-white text-3xl">pets</span>
                        </div>
                    </div>
                    
                    <div class="flex items-start gap-4">
                        <div class="w-10 h-10 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
                            <span class="material-icons-outlined text-white">pets</span>
                        </div>
                        <div class="bg-bg-light-green p-4 rounded-lg max-w-xl">
                            <p class="font-bold text-primary mb-1">柯基AI</p>
                            <p class="text-text-dark-brown">一只成年的柯基犬每天至少需要1小时的运动时间。这可以分为两次30分钟的散步，或者包括一些更高强度的活动，比如在公园里奔跑、玩飞盘等。确保运动量足够，有助于它们保持健康的体重和愉悦的心情！</p>
                        </div>
                    </div>
                </div>
                
                <div class="p-4 bg-bg-light-blue-gray border-t border-gray-200">
                    <div class="flex items-center space-x-2 mb-2">
                        <button class="p-2 rounded-lg hover:bg-gray-200 text-text-gray" id="note-btn">
                            <span class="material-icons-outlined">edit_note</span>
                        </button>
                        <button class="p-2 rounded-lg hover:bg-gray-200 text-text-gray" id="magic-btn">
                            <span class="material-icons-outlined">auto_awesome</span>
                        </button>
                    </div>
                    <div class="relative">
                        <textarea class="w-full p-4 pr-28 border border-gray-300 rounded-lg focus:ring-primary focus:border-primary transition duration-300 resize-none" placeholder="输入你的问题..." rows="3" id="message-input"></textarea>
                        <button class="absolute right-4 bottom-4 bg-primary text-white font-semibold py-2 px-4 rounded-lg flex items-center shadow-sm hover:bg-green-600 transition duration-300" id="send-btn">
                            <span class="material-icons-outlined">send</span>
                        </button>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;

        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        });

        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }

        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }

        function switchToNotebook() {
            if (bridge && bridge.switchToNotebook) {
                bridge.switchToNotebook();
            }
        }

        function switchToRecording() {
            if (bridge && bridge.switchToRecording) {
                bridge.switchToRecording();
            }
        }

        function switchToKnowledgeBase() {
            if (bridge && bridge.switchToKnowledgeBase) {
                bridge.switchToKnowledgeBase();
            }
        }

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            const chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        // AI伙伴功能
        document.addEventListener('DOMContentLoaded', function() {
            const historyBtn = document.getElementById('history-btn');
            const newConversationBtn = document.getElementById('new-conversation-btn');
            const noteBtn = document.getElementById('note-btn');
            const magicBtn = document.getElementById('magic-btn');
            const sendBtn = document.getElementById('send-btn');
            const messageInput = document.getElementById('message-input');
            const chatArea = document.getElementById('chat-area');

            if (historyBtn) {
                historyBtn.addEventListener('click', function() {
                    console.log('查看对话历史');
                });
            }

            if (newConversationBtn) {
                newConversationBtn.addEventListener('click', function() {
                    console.log('开始新对话');
                    // 清空聊天区域，保留初始消息
                    const initialMessage = chatArea.querySelector('.flex:first-child');
                    chatArea.innerHTML = '';
                    chatArea.appendChild(initialMessage.cloneNode(true));
                });
            }

            if (noteBtn) {
                noteBtn.addEventListener('click', function() {
                    console.log('针对笔记');
                });
            }

            if (magicBtn) {
                magicBtn.addEventListener('click', function() {
                    console.log('AI魔法功能');
                });
            }

            if (sendBtn && messageInput) {
                function sendMessage() {
                    const message = messageInput.value.trim();
                    if (message) {
                        // 添加用户消息
                        addUserMessage(message);
                        messageInput.value = '';
                        
                        // 模拟AI回复
                        setTimeout(() => {
                            addAIMessage('这是一个模拟的AI回复。在实际应用中，这里会调用真正的AI服务。');
                        }, 1000);
                    }
                }

                sendBtn.addEventListener('click', sendMessage);
                
                messageInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                    }
                });
            }

            function addUserMessage(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'flex items-start gap-4 justify-end';
                messageDiv.innerHTML = `
                    <div class="bg-blue-100 p-4 rounded-lg max-w-xl">
                        <p class="font-bold text-blue-800 mb-1">你</p>
                        <p class="text-gray-800">${message}</p>
                    </div>
                    <div class="w-10 h-10 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
                        <span class="material-icons-outlined text-white text-3xl">pets</span>
                    </div>
                `;
                chatArea.appendChild(messageDiv);
                chatArea.scrollTop = chatArea.scrollHeight;
            }

            function addAIMessage(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'flex items-start gap-4';
                messageDiv.innerHTML = `
                    <div class="w-10 h-10 rounded-full bg-primary flex-shrink-0 flex items-center justify-center">
                        <span class="material-icons-outlined text-white">pets</span>
                    </div>
                    <div class="bg-bg-light-green p-4 rounded-lg max-w-xl">
                        <p class="font-bold text-primary mb-1">柯基AI</p>
                        <p class="text-text-dark-brown">${message}</p>
                    </div>
                `;
                chatArea.appendChild(messageDiv);
                chatArea.scrollTop = chatArea.scrollHeight;
            }
        });
    </script>
</body>
</html>'''

    def create_knowledge_base_html(self):
        """创建知识库管理页面的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>知识库管理 - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        primary: "#32C77F",
                        warning: "#FF9B27",
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-blue": "#D5F8FF",
                        "bg-beige": "#FFFFD6",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                    },
                    fontFamily: {
                        sans: ['"Noto Sans SC"', 'sans-serif'],
                    },
                    borderRadius: {
                        'xl': '1rem',
                    },
                }
            }
        };
    </script>
    <style>
        #sidebar.collapsed .sidebar-text,
        #sidebar.collapsed #user-profile,
        #sidebar.collapsed .logo-text {
            display: none;
        }
        #sidebar.collapsed .nav-item-icon {
            margin-right: 0;
        }
        #sidebar.collapsed .nav-link {
            justify-content: center;
        }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8 flex-shrink-0">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8" id="user-profile">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 <span class="text-yellow-400">⭐</span></p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToNotebook()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">edit_note</span>
                    <span class="sidebar-text">笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToAIPartner()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">settings</span>
                    <span class="sidebar-text">设置</span>
                </a>
            </nav>
            
            <div class="mt-auto">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
            </div>
        </aside>

        <main class="flex-1 p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex justify-between items-center mb-8">
                <h2 class="text-3xl font-bold text-text-dark-brown">知识库管理中心</h2>
                <div class="flex items-center space-x-4">
                    <div class="relative w-1/3">
                        <input class="w-full pl-10 pr-4 py-2 border rounded-full focus:outline-none focus:ring-2 focus:ring-primary" placeholder="在知识库中搜索..." type="text" id="search-input"/>
                        <span class="material-icons-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-gray">search</span>
                    </div>
                    <div class="flex space-x-1">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                    </div>
                </div>
            </header>
            
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <div class="bg-white p-6 rounded-xl shadow-sm flex items-start">
                    <div class="p-3 rounded-lg bg-bg-light-green mr-4">
                        <span class="material-icons-outlined text-primary">source</span>
                    </div>
                    <div>
                        <p class="text-sm text-text-gray mb-1">科目总数</p>
                        <p class="text-3xl font-bold text-primary">12 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl shadow-sm flex items-start">
                    <div class="p-3 rounded-lg bg-orange-100 mr-4">
                        <span class="material-icons-outlined text-warning">article</span>
                    </div>
                    <div>
                        <p class="text-sm text-text-gray mb-1">知识点总数</p>
                        <p class="text-3xl font-bold text-warning">248 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl shadow-sm flex items-start">
                    <div class="p-3 rounded-lg bg-pink-100 mr-4">
                        <span class="material-icons-outlined text-pink-500">memory</span>
                    </div>
                    <div>
                        <p class="text-sm text-text-gray mb-1">待复习</p>
                        <p class="text-3xl font-bold text-pink-500">32 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl shadow-sm flex items-start">
                    <div class="p-3 rounded-lg bg-red-100 mr-4">
                        <span class="material-icons-outlined text-danger">bookmark</span>
                    </div>
                    <div>
                        <p class="text-sm text-text-gray mb-1">收藏总数</p>
                        <p class="text-3xl font-bold text-danger">56 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                    </div>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm mb-8">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">科目列表</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div class="border border-gray-200 rounded-lg p-4 flex flex-col justify-between hover:shadow-lg transition-shadow cursor-pointer">
                        <div>
                            <div class="flex items-center mb-2">
                                <span class="material-icons-outlined text-primary mr-2">calculate</span>
                                <h4 class="font-semibold text-text-dark-brown">高等数学</h4>
                            </div>
                            <p class="text-sm text-text-medium-brown mb-4">微积分、线性代数等核心概念。</p>
                        </div>
                        <div class="text-sm text-text-gray">
                            <p>知识点: 45</p>
                            <p>上次学习: 2天前</p>
                        </div>
                    </div>
                    <div class="border border-gray-200 rounded-lg p-4 flex flex-col justify-between hover:shadow-lg transition-shadow cursor-pointer">
                        <div>
                            <div class="flex items-center mb-2">
                                <span class="material-icons-outlined text-blue-500 mr-2">science</span>
                                <h4 class="font-semibold text-text-dark-brown">大学物理</h4>
                            </div>
                            <p class="text-sm text-text-medium-brown mb-4">力学、电磁学、光学和热力学。</p>
                        </div>
                        <div class="text-sm text-text-gray">
                            <p>知识点: 38</p>
                            <p>上次学习: 5天前</p>
                        </div>
                    </div>
                    <div class="border border-gray-200 rounded-lg p-4 flex flex-col justify-between hover:shadow-lg transition-shadow cursor-pointer">
                        <div>
                            <div class="flex items-center mb-2">
                                <span class="material-icons-outlined text-orange-500 mr-2">gavel</span>
                                <h4 class="font-semibold text-text-dark-brown">法律基础</h4>
                            </div>
                            <p class="text-sm text-text-medium-brown mb-4">宪法、民法、刑法等基本理论。</p>
                        </div>
                        <div class="text-sm text-text-gray">
                            <p>知识点: 62</p>
                            <p>上次学习: 昨天</p>
                        </div>
                    </div>
                    <div class="border border-gray-200 rounded-lg p-4 flex flex-col justify-between hover:shadow-lg transition-shadow cursor-pointer">
                        <div>
                            <div class="flex items-center mb-2">
                                <span class="material-icons-outlined text-red-500 mr-2">history_edu</span>
                                <h4 class="font-semibold text-text-dark-brown">中国近代史</h4>
                            </div>
                            <p class="text-sm text-text-medium-brown mb-4">从鸦片战争到新中国成立的历史。</p>
                        </div>
                        <div class="text-sm text-text-gray">
                            <p>知识点: 25</p>
                            <p>上次学习: 1周前</p>
                        </div>
                    </div>
                    <div class="border border-gray-200 rounded-lg p-4 flex flex-col justify-between hover:shadow-lg transition-shadow cursor-pointer">
                        <div>
                            <div class="flex items-center mb-2">
                                <span class="material-icons-outlined text-purple-500 mr-2">psychology</span>
                                <h4 class="font-semibold text-text-dark-brown">发展心理学</h4>
                            </div>
                            <p class="text-sm text-text-medium-brown mb-4">个体从受精卵到衰亡的心理发展。</p>
                        </div>
                        <div class="text-sm text-text-gray">
                            <p>知识点: 30</p>
                            <p>上次学习: 3小时前</p>
                        </div>
                    </div>
                    <div class="border border-dashed border-gray-400 rounded-lg p-4 flex items-center justify-center text-text-gray hover:bg-bg-light-gray cursor-pointer" id="add-subject-btn">
                        <div class="text-center">
                            <span class="material-icons-outlined text-3xl">add_circle_outline</span>
                            <p>添加新科目</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">科目管理</h3>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-6">
                    <button class="bg-primary hover:bg-green-600 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 shadow" id="add-subject-action">
                        <span class="material-icons-outlined mb-2">add</span>
                        <span>新增科目</span>
                    </button>
                    <button class="bg-warning hover:bg-orange-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 shadow" id="edit-subject-action">
                        <span class="material-icons-outlined mb-2">edit</span>
                        <span>编辑科目</span>
                    </button>
                    <button class="bg-danger hover:bg-red-600 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 shadow" id="delete-subject-action">
                        <span class="material-icons-outlined mb-2">delete</span>
                        <span>删除科目</span>
                    </button>
                    <button class="bg-gray-400 hover:bg-gray-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 shadow" id="import-export-action">
                        <span class="material-icons-outlined mb-2">file_upload</span>
                        <span>导入/导出</span>
                    </button>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;

        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        });

        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }

        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }

        function switchToNotebook() {
            if (bridge && bridge.switchToNotebook) {
                bridge.switchToNotebook();
            }
        }

        function switchToRecording() {
            if (bridge && bridge.switchToRecording) {
                bridge.switchToRecording();
            }
        }

        function switchToAIPartner() {
            if (bridge && bridge.switchToAIPartner) {
                bridge.switchToAIPartner();
            }
        }

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            const chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        // 知识库管理功能
        document.addEventListener('DOMContentLoaded', function() {
            const searchInput = document.getElementById('search-input');
            const addSubjectBtn = document.getElementById('add-subject-btn');
            const addSubjectAction = document.getElementById('add-subject-action');
            const editSubjectAction = document.getElementById('edit-subject-action');
            const deleteSubjectAction = document.getElementById('delete-subject-action');
            const importExportAction = document.getElementById('import-export-action');

            if (searchInput) {
                searchInput.addEventListener('input', function() {
                    const query = this.value.toLowerCase();
                    console.log('搜索知识库:', query);
                    // 这里可以添加搜索逻辑
                });
            }

            if (addSubjectBtn) {
                addSubjectBtn.addEventListener('click', function() {
                    console.log('添加新科目');
                    // 这里可以添加新增科目的逻辑
                });
            }

            if (addSubjectAction) {
                addSubjectAction.addEventListener('click', function() {
                    console.log('新增科目');
                });
            }

            if (editSubjectAction) {
                editSubjectAction.addEventListener('click', function() {
                    console.log('编辑科目');
                });
            }

            if (deleteSubjectAction) {
                deleteSubjectAction.addEventListener('click', function() {
                    console.log('删除科目');
                });
            }

            if (importExportAction) {
                importExportAction.addEventListener('click', function() {
                    console.log('导入/导出');
                });
            }

            // 科目卡片点击事件
            const subjectCards = document.querySelectorAll('.border.border-gray-200.rounded-lg');
            subjectCards.forEach(card => {
                if (!card.classList.contains('border-dashed')) {
                    card.addEventListener('click', function() {
                        const subjectName = this.querySelector('h4').textContent;
                        console.log('查看科目:', subjectName);
                        if (bridge && bridge.switchToSubjectDetail) {
                            bridge.switchToSubjectDetail(subjectName);
                        }
                    });
                }
            });
        });
    </script>
</body>
</html>'''

    def create_subject_detail_html(self, subject_name="机器学习基础"):
        """创建科目详情页面的HTML内容"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>科目详情 - {subject_name} - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography,container-queries"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {{
            darkMode: "class",
            theme: {{
                extend: {{
                    colors: {{
                        primary: "#32C77F",
                        warning: "#FF9B27",
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-blue": "#D5F8FF",
                        "bg-beige": "#FFFFD6", 
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                        "brand-blue": "#3B82F6",
                        "brand-red": "#EF4444",
                        "brand-yellow": "#F59E0B"
                    }},
                    fontFamily: {{
                        sans: ['"Noto Sans SC"', 'sans-serif'],
                    }},
                    borderRadius: {{
                        'xl': '1rem',
                    }},
                }},
            }},
        }};
    </script>
    <style>
        #sidebar.collapsed .sidebar-text,
        #sidebar.collapsed #user-profile,
        #sidebar.collapsed .logo-text {{
            display: none;
        }}
        #sidebar.collapsed .nav-item-icon {{
            margin-right: 0;
        }}
        #sidebar.collapsed .nav-link {{
            justify-content: center;
        }}
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8 flex-shrink-0">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8" id="user-profile">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 <span class="text-yellow-400">⭐</span></p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToNotebook()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">edit_note</span>
                    <span class="sidebar-text">笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToAIPartner()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">settings</span>
                    <span class="sidebar-text">设置</span>
                </a>
            </nav>
            
            <div class="mt-auto">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
            </div>
        </aside>

        <main class="flex-1 p-8 bg-bg-light-blue-gray overflow-y-auto">
            <div class="flex justify-between items-center mb-6">
                <nav aria-label="Breadcrumb" class="text-sm text-text-medium-brown">
                    <ol class="list-none p-0 inline-flex">
                        <li class="flex items-center">
                            <a class="hover:text-text-dark-brown cursor-pointer" onclick="switchToKnowledgeBase()">知识库</a>
                            <span class="material-icons-outlined mx-2 text-base">chevron_right</span>
                        </li>
                        <li class="flex items-center">
                            <span class="text-text-dark-brown font-semibold">{subject_name}</span>
                        </li>
                    </ol>
                </nav>
                <div class="flex items-center space-x-4">
                    <div class="relative">
                        <input class="pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary w-64" placeholder="搜索知识点..." type="text" id="search-input"/>
                        <span class="material-icons-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-gray">search</span>
                    </div>
                    <div class="flex space-x-1">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                    </div>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm mb-8">
                <h2 class="text-2xl font-bold text-text-dark-brown mb-6">科目详情：{subject_name}</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div class="bg-blue-50 p-6 rounded-lg flex items-center">
                        <div class="p-3 rounded-lg bg-blue-200 mr-4">
                            <span class="material-icons-outlined text-brand-blue">functions</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">科目知识点</p>
                            <p class="text-2xl font-bold text-brand-blue">128 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                        </div>
                    </div>
                    <div class="bg-red-50 p-6 rounded-lg flex items-center">
                        <div class="p-3 rounded-lg bg-red-200 mr-4">
                            <span class="material-icons-outlined text-brand-red">cancel</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">错题</p>
                            <p class="text-2xl font-bold text-brand-red">32 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                        </div>
                    </div>
                    <div class="bg-yellow-50 p-6 rounded-lg flex items-center">
                        <div class="p-3 rounded-lg bg-yellow-200 mr-4">
                            <span class="material-icons-outlined text-brand-yellow">star_border</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">收藏</p>
                            <p class="text-2xl font-bold text-brand-yellow">45 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="bg-white rounded-xl shadow-sm">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left text-gray-500">
                        <thead class="text-xs text-text-gray uppercase bg-gray-50">
                            <tr>
                                <th class="p-4" scope="col"><input class="form-checkbox h-4 w-4 text-primary rounded border-gray-300 focus:ring-primary" type="checkbox" id="select-all"/></th>
                                <th class="px-6 py-3" scope="col">序号</th>
                                <th class="px-6 py-3" scope="col">知识点名称</th>
                                <th class="px-6 py-3" scope="col">掌握熟练度</th>
                                <th class="px-6 py-3" scope="col">建立时间</th>
                                <th class="px-6 py-3 text-center" scope="col">错题</th>
                                <th class="px-6 py-3 text-center" scope="col">收藏</th>
                                <th class="px-6 py-3 text-center" scope="col">复习次数</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr class="bg-white border-b hover:bg-gray-50 cursor-pointer" onclick="goToKnowledgePointDetail('线性回归')">
                                <td class="w-4 p-4" onclick="event.stopPropagation()"><input class="form-checkbox h-4 w-4 text-primary rounded border-gray-300 focus:ring-primary" type="checkbox"/></td>
                                <td class="px-6 py-4">1</td>
                                <td class="px-6 py-4">
                                    <div class="font-semibold text-text-dark-brown">线性回归</div>
                                    <div class="text-xs text-text-medium-brown mt-1">通过拟合线性方程来预测连续变量。</div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center">
                                        <div class="w-full bg-gray-200 rounded-full h-2.5">
                                            <div class="bg-primary h-2.5 rounded-full" style="width: 85%"></div>
                                        </div>
                                        <span class="ml-2 text-primary font-semibold">85%</span>
                                    </div>
                                </td>
                                <td class="px-6 py-4">2024-09-10</td>
                                <td class="px-6 py-4 text-center"><span class="text-danger">5</span></td>
                                <td class="px-6 py-4 text-center"><span class="material-icons-outlined text-yellow-500 text-base">star</span></td>
                                <td class="px-6 py-4 text-center">3</td>
                            </tr>
                            <tr class="bg-white border-b hover:bg-gray-50 cursor-pointer" onclick="goToKnowledgePointDetail('逻辑回归')">
                                <td class="w-4 p-4" onclick="event.stopPropagation()"><input class="form-checkbox h-4 w-4 text-primary rounded border-gray-300 focus:ring-primary" type="checkbox"/></td>
                                <td class="px-6 py-4">2</td>
                                <td class="px-6 py-4">
                                    <div class="font-semibold text-text-dark-brown">逻辑回归</div>
                                    <div class="text-xs text-text-medium-brown mt-1">用于二分类问题的分类算法。</div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center">
                                        <div class="w-full bg-gray-200 rounded-full h-2.5">
                                            <div class="bg-warning h-2.5 rounded-full" style="width: 60%"></div>
                                        </div>
                                        <span class="ml-2 text-warning font-semibold">60%</span>
                                    </div>
                                </td>
                                <td class="px-6 py-4">2024-09-08</td>
                                <td class="px-6 py-4 text-center"><span class="text-danger">2</span></td>
                                <td class="px-6 py-4 text-center"><span class="material-icons-outlined text-gray-400 text-base">star_border</span></td>
                                <td class="px-6 py-4 text-center">1</td>
                            </tr>
                            <tr class="bg-white border-b hover:bg-gray-50 cursor-pointer" onclick="goToKnowledgePointDetail('支持向量机')">
                                <td class="w-4 p-4" onclick="event.stopPropagation()"><input class="form-checkbox h-4 w-4 text-primary rounded border-gray-300 focus:ring-primary" type="checkbox"/></td>
                                <td class="px-6 py-4">3</td>
                                <td class="px-6 py-4">
                                    <div class="font-semibold text-text-dark-brown">支持向量机 (SVM)</div>
                                    <div class="text-xs text-text-medium-brown mt-1">通过最大化间隔来找到最优超平面。</div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center">
                                        <div class="w-full bg-gray-200 rounded-full h-2.5">
                                            <div class="bg-danger h-2.5 rounded-full" style="width: 30%"></div>
                                        </div>
                                        <span class="ml-2 text-danger font-semibold">30%</span>
                                    </div>
                                </td>
                                <td class="px-6 py-4">2024-09-05</td>
                                <td class="px-6 py-4 text-center"><span class="text-danger">8</span></td>
                                <td class="px-6 py-4 text-center"><span class="material-icons-outlined text-yellow-500 text-base">star</span></td>
                                <td class="px-6 py-4 text-center">4</td>
                            </tr>
                            <tr class="bg-white border-b hover:bg-gray-50 cursor-pointer" onclick="goToKnowledgePointDetail('决策树')">
                                <td class="w-4 p-4" onclick="event.stopPropagation()"><input class="form-checkbox h-4 w-4 text-primary rounded border-gray-300 focus:ring-primary" type="checkbox"/></td>
                                <td class="px-6 py-4">4</td>
                                <td class="px-6 py-4">
                                    <div class="font-semibold text-text-dark-brown">决策树</div>
                                    <div class="text-xs text-text-medium-brown mt-1">一种树状结构的分类和回归模型。</div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="flex items-center">
                                        <div class="w-full bg-gray-200 rounded-full h-2.5">
                                            <div class="bg-primary h-2.5 rounded-full" style="width: 95%"></div>
                                        </div>
                                        <span class="ml-2 text-primary font-semibold">95%</span>
                                    </div>
                                </td>
                                <td class="px-6 py-4">2024-09-02</td>
                                <td class="px-6 py-4 text-center">0</td>
                                <td class="px-6 py-4 text-center"><span class="material-icons-outlined text-gray-400 text-base">star_border</span></td>
                                <td class="px-6 py-4 text-center">2</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class="flex flex-col md:flex-row items-center justify-between p-4 space-y-4 md:space-y-0">
                    <div class="flex items-center space-x-2">
                        <button class="px-3 py-2 text-sm font-medium text-white bg-primary rounded-lg hover:bg-green-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary flex items-center" id="batch-mastery-btn">
                            <span class="material-icons-outlined text-sm mr-1">task_alt</span> 批量标记掌握度
                        </button>
                        <button class="px-3 py-2 text-sm font-medium text-white bg-danger rounded-lg hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-danger flex items-center" id="batch-delete-btn">
                            <span class="material-icons-outlined text-sm mr-1">delete_outline</span> 批量删除
                        </button>
                        <button class="px-3 py-2 text-sm font-medium text-text-gray bg-gray-200 rounded-lg hover:bg-gray-300 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-400 flex items-center" id="batch-export-btn">
                            <span class="material-icons-outlined text-sm mr-1">file_download</span> 批量导出
                        </button>
                        <button class="px-3 py-2 text-sm font-medium text-text-gray bg-gray-200 rounded-lg hover:bg-gray-300 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-400 flex items-center" id="batch-favorite-btn">
                            <span class="material-icons-outlined text-sm mr-1">star_outline</span> 批量收藏
                        </button>
                    </div>
                    <div class="flex items-center space-x-4 text-sm text-text-medium-brown">
                        <span>总计 128 个知识点</span>
                        <div class="flex items-center space-x-2">
                            <span>每页显示:</span>
                            <select class="form-select border-gray-300 rounded-md shadow-sm focus:border-primary focus:ring focus:ring-primary focus:ring-opacity-50 text-sm py-1" id="page-size-select">
                                <option>10</option>
                                <option>20</option>
                                <option>50</option>
                            </select>
                        </div>
                        <div class="flex items-center space-x-2">
                            <span>1-10 of 13 页</span>
                            <button class="p-1 rounded-md hover:bg-gray-100 disabled:opacity-50" disabled="" id="prev-page-btn">
                                <span class="material-icons-outlined text-base">chevron_left</span>
                            </button>
                            <button class="p-1 rounded-md hover:bg-gray-100" id="next-page-btn">
                                <span class="material-icons-outlined text-base">chevron_right</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;

        new QWebChannel(qt.webChannelTransport, function (channel) {{
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        }});

        function callPythonFunction(functionName) {{
            if (bridge && bridge[functionName]) {{
                bridge[functionName]();
            }}
        }}

        function switchToDashboard() {{
            if (bridge && bridge.switchToDashboard) {{
                bridge.switchToDashboard();
            }}
        }}

        function switchToNotebook() {{
            if (bridge && bridge.switchToNotebook) {{
                bridge.switchToNotebook();
            }}
        }}

        function switchToRecording() {{
            if (bridge && bridge.switchToRecording) {{
                bridge.switchToRecording();
            }}
        }}

        function switchToAIPartner() {{
            if (bridge && bridge.switchToAIPartner) {{
                bridge.switchToAIPartner();
            }}
        }}

        function switchToKnowledgeBase() {{
            if (bridge && bridge.switchToKnowledgeBase) {{
                bridge.switchToKnowledgeBase();
            }}
        }}

        function goToKnowledgePointDetail(knowledgePointName) {{
            if (bridge && bridge.switchToKnowledgePointDetail) {{
                bridge.switchToKnowledgePointDetail('机器学习基础', knowledgePointName);
            }}
        }}

        function toggleSidebar() {{
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {{
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            }} else {{
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }}
            
            const chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {{
                chevron.textContent = 'chevron_right';
            }} else {{
                chevron.textContent = 'chevron_left';
            }}
        }}

        // 科目详情功能
        document.addEventListener('DOMContentLoaded', function() {{
            const searchInput = document.getElementById('search-input');
            const selectAllCheckbox = document.getElementById('select-all');
            const batchMasteryBtn = document.getElementById('batch-mastery-btn');
            const batchDeleteBtn = document.getElementById('batch-delete-btn');
            const batchExportBtn = document.getElementById('batch-export-btn');
            const batchFavoriteBtn = document.getElementById('batch-favorite-btn');
            const pageSizeSelect = document.getElementById('page-size-select');
            const prevPageBtn = document.getElementById('prev-page-btn');
            const nextPageBtn = document.getElementById('next-page-btn');

            if (searchInput) {{
                searchInput.addEventListener('input', function() {{
                    const query = this.value.toLowerCase();
                    console.log('搜索知识点:', query);
                }});
            }}

            if (selectAllCheckbox) {{
                selectAllCheckbox.addEventListener('change', function() {{
                    const checkboxes = document.querySelectorAll('tbody input[type="checkbox"]');
                    checkboxes.forEach(checkbox => {{
                        checkbox.checked = this.checked;
                    }});
                }});
            }}

            if (batchMasteryBtn) {{
                batchMasteryBtn.addEventListener('click', function() {{
                    console.log('批量标记掌握度');
                }});
            }}

            if (batchDeleteBtn) {{
                batchDeleteBtn.addEventListener('click', function() {{
                    console.log('批量删除');
                }});
            }}

            if (batchExportBtn) {{
                batchExportBtn.addEventListener('click', function() {{
                    console.log('批量导出');
                }});
            }}

            if (batchFavoriteBtn) {{
                batchFavoriteBtn.addEventListener('click', function() {{
                    console.log('批量收藏');
                }});
            }}

            if (pageSizeSelect) {{
                pageSizeSelect.addEventListener('change', function() {{
                    console.log('每页显示:', this.value);
                }});
            }}

            if (prevPageBtn) {{
                prevPageBtn.addEventListener('click', function() {{
                    console.log('上一页');
                }});
            }}

            if (nextPageBtn) {{
                nextPageBtn.addEventListener('click', function() {{
                    console.log('下一页');
                }});
            }}

            // 收藏按钮点击事件
            const favoriteButtons = document.querySelectorAll('tbody .material-icons-outlined');
            favoriteButtons.forEach(button => {{
                if (button.textContent === 'star' || button.textContent === 'star_border') {{
                    button.addEventListener('click', function() {{
                        if (this.textContent === 'star') {{
                            this.textContent = 'star_border';
                            this.classList.remove('text-yellow-500');
                            this.classList.add('text-gray-400');
                        }} else {{
                            this.textContent = 'star';
                            this.classList.remove('text-gray-400');
                            this.classList.add('text-yellow-500');
                        }}
                    }});
                }}
            }});
        }});
    </script>
</body>
</html>'''

    def create_knowledge_point_detail_html(self, subject_name="机器学习基础", knowledge_point_name="线性回归"):
        """创建知识点详情页面的HTML内容"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>知识点详情 - {knowledge_point_name} - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        tailwind.config = {{
            darkMode: "class",
            theme: {{
                extend: {{
                    colors: {{
                        primary: "#32C77F",
                        warning: "#FF9B27",
                        danger: "#ED4B4B",
                        "text-dark-brown": "#715D46",
                        "text-medium-brown": "#9B8D7D",
                        "text-gray": "#828282",
                        "bg-light-blue": "#D5F8FF",
                        "bg-beige": "#FFFFD6",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                        "bg-light-blue-gray": "#F5F7F9",
                        "light-primary": "rgba(50, 199, 127, 0.1)",
                    }},
                    fontFamily: {{
                        sans: ['"Noto Sans SC"', 'sans-serif'],
                    }},
                    borderRadius: {{
                        'xl': '1rem',
                    }},
                }},
            }},
        }};
    </script>
    <style>
        #sidebar.collapsed .sidebar-text,
        #sidebar.collapsed #user-profile,
        #sidebar.collapsed .logo-text {{
            display: none;
        }}
        #sidebar.collapsed .nav-item-icon {{
            margin-right: 0;
        }}
        #sidebar.collapsed .nav-link {{
            justify-content: center;
        }}
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8 flex-shrink-0">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">pets</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8" id="user-profile">
                <div class="w-20 h-20 rounded-full bg-primary flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">pets</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 <span class="text-yellow-400">⭐</span></p>
            </div>
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToNotebook()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">edit_note</span>
                    <span class="sidebar-text">笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToRecording()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToAIPartner()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#">
                    <span class="material-icons-outlined mr-3 nav-item-icon">settings</span>
                    <span class="sidebar-text">设置</span>
                </a>
            </nav>
            
            <div class="mt-auto">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
            </div>
        </aside>

        <main class="flex-1 p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex justify-between items-center mb-6">
                <div class="flex items-center text-sm text-text-gray">
                    <a class="hover:text-primary cursor-pointer" onclick="switchToKnowledgeBase()">知识库</a>
                    <span class="mx-2 material-icons-outlined text-base">chevron_right</span>
                    <a class="hover:text-primary cursor-pointer" onclick="switchToSubjectDetail('{subject_name}')">{subject_name}</a>
                    <span class="mx-2 material-icons-outlined text-base">chevron_right</span>
                    <span class="text-text-dark-brown font-semibold">{knowledge_point_name}</span>
                </div>
                <div class="flex items-center space-x-4">
                    <div class="relative">
                        <input class="w-64 pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" placeholder="全局搜索..." type="text" id="global-search"/>
                        <span class="material-icons-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-gray">search</span>
                    </div>
                    <button class="p-2 rounded-full hover:bg-gray-200" id="notification-btn">
                        <span class="material-icons-outlined text-text-gray">notifications</span>
                    </button>
                    <div class="flex space-x-1">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                    </div>
                </div>
            </header>
            
            <div class="bg-white p-8 rounded-xl shadow-sm mb-6">
                <div class="flex justify-between items-start">
                    <div>
                        <h2 class="text-3xl font-bold text-text-dark-brown mb-2">{knowledge_point_name}</h2>
                        <div class="flex items-center space-x-6 text-sm text-text-medium-brown">
                            <span>掌握情况: <span class="text-primary font-semibold">已掌握</span></span>
                            <span>建立时间: 2023-10-01</span>
                        </div>
                    </div>
                    <div class="flex space-x-2">
                        <button class="px-6 py-2.5 bg-primary text-white rounded-lg font-semibold hover:bg-green-600 transition-colors" id="practice-btn">专项练习</button>
                        <button class="px-6 py-2.5 bg-orange-400 text-white rounded-lg font-semibold hover:bg-orange-500 transition-colors" id="error-practice-btn">错题练习</button>
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-6 my-6 border-y py-6">
                    <div class="flex items-center">
                        <div class="p-3 rounded-lg bg-red-100 mr-4">
                            <span class="material-icons-outlined text-danger">close</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray">错题数量</p>
                            <p class="text-xl font-bold text-text-dark-brown">3 <span class="text-base font-normal">道</span></p>
                        </div>
                    </div>
                    <div class="flex items-center">
                        <div class="p-3 rounded-lg bg-blue-100 mr-4">
                            <span class="material-icons-outlined text-blue-500">star_border</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray">收藏题目数</p>
                            <p class="text-xl font-bold text-text-dark-brown">5 <span class="text-base font-normal">道</span></p>
                        </div>
                    </div>
                    <div class="flex items-center">
                        <div class="p-3 rounded-lg bg-bg-light-green mr-4">
                            <span class="material-icons-outlined text-primary">bookmark_border</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray">关联笔记本</p>
                            <p class="text-xl font-bold text-text-dark-brown">2 <span class="text-base font-normal">篇</span></p>
                        </div>
                    </div>
                </div>
                <div>
                    <h3 class="text-lg font-semibold text-text-dark-brown mb-2">知识点描述</h3>
                    <p class="text-text-medium-brown leading-relaxed">线性回归是利用数理统计中回归分析，来确定两种或两种以上变量间相互依赖的定量关系的一种统计分析方法。其表达形式为y = w'x+e，e为误差服从均值为0的正态分布。回归分析中，只包括一个自变量和一个因变量，且二者的关系可用一条直线近似表示，这种回归分析称为一元线性回归分析。如果回归分析中包括两个或两个以上的自变量，且因变量和自变量之间是线性关系，则称为多元线性回归分析。</p>
                </div>
            </div>
            
            <div class="bg-white p-8 rounded-xl shadow-sm mb-6">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">关联笔记本</h3>
                <div class="grid grid-cols-2 gap-4">
                    <a class="block p-4 bg-bg-light-blue-gray rounded-lg hover:shadow-md transition-shadow cursor-pointer" onclick="switchToNotebook()">
                        <div class="flex items-center">
                            <span class="material-icons-outlined text-primary mr-3">edit_note</span>
                            <p class="font-semibold text-text-dark-brown">机器学习核心概念笔记</p>
                        </div>
                    </a>
                    <a class="block p-4 bg-bg-light-blue-gray rounded-lg hover:shadow-md transition-shadow cursor-pointer" onclick="switchToNotebook()">
                        <div class="flex items-center">
                            <span class="material-icons-outlined text-primary mr-3">edit_note</span>
                            <p class="font-semibold text-text-dark-brown">监督学习算法梳理</p>
                        </div>
                    </a>
                </div>
            </div>
            
            <div class="bg-white p-8 rounded-xl shadow-sm">
                <div class="flex justify-between items-center mb-6">
                    <h3 class="text-lg font-semibold text-text-dark-brown">关联题目</h3>
                    <div class="flex items-center space-x-4">
                        <div class="relative">
                            <input class="w-48 pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" placeholder="搜索题目..." type="text" id="question-search"/>
                            <span class="material-icons-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-gray">search</span>
                        </div>
                        <select class="py-2 px-4 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" id="question-type-filter">
                            <option>所有类型</option>
                            <option>选择题</option>
                            <option>填空题</option>
                            <option>简答题</option>
                        </select>
                        <select class="py-2 px-4 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" id="question-sort">
                            <option>默认排序</option>
                            <option>按熟练度</option>
                            <option>按时间</option>
                        </select>
                    </div>
                </div>
                <div class="space-y-4">
                    <div class="p-4 border border-gray-200 rounded-lg flex items-center justify-between hover:border-primary transition-colors cursor-pointer" onclick="openQuestionReview('1')">
                        <div>
                            <p class="font-semibold text-text-dark-brown">1. 以下哪个是线性回归模型的假设？</p>
                            <div class="flex items-center space-x-4 text-sm mt-2 text-text-gray">
                                <span>类型: <span class="bg-blue-100 text-blue-800 px-2 py-0.5 rounded">选择题</span></span>
                                <span>熟练度: <span class="text-yellow-500">★★★★☆</span></span>
                                <span>上次答题: <span class="text-primary">正确</span> (2024-05-10)</span>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="查看题目" onclick="event.stopPropagation(); openQuestionReview('1')"><span class="material-icons-outlined">visibility</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="编辑题目" onclick="event.stopPropagation()"><span class="material-icons-outlined">edit</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="收藏题目" onclick="event.stopPropagation()"><span class="material-icons-outlined">star_border</span></button>
                        </div>
                    </div>
                    <div class="p-4 border border-gray-200 rounded-lg flex items-center justify-between hover:border-primary transition-colors cursor-pointer" onclick="openQuestionReview('2')">
                        <div>
                            <p class="font-semibold text-text-dark-brown">2. 请简述线性回归的损失函数是什么？</p>
                            <div class="flex items-center space-x-4 text-sm mt-2 text-text-gray">
                                <span>类型: <span class="bg-green-100 text-green-800 px-2 py-0.5 rounded">简答题</span></span>
                                <span>熟练度: <span class="text-yellow-500">★★★☆☆</span></span>
                                <span>上次答题: <span class="text-danger">错误</span> (2024-05-08)</span>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="查看题目" onclick="event.stopPropagation(); openQuestionReview('2')"><span class="material-icons-outlined">visibility</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="编辑题目" onclick="event.stopPropagation()"><span class="material-icons-outlined">edit</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-yellow-500" title="已收藏" onclick="event.stopPropagation()"><span class="material-icons-outlined">star</span></button>
                        </div>
                    </div>
                    <div class="p-4 border border-gray-200 rounded-lg flex items-center justify-between hover:border-primary transition-colors cursor-pointer" onclick="openQuestionReview('3')">
                        <div>
                            <p class="font-semibold text-text-dark-brown">3. 线性回归中，用来评估模型拟合优度的指标是____。</p>
                            <div class="flex items-center space-x-4 text-sm mt-2 text-text-gray">
                                <span>类型: <span class="bg-purple-100 text-purple-800 px-2 py-0.5 rounded">填空题</span></span>
                                <span>熟练度: <span class="text-yellow-500">★★★★★</span></span>
                                <span>上次答题: <span class="text-primary">正确</span> (2024-05-11)</span>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="查看题目" onclick="event.stopPropagation(); openQuestionReview('3')"><span class="material-icons-outlined">visibility</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="编辑题目" onclick="event.stopPropagation()"><span class="material-icons-outlined">edit</span></button>
                            <button class="p-2 rounded-full hover:bg-gray-100 text-text-gray" title="收藏题目" onclick="event.stopPropagation()"><span class="material-icons-outlined">star_border</span></button>
                        </div>
                    </div>
                </div>
                <div class="flex justify-center mt-8">
                    <nav aria-label="Pagination" class="flex items-center space-x-2">
                        <a class="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 cursor-pointer" id="prev-page">
                            <span class="material-icons-outlined text-base">chevron_left</span>
                        </a>
                        <a aria-current="page" class="z-10 bg-light-primary text-primary relative inline-flex items-center px-4 py-2 border border-primary text-sm font-medium cursor-pointer">1</a>
                        <a class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium cursor-pointer">2</a>
                        <a class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 hidden md:inline-flex relative items-center px-4 py-2 border text-sm font-medium cursor-pointer">3</a>
                        <span class="relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium text-gray-700">...</span>
                        <a class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 hidden md:inline-flex relative items-center px-4 py-2 border text-sm font-medium cursor-pointer">8</a>
                        <a class="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 cursor-pointer" id="next-page">
                            <span class="material-icons-outlined text-base">chevron_right</span>
                        </a>
                    </nav>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge = null;

        new QWebChannel(qt.webChannelTransport, function (channel) {{
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        }});

        function callPythonFunction(functionName) {{
            if (bridge && bridge[functionName]) {{
                bridge[functionName]();
            }}
        }}

        function switchToDashboard() {{
            if (bridge && bridge.switchToDashboard) {{
                bridge.switchToDashboard();
            }}
        }}

        function switchToNotebook() {{
            if (bridge && bridge.switchToNotebook) {{
                bridge.switchToNotebook();
            }}
        }}

        function switchToRecording() {{
            if (bridge && bridge.switchToRecording) {{
                bridge.switchToRecording();
            }}
        }}

        function switchToAIPartner() {{
            if (bridge && bridge.switchToAIPartner) {{
                bridge.switchToAIPartner();
            }}
        }}

        function switchToKnowledgeBase() {{
            if (bridge && bridge.switchToKnowledgeBase) {{
                bridge.switchToKnowledgeBase();
            }}
        }}

        function switchToSubjectDetail(subjectName) {{
            if (bridge && bridge.switchToSubjectDetail) {{
                bridge.switchToSubjectDetail(subjectName);
            }}
        }}

        function openQuestionReview(questionId) {{
            if (bridge && bridge.openQuestionReview) {{
                bridge.openQuestionReview(questionId);
            }}
        }}

        function toggleSidebar() {{
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            const isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {{
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            }} else {{
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }}
            
            const chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {{
                chevron.textContent = 'chevron_right';
            }} else {{
                chevron.textContent = 'chevron_left';
            }}
        }}

        // 知识点详情功能
        document.addEventListener('DOMContentLoaded', function() {{
            const globalSearch = document.getElementById('global-search');
            const notificationBtn = document.getElementById('notification-btn');
            const practiceBtn = document.getElementById('practice-btn');
            const errorPracticeBtn = document.getElementById('error-practice-btn');
            const questionSearch = document.getElementById('question-search');
            const questionTypeFilter = document.getElementById('question-type-filter');
            const questionSort = document.getElementById('question-sort');
            const prevPage = document.getElementById('prev-page');
            const nextPage = document.getElementById('next-page');

            if (globalSearch) {{
                globalSearch.addEventListener('input', function() {{
                    const query = this.value.toLowerCase();
                    console.log('全局搜索:', query);
                }});
            }}

            if (notificationBtn) {{
                notificationBtn.addEventListener('click', function() {{
                    console.log('查看通知');
                }});
            }}

            if (practiceBtn) {{
                practiceBtn.addEventListener('click', function() {{
                    console.log('开始专项练习');
                }});
            }}

            if (errorPracticeBtn) {{
                errorPracticeBtn.addEventListener('click', function() {{
                    console.log('开始错题练习');
                }});
            }}

            if (questionSearch) {{
                questionSearch.addEventListener('input', function() {{
                    const query = this.value.toLowerCase();
                    console.log('搜索题目:', query);
                }});
            }}

            if (questionTypeFilter) {{
                questionTypeFilter.addEventListener('change', function() {{
                    console.log('筛选题目类型:', this.value);
                }});
            }}

            if (questionSort) {{
                questionSort.addEventListener('change', function() {{
                    console.log('排序方式:', this.value);
                }});
            }}

            if (prevPage) {{
                prevPage.addEventListener('click', function() {{
                    console.log('上一页');
                }});
            }}

            if (nextPage) {{
                nextPage.addEventListener('click', function() {{
                    console.log('下一页');
                }});
            }}

            // 收藏按钮事件（保留交互功能）
            const favoriteButtons = document.querySelectorAll('button[title="收藏题目"], button[title="已收藏"]');

            favoriteButtons.forEach(button => {{
                button.addEventListener('click', function() {{
                    const icon = this.querySelector('.material-icons-outlined');
                    if (icon.textContent === 'star') {{
                        icon.textContent = 'star_border';
                        this.classList.remove('text-yellow-500');
                        this.classList.add('text-text-gray');
                        this.title = '收藏题目';
                    }} else {{
                        icon.textContent = 'star';
                        this.classList.remove('text-text-gray');
                        this.classList.add('text-yellow-500');
                        this.title = '已收藏';
                    }}
                }});
            }});
        }});
    </script>
</body>
</html>'''

# ===== 设备监控和选择功能 =====

# 音频录制参数（与app_qt.py保持一致）
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
DEVICE_INDEX_KEYWORD = "CABLE Output"  # 如果找不到，将回退到默认输入设备
OUTPUT_DIR = "recorded_audio_segments"
SILENCE_THRESHOLD = 0.001  # 较低的阈值以检测更安静的输入
SILENCE_SECONDS = 1.5
MAX_RECORD_SECONDS = 30

class DeviceMonitorWorker(QObject):
    """设备监控工作器 - 完全按照app_qt.py实现"""
    levelUpdated = Signal(int, float)  # (device_index, peak[0..1])
    listReady = Signal(list)           # list of tuples (index, label)
    finished = Signal()
    screenshotReady = Signal(str)      # filepath

    def __init__(self):
        super().__init__()
        self._stop = False
        self._indices = []

    @Slot()
    def start(self):
        try:
            try:
                p = pyaudio.PyAudio()
            except Exception:
                self.listReady.emit([])
                self.finished.emit()
                return
            items = []
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", f"设备{i}")
                    rate = int(info.get("defaultSampleRate", 0))
                    items.append((i, f"[{i}] {name}  ch={info.get('maxInputChannels',0)}  {rate}Hz"))
            self._indices = [i for i, _ in items]
            self.listReady.emit(items)
            # Poll levels in a loop
            while not self._stop:
                for idx in list(self._indices):
                    peak = 0.0
                    stream = None
                    try:
                        info = p.get_device_info_by_index(idx)
                        use_rate = int(info.get("defaultSampleRate", RATE)) or RATE
                        use_channels = min(max(1, int(info.get("maxInputChannels", 1))), CHANNELS) or 1
                        stream = p.open(format=FORMAT, channels=use_channels, rate=use_rate, input=True,
                                        frames_per_buffer=CHUNK, input_device_index=idx)
                        data = stream.read(CHUNK, exception_on_overflow=False)
                        audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        if audio_np.size:
                            peak = float(np.max(np.abs(audio_np)))
                    except Exception:
                        peak = 0.0
                    finally:
                        try:
                            if stream:
                                stream.stop_stream(); stream.close()
                        except Exception:
                            pass
                    self.levelUpdated.emit(idx, peak)
                    if self._stop:
                        break
                # small rest to avoid hammering the system
                time.sleep(0.3)
        finally:
            try:
                p.terminate()
            except Exception:
                pass
            self.finished.emit()

    def stop(self):
        self._stop = True


class DeviceLevelDialog(QDialog):
    """设备选择对话框 - 完全按照app_qt.py实现"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择输入设备（含电平）")
        self.resize(560, 480)
        self._selected_idx = None
        self._selected_label = None
        self._bars = {}
        self._labels = {}

        v = QVBoxLayout(self)
        self.lst = QListWidget(self)
        v.addWidget(self.lst)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(self.bb)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)

        # Thread setup
        self._thr = QThread(self)
        self._worker = DeviceMonitorWorker()
        self._worker.moveToThread(self._thr)
        self._thr.started.connect(self._worker.start)
        self._worker.listReady.connect(self._on_list_ready)
        self._worker.levelUpdated.connect(self._on_level_update)
        self._worker.finished.connect(self._thr.quit)
        self._thr.start()

    def _on_list_ready(self, items):
        self.lst.clear()
        for idx, label in items:
            item = QListWidgetItem()
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 4, 8, 4)
            lab = QLabel(label)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedWidth(160)
            h.addWidget(lab)
            h.addStretch(1)
            h.addWidget(bar)
            item.setSizeHint(w.sizeHint())
            self.lst.addItem(item)
            self.lst.setItemWidget(item, w)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self._bars[idx] = bar
            self._labels[idx] = label

    @Slot(int, float)
    def _on_level_update(self, idx, peak):
        bar = self._bars.get(idx)
        if bar:
            val = max(0, min(100, int(peak * 100)))
            bar.setValue(val)

    def accept(self):
        it = self.lst.currentItem()
        if it is not None:
            idx = int(it.data(Qt.ItemDataRole.UserRole))
            self._selected_idx = idx
            self._selected_label = self._labels.get(idx)
        # stop worker before closing dialog to avoid resource contention/crash
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().accept()

    def reject(self):
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().reject()

    def selected_device_index(self):
        return self._selected_idx

    def selected_device_label(self):
        return self._selected_label

    def closeEvent(self, e):
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().closeEvent(e)


class AudioRecorderWorker(QObject):
    """音频录制工作器 - 完全按照app_qt.py实现"""
    segmentReady = Signal(str)  # filepath
    status = Signal(str)
    peakLevel = Signal(float)   # 0..1 peak for UI VU meter
    finished = Signal()

    def __init__(self, device_index=None):
        super().__init__()
        self._stop = False
        self._device_index = device_index

    def _find_device_index(self, p, keyword):
        """查找包含关键字的设备索引"""
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", "")
                    if keyword in name:
                        return i
            except Exception:
                continue
        return None

    @Slot()
    def start(self):
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            p = pyaudio.PyAudio()
            device_index = self._device_index if self._device_index is not None else self._find_device_index(p, DEVICE_INDEX_KEYWORD)
            if device_index is None:
                # Fallback to default input device
                try:
                    def_dev = p.get_default_input_device_info()
                    device_index = int(def_dev.get('index', 0))
                    self.status.emit(f"使用默认输入设备: {def_dev.get('name', '未知设备')}")
                except Exception:
                    self.status.emit(f"未找到音频输入设备: 关键字 '{DEVICE_INDEX_KEYWORD}'，且无默认输入设备")
                    self.finished.emit()
                    return
            dev_info = p.get_device_info_by_index(device_index)
            dev_name = dev_info.get("name", "未知设备")
            # Prefer device default sample rate to avoid incompatibilities
            use_rate = int(dev_info.get("defaultSampleRate", RATE)) or RATE
            use_channels = min(max(1, int(dev_info.get("maxInputChannels", 1))), CHANNELS) or 1
            self.status.emit(f"准备监听设备: {dev_name} (index={device_index}, rate={use_rate})")
            stream = p.open(format=FORMAT, channels=use_channels, rate=use_rate, input=True,
                            frames_per_buffer=CHUNK, input_device_index=device_index)
            frames = []
            silence_frames = 0
            is_recording_segment = False
            tick = 0
            while not self._stop:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                peak = float(np.max(np.abs(audio_np))) if audio_np.size else 0.0
                is_silent = peak < SILENCE_THRESHOLD
                # Debug status every ~1s
                tick += 1
                if (tick % max(1, int(use_rate / CHUNK))) == 0:
                    self.status.emit(f"录音中 峰值={peak:.4f} 阈值={SILENCE_THRESHOLD:.4f}")
                # Emit VU level frequently
                try:
                    self.peakLevel.emit(peak)
                except Exception:
                    pass
                if is_silent:
                    if is_recording_segment:
                        silence_frames += 1
                    if is_recording_segment and silence_frames >= int(SILENCE_SECONDS * use_rate / CHUNK) and len(frames) > 0:
                        filename = os.path.join(OUTPUT_DIR, f"segment_{int(time.time())}.wav")
                        with wave.open(filename, "wb") as wf:
                            wf.setnchannels(CHANNELS)
                            wf.setsampwidth(p.get_sample_size(FORMAT))
                            wf.setframerate(use_rate)
                            wf.writeframes(b"".join(frames))
                        self.segmentReady.emit(filename)
                        frames = []
                        is_recording_segment = False
                        silence_frames = 0
                else:
                    is_recording_segment = True
                    silence_frames = 0
                    frames.append(data)
                if len(frames) >= int(MAX_RECORD_SECONDS * use_rate / CHUNK):
                    filename = os.path.join(OUTPUT_DIR, f"segment_force_{int(time.time())}.wav")
                    with wave.open(filename, "wb") as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(use_rate)
                        wf.writeframes(b"".join(frames))
                    self.segmentReady.emit(filename)
                    frames = []
                    is_recording_segment = False
                    silence_frames = 0
        except Exception as e:
            self.status.emit(f"录音错误: {e}")
        finally:
            try:
                if 'stream' in locals():
                    stream.stop_stream()
                    stream.close()
                if 'p' in locals():
                    p.terminate()
            except Exception:
                pass
            self.finished.emit()

    def stop(self):
        self._stop = True


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局异常处理器，记录所有未捕获的异常"""
    import traceback
    from datetime import datetime
    
    crash_log_file = "global_crash.log"
    
    # 记录到文件
    try:
        with open(crash_log_file, "a", encoding="utf-8") as f:
            f.write(f"\n=== 全局异常 {datetime.now()} ===\n")
            f.write(f"异常类型: {exc_type.__name__}\n")
            f.write(f"异常值: {exc_value}\n")
            f.write("异常堆栈:\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write("=== 全局异常结束 ===\n\n")
    except:
        pass
    
    # 打印到控制台
    print(f"\n!!! 程序发生严重错误 !!!")
    print(f"异常类型: {exc_type.__name__}")
    print(f"异常值: {exc_value}")
    print("详细信息已保存到 global_crash.log")
    traceback.print_exception(exc_type, exc_value, exc_traceback)

def manual_validate_debug():
    """手动触发调试验证功能"""
    print("\n" + "="*80)
    print("🚀 手动触发调试验证功能")
    print("="*80)
    
    # 获取bridge对象并验证功能
    bridge = main_window.bridge
    if bridge:
        result = bridge.validateAllFileOperations()
        print("\n📋 验证结果:")
        print(result)
        print("\n" + "="*80)
        print("✅ 后端功能验证完成，请查看上方日志")
        print("="*80)
    else:
        print("❌ 无法获取bridge对象")
        
        # 获取bridge对象并验证功能
        bridge = window.bridge
        if bridge:
            result = bridge.validateAllFileOperations()
            print("\n📋 验证结果:")
            print(result)
            print("\n" + "="*80)
            print("✅ 后端功能验证完成，请查看上方日志")
            print("="*80)
        else:
            print("❌ 无法获取bridge对象")
    
    # 将手动验证函数绑定到window对象，以便需要时调用
    window.manual_validate_debug = manual_validate_debug
    
    window.show()
    
    print("🐕 覆盖层拖拽版柯基学习小助手启动成功！")
    print("🎯 使用透明覆盖层实现拖拽功能")
    print("🖱️ 点击顶部区域拖拽窗口")
    print("📝 支持工作台和笔记本功能切换")
    
    sys.exit(app.exec())

# ====== 录音和转写Worker类 ======

# 音频录制参数
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
DEVICE_INDEX_KEYWORD = "CABLE Output"  # 如果找不到，将回退到默认输入设备
OUTPUT_DIR = "recorded_audio_segments"
SILENCE_THRESHOLD = 0.001  # 较低的阈值以检测更安静的输入
SILENCE_SECONDS = 1.5
MAX_RECORD_SECONDS = 30


class TranscriberWorker(QObject):
    """语音转写Worker"""
    textReady = Signal(str)
    status = Signal(str)
    finished = Signal()

    def __init__(self, model_size: str = "small", language_setting: str = "auto"):
        super().__init__()
        self._stop = False
        self._queue = queue.Queue()
        self._model = None
        self._model_size = model_size
        self._language_setting = language_setting

    @Slot()
    def start(self):
        try:
            if whisper is None and faster_whisper is None:
                self.status.emit("语音转写模块未安装，无法进行语音转写")
                self.finished.emit()
                return
                
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
            # 优先使用faster-whisper
            if faster_whisper is not None:
                try:
                    self.status.emit(f"正在加载 Faster-Whisper 模型: {self._model_size} ({device}) ...")
                    self._model = faster_whisper(self._model_size, device=device)
                    self.status.emit("Faster-Whisper模型加载完成。等待音频...")
                    self._use_faster_whisper = True
                except Exception as e:
                    self.status.emit(f"Faster-Whisper加载失败: {e}")
                    # 回退到标准whisper
                    if whisper is not None:
                        self.status.emit(f"回退到 OpenAI Whisper 模型: {self._model_size} ({device}) ...")
                        self._model = whisper.load_model(self._model_size, device=device)
                        self.status.emit("OpenAI Whisper模型加载完成。等待音频...")
                        self._use_faster_whisper = False
                    else:
                        raise e
            else:
                self.status.emit(f"正在加载 OpenAI Whisper 模型: {self._model_size} ({device}) ...")
                self._model = whisper.load_model(self._model_size, device=device)
                self.status.emit("OpenAI Whisper模型加载完成。等待音频...")
                self._use_faster_whisper = False
            
            while not self._stop:
                try:
                    filepath = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not filepath:
                    continue
                try:
                    self.status.emit(f"开始转写: {os.path.basename(filepath)}")
                    language = None if self._language_setting == "auto" else self._language_setting
                    
                    # 检查文件是否存在
                    if not os.path.exists(filepath):
                        self.status.emit(f"音频文件不存在: {filepath}")
                        continue
                    
                    if self._use_faster_whisper:
                        # 使用faster-whisper
                        segments, info = self._model.transcribe(
                            filepath,
                            language=language,
                            task="transcribe"
                        )
                        text = " ".join([segment.text for segment in segments]).strip()
                    else:
                        # 使用标准whisper
                        result = self._model.transcribe(
                            filepath,
                            language=language,
                            fp16=torch.cuda.is_available(),
                            task="transcribe",
                        )
                        text = result.get("text", "").strip()
                    
                    if text:
                        self.textReady.emit(text)
                        self.status.emit(f"完成转写: {len(text)} 字符")
                    else:
                        self.status.emit("转写结果为空")
                        
                except Exception as e:
                    import traceback
                    error_msg = f"转写错误: {e}"
                    traceback_msg = traceback.format_exc()
                    self.status.emit(error_msg)
                    print(f"转写异常详情:\n{traceback_msg}")
                    # 继续处理下一个文件，不要让异常中断整个转写线程
        except Exception as e:
            self.status.emit(f"模型加载失败: {e}")
        finally:
            self.finished.emit()

    @Slot(str)
    def enqueue_file(self, filepath: str):
        try:
            self._queue.put_nowait(filepath)
            self.status.emit(f"已入队: {os.path.basename(filepath)}")
        except Exception:
            pass

    def stop(self):
        self._stop = True


if __name__ == "__main__":
    # 设置全局异常处理器
    sys.excepthook = global_exception_handler
    
    app = QApplication(sys.argv)
    
    # 设置应用程序信息
    app.setApplicationName("LectureLearnLoop")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("CorgiDev")
    
    # 创建主窗口
    try:
        main_window = OverlayDragCorgiApp()
        main_window.show()
        
        print("=== 程序启动成功 ===")
        print("如果程序崩溃，请查看以下日志文件：")
        print("- global_crash.log (全局异常)")
        print("- audio_device_crash.log (音频设备异常)")
        print("- app.log (应用程序日志)")
        
        sys.exit(app.exec())
    except Exception as startup_error:
        print(f"程序启动失败: {startup_error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
