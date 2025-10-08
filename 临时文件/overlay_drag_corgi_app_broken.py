#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
柯基学习小助手 - 覆盖层拖拽版本
使用透明覆盖层解决拖拽问题，支持工作台和笔记本功能
"""

import sys
import json
import os
import markdown
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QHBoxLayout, QLabel
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, Qt, QObject, Slot, Signal, QPoint, QRect
from PySide6.QtGui import QFont, QMouseEvent, QCursor

class CorgiWebBridge(QObject):
    """Python与JavaScript通信桥梁"""
    
    pageChanged = Signal(str)
    dataUpdated = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = "dashboard"
        self.main_window = parent

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
            
    # 一级菜单切换方法
    @Slot()
    def switchToDashboard(self):
        """切换到工作台页面"""
        if self.main_window:
            self.main_window.load_dashboard_content()
            print("🏠 切换到工作台页面")
    
    @Slot()
    def switchToLearn(self):
        """切换到学习页面（显示二级菜单）"""
        if self.main_window:
            self.main_window.load_learn_content()
            print("📚 切换到学习页面")
    
    @Slot()
    def switchToPractice(self):
        """切换到练习页面（显示二级菜单）"""
        if self.main_window:
            self.main_window.load_practice_content()
            print("✏️ 切换到练习页面")
    
    @Slot()
    def switchToMemory(self):
        """切换到记忆页面（显示二级菜单）"""
        if self.main_window:
            self.main_window.load_memory_content()
            print("🧠 切换到记忆页面")
    
    @Slot()
    def switchToKnowledgeBase(self):
        """切换到知识库管理页面"""
        if self.main_window:
            self.main_window.load_knowledge_base_content()
            print("📚 切换到知识库管理页面")
    
    @Slot()
    def openSettings(self):
        """打开设置窗口"""
        if self.main_window:
            self.main_window.open_settings_dialog()
            print("⚙️ 打开设置窗口")
    
    # 二级菜单切换方法 - 学习模块
    @Slot()
    def switchToLearnFromMaterials(self):
        """切换到从资料学习页面"""
        print("🔄 Bridge: switchToLearnFromMaterials 被调用")
        if self.main_window:
            self.main_window.load_learn_from_materials_content()
            print("📝 切换到从资料学习页面")
        else:
            print("❌ main_window 为 None")
    
    @Slot()
    def switchToLearnFromMedia(self):
        """切换到从音视频学习页面"""
        if self.main_window:
            self.main_window.load_learn_from_media_content()
            print("🎤 切换到从音视频学习页面")
    
    # 二级菜单切换方法 - 练习模块
    @Slot()
    def switchToPracticeFromMaterials(self):
        """切换到基于学习资料练习页面"""
        if self.main_window:
            self.main_window.load_practice_from_materials_content()
            print("📖 切换到基于学习资料练习页面")
    
    @Slot()
    def switchToPracticeFromKnowledge(self):
        """切换到基于知识点练习页面"""
        if self.main_window:
            self.main_window.load_practice_from_knowledge_content()
            print("🎯 切换到基于知识点练习页面")
    
    @Slot()
    def switchToPracticeFromErrors(self):
        """切换到基于错题练习页面"""
        if self.main_window:
            self.main_window.load_practice_from_errors_content()
            print("❌ 切换到基于错题练习页面")
    
    # 二级菜单切换方法 - 记忆模块
    @Slot()
    def switchToMemoryFromKnowledge(self):
        """切换到基于知识点记忆页面"""
        if self.main_window:
            self.main_window.load_memory_from_knowledge_content()
            print("🧠 切换到基于知识点记忆页面")
    
    @Slot()
    def switchToMemoryFromErrors(self):
        """切换到基于错题记忆页面"""
        if self.main_window:
            self.main_window.load_memory_from_errors_content()
            print("🔄 切换到基于错题记忆页面")
    
    # 新的动态内容加载方法
    @Slot()
    def loadDashboardContent(self):
        """加载工作台内容到右侧区域"""
        if self.main_window:
            self.main_window.load_dashboard_content_only()
            print("🏠 加载工作台内容")
    
    @Slot()
    def loadLearnFromMaterialsContent(self):
        """加载从资料学习内容到右侧区域"""
        if self.main_window:
            self.main_window.load_learn_materials_content_only()
            print("📝 加载从资料学习内容")
    
    @Slot()
    def loadLearnFromMediaContent(self):
        """加载从音视频学习内容到右侧区域"""
        if self.main_window:
            self.main_window.load_learn_media_content_only()
            print("🎤 加载从音视频学习内容")
    
    @Slot()
    def loadPracticeFromMaterialsContent(self):
        """加载基于学习资料练习内容到右侧区域"""
        if self.main_window:
            self.main_window.load_practice_materials_content_only()
            print("📖 加载基于学习资料练习内容")
    
    @Slot()
    def loadPracticeFromKnowledgeContent(self):
        """加载基于知识点练习内容到右侧区域"""
        if self.main_window:
            self.main_window.load_practice_knowledge_content_only()
            print("🎯 加载基于知识点练习内容")
    
    @Slot()
    def loadPracticeFromErrorsContent(self):
        """加载基于错题练习内容到右侧区域"""
        if self.main_window:
            self.main_window.load_practice_errors_content_only()
            print("❌ 加载基于错题练习内容")
    
    @Slot()
    def loadMemoryFromKnowledgeContent(self):
        """加载基于知识点记忆内容到右侧区域"""
        if self.main_window:
            self.main_window.load_memory_knowledge_content_only()
            print("🧠 加载基于知识点记忆内容")
    
    @Slot()
    def loadMemoryFromErrorsContent(self):
        """加载基于错题记忆内容到右侧区域"""
        if self.main_window:
            self.main_window.load_memory_errors_content_only()
            print("🔄 加载基于错题记忆内容")
    
    @Slot()
    def loadKnowledgeBaseContent(self):
        """加载知识库管理内容到右侧区域"""
        if self.main_window:
            self.main_window.load_knowledge_base_content_only()
            print("📚 加载知识库管理内容")
    
    @Slot()
    def loadSettingsContent(self):
        """加载设置内容到右侧区域"""
        if self.main_window:
            self.main_window.load_settings_content_only()
            print("⚙️ 加载设置内容")
    
    # 保留原有方法以兼容现有功能
    @Slot()
    def switchToNotebook(self):
        """切换到笔记本页面（兼容方法，映射到从资料学习）"""
        print("🔄 Bridge: switchToNotebook 被调用")
        self.switchToLearnFromMaterials()
            
    @Slot()
    def switchToRecording(self):
        """切换到录音室页面（兼容方法，映射到从音视频学习）"""
        self.switchToLearnFromMedia()
            
    @Slot()
    def switchToAIPartner(self):
        """切换到AI伙伴页面（兼容方法，暂时保留）"""
        if self.main_window:
            self.main_window.load_ai_partner_content()
            print("🤖 切换到AI伙伴页面")
            
    @Slot(str)
    def switchToSubjectDetail(self, subject_name):
        """切换到科目详情页面"""
        if self.main_window:
            self.main_window.load_subject_detail_content(subject_name)
            print(f"📖 切换到科目详情页面: {subject_name}")
            
    @Slot(str, str)
    def switchToKnowledgePointDetail(self, subject_name, knowledge_point_name):
        """切换到知识点详情页面"""
        if self.main_window:
            self.main_window.load_knowledge_point_detail_content(subject_name, knowledge_point_name)
            print(f"🔍 切换到知识点详情页面: {subject_name} - {knowledge_point_name}")
    
    @Slot(str)
    def openQuestionReview(self, question_id):
        """打开题目复习面板"""
        if self.main_window:
            self.main_window.open_question_review_panel(question_id)
            print(f"📝 打开题目复习面板: {question_id}")
            
    @Slot(result=str)
    def getFileStructure(self):
        """获取vault文件夹的文件结构"""
        vault_path = Path("vault")
        if not vault_path.exists():
            vault_path.mkdir(exist_ok=True)
        
        def build_tree(path, level=0):
            items = []
            try:
                for item in sorted(path.iterdir()):
                    if item.name.startswith('.'):
                        continue
                    
                    if item.is_dir():
                        items.append({
                            "name": item.name,
                            "type": "folder",
                            "path": str(item),
                            "level": level,
                            "children": build_tree(item, level + 1)
                        })
                    elif item.suffix == '.md':
                        items.append({
                            "name": item.name,
                            "type": "file",
                            "path": str(item),
                            "level": level
                        })
            except PermissionError:
                pass
            return items
        
        structure = build_tree(vault_path)
        return json.dumps(structure, ensure_ascii=False)
    
    @Slot(str, result=str)
    def loadMarkdownFile(self, file_path):
        """加载Markdown文件内容"""
        try:
            path = Path(file_path)
            if path.exists() and path.suffix == '.md':
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 转换为HTML
                html_content = markdown.markdown(content, extensions=['codehilite', 'fenced_code'])
                return html_content
        except Exception as e:
            print(f"加载文件失败: {e}")
        return ""
    
    @Slot(str, result=str)
    def loadMarkdownRaw(self, file_path):
        """加载Markdown原始内容用于编辑"""
        try:
            path = Path(file_path)
            if path.exists() and path.suffix == '.md':
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            print(f"加载原始文件失败: {e}")
        return ""
    
    @Slot(str, str, result=bool)
    def saveMarkdownFile(self, file_path, content):
        """保存Markdown文件"""
        try:
            path = Path(file_path)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"文件已保存: {file_path}")
            return True
        except Exception as e:
            print(f"保存文件失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def createNewNote(self, note_name, parent_path=""):
        """创建新的Markdown笔记文件"""
        try:
            # 确定创建位置
            if parent_path and parent_path != "":
                base_path = Path(parent_path)
            else:
                base_path = Path("vault")
            
            # 确保父目录存在
            base_path.mkdir(parents=True, exist_ok=True)
            
            # 创建文件路径
            if not note_name.endswith('.md'):
                note_name += '.md'
            
            file_path = base_path / note_name
            
            # 检查文件是否已存在
            if file_path.exists():
                print(f"文件已存在: {file_path}")
                return False
            
            # 创建新文件，写入基本模板
            template_content = f"""# {note_name.replace('.md', '')}

## 概述

在这里写下你的笔记内容...

## 要点

- 要点1
- 要点2
- 要点3

## 总结

"""
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(template_content)
            
            print(f"新笔记已创建: {file_path}")
            return True
            
        except Exception as e:
            print(f"创建笔记失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def createNewFolder(self, folder_name, parent_path=""):
        """创建新文件夹"""
        try:
            # 确定创建位置
            if parent_path and parent_path != "":
                base_path = Path(parent_path)
            else:
                base_path = Path("vault")
            
            # 创建文件夹路径
            folder_path = base_path / folder_name
            
            # 检查文件夹是否已存在
            if folder_path.exists():
                print(f"文件夹已存在: {folder_path}")
                return False
            
            # 创建文件夹
            folder_path.mkdir(parents=True, exist_ok=True)
            
            print(f"新文件夹已创建: {folder_path}")
            return True
            
        except Exception as e:
            print(f"创建文件夹失败: {e}")
            return False
    
    @Slot(str, result=str)
    def extractKnowledgePoints(self, file_content):
        """提取文档中的知识点"""
        try:
            # 这里应该调用知识管理系统来提取知识点
            # 暂时返回模拟数据
            import json
            
            mock_knowledge_points = [
                {
                    "name": "机器学习定义",
                    "description": "机器学习是人工智能的一个重要分支，它使计算机能够在没有明确编程的情况下学习和改进。",
                    "anchor": "机器学习",
                    "position": 0
                },
                {
                    "name": "监督学习",
                    "description": "使用标记数据训练模型，包括分类和回归任务。",
                    "anchor": "监督学习",
                    "position": 100
                },
                {
                    "name": "无监督学习", 
                    "description": "从未标记的数据中发现隐藏的模式和结构。",
                    "anchor": "无监督学习",
                    "position": 200
                }
            ]
            
            return json.dumps(mock_knowledge_points, ensure_ascii=False)
            
        except Exception as e:
            print(f"提取知识点失败: {e}")
            return "[]"
    
    @Slot(str, str, result=bool)
    def renameFileOrFolder(self, old_path, new_name):
        """重命名文件或文件夹"""
        try:
            old_path_obj = Path(old_path)
            if not old_path_obj.exists():
                print(f"路径不存在: {old_path}")
                return False
            
            # 构建新路径
            parent_dir = old_path_obj.parent
            if old_path_obj.is_file() and not new_name.endswith('.md'):
                new_name += '.md'
            
            new_path = parent_dir / new_name
            
            # 检查新名称是否已存在
            if new_path.exists():
                print(f"目标路径已存在: {new_path}")
                return False
            
            # 执行重命名
            old_path_obj.rename(new_path)
            print(f"重命名成功: {old_path} -> {new_path}")
            return True
            
        except Exception as e:
            print(f"重命名失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def moveFileOrFolder(self, source_path, target_parent_path):
        """移动文件或文件夹到新位置"""
        try:
            source_path_obj = Path(source_path)
            target_parent_obj = Path(target_parent_path)
            
            if not source_path_obj.exists():
                print(f"源路径不存在: {source_path}")
                return False
            
            if not target_parent_obj.exists():
                print(f"目标父目录不存在: {target_parent_path}")
                return False
            
            if not target_parent_obj.is_dir():
                print(f"目标路径不是目录: {target_parent_path}")
                return False
            
            # 构建目标路径
            target_path = target_parent_obj / source_path_obj.name
            
            # 检查目标路径是否已存在
            if target_path.exists():
                print(f"目标路径已存在: {target_path}")
                return False
            
            # 执行移动
            import shutil
            if source_path_obj.is_dir():
                shutil.move(str(source_path_obj), str(target_path))
            else:
                shutil.move(str(source_path_obj), str(target_path))
            
            print(f"移动成功: {source_path} -> {target_path}")
            return True
            
        except Exception as e:
            print(f"移动失败: {e}")
            return False

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
        
    def handle_js_console_message(self, level, message, line_number, source_id):
        """处理JavaScript控制台消息"""
        level_names = {
            0: "INFO",
            1: "WARNING", 
            2: "ERROR"
        }
        level_name = level_names.get(level, "UNKNOWN")
        print(f"🔍 JS {level_name}: {message}")
        if line_number > 0:
            print(f"   📍 Line: {line_number}")
        if source_id:
            print(f"   📄 Source: {source_id}")
        print("   " + "="*50)
        
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
        
        # 添加JavaScript控制台日志监听
        self.web_view.page().javaScriptConsoleMessage = self.handle_js_console_message
        
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
        
    # 一级菜单页面加载方法
    def load_dashboard_content(self):
        """加载工作台页面内容"""
        html_content = self.create_dashboard_html()
        self.web_view.setHtml(html_content)
    
    def load_learn_content(self):
        """加载学习页面内容（显示二级菜单）"""
        html_content = self.create_learn_menu_html()
        self.web_view.setHtml(html_content)
    
    def load_practice_content(self):
        """加载练习页面内容（显示二级菜单）"""
        html_content = self.create_practice_menu_html()
        self.web_view.setHtml(html_content)
    
    def load_memory_content(self):
        """加载记忆页面内容（显示二级菜单）"""
        html_content = self.create_memory_menu_html()
        self.web_view.setHtml(html_content)
    
    def load_knowledge_base_content(self):
        """加载知识库管理页面内容"""
        html_content = self.create_knowledge_base_html()
        self.web_view.setHtml(html_content)
    
    def open_settings_dialog(self):
        """打开设置对话框"""
        html_content = self.create_settings_html()
        self.web_view.setHtml(html_content)
    
    # 二级菜单页面加载方法 - 学习模块
    def load_learn_from_materials_content(self):
        """加载从资料学习页面内容（原笔记本功能）"""
        print("📚 创建从资料学习HTML内容...")
        html_content = self.create_notebook_html()
        print(f"📝 HTML内容长度: {len(html_content)} 字符")
        print("🌐 设置HTML到WebView...")
        self.web_view.setHtml(html_content)
        print("✅ HTML设置完成，等待页面加载...")
    
    def load_learn_from_media_content(self):
        """加载从音视频学习页面内容（原录音室功能）"""
        html_content = self.create_recording_html()
        self.web_view.setHtml(html_content)
    
    # 二级菜单页面加载方法 - 练习模块
    def load_practice_from_materials_content(self):
        """加载基于学习资料练习页面内容（预留）"""
        html_content = self.create_placeholder_html("基于学习资料练习", "支持用户选择已有的学习笔记，基于笔记内容生成练习题进行练习。")
        self.web_view.setHtml(html_content)
    
    def load_practice_from_knowledge_content(self):
        """加载基于知识点练习页面内容"""
        html_content = self.create_practice_knowledge_html()
        self.web_view.setHtml(html_content)
    
    def load_practice_from_errors_content(self):
        """加载基于错题练习页面内容"""
        html_content = self.create_practice_errors_html()
        self.web_view.setHtml(html_content)
    
    # 二级菜单页面加载方法 - 记忆模块
    def load_memory_from_knowledge_content(self):
        """加载基于知识点记忆页面内容（预留）"""
        html_content = self.create_placeholder_html("基于知识点记忆", "支持用户选择学科，以脑图形式展示该学科知识点；支持知识点搜索，根据知识点熟练度推荐用户复习不熟悉的内容。")
        self.web_view.setHtml(html_content)
    
    def load_memory_from_errors_content(self):
        """加载基于错题记忆页面内容（预留）"""
        html_content = self.create_placeholder_html("基于错题记忆", "支持用户搜索错题，或系统自动推荐错题；用户可针对推荐/搜索到的错题进行复习，强化记忆。")
        self.web_view.setHtml(html_content)
    
    # 新的动态内容加载方法（只加载内容部分，不包含侧边栏）
    def load_dashboard_content_only(self):
        """只加载工作台内容部分"""
        content_html = self.create_dashboard_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_learn_materials_content_only(self):
        """只加载从资料学习内容部分"""
        content_html = self.create_learn_materials_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_learn_media_content_only(self):
        """只加载从音视频学习内容部分"""
        content_html = self.create_learn_media_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_practice_materials_content_only(self):
        """只加载基于学习资料练习内容部分"""
        content_html = self.create_placeholder_content_html("基于学习资料练习", "支持用户选择已有的学习笔记，基于笔记内容生成练习题进行练习。")
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_practice_knowledge_content_only(self):
        """只加载基于知识点练习内容部分"""
        content_html = self.create_practice_knowledge_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_practice_errors_content_only(self):
        """只加载基于错题练习内容部分"""
        content_html = self.create_practice_errors_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_memory_knowledge_content_only(self):
        """只加载基于知识点记忆内容部分"""
        content_html = self.create_placeholder_content_html("基于知识点记忆", "支持用户选择学科，以脑图形式展示该学科知识点；支持知识点搜索，根据知识点熟练度推荐用户复习不熟悉的内容。")
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_memory_errors_content_only(self):
        """只加载基于错题记忆内容部分"""
        content_html = self.create_placeholder_content_html("基于错题记忆", "支持用户搜索错题，或系统自动推荐错题；用户可针对推荐/搜索到的错题进行复习，强化记忆。")
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_knowledge_base_content_only(self):
        """只加载知识库管理内容部分"""
        content_html = self.create_knowledge_base_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    def load_settings_content_only(self):
        """只加载设置内容部分"""
        content_html = self.create_settings_content_html()
        self.web_view.page().runJavaScript(f"document.getElementById('content-area').innerHTML = `{content_html}`;")
    
    # 兼容方法（保留原有功能）
    def load_notebook_content(self):
        """加载笔记本页面内容（兼容方法）"""
        print("🔄 开始加载从资料学习页面...")
        self.load_learn_from_materials_content()
        print("✅ 从资料学习页面加载完成")
        
    def load_recording_content(self):
        """加载录音室页面内容（兼容方法）"""
        self.load_learn_from_media_content()
        
    def load_ai_partner_content(self):
        """加载 AI伙伴页面内容（暂时保留）"""
        html_content = self.create_ai_partner_html()
        self.web_view.setHtml(html_content)
        
    def load_subject_detail_content(self, subject_name="机器学习基础"):
        """加载科目详情页面内容"""
        html_content = self.create_subject_detail_html(subject_name)
        self.web_view.setHtml(html_content)
        
    def load_knowledge_point_detail_content(self, subject_name="机器学习基础", knowledge_point_name="线性回归"):
        """加载知识点详情页面内容"""
        html_content = self.create_knowledge_point_detail_html(subject_name, knowledge_point_name)
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
        
    def create_dashboard_html(self):
        """创建单页面应用的HTML内容"""
        return self.create_spa_html()
    
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
        if (typeof tailwind !== 'undefined') {
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
        }};
        }}
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
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToLearn()">
                    <span class="material-icons-outlined mr-3">school</span>
                    <span>学</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToPractice()">
                    <span class="material-icons-outlined mr-3">quiz</span>
                    <span>练</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToMemory()">
                    <span class="material-icons-outlined mr-3">psychology</span>
                    <span>记</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3">library_books</span>
                    <span>知识库管理</span>
                </a>
            </nav>
            
            <!-- 设置图标固定在底部 -->
            <div class="mt-auto flex justify-between items-center">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
                <button class="p-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="openSettings()" title="设置">
                    <span class="material-icons-outlined">settings</span>
                </button>
            </div>
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
            
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                <!-- 学习模块数据 -->
                <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-blue-500">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-semibold text-text-dark-brown">学习进度</h3>
                        <span class="material-icons-outlined text-blue-500">school</span>
                    </div>
                    <div class="space-y-2">
                        <p class="text-sm text-text-medium-brown">今日学习: <span class="font-semibold text-primary">2小时</span></p>
                        <p class="text-sm text-text-medium-brown">本周笔记: <span class="font-semibold text-primary">5篇</span></p>
                        <p class="text-sm text-text-medium-brown">音视频学习: <span class="font-semibold text-primary">3个</span></p>
                    </div>
                    <button class="mt-4 w-full bg-blue-500 text-white py-2 rounded-lg hover:bg-blue-600 transition" onclick="switchToLearn()">进入学习</button>
                </div>
                
                <!-- 练习模块数据 -->
                <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-green-500">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-semibold text-text-dark-brown">练习情况</h3>
                        <span class="material-icons-outlined text-green-500">quiz</span>
                    </div>
                    <div class="space-y-2">
                        <p class="text-sm text-text-medium-brown">待完成练习: <span class="font-semibold text-warning">3个</span></p>
                        <p class="text-sm text-text-medium-brown">本周完成: <span class="font-semibold text-primary">12个</span></p>
                        <p class="text-sm text-text-medium-brown">正确率: <span class="font-semibold text-primary">85%</span></p>
                    </div>
                    <button class="mt-4 w-full bg-green-500 text-white py-2 rounded-lg hover:bg-green-600 transition" onclick="switchToPractice()">开始练习</button>
                </div>
                
                <!-- 记忆模块数据 -->
                <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-purple-500">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-semibold text-text-dark-brown">记忆复习</h3>
                        <span class="material-icons-outlined text-purple-500">psychology</span>
                    </div>
                    <div class="space-y-2">
                        <p class="text-sm text-text-medium-brown">待复习知识点: <span class="font-semibold text-warning">8个</span></p>
                        <p class="text-sm text-text-medium-brown">待复习错题: <span class="font-semibold text-danger">5个</span></p>
                        <p class="text-sm text-text-medium-brown">掌握率: <span class="font-semibold text-primary">78%</span></p>
                    </div>
                    <button class="mt-4 w-full bg-purple-500 text-white py-2 rounded-lg hover:bg-purple-600 transition" onclick="switchToMemory()">开始记忆</button>
                </div>
            </div>
            
            <!-- 快速操作区域 -->
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">快速操作</h3>
                <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="switchToLearnFromMaterials()">
                        <span class="material-icons-outlined text-2xl text-blue-500 mb-2">edit_note</span>
                        <span class="text-sm text-text-dark-brown">从资料学习</span>
                    </button>
                    <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="switchToLearnFromMedia()">
                        <span class="material-icons-outlined text-2xl text-green-500 mb-2">mic</span>
                        <span class="text-sm text-text-dark-brown">从音视频学习</span>
                    </button>
                    <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="switchToPracticeFromKnowledge()">
                        <span class="material-icons-outlined text-2xl text-orange-500 mb-2">quiz</span>
                        <span class="text-sm text-text-dark-brown">知识点练习</span>
                    </button>
                    <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="switchToKnowledgeBase()">
                        <span class="material-icons-outlined text-2xl text-purple-500 mb-2">library_books</span>
                        <span class="text-sm text-text-dark-brown">知识库管理</span>
                    </button>
                </div>
            </div>
        </main>
    </div>

    <script>
        var bridge = null;
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        });
        
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }
        
        // 一级菜单切换函数
        function switchToLearn() {
            if (bridge && bridge.switchToLearn) {
                bridge.switchToLearn();
            }
        }
        
        function switchToPractice() {
            if (bridge && bridge.switchToPractice) {
                bridge.switchToPractice();
            }
        }
        
        function switchToMemory() {
            if (bridge && bridge.switchToMemory) {
                bridge.switchToMemory();
            }
        }
        
        function switchToKnowledgeBase() {
            if (bridge && bridge.switchToKnowledgeBase) {
                bridge.switchToKnowledgeBase();
            }
        }
        
        function openSettings() {
            if (bridge && bridge.openSettings) {
                bridge.openSettings();
            }
        }
        
        // 二级菜单切换函数
        function switchToLearnFromMaterials() {
            if (bridge && bridge.switchToLearnFromMaterials) {
                bridge.switchToLearnFromMaterials();
            }
        }
        
        function switchToLearnFromMedia() {
            if (bridge && bridge.switchToLearnFromMedia) {
                bridge.switchToLearnFromMedia();
            }
        }
        
        function switchToPracticeFromKnowledge() {
            if (bridge && bridge.switchToPracticeFromKnowledge) {
                bridge.switchToPracticeFromKnowledge();
            }
        }
        
        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }
        
        // 兼容方法（保留原有功能）
        function switchToNotebook() {
            switchToLearnFromMaterials();
        }
        
        function switchToRecording() {
            switchToLearnFromMedia();
        }
    </script>
</body>
</html>'''

    def create_notebook_html(self):
        """创建笔记本页面的HTML内容 - 简化测试版本"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>从资料学习 - 测试版本</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-8">
    <div class="max-w-4xl mx-auto">
        <h1 class="text-3xl font-bold text-gray-800 mb-6">从资料学习</h1>
        <div class="bg-white rounded-lg shadow p-6">
            <p class="text-gray-600 mb-4">这是简化的测试版本</p>
            <button class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600" onclick="testFunction()">测试按钮</button>
        </div>
    </div>
    
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        console.log('页面开始加载...');
        
        var bridge = null;
        
        function testFunction() {
            console.log('测试按钮被点击');
            alert('测试成功！');
        }
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
        });
        
        console.log('页面加载完成');
    </script>
</body>
</html>'''
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
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#" onclick="switchToLearn()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">school</span>
                    <span class="sidebar-text">学</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToPractice()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">quiz</span>
                    <span class="sidebar-text">练</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToMemory()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">psychology</span>
                    <span class="sidebar-text">记</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchToKnowledgeBase()">
                    <span class="material-icons-outlined mr-3 nav-item-icon">library_books</span>
                    <span class="sidebar-text">知识库管理</span>
                </a>
            </nav>
            
            <!-- 设置图标固定在底部 -->
            <div class="mt-auto flex justify-between items-center">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
                <button class="p-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="openSettings()" title="设置">
                    <span class="material-icons-outlined">settings</span>
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
        var bridge = null;
        var currentFilePath = null;

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
        
        // 新的一级菜单切换函数
        function switchToLearn() {
            if (bridge && bridge.switchToLearn) {
                bridge.switchToLearn();
            }
        }
        
        function switchToPractice() {
            if (bridge && bridge.switchToPractice) {
                bridge.switchToPractice();
            }
        }
        
        function switchToMemory() {
            if (bridge && bridge.switchToMemory) {
                bridge.switchToMemory();
            }
        }
        
        function openSettings() {
            if (bridge && bridge.openSettings) {
                bridge.openSettings();
            }
        }

        function toggleSidebar() {
            var sidebar = document.getElementById('sidebar');
            var fileStructure = document.getElementById('file-structure');
            var mainContent = document.getElementById('main-content');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                fileStructure.classList.add('hidden');
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                fileStructure.classList.remove('hidden');
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        function loadFileStructure() {
            if (bridge && bridge.getFileStructure) {
                bridge.getFileStructure().then(function(structureJson) {
                    var fileStructure = JSON.parse(structureJson);
                    renderFileTree(fileStructure);
                });
            }
        }

        function renderFileTree(structure) {
            var container = document.getElementById('file-tree');
            container.innerHTML = '';
            
            function renderItems(items, container, level) {
                level = level || 0;
                items.forEach(function(item) {
                    var div = document.createElement('div');
                    div.className = 'flex items-center p-2 rounded-md hover:bg-bg-light-gray cursor-pointer';
                    div.style.paddingLeft = (level * 20 + 8) + 'px';
                    
                    if (item.type === 'folder') {
                        div.innerHTML = '<span class="material-icons-outlined text-yellow-500 mr-2">folder</span>' +
                            '<span class="text-text-dark-brown font-medium">' + item.name + '</span>' +
                            '<span class="material-icons-outlined text-text-gray ml-auto">chevron_right</span>';
                    } else if (item.type === 'file') {
                        div.innerHTML = '<span class="material-icons-outlined text-gray-500 mr-2">description</span>' +
                            '<span class="text-text-medium-brown">' + item.name + '</span>';
                        
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
            var allFiles = document.querySelectorAll('#file-tree > div, #file-tree div div');
            allFiles.forEach(function(file) {
                file.classList.remove('bg-bg-light-green');
                var span = file.querySelector('span:last-child');
                if (span) {
                    span.classList.remove('text-primary', 'font-semibold');
                    span.classList.add('text-text-medium-brown');
                }
            });
            
            // 高亮当前选中的文件
            var currentFile = Array.from(allFiles).find(function(file) {
                var nameSpan = file.querySelector('span:last-child');
                return nameSpan && nameSpan.textContent === fileName;
            });
            
            if (currentFile) {
                currentFile.classList.add('bg-bg-light-green');
                var nameSpan = currentFile.querySelector('span:last-child');
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
            var previewBtn = document.getElementById('preview-btn');
            var editBtn = document.getElementById('edit-btn');
            
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
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
    def load_html_content(self):
        """加载HTML内容"""
        # 默认加载工作台页面
        html_content = self.create_dashboard_html()
        self.web_view.setHtml(html_content)
        
    def create_recording_html(self):
        """创建录音室页面的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>录音室 - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        if (typeof tailwind !== 'undefined') {
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
        }};
        }}
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
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg shadow-md nav-link" href="#">
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

        <main class="flex-1 flex flex-col p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex-shrink-0 flex justify-between items-center mb-6">
                <h2 class="text-2xl font-bold text-text-dark-brown">录音室</h2>
                <div class="flex items-center space-x-4">
                    <button class="bg-primary text-white font-semibold py-2 px-4 rounded-lg flex items-center shadow-sm hover:bg-green-600 transition duration-300" id="start-recording">
                        <span class="material-icons-outlined mr-2">play_arrow</span>
                        <span>开始录音</span>
                    </button>
                    <button class="bg-white text-text-gray font-semibold py-2 px-4 rounded-lg flex items-center border border-gray-300 hover:bg-gray-50 transition duration-300" id="pause-recording">
                        <span class="material-icons-outlined mr-2">pause</span>
                        <span>暂停录音</span>
                    </button>
                    <button class="bg-white text-text-gray font-semibold py-2 px-4 rounded-lg flex items-center border border-gray-300 hover:bg-gray-50 transition duration-300" id="save-notes">
                        <span class="material-icons-outlined mr-2">save</span>
                        <span>保存笔记</span>
                    </button>
                    <button class="bg-white text-text-gray font-semibold py-2 px-4 rounded-lg flex items-center border border-gray-300 hover:bg-gray-50 transition duration-300" id="manual-summary">
                        <span class="material-icons-outlined mr-2">auto_awesome</span>
                        <span>手动总结</span>
                    </button>
                    <button class="bg-white text-text-gray font-semibold py-2 px-4 rounded-lg flex items-center border border-gray-300 hover:bg-gray-50 transition duration-300" id="screenshot-notes">
                        <span class="material-icons-outlined mr-2">photo_camera</span>
                        <span>截图笔记</span>
                    </button>
                    <div class="flex space-x-1 ml-4">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                    </div>
                </div>
            </header>
            
            <div class="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div class="bg-white p-6 rounded-xl shadow-sm flex flex-col">
                    <h3 class="text-xl font-semibold text-text-dark-brown mb-4">笔记总结 (Markdown)</h3>
                    <div class="flex-1 border border-gray-200 rounded-lg p-4 prose max-w-none" id="markdown-editor">
                        <h4># 标题一</h4>
                        <p>这是<strong>加粗</strong>的文本，这是<em>斜体</em>的文本。</p>
                        <ul>
                            <li>列表项一</li>
                            <li>列表项二</li>
                        </ul>
                        <pre><code>// 代码块
function helloWorld() {
  console.log("Hello, world!");
}
                        </code></pre>
                        <blockquote>
                            <p>这是一段引用的文字。</p>
                        </blockquote>
                        <p>在这里编辑和查看您的Markdown笔记总结。</p>
                    </div>
                </div>
                
                <div class="bg-white p-6 rounded-xl shadow-sm flex flex-col">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-xl font-semibold text-text-dark-brown">实时语音转写</h3>
                        <div class="flex items-center space-x-2">
                            <span class="text-sm text-text-gray">音量</span>
                            <div class="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                                <div class="h-full bg-primary transition-all duration-300" style="width: 60%;" id="volume-bar"></div>
                            </div>
                        </div>
                    </div>
                    <div class="flex-1 border border-gray-200 rounded-lg p-4 space-y-4 overflow-y-auto" style="min-height: 300px;" id="transcription-area">
                        <div class="flex">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:03]</span>
                            <p class="text-text-medium-brown">今天我们来学习一下柯基的日常行为习惯。柯基犬，全名彭布罗克威尔士柯基犬，是一种非常聪明活泼的犬种。</p>
                        </div>
                        <div class="flex">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:15]</span>
                            <p class="text-text-medium-brown">它们的精力非常旺盛，需要每天有足够的运动量来消耗体力，否则可能会出现一些破坏性行为。</p>
                        </div>
                        <div class="flex bg-bg-light-green p-2 rounded-lg">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:28]</span>
                            <p class="text-text-dark-brown">请注意，这里的重点是运动量，这是保证柯基身心健康的关键。</p>
                        </div>
                        <div class="flex">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:40]</span>
                            <p class="text-text-medium-brown">在饮食方面，需要注意控制体重，因为它们天生容易发胖，过胖会对脊椎造成很大压力。</p>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        var bridge = null;
        var isRecording = false;

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
            var sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        // 录音功能
        document.addEventListener('DOMContentLoaded', function() {
            var startBtn = document.getElementById('start-recording');
            var pauseBtn = document.getElementById('pause-recording');
            var saveBtn = document.getElementById('save-notes');
            var summaryBtn = document.getElementById('manual-summary');
            var screenshotBtn = document.getElementById('screenshot-notes');
            var volumeBar = document.getElementById('volume-bar');

            if (startBtn) {
                startBtn.addEventListener('click', function() {
                    if (!isRecording) {
                        isRecording = true;
                        startBtn.innerHTML = '<span class="material-icons-outlined mr-2">stop</span><span>停止录音</span>';
                        startBtn.classList.remove('bg-primary');
                        startBtn.classList.add('bg-danger');
                        console.log('开始录音');
                        
                        // 模拟音量变化
                        simulateVolumeChange();
                    } else {
                        isRecording = false;
                        startBtn.innerHTML = '<span class="material-icons-outlined mr-2">play_arrow</span><span>开始录音</span>';
                        startBtn.classList.remove('bg-danger');
                        startBtn.classList.add('bg-primary');
                        console.log('停止录音');
                    }
                });
            }

            if (pauseBtn) {
                pauseBtn.addEventListener('click', function() {
                    console.log('暂停录音');
                });
            }

            if (saveBtn) {
                saveBtn.addEventListener('click', function() {
                    console.log('保存笔记');
                });
            }

            if (summaryBtn) {
                summaryBtn.addEventListener('click', function() {
                    console.log('手动总结');
                });
            }

            if (screenshotBtn) {
                screenshotBtn.addEventListener('click', function() {
                    console.log('截图笔记');
                });
            }

            function simulateVolumeChange() {
                if (!isRecording) return;
                
                var randomVolume = Math.random() * 100;
                volumeBar.style.width = randomVolume + '%';
                
                setTimeout(simulateVolumeChange, 200);
            }
        });
    </script>
</body>
</html>'''

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
        if (typeof tailwind !== 'undefined') {
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
        }};
        }}
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
        var bridge = null;

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
            var sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        // AI伙伴功能
        document.addEventListener('DOMContentLoaded', function() {
            var historyBtn = document.getElementById('history-btn');
            var newConversationBtn = document.getElementById('new-conversation-btn');
            var noteBtn = document.getElementById('note-btn');
            var magicBtn = document.getElementById('magic-btn');
            var sendBtn = document.getElementById('send-btn');
            var messageInput = document.getElementById('message-input');
            var chatArea = document.getElementById('chat-area');

            if (historyBtn) {
                historyBtn.addEventListener('click', function() {
                    console.log('查看对话历史');
                });
            }

            if (newConversationBtn) {
                newConversationBtn.addEventListener('click', function() {
                    console.log('开始新对话');
                    // 清空聊天区域，保留初始消息
                    var initialMessage = chatArea.querySelector('.flex:first-child');
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
                    var message = messageInput.value.trim();
                    if (message) {
                        // 添加用户消息
                        addUserMessage(message);
                        messageInput.value = '';
                        
                        // 模拟AI回复
                        setTimeout(function() {
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
                var messageDiv = document.createElement('div');
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
                var messageDiv = document.createElement('div');
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
        if (typeof tailwind !== 'undefined') {
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
        }};
        }}
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
        var bridge = null;

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
            var sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            } else {
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {
                chevron.textContent = 'chevron_right';
            } else {
                chevron.textContent = 'chevron_left';
            }
        }

        // 知识库管理功能
        document.addEventListener('DOMContentLoaded', function() {
            var searchInput = document.getElementById('search-input');
            var addSubjectBtn = document.getElementById('add-subject-btn');
            var addSubjectAction = document.getElementById('add-subject-action');
            var editSubjectAction = document.getElementById('edit-subject-action');
            var deleteSubjectAction = document.getElementById('delete-subject-action');
            var importExportAction = document.getElementById('import-export-action');

            if (searchInput) {
                searchInput.addEventListener('input', function() {
                    var query = this.value.toLowerCase();
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
            var subjectCards = document.querySelectorAll('.border.border-gray-200.rounded-lg');
            subjectCards.forEach(function(card) {
                if (!card.classList.contains('border-dashed')) {
                    card.addEventListener('click', function() {
                        var subjectName = this.querySelector('h4').textContent;
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
        if (typeof tailwind !== 'undefined') {{
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
        var bridge = null;

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
            var sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {{
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            }} else {{
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }}
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {{
                chevron.textContent = 'chevron_right';
            }} else {{
                chevron.textContent = 'chevron_left';
            }}
        }}

        // 科目详情功能
        document.addEventListener('DOMContentLoaded', function() {{
            var searchInput = document.getElementById('search-input');
            var selectAllCheckbox = document.getElementById('select-all');
            var batchMasteryBtn = document.getElementById('batch-mastery-btn');
            var batchDeleteBtn = document.getElementById('batch-delete-btn');
            var batchExportBtn = document.getElementById('batch-export-btn');
            var batchFavoriteBtn = document.getElementById('batch-favorite-btn');
            var pageSizeSelect = document.getElementById('page-size-select');
            var prevPageBtn = document.getElementById('prev-page-btn');
            var nextPageBtn = document.getElementById('next-page-btn');

            if (searchInput) {{
                searchInput.addEventListener('input', function() {{
                    var query = this.value.toLowerCase();
                    console.log('搜索知识点:', query);
                }});
            }}

            if (selectAllCheckbox) {{
                selectAllCheckbox.addEventListener('change', function() {{
                    var checkboxes = document.querySelectorAll('tbody input[type="checkbox"]');
                    checkboxes.forEach(function(checkbox) {{
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
            var favoriteButtons = document.querySelectorAll('tbody .material-icons-outlined');
            favoriteButtons.forEach(function(button) {{
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
        if (typeof tailwind !== 'undefined') {{
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
        var bridge = null;

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
            var sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            var isCollapsed = sidebar.classList.contains('collapsed');
            
            if (isCollapsed) {{
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
            }} else {{
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
            }}
            
            var chevron = document.getElementById('toggle-icon');
            if (isCollapsed) {{
                chevron.textContent = 'chevron_right';
            }} else {{
                chevron.textContent = 'chevron_left';
            }}
        }}

        // 知识点详情功能
        document.addEventListener('DOMContentLoaded', function() {{
            var globalSearch = document.getElementById('global-search');
            var notificationBtn = document.getElementById('notification-btn');
            var practiceBtn = document.getElementById('practice-btn');
            var errorPracticeBtn = document.getElementById('error-practice-btn');
            var questionSearch = document.getElementById('question-search');
            var questionTypeFilter = document.getElementById('question-type-filter');
            var questionSort = document.getElementById('question-sort');
            var prevPage = document.getElementById('prev-page');
            var nextPage = document.getElementById('next-page');

            if (globalSearch) {{
                globalSearch.addEventListener('input', function() {{
                    var query = this.value.toLowerCase();
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
                    var query = this.value.toLowerCase();
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
            var favoriteButtons = document.querySelectorAll('button[title="收藏题目"], button[title="已收藏"]');

            favoriteButtons.forEach(function(button) {{
                button.addEventListener('click', function() {{
                    var icon = this.querySelector('.material-icons-outlined');
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

    def create_spa_html(self):
        """创建单页面应用的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
    <script>
        if (typeof tailwind !== 'undefined') {
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
        }};
        }}
    </script>
    <style>
        .submenu {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }
        .submenu.expanded {
            max-height: 200px;
        }
        .menu-item.active {
            background-color: #32C77F;
            color: white;
        }
        .menu-item.active .material-icons-outlined {
            color: white;
        }
        /* 侧边栏收缩样式 */
        .sidebar-collapsed {
            width: 80px !important;
        }
        .sidebar-collapsed .sidebar-text,
        .sidebar-collapsed .user-profile,
        .sidebar-collapsed .logo-text {
            display: none;
        }
        .sidebar-collapsed .nav-item-icon {
            margin-right: 0 !important;
        }
        .sidebar-collapsed .menu-item {
            justify-content: center;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        .sidebar-collapsed .submenu {
            display: none;
        }
        .sidebar-collapsed .expand-arrow {
            display: none;
        }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <!-- 左侧固定菜单 -->
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200 transition-all duration-300" id="sidebar">
            <div class="flex items-center mb-8">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3 flex-shrink-0">
                    <span class="material-icons-outlined text-white">school</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown logo-text">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8 user-profile">
                <div class="w-20 h-20 rounded-full bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center mb-2">
                    <span class="material-icons-outlined text-white text-3xl">account_circle</span>
                </div>
                <p class="font-semibold text-text-dark-brown sidebar-text">柯基的主人</p>
                <p class="text-sm text-text-medium-brown sidebar-text">学习等级: Lv.5 ⭐</p>
            </div>
            
            <nav class="flex-1 space-y-1">
                <!-- 工作台 -->
                <div class="menu-item flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer active" onclick="loadContent('dashboard')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">work</span>
                    <span class="sidebar-text">工作台</span>
                </div>
                
                <!-- 学 -->
                <div>
                    <div class="menu-item flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="toggleSubmenu('learn')">
                        <span class="material-icons-outlined mr-3 nav-item-icon">school</span>
                        <span class="flex-1 sidebar-text">学</span>
                        <span class="material-icons-outlined text-sm transition-transform expand-arrow" id="learn-arrow">expand_more</span>
                    </div>
                    <div class="submenu ml-6" id="learn-submenu">
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('learn-materials')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">edit_note</span>
                            <span class="sidebar-text">从资料学习</span>
                        </div>
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('learn-media')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">mic</span>
                            <span class="sidebar-text">从音视频学习</span>
                        </div>
                    </div>
                </div>
                
                <!-- 练 -->
                <div>
                    <div class="menu-item flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="toggleSubmenu('practice')">
                        <span class="material-icons-outlined mr-3 nav-item-icon">quiz</span>
                        <span class="flex-1 sidebar-text">练</span>
                        <span class="material-icons-outlined text-sm transition-transform expand-arrow" id="practice-arrow">expand_more</span>
                    </div>
                    <div class="submenu ml-6" id="practice-submenu">
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('practice-materials')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">description</span>
                            <span class="sidebar-text">基于学习资料练习</span>
                        </div>
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('practice-knowledge')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">lightbulb</span>
                            <span class="sidebar-text">基于知识点练习</span>
                        </div>
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('practice-errors')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">error</span>
                            <span class="sidebar-text">基于错题练习</span>
                        </div>
                    </div>
                </div>
                
                <!-- 记 -->
                <div>
                    <div class="menu-item flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="toggleSubmenu('memory')">
                        <span class="material-icons-outlined mr-3 nav-item-icon">psychology</span>
                        <span class="flex-1 sidebar-text">记</span>
                        <span class="material-icons-outlined text-sm transition-transform expand-arrow" id="memory-arrow">expand_more</span>
                    </div>
                    <div class="submenu ml-6" id="memory-submenu">
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('memory-knowledge')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">account_tree</span>
                            <span class="sidebar-text">基于知识点记忆</span>
                        </div>
                        <div class="menu-item flex items-center px-4 py-2 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('memory-errors')">
                            <span class="material-icons-outlined mr-3 text-sm nav-item-icon">refresh</span>
                            <span class="sidebar-text">基于错题记忆</span>
                        </div>
                    </div>
                </div>
                
                <!-- 知识库管理 -->
                <div class="menu-item flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg cursor-pointer" onclick="loadContent('knowledge-base')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">library_books</span>
                    <span class="sidebar-text">知识库管理</span>
                </div>
            </nav>
            
            <!-- 设置图标固定在底部 -->
            <div class="mt-auto flex justify-between items-center">
                <button class="flex items-center justify-center w-full py-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="toggleSidebar()" id="toggle-btn">
                    <span class="material-icons-outlined" id="toggle-icon">chevron_left</span>
                </button>
                <button class="p-2 text-text-gray hover:bg-bg-light-gray rounded-lg" onclick="loadContent('settings')" title="设置">
                    <span class="material-icons-outlined">settings</span>
                </button>
            </div>
        </aside>
        
        <!-- 右侧动态内容区域 -->
        <main class="flex-1 flex flex-col">
            <header class="flex justify-between items-center p-6 bg-white border-b border-gray-200">
                <h2 class="text-2xl font-bold text-text-dark-brown" id="page-title">柯基的学习乐园</h2>
                <div class="flex space-x-2">
                    <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                    <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                    <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                </div>
            </header>
            
            <div class="flex-1 p-6 bg-bg-light-blue-gray overflow-y-auto" id="content-area">
                <!-- 动态加载的内容将显示在这里 -->
            </div>
        </main>
    </div>

    <script>
        var bridge = null;
        var currentContent = 'dashboard';
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
            // 默认加载工作台内容
            loadContent('dashboard');
        });
        
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }
        
        // 切换子菜单展开/折叠
        function toggleSubmenu(menuId) {
            var submenu = document.getElementById(menuId + '-submenu');
            var arrow = document.getElementById(menuId + '-arrow');
            
            if (submenu.classList.contains('expanded')) {
                submenu.classList.remove('expanded');
                arrow.style.transform = 'rotate(0deg)';
            } else {
                // 先折叠所有其他子菜单
                document.querySelectorAll('.submenu').forEach(function(sub) {
                    sub.classList.remove('expanded');
                });
                document.querySelectorAll('[id$="-arrow"]').forEach(function(arr) {
                    arr.style.transform = 'rotate(0deg)';
                });
                
                // 展开当前子菜单
                submenu.classList.add('expanded');
                arrow.style.transform = 'rotate(180deg)';
            }
        }
        
        // 切换侧边栏收缩状态
        function toggleSidebar() {
            var sidebar = document.getElementById('sidebar');
            var toggleIcon = document.getElementById('toggle-icon');
            
            if (sidebar.classList.contains('sidebar-collapsed')) {
                // 展开侧边栏
                sidebar.classList.remove('sidebar-collapsed');
                sidebar.classList.remove('w-20');
                sidebar.classList.add('w-64');
                toggleIcon.textContent = 'chevron_left';
            } else {
                // 收缩侧边栏
                sidebar.classList.add('sidebar-collapsed');
                sidebar.classList.remove('w-64');
                sidebar.classList.add('w-20');
                toggleIcon.textContent = 'chevron_right';
                
                // 收缩时自动折叠所有子菜单
                document.querySelectorAll('.submenu').forEach(function(sub) {
                    sub.classList.remove('expanded');
                });
                document.querySelectorAll('[id$="-arrow"]').forEach(function(arr) {
                    arr.style.transform = 'rotate(0deg)';
                });
            }
        }
        
        // 加载内容到右侧区域
        function loadContent(contentType) {
            // 更新菜单激活状态
            document.querySelectorAll('.menu-item').forEach(function(item) {
                item.classList.remove('active');
            });
            
            // 根据内容类型调用对应的Python方法
            currentContent = contentType;
            
            if (bridge) {
                switch(contentType) {
                    case 'dashboard':
                        bridge.loadDashboardContent();
                        document.querySelector('[onclick="loadContent(\\'dashboard\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '柯基的学习乐园';
                        break;
                    case 'learn-materials':
                        bridge.loadLearnFromMaterialsContent();
                        document.querySelector('[onclick="loadContent(\\'learn-materials\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '从资料学习';
                        break;
                    case 'learn-media':
                        bridge.loadLearnFromMediaContent();
                        document.querySelector('[onclick="loadContent(\\'learn-media\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '从音视频学习';
                        break;
                    case 'practice-materials':
                        bridge.loadPracticeFromMaterialsContent();
                        document.querySelector('[onclick="loadContent(\\'practice-materials\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '基于学习资料练习';
                        break;
                    case 'practice-knowledge':
                        bridge.loadPracticeFromKnowledgeContent();
                        document.querySelector('[onclick="loadContent(\\'practice-knowledge\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '基于知识点练习';
                        break;
                    case 'practice-errors':
                        bridge.loadPracticeFromErrorsContent();
                        document.querySelector('[onclick="loadContent(\\'practice-errors\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '基于错题练习';
                        break;
                    case 'memory-knowledge':
                        bridge.loadMemoryFromKnowledgeContent();
                        document.querySelector('[onclick="loadContent(\\'memory-knowledge\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '基于知识点记忆';
                        break;
                    case 'memory-errors':
                        bridge.loadMemoryFromErrorsContent();
                        document.querySelector('[onclick="loadContent(\\'memory-errors\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '基于错题记忆';
                        break;
                    case 'knowledge-base':
                        bridge.loadKnowledgeBaseContent();
                        document.querySelector('[onclick="loadContent(\\'knowledge-base\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '知识库管理';
                        break;
                    case 'settings':
                        bridge.loadSettingsContent();
                        document.querySelector('[onclick="loadContent(\\'settings\\')"]').classList.add('active');
                        document.getElementById('page-title').textContent = '系统设置';
                        break;
                }
            }
        }
    </script>
</body>
</html>'''

    def create_placeholder_html(self, title, description):
        """创建预留页面的HTML内容"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title} - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
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
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3">work</span>
                    <span>工作台</span>
                </a>
            </nav>
        </aside>
        
        <main class="flex-1 flex flex-col items-center justify-center p-8">
            <div class="text-center max-w-md">
                <div class="w-24 h-24 bg-primary rounded-full flex items-center justify-center mx-auto mb-6">
                    <span class="material-icons-outlined text-white text-4xl">construction</span>
                </div>
                <h2 class="text-2xl font-bold text-text-dark-brown mb-4">{title}</h2>
                <p class="text-text-medium-brown mb-6">{description}</p>
                <p class="text-sm text-text-gray">此功能正在开发中，敬请期待！</p>
                <button class="mt-6 bg-primary text-white px-6 py-2 rounded-lg hover:bg-green-600 transition" onclick="switchToDashboard()">
                    返回工作台
                </button>
            </div>
        </main>
    </div>
    
    <script>
        var bridge = null;
        new QWebChannel(qt.webChannelTransport, function(channel) {{
            bridge = channel.objects.bridge;
        }});
        
        function switchToDashboard() {{
            if (bridge && bridge.switchToDashboard) {{
                bridge.switchToDashboard();
            }}
        }}
    </script>
</body>
</html>'''

    def create_learn_menu_html(self):
        """创建学习模块二级菜单页面"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>学习 - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
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
            
            <nav class="flex-1 space-y-2">
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg" href="#" onclick="switchToDashboard()">
                    <span class="material-icons-outlined mr-3">work</span>
                    <span>工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-white bg-primary rounded-lg" href="#">
                    <span class="material-icons-outlined mr-3">school</span>
                    <span>学</span>
                </a>
            </nav>
        </aside>
        
        <main class="flex-1 p-8">
            <header class="flex justify-between items-center mb-8">
                <h2 class="text-3xl font-bold text-text-dark-brown">学习模块</h2>
                <div class="flex space-x-2">
                    <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('minimizeWindow')">−</button>
                    <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('maximizeWindow')">□</button>
                    <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold" onclick="callPythonFunction('closeWindow')">×</button>
                </div>
            </header>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div class="bg-white p-8 rounded-xl shadow-sm border-2 border-blue-200 hover:border-blue-400 transition cursor-pointer" onclick="switchToLearnFromMaterials()">
                    <div class="text-center">
                        <div class="w-20 h-20 bg-blue-500 rounded-full flex items-center justify-center mx-auto mb-4">
                            <span class="material-icons-outlined text-white text-3xl">edit_note</span>
                        </div>
                        <h3 class="text-xl font-bold text-text-dark-brown mb-3">从资料学习</h3>
                        <p class="text-text-medium-brown mb-4">支持导入MD、PDF文件；页面显示文件列表+预览框；用户可在预览时加亮文本，手动总结至左侧学习笔记，生成新MD文件。</p>
                        <button class="bg-blue-500 text-white px-6 py-2 rounded-lg hover:bg-blue-600 transition">开始学习</button>
                    </div>
                </div>
                
                <div class="bg-white p-8 rounded-xl shadow-sm border-2 border-green-200 hover:border-green-400 transition cursor-pointer" onclick="switchToLearnFromMedia()">
                    <div class="text-center">
                        <div class="w-20 h-20 bg-green-500 rounded-full flex items-center justify-center mx-auto mb-4">
                            <span class="material-icons-outlined text-white text-3xl">mic</span>
                        </div>
                        <h3 class="text-xl font-bold text-text-dark-brown mb-3">从音视频学习</h3>
                        <p class="text-text-medium-brown mb-4">支持输入在线音视频链接或导入本地音视频；实时转写声音为文字，用户可手动总结或设置定时自动总结转写文稿。</p>
                        <button class="bg-green-500 text-white px-6 py-2 rounded-lg hover:bg-green-600 transition">开始学习</button>
                    </div>
                </div>
            </div>
        </main>
    </div>
    
    <script>
        var bridge = null;
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
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
        
        function switchToLearnFromMaterials() {
            if (bridge && bridge.switchToLearnFromMaterials) {
                bridge.switchToLearnFromMaterials();
            }
        }
        
        function switchToLearnFromMedia() {
            if (bridge && bridge.switchToLearnFromMedia) {
                bridge.switchToLearnFromMedia();
            }
        }
    </script>
</body>
</html>'''

    def create_practice_menu_html(self):
        """创建练习模块二级菜单页面"""
        return self.create_placeholder_html("练习模块", "练习功能正在开发中，包含基于学习资料练习、基于知识点练习、基于错题练习三个子模块。")

    def create_memory_menu_html(self):
        """创建记忆模块二级菜单页面"""
        return self.create_placeholder_html("记忆模块", "记忆功能正在开发中，包含基于知识点记忆、基于错题记忆两个子模块。")

    def create_practice_knowledge_html(self):
        """创建基于知识点练习页面"""
        return self.create_placeholder_html("基于知识点练习", "支持用户搜索、查找知识点，将选中知识点从左侧移至右侧'练习池'，点击生成按钮后调用AI生成对应练习题。")

    def create_practice_errors_html(self):
        """创建基于错题练习页面"""
        return self.create_placeholder_html("基于错题练习", "支持用户搜索、勾选已有错题，将选中错题归入'错题练习池'，点击练习按钮后基于这些错题进行练习。")

    def create_dashboard_content_html(self):
        """创建工作台内容HTML（不包含侧边栏）"""
        return '''
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
            <!-- 学习模块数据 -->
            <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-blue-500">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold text-text-dark-brown">学习进度</h3>
                    <span class="material-icons-outlined text-blue-500">school</span>
                </div>
                <div class="space-y-2">
                    <p class="text-sm text-text-medium-brown">今日学习: <span class="font-semibold text-primary">2小时</span></p>
                    <p class="text-sm text-text-medium-brown">本周笔记: <span class="font-semibold text-primary">5篇</span></p>
                    <p class="text-sm text-text-medium-brown">音视频学习: <span class="font-semibold text-primary">3个</span></p>
                </div>
                <button class="mt-4 w-full bg-blue-500 text-white py-2 rounded-lg hover:bg-blue-600 transition" onclick="loadContent('learn-materials')">进入学习</button>
            </div>
            
            <!-- 练习模块数据 -->
            <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-green-500">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold text-text-dark-brown">练习情况</h3>
                    <span class="material-icons-outlined text-green-500">quiz</span>
                </div>
                <div class="space-y-2">
                    <p class="text-sm text-text-medium-brown">待完成练习: <span class="font-semibold text-warning">3个</span></p>
                    <p class="text-sm text-text-medium-brown">本周完成: <span class="font-semibold text-primary">12个</span></p>
                    <p class="text-sm text-text-medium-brown">正确率: <span class="font-semibold text-primary">85%</span></p>
                </div>
                <button class="mt-4 w-full bg-green-500 text-white py-2 rounded-lg hover:bg-green-600 transition" onclick="loadContent('practice-knowledge')">开始练习</button>
            </div>
            
            <!-- 记忆模块数据 -->
            <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-purple-500">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold text-text-dark-brown">记忆复习</h3>
                    <span class="material-icons-outlined text-purple-500">psychology</span>
                </div>
                <div class="space-y-2">
                    <p class="text-sm text-text-medium-brown">待复习知识点: <span class="font-semibold text-warning">8个</span></p>
                    <p class="text-sm text-text-medium-brown">待复习错题: <span class="font-semibold text-danger">5个</span></p>
                    <p class="text-sm text-text-medium-brown">掌握率: <span class="font-semibold text-primary">78%</span></p>
                </div>
                <button class="mt-4 w-full bg-purple-500 text-white py-2 rounded-lg hover:bg-purple-600 transition" onclick="loadContent('memory-knowledge')">开始记忆</button>
            </div>
        </div>
        
        <!-- 快速操作区域 -->
        <div class="bg-white p-6 rounded-xl shadow-sm">
            <h3 class="text-xl font-semibold text-text-dark-brown mb-4">快速操作</h3>
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="loadContent('learn-materials')">
                    <span class="material-icons-outlined text-2xl text-blue-500 mb-2">edit_note</span>
                    <span class="text-sm text-text-dark-brown">从资料学习</span>
                </button>
                <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="loadContent('learn-media')">
                    <span class="material-icons-outlined text-2xl text-green-500 mb-2">mic</span>
                    <span class="text-sm text-text-dark-brown">从音视频学习</span>
                </button>
                <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="loadContent('practice-knowledge')">
                    <span class="material-icons-outlined text-2xl text-orange-500 mb-2">quiz</span>
                    <span class="text-sm text-text-dark-brown">知识点练习</span>
                </button>
                <button class="flex flex-col items-center p-4 bg-bg-light-blue-gray rounded-lg hover:bg-gray-200 transition" onclick="loadContent('knowledge-base')">
                    <span class="material-icons-outlined text-2xl text-purple-500 mb-2">library_books</span>
                    <span class="text-sm text-text-dark-brown">知识库管理</span>
                </button>
            </div>
        </div>
        '''

    def create_learn_materials_content_html(self):
        """创建从资料学习内容HTML"""
        return '''
        <div class="flex h-full gap-4">
            <!-- 文件列表面板 -->
            <div class="w-1/4 bg-white rounded-xl shadow-sm flex flex-col">
                <div class="flex justify-between items-center p-4 border-b border-gray-200">
                    <h3 class="text-lg font-semibold text-text-dark-brown">文件列表</h3>
                    <div class="flex space-x-2">
                        <button class="text-primary hover:text-green-600 p-1 rounded" onclick="createNewNote()" title="新建笔记">
                            <span class="material-icons-outlined text-sm">note_add</span>
                        </button>
                        <button class="text-primary hover:text-green-600 p-1 rounded" onclick="createNewFolder()" title="新建文件夹">
                            <span class="material-icons-outlined text-sm">create_new_folder</span>
                        </button>
                    </div>
                </div>
                <div class="flex-1 overflow-y-auto p-4" id="file-tree-container">
                    <!-- 文件树将在这里动态生成 -->
                    <div class="text-center text-gray-500 py-8">
                        <span class="material-icons-outlined text-4xl mb-2 block">folder_open</span>
                        <p>正在加载文件列表...</p>
                    </div>
                </div>
            </div>
            
            <!-- 文档预览区 -->
            <div class="flex-1 bg-white rounded-xl shadow-sm flex flex-col">
                <div class="flex justify-between items-center p-4 border-b border-gray-200">
                    <h3 class="text-lg font-semibold text-text-dark-brown" id="document-title">文档预览区</h3>
                    <div class="flex items-center space-x-2">
                        <button class="flex items-center bg-primary text-white px-3 py-1.5 rounded-lg hover:bg-green-600 transition" id="preview-mode-btn" onclick="switchToPreviewMode()">
                            <span class="material-icons-outlined text-sm mr-1">visibility</span>
                            <span>预览</span>
                        </button>
                        <button class="flex items-center bg-gray-300 text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-400 transition" id="edit-mode-btn" onclick="switchToEditMode()">
                            <span class="material-icons-outlined text-sm mr-1">edit</span>
                            <span>编辑</span>
                        </button>
                    </div>
                </div>
                <div class="flex-1 p-6 overflow-y-auto">
                    <!-- 预览模式 -->
                    <div id="preview-content" class="prose max-w-none">
                        <div class="text-center text-gray-500 py-20">
                            <span class="material-icons-outlined text-6xl mb-4 block">description</span>
                            <p class="text-xl">选择一个Markdown文件开始阅读</p>
                        </div>
                    </div>
                    <!-- 编辑模式 -->
                    <div id="edit-content" class="hidden h-full">
                        <textarea id="markdown-editor" class="w-full h-full p-4 border border-gray-300 rounded-lg resize-none font-mono text-sm" placeholder="在这里编辑Markdown内容..."></textarea>
                        <div class="flex justify-end mt-4 space-x-2">
                            <button class="bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400 transition" onclick="cancelEdit()">取消</button>
                            <button class="bg-primary text-white px-4 py-2 rounded-lg hover:bg-green-600 transition" onclick="saveMarkdown()">保存</button>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 学习笔记面板 -->
            <div class="w-1/4 bg-white rounded-xl shadow-sm flex flex-col">
                <div class="p-4 border-b border-gray-200">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-lg font-semibold text-text-dark-brown">学习笔记</h3>
                    </div>
                    <div class="flex space-x-2 mb-4">
                        <button class="flex-1 bg-primary text-white px-3 py-2 rounded-lg hover:bg-green-600 transition text-sm" onclick="extractKnowledgePoints()">
                            <span class="material-icons-outlined text-sm mr-1">auto_awesome</span>
                            提取全文知识点
                        </button>
                    </div>
                </div>
                <div class="flex-1 overflow-y-auto p-4" id="knowledge-points-container">
                    <div class="space-y-3" id="knowledge-points-list">
                        <!-- 知识点列表将在这里动态生成 -->
                        <div class="text-center text-gray-500 py-8">
                            <span class="material-icons-outlined text-4xl mb-2 block">lightbulb</span>
                            <p>暂无知识点</p>
                            <p class="text-sm mt-1">选择文档后点击"提取全文知识点"</p>
                        </div>
                    </div>
                </div>
                <div class="p-4 border-t border-gray-200">
                    <button class="w-full bg-gray-200 text-gray-700 px-3 py-2 rounded-lg hover:bg-gray-300 transition text-sm" onclick="addManualKnowledgePoint()">
                        <span class="material-icons-outlined text-sm mr-1">add</span>
                        手动增加知识点
                    </button>
                </div>
            </div>
        </div>
        
        <!-- 新建笔记对话框 -->
        <div id="new-note-dialog" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 w-96">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">新建笔记</h3>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-2">笔记名称</label>
                    <input type="text" id="new-note-name" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" placeholder="请输入笔记名称">
                </div>
                <div class="flex justify-end space-x-2">
                    <button class="bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400 transition" onclick="closeNewNoteDialog()">取消</button>
                    <button class="bg-primary text-white px-4 py-2 rounded-lg hover:bg-green-600 transition" onclick="confirmCreateNote()">确认</button>
                </div>
            </div>
        </div>
        
        <!-- 新建文件夹对话框 -->
        <div id="new-folder-dialog" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 w-96">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">新建文件夹</h3>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-2">文件夹名称</label>
                    <input type="text" id="new-folder-name" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" placeholder="请输入文件夹名称">
                </div>
                <div class="flex justify-end space-x-2">
                    <button class="bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400 transition" onclick="closeNewFolderDialog()">取消</button>
                    <button class="bg-primary text-white px-4 py-2 rounded-lg hover:bg-green-600 transition" onclick="confirmCreateFolder()">确认</button>
                </div>
            </div>
        </div>
        
        <!-- 手动添加知识点对话框 -->
        <div id="add-knowledge-dialog" class="fixed inset-0 bg-black bg-opacity-50 hidden flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 w-96">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">添加知识点</h3>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-2">知识点名称</label>
                    <input type="text" id="knowledge-point-name" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" placeholder="请输入知识点名称">
                </div>
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-2">知识点描述</label>
                    <textarea id="knowledge-point-description" class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary resize-none" rows="3" placeholder="请输入知识点描述"></textarea>
                </div>
                <div class="flex justify-end space-x-2">
                    <button class="bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400 transition" onclick="closeAddKnowledgeDialog()">取消</button>
                    <button class="bg-primary text-white px-4 py-2 rounded-lg hover:bg-green-600 transition" onclick="confirmAddKnowledge()">确认</button>
                </div>
            </div>
        </div>
        
        <script>
            var currentFilePath = null;
            var currentFileContent = null;
            var isEditMode = false;
            var selectedTreeNode = null;
            var knowledgePoints = [];
            
            // 页面加载完成后初始化
            document.addEventListener('DOMContentLoaded', function() {
                loadFileTree();
            });
            
            // 加载文件树
            function loadFileTree() {
                if (bridge && bridge.getFileStructure) {
                    bridge.getFileStructure().then(function(structureJson) {
                        var fileStructure = JSON.parse(structureJson);
                        renderFileTree(fileStructure);
                    });
                }
            }
            
            // 渲染文件树
            function renderFileTree(structure) {
                var container = document.getElementById('file-tree-container');
                container.innerHTML = '';
                
                function renderItems(items, container, level) {
                    level = level || 0;
                    items.forEach(function(item) {
                        var div = document.createElement('div');
                        div.className = 'file-tree-item';
                        div.style.paddingLeft = (level * 16 + 8) + 'px';
                        
                        if (item.type === 'folder') {
                            div.innerHTML = `
                                <div class="flex items-center p-2 rounded-md hover:bg-gray-100 cursor-pointer group" 
                                     onclick="toggleFolder(this)" 
                                     oncontextmenu="showContextMenu(event, '${item.path}', '${item.name}', 'folder')"
                                     draggable="true"
                                     ondragstart="handleDragStart(event, '${item.path}', 'folder')"
                                     ondragover="handleDragOver(event)"
                                     ondrop="handleDrop(event, '${item.path}')"
                                     data-path="${item.path}">
                                    <span class="material-icons-outlined text-yellow-600 mr-2 text-sm folder-icon">folder</span>
                                    <span class="text-sm font-medium text-gray-800 flex-1 item-name">${item.name}</span>
                                    <span class="material-icons-outlined text-gray-400 text-sm expand-icon">chevron_right</span>
                                    <div class="hidden group-hover:flex space-x-1 ml-2">
                                        <button class="text-gray-400 hover:text-blue-600 p-1" onclick="event.stopPropagation(); startRename('${item.path}', '${item.name}', 'folder')" title="重命名">
                                            <span class="material-icons-outlined text-xs">edit</span>
                                        </button>
                                    </div>
                                </div>
                                <div class="folder-children hidden ml-4"></div>
                            `;
                            
                            var childrenContainer = div.querySelector('.folder-children');
                            if (item.children && item.children.length > 0) {
                                renderItems(item.children, childrenContainer, level + 1);
                            }
                        } else if (item.type === 'file') {
                            div.innerHTML = `
                                <div class="flex items-center p-2 rounded-md hover:bg-gray-100 cursor-pointer group" 
                                     onclick="selectFile('${item.path}', '${item.name}')" 
                                     oncontextmenu="showContextMenu(event, '${item.path}', '${item.name}', 'file')"
                                     draggable="true"
                                     ondragstart="handleDragStart(event, '${item.path}', 'file')"
                                     data-path="${item.path}">
                                    <span class="material-icons-outlined text-blue-600 mr-2 text-sm">description</span>
                                    <span class="text-sm text-gray-700 flex-1 item-name">${item.name}</span>
                                    <div class="hidden group-hover:flex space-x-1 ml-2">
                                        <button class="text-gray-400 hover:text-blue-600 p-1" onclick="event.stopPropagation(); startRename('${item.path}', '${item.name}', 'file')" title="重命名">
                                            <span class="material-icons-outlined text-xs">edit</span>
                                        </button>
                                    </div>
                                </div>
                            `;
                        }
                        
                        container.appendChild(div);
                    });
                }
                
                renderItems(structure, container);
            }
            
            // 切换文件夹展开/折叠
            function toggleFolder(element) {
                var childrenContainer = element.parentElement.querySelector('.folder-children');
                var expandIcon = element.querySelector('.expand-icon');
                var folderIcon = element.querySelector('.folder-icon');
                
                if (childrenContainer.classList.contains('hidden')) {
                    childrenContainer.classList.remove('hidden');
                    expandIcon.textContent = 'expand_more';
                    folderIcon.textContent = 'folder_open';
                } else {
                    childrenContainer.classList.add('hidden');
                    expandIcon.textContent = 'chevron_right';
                    folderIcon.textContent = 'folder';
                }
                
                selectedTreeNode = element.dataset.path;
            }
            
            // 选择文件
            function selectFile(filePath, fileName) {
                currentFilePath = filePath;
                document.getElementById('document-title').textContent = fileName;
                
                // 高亮选中的文件
                document.querySelectorAll('.file-tree-item .group').forEach(function(item) {
                    item.classList.remove('bg-blue-100');
                });
                event.target.closest('.group').classList.add('bg-blue-100');
                
                selectedTreeNode = filePath;
                loadFileContent(filePath);
            }
            
            // 加载文件内容
            function loadFileContent(filePath) {
                if (bridge && bridge.loadMarkdownFile) {
                    bridge.loadMarkdownFile(filePath).then(function(htmlContent) {
                        document.getElementById('preview-content').innerHTML = htmlContent;
                        // 同时加载原始内容用于编辑
                        if (bridge.loadMarkdownRaw) {
                            bridge.loadMarkdownRaw(filePath).then(function(rawContent) {
                                currentFileContent = rawContent;
                                document.getElementById('markdown-editor').value = rawContent;
                            });
                        }
                    });
                }
            }
            
            // 切换到预览模式
            function switchToPreviewMode() {
                isEditMode = false;
                document.getElementById('preview-content').classList.remove('hidden');
                document.getElementById('edit-content').classList.add('hidden');
                document.getElementById('preview-mode-btn').classList.remove('bg-gray-300', 'text-gray-700');
                document.getElementById('preview-mode-btn').classList.add('bg-primary', 'text-white');
                document.getElementById('edit-mode-btn').classList.remove('bg-primary', 'text-white');
                document.getElementById('edit-mode-btn').classList.add('bg-gray-300', 'text-gray-700');
            }
            
            // 切换到编辑模式
            function switchToEditMode() {
                if (!currentFilePath) {
                    alert('请先选择一个文件');
                    return;
                }
                isEditMode = true;
                document.getElementById('preview-content').classList.add('hidden');
                document.getElementById('edit-content').classList.remove('hidden');
                document.getElementById('edit-mode-btn').classList.remove('bg-gray-300', 'text-gray-700');
                document.getElementById('edit-mode-btn').classList.add('bg-primary', 'text-white');
                document.getElementById('preview-mode-btn').classList.remove('bg-primary', 'text-white');
                document.getElementById('preview-mode-btn').classList.add('bg-gray-300', 'text-gray-700');
            }
            
            // 取消编辑
            function cancelEdit() {
                document.getElementById('markdown-editor').value = currentFileContent;
                switchToPreviewMode();
            }
            
            // 保存Markdown
            function saveMarkdown() {
                if (!currentFilePath) return;
                
                var content = document.getElementById('markdown-editor').value;
                if (bridge && bridge.saveMarkdownFile) {
                    bridge.saveMarkdownFile(currentFilePath, content).then(function(success) {
                        if (success) {
                            currentFileContent = content;
                            // 重新加载预览内容
                            loadFileContent(currentFilePath);
                            switchToPreviewMode();
                            alert('保存成功！');
                        } else {
                            alert('保存失败！');
                        }
                    });
                }
            }
            
            // 新建笔记相关函数
            function createNewNote() {
                document.getElementById('new-note-dialog').classList.remove('hidden');
                document.getElementById('new-note-name').focus();
            }
            
            function closeNewNoteDialog() {
                document.getElementById('new-note-dialog').classList.add('hidden');
                document.getElementById('new-note-name').value = '';
            }
            
            function confirmCreateNote() {
                var noteName = document.getElementById('new-note-name').value.trim();
                if (!noteName) {
                    alert('请输入笔记名称');
                    return;
                }
                
                // 调用Python方法创建新笔记
                if (bridge && bridge.createNewNote) {
                    bridge.createNewNote(noteName, selectedTreeNode || '').then(function(success) {
                        if (success) {
                            closeNewNoteDialog();
                            // 重新加载文件树
                            loadFileTree();
                            alert('笔记创建成功！');
                        } else {
                            alert('笔记创建失败，可能文件已存在');
                        }
                    });
                } else {
                    console.log('创建新笔记:', noteName, '位置:', selectedTreeNode);
                    closeNewNoteDialog();
                    loadFileTree();
                }
            }
            
            // 新建文件夹相关函数
            function createNewFolder() {
                document.getElementById('new-folder-dialog').classList.remove('hidden');
                document.getElementById('new-folder-name').focus();
            }
            
            function closeNewFolderDialog() {
                document.getElementById('new-folder-dialog').classList.add('hidden');
                document.getElementById('new-folder-name').value = '';
            }
            
            function confirmCreateFolder() {
                var folderName = document.getElementById('new-folder-name').value.trim();
                if (!folderName) {
                    alert('请输入文件夹名称');
                    return;
                }
                
                // 调用Python方法创建新文件夹
                if (bridge && bridge.createNewFolder) {
                    bridge.createNewFolder(folderName, selectedTreeNode || '').then(function(success) {
                        if (success) {
                            closeNewFolderDialog();
                            // 重新加载文件树
                            loadFileTree();
                            alert('文件夹创建成功！');
                        } else {
                            alert('文件夹创建失败，可能文件夹已存在');
                        }
                    });
                } else {
                    console.log('创建新文件夹:', folderName, '位置:', selectedTreeNode);
                    closeNewFolderDialog();
                    loadFileTree();
                }
            }
            
            // 提取知识点
            function extractKnowledgePoints() {
                if (!currentFilePath || !currentFileContent) {
                    alert('请先选择一个文件');
                    return;
                }
                
                // 调用Python方法提取知识点
                if (bridge && bridge.extractKnowledgePoints) {
                    bridge.extractKnowledgePoints(currentFileContent).then(function(knowledgePointsJson) {
                        try {
                            var extractedPoints = JSON.parse(knowledgePointsJson);
                            knowledgePoints = extractedPoints;
                            renderKnowledgePoints();
                            alert('知识点提取完成！');
                        } catch (e) {
                            console.error('解析知识点数据失败:', e);
                            alert('知识点提取失败');
                        }
                    });
                } else {
                    console.log('提取知识点:', currentFilePath);
                    
                    // 模拟提取的知识点数据
                    var mockKnowledgePoints = [
                        {
                            name: "机器学习定义",
                            description: "机器学习是人工智能的一个重要分支，它使计算机能够在没有明确编程的情况下学习和改进。",
                            anchor: "机器学习"
                        },
                        {
                            name: "监督学习",
                            description: "使用标记数据训练模型，包括分类和回归任务。",
                            anchor: "监督学习"
                        },
                        {
                            name: "无监督学习",
                            description: "从未标记的数据中发现隐藏的模式和结构。",
                            anchor: "无监督学习"
                        }
                    ];
                    
                    knowledgePoints = mockKnowledgePoints;
                    renderKnowledgePoints();
                }
            }
            
            // 渲染知识点列表
            function renderKnowledgePoints() {
                var container = document.getElementById('knowledge-points-list');
                
                if (knowledgePoints.length === 0) {
                    container.innerHTML = `
                        <div class="text-center text-gray-500 py-8">
                            <span class="material-icons-outlined text-4xl mb-2 block">lightbulb</span>
                            <p>暂无知识点</p>
                            <p class="text-sm mt-1">选择文档后点击"提取全文知识点"</p>
                        </div>
                    `;
                    return;
                }
                
                container.innerHTML = '';
                knowledgePoints.forEach(function(point, index) {
                    var div = document.createElement('div');
                    div.className = 'knowledge-point-item bg-blue-50 p-3 rounded-lg cursor-pointer hover:shadow-md transition-shadow relative group';
                    div.innerHTML = `
                        <h4 class="font-semibold text-blue-800 mb-1">${point.name}</h4>
                        <p class="text-sm text-gray-600">${point.description}</p>
                        <div class="absolute bottom-2 right-2 hidden group-hover:flex space-x-1">
                            <button class="bg-yellow-500 text-white p-1 rounded text-xs hover:bg-yellow-600" onclick="editKnowledgePoint(${index})" title="编辑">
                                <span class="material-icons-outlined text-xs">edit</span>
                            </button>
                            <button class="bg-red-500 text-white p-1 rounded text-xs hover:bg-red-600" onclick="deleteKnowledgePoint(${index})" title="删除">
                                <span class="material-icons-outlined text-xs">delete</span>
                            </button>
                        </div>
                    `;
                    
                    // 点击知识点定位到文档位置
                    div.addEventListener('click', function() {
                        locateInDocument(point.anchor);
                    });
                    
                    container.appendChild(div);
                });
            }
            
            // 定位到文档中的位置
            function locateInDocument(anchor) {
                // TODO: 实现文档定位功能
                console.log('定位到:', anchor);
            }
            
            // 编辑知识点
            function editKnowledgePoint(index) {
                var point = knowledgePoints[index];
                document.getElementById('knowledge-point-name').value = point.name;
                document.getElementById('knowledge-point-description').value = point.description;
                document.getElementById('add-knowledge-dialog').classList.remove('hidden');
                
                // 标记为编辑模式
                document.getElementById('add-knowledge-dialog').dataset.editIndex = index;
            }
            
            // 删除知识点
            function deleteKnowledgePoint(index) {
                if (confirm('确定要删除这个知识点吗？')) {
                    knowledgePoints.splice(index, 1);
                    renderKnowledgePoints();
                }
            }
            
            // 手动添加知识点
            function addManualKnowledgePoint() {
                document.getElementById('add-knowledge-dialog').classList.remove('hidden');
                document.getElementById('knowledge-point-name').focus();
                // 清除编辑模式标记
                delete document.getElementById('add-knowledge-dialog').dataset.editIndex;
            }
            
            function closeAddKnowledgeDialog() {
                document.getElementById('add-knowledge-dialog').classList.add('hidden');
                document.getElementById('knowledge-point-name').value = '';
                document.getElementById('knowledge-point-description').value = '';
                delete document.getElementById('add-knowledge-dialog').dataset.editIndex;
            }
            
            function confirmAddKnowledge() {
                var name = document.getElementById('knowledge-point-name').value.trim();
                var description = document.getElementById('knowledge-point-description').value.trim();
                
                if (!name || !description) {
                    alert('请填写完整的知识点信息');
                    return;
                }
                
                var editIndex = document.getElementById('add-knowledge-dialog').dataset.editIndex;
                
                if (editIndex !== undefined) {
                    // 编辑模式
                    knowledgePoints[parseInt(editIndex)] = { name, description, anchor: name };
                } else {
                    // 新增模式
                    knowledgePoints.push({ name, description, anchor: name });
                }
                
                renderKnowledgePoints();
                closeAddKnowledgeDialog();
            }
            
            // 拖放功能相关变量
            var draggedItem = null;
            var draggedType = null;
            
            // 拖拽开始
            function handleDragStart(event, itemPath, itemType) {
                draggedItem = itemPath;
                draggedType = itemType;
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', itemPath);
                
                // 添加拖拽样式
                event.target.style.opacity = '0.5';
            }
            
            // 拖拽经过
            function handleDragOver(event) {
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                
                // 添加拖拽目标样式
                var target = event.currentTarget;
                if (target.dataset.path !== draggedItem) {
                    target.style.backgroundColor = '#e3f2fd';
                }
            }
            
            // 拖拽离开
            function handleDragLeave(event) {
                event.currentTarget.style.backgroundColor = '';
            }
            
            // 拖拽结束
            function handleDragEnd(event) {
                event.target.style.opacity = '';
                
                // 清除所有拖拽样式
                document.querySelectorAll('.file-tree-item .group').forEach(function(item) {
                    item.style.backgroundColor = '';
                });
            }
            
            // 拖拽放下
            function handleDrop(event, targetPath) {
                event.preventDefault();
                event.currentTarget.style.backgroundColor = '';
                
                if (!draggedItem || draggedItem === targetPath) {
                    return;
                }
                
                // 调用Python方法移动文件/文件夹
                if (bridge && bridge.moveFileOrFolder) {
                    bridge.moveFileOrFolder(draggedItem, targetPath).then(function(success) {
                        if (success) {
                            loadFileTree();
                            alert('移动成功！');
                        } else {
                            alert('移动失败，可能目标位置已存在同名文件');
                        }
                    });
                }
                
                draggedItem = null;
                draggedType = null;
            }
            
            // 重命名功能
            function startRename(itemPath, currentName, itemType) {
                var newName = prompt('请输入新名称:', currentName.replace('.md', ''));
                if (newName && newName.trim() !== '' && newName.trim() !== currentName.replace('.md', '')) {
                    if (bridge && bridge.renameFileOrFolder) {
                        bridge.renameFileOrFolder(itemPath, newName.trim()).then(function(success) {
                            if (success) {
                                loadFileTree();
                                alert('重命名成功！');
                                
                                // 如果重命名的是当前打开的文件，更新相关信息
                                if (currentFilePath === itemPath) {
                                    var newPath = itemPath.replace(currentName, newName.trim() + (itemType === 'file' ? '.md' : ''));
                                    currentFilePath = newPath;
                                    document.getElementById('document-title').textContent = newName.trim() + (itemType === 'file' ? '.md' : '');
                                }
                            } else {
                                alert('重命名失败，可能新名称已存在');
                            }
                        });
                    }
                }
            }
            
            // 右键菜单功能
            function showContextMenu(event, itemPath, itemName, itemType) {
                event.preventDefault();
                
                // 创建右键菜单
                var contextMenu = document.createElement('div');
                contextMenu.className = 'fixed bg-white border border-gray-300 rounded-lg shadow-lg py-2 z-50';
                contextMenu.style.left = event.pageX + 'px';
                contextMenu.style.top = event.pageY + 'px';
                
                var menuItems = [
                    {
                        text: '重命名',
                        icon: 'edit',
                        action: function() { startRename(itemPath, itemName, itemType); }
                    }
                ];
                
                if (itemType === 'folder') {
                    menuItems.unshift({
                        text: '新建笔记',
                        icon: 'note_add',
                        action: function() {
                            selectedTreeNode = itemPath;
                            createNewNote();
                        }
                    });
                    menuItems.unshift({
                        text: '新建文件夹',
                        icon: 'create_new_folder',
                        action: function() {
                            selectedTreeNode = itemPath;
                            createNewFolder();
                        }
                    });
                }
                
                menuItems.forEach(function(item) {
                    var menuItem = document.createElement('div');
                    menuItem.className = 'flex items-center px-4 py-2 hover:bg-gray-100 cursor-pointer';
                    menuItem.innerHTML = `
                        <span class="material-icons-outlined text-sm mr-2">${item.icon}</span>
                        <span class="text-sm">${item.text}</span>
                    `;
                    menuItem.onclick = function() {
                        item.action();
                        document.body.removeChild(contextMenu);
                    };
                    contextMenu.appendChild(menuItem);
                });
                
                document.body.appendChild(contextMenu);
                
                // 点击其他地方关闭菜单
                var closeMenu = function(e) {
                    if (!contextMenu.contains(e.target)) {
                        document.body.removeChild(contextMenu);
                        document.removeEventListener('click', closeMenu);
                    }
                };
                
                setTimeout(function() {
                    document.addEventListener('click', closeMenu);
                }, 100);
            }
            
            // 添加拖拽事件监听器
            document.addEventListener('dragend', handleDragEnd);
            document.addEventListener('dragleave', handleDragLeave);
        </script>
        '''

    def create_learn_media_content_html(self):
        """创建从音视频学习内容HTML"""
        return '''
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">音视频播放</h3>
                <div class="bg-gray-200 h-64 rounded-lg flex items-center justify-center mb-4">
                    <span class="material-icons-outlined text-6xl text-gray-400">play_circle</span>
                </div>
                <div class="flex space-x-2">
                    <button class="bg-primary text-white px-4 py-2 rounded-lg hover:bg-green-600 transition">开始录音</button>
                    <button class="bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400 transition">暂停</button>
                    <button class="bg-warning text-white px-4 py-2 rounded-lg hover:bg-yellow-500 transition">保存</button>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">实时转写</h3>
                <div class="border border-gray-300 rounded-lg p-4 h-64 overflow-y-auto mb-4">
                    <div class="space-y-2">
                        <div class="flex">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:03]</span>
                            <p class="text-sm text-text-medium-brown">今天我们来学习机器学习的基础概念...</p>
                        </div>
                        <div class="flex">
                            <span class="text-sm font-semibold text-primary mr-3">[00:00:15]</span>
                            <p class="text-sm text-text-medium-brown">机器学习可以分为三大类：监督学习、无监督学习和强化学习。</p>
                        </div>
                    </div>
                </div>
                <button class="w-full bg-primary text-white py-2 rounded-lg hover:bg-green-600 transition">生成学习总结</button>
            </div>
        </div>
        '''

    def create_placeholder_content_html(self, title, description):
        """创建预留内容HTML"""
        return f'''
        <div class="flex items-center justify-center h-full">
            <div class="text-center max-w-md">
                <div class="w-24 h-24 bg-primary rounded-full flex items-center justify-center mx-auto mb-6">
                    <span class="material-icons-outlined text-white text-4xl">construction</span>
                </div>
                <h3 class="text-2xl font-bold text-text-dark-brown mb-4">{title}</h3>
                <p class="text-text-medium-brown mb-6">{description}</p>
                <p class="text-sm text-text-gray">此功能正在开发中，敬请期待！</p>
            </div>
        </div>
        '''

    def create_practice_knowledge_content_html(self):
        """创建基于知识点练习内容HTML"""
        return '''
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">知识点库</h3>
                <div class="space-y-2 max-h-96 overflow-y-auto">
                    <div class="p-3 bg-bg-light-gray rounded-lg cursor-pointer hover:bg-bg-light-green transition">
                        <span class="text-sm font-medium">线性回归</span>
                    </div>
                    <div class="p-3 bg-bg-light-gray rounded-lg cursor-pointer hover:bg-bg-light-green transition">
                        <span class="text-sm font-medium">逻辑回归</span>
                    </div>
                    <div class="p-3 bg-bg-light-gray rounded-lg cursor-pointer hover:bg-bg-light-green transition">
                        <span class="text-sm font-medium">决策树</span>
                    </div>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">练习池</h3>
                <div class="border-2 border-dashed border-gray-300 rounded-lg p-4 h-64 flex items-center justify-center">
                    <p class="text-text-gray">拖拽知识点到这里生成练习题</p>
                </div>
                <button class="mt-4 w-full bg-primary text-white py-2 rounded-lg hover:bg-green-600 transition">生成练习题</button>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">练习统计</h3>
                <div class="space-y-4">
                    <div class="flex justify-between">
                        <span class="text-sm text-text-medium-brown">总练习数</span>
                        <span class="text-sm font-semibold text-text-dark-brown">156</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-text-medium-brown">正确率</span>
                        <span class="text-sm font-semibold text-primary">85%</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-text-medium-brown">本周练习</span>
                        <span class="text-sm font-semibold text-text-dark-brown">12</span>
                    </div>
                </div>
            </div>
        </div>
        '''

    def create_practice_errors_content_html(self):
        """创建基于错题练习内容HTML"""
        return '''
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">错题库</h3>
                <div class="space-y-3 max-h-96 overflow-y-auto">
                    <div class="p-4 border border-red-200 rounded-lg cursor-pointer hover:bg-red-50 transition">
                        <div class="flex items-start justify-between">
                            <div class="flex-1">
                                <p class="text-sm font-medium text-text-dark-brown">线性回归的损失函数是什么？</p>
                                <p class="text-xs text-red-500 mt-1">错误次数: 3</p>
                            </div>
                            <input type="checkbox" class="mt-1">
                        </div>
                    </div>
                    <div class="p-4 border border-red-200 rounded-lg cursor-pointer hover:bg-red-50 transition">
                        <div class="flex items-start justify-between">
                            <div class="flex-1">
                                <p class="text-sm font-medium text-text-dark-brown">决策树的剪枝方法有哪些？</p>
                                <p class="text-xs text-red-500 mt-1">错误次数: 2</p>
                            </div>
                            <input type="checkbox" class="mt-1">
                        </div>
                    </div>
                </div>
                <button class="mt-4 w-full bg-danger text-white py-2 rounded-lg hover:bg-red-600 transition">开始错题练习</button>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">错题分析</h3>
                <div class="space-y-4">
                    <div class="p-4 bg-red-50 rounded-lg">
                        <h4 class="font-semibold text-red-700 mb-2">高频错误知识点</h4>
                        <div class="space-y-2">
                            <div class="flex justify-between">
                                <span class="text-sm">线性回归</span>
                                <span class="text-sm text-red-600">5次</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-sm">决策树</span>
                                <span class="text-sm text-red-600">3次</span>
                            </div>
                        </div>
                    </div>
                    <div class="p-4 bg-yellow-50 rounded-lg">
                        <h4 class="font-semibold text-yellow-700 mb-2">建议复习</h4>
                        <p class="text-sm text-yellow-600">建议重点复习线性回归相关概念，特别是损失函数部分。</p>
                    </div>
                </div>
            </div>
        </div>
        '''

    def create_knowledge_base_content_html(self):
        """创建知识库管理内容HTML"""
        return '''
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">学科列表</h3>
                <div class="space-y-2">
                    <div class="p-3 bg-bg-light-green rounded-lg cursor-pointer">
                        <span class="font-medium text-primary">机器学习基础</span>
                        <p class="text-xs text-text-medium-brown mt-1">15个知识点</p>
                    </div>
                    <div class="p-3 bg-bg-light-gray rounded-lg cursor-pointer">
                        <span class="font-medium">深度学习</span>
                        <p class="text-xs text-text-medium-brown mt-1">8个知识点</p>
                    </div>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">知识点</h3>
                <div class="space-y-2">
                    <div class="p-3 border border-gray-200 rounded-lg">
                        <span class="font-medium">线性回归</span>
                        <p class="text-xs text-text-medium-brown mt-1">5个错题</p>
                    </div>
                    <div class="p-3 border border-gray-200 rounded-lg">
                        <span class="font-medium">逻辑回归</span>
                        <p class="text-xs text-text-medium-brown mt-1">3个错题</p>
                    </div>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-semibold text-text-dark-brown mb-4">错题列表</h3>
                <div class="space-y-2">
                    <div class="p-3 border border-red-200 rounded-lg">
                        <p class="text-sm font-medium">线性回归的损失函数是什么？</p>
                        <p class="text-xs text-red-500 mt-1">错误 3 次</p>
                    </div>
                </div>
            </div>
        </div>
        '''

    def create_settings_content_html(self):
        """创建设置内容HTML"""
        return '''
        <div class="max-w-md mx-auto">
            <div class="bg-white p-8 rounded-xl shadow-sm">
                <div class="text-center mb-6">
                    <div class="w-16 h-16 bg-primary rounded-full flex items-center justify-center mx-auto mb-4">
                        <span class="material-icons-outlined text-white text-2xl">settings</span>
                    </div>
                    <h3 class="text-2xl font-bold text-text-dark-brown">系统设置</h3>
                </div>
                
                <div class="space-y-6">
                    <div>
                        <label class="block text-sm font-medium text-text-dark-brown mb-2">大语言模型选择</label>
                        <select class="w-full p-3 border border-gray-300 rounded-lg focus:ring-primary focus:border-primary">
                            <option value="gemini">Gemini API</option>
                            <option value="ollama">Ollama (本地)</option>
                            <option value="openai">OpenAI GPT</option>
                        </select>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium text-text-dark-brown mb-2">API Key</label>
                        <input type="password" class="w-full p-3 border border-gray-300 rounded-lg focus:ring-primary focus:border-primary" placeholder="请输入API Key">
                    </div>
                    
                    <div class="flex space-x-4 pt-4">
                        <button class="flex-1 bg-primary text-white py-3 rounded-lg hover:bg-green-600 transition">保存设置</button>
                        <button class="flex-1 bg-gray-300 text-gray-700 py-3 rounded-lg hover:bg-gray-400 transition" onclick="loadContent('dashboard')">取消</button>
                    </div>
                </div>
            </div>
        </div>
        '''

    def create_settings_html(self):
        """创建设置页面"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>设置 - 柯基学习小助手</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet">
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <main class="flex-1 flex flex-col items-center justify-center p-8">
            <div class="bg-white p-8 rounded-xl shadow-lg max-w-md w-full">
                <div class="text-center mb-6">
                    <div class="w-16 h-16 bg-primary rounded-full flex items-center justify-center mx-auto mb-4">
                        <span class="material-icons-outlined text-white text-2xl">settings</span>
                    </div>
                    <h2 class="text-2xl font-bold text-text-dark-brown">系统设置</h2>
                </div>
                
                <div class="space-y-6">
                    <div>
                        <label class="block text-sm font-medium text-text-dark-brown mb-2">大语言模型选择</label>
                        <select class="w-full p-3 border border-gray-300 rounded-lg focus:ring-primary focus:border-primary">
                            <option value="gemini">Gemini API</option>
                            <option value="ollama">Ollama (本地)</option>
                            <option value="openai">OpenAI GPT</option>
                        </select>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium text-text-dark-brown mb-2">API Key</label>
                        <input type="password" class="w-full p-3 border border-gray-300 rounded-lg focus:ring-primary focus:border-primary" placeholder="请输入API Key">
                    </div>
                    
                    <div class="flex space-x-4 pt-4">
                        <button class="flex-1 bg-primary text-white py-3 rounded-lg hover:bg-green-600 transition">保存设置</button>
                        <button class="flex-1 bg-gray-300 text-gray-700 py-3 rounded-lg hover:bg-gray-400 transition" onclick="switchToDashboard()">取消</button>
                    </div>
                </div>
            </div>
        </main>
    </div>
    
    <script>
        var bridge = null;
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
        });
        
        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }
    </script>
</body>
</html>'''

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用程序图标和名称
    app.setApplicationName("柯基学习小助手")
    app.setApplicationVersion("2.0.0")
    
    window = OverlayDragCorgiApp()
    window.show()
    
    print("🐕 覆盖层拖拽版柯基学习小助手启动成功！")
    print("🎯 使用透明覆盖层实现拖拽功能")
    print("🖱️ 点击顶部区域拖拽窗口")
    print("📝 支持工作台和笔记本功能切换")
    
    sys.exit(app.exec())
if __name__ == "__main__":
    main()
