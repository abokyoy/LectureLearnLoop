#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
柯基学习小助手 - 覆盖层拖拽版本
使用透明覆盖层解决拖拽问题
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
            
    @Slot()
    def switchToNotebook(self):
        """切换到笔记本页面"""
        if self.main_window:
            self.main_window.load_notebook_content()
            print("📝 切换到笔记本页面")
            
    @Slot()
    def switchToDashboard(self):
        """切换到工作台页面"""
        if self.main_window:
            self.main_window.load_dashboard_content()
            print("🏠 切换到工作台页面")
            
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
        
        # 不使用布局，直接处理鼠标事件
        
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
        
    def load_notebook_content(self):
        """加载笔记本页面内容"""
        html_content = self.create_notebook_html()
        self.web_view.setHtml(html_content)
        
    def load_dashboard_content(self):
        """加载工作台页面内容"""
        html_content = self.create_dashboard_html()
        self.web_view.setHtml(html_content)
        
    def create_notebook_html(self):
        """创建笔记本页面的HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
                },
            },
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
        .prose {
            max-width: none;
        }
        .prose h1 {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 0.5em;
            color: #715D46;
        }
        .prose h2 {
            font-size: 1.5em;
            font-weight: bold;
            margin-top: 1em;
            margin-bottom: 0.5em;
            color: #715D46;
        }
        .prose p {
            margin-bottom: 1em;
            line-height: 1.6;
        }
        .prose ul {
            margin-bottom: 1em;
            padding-left: 1.5em;
        }
        .prose li {
            margin-bottom: 0.5em;
        }
        .prose code {
            background-color: #f3f4f6;
            padding: 0.2em 0.4em;
            border-radius: 0.25em;
            font-family: monospace;
        }
        .prose pre {
            background-color: #1f2937;
            color: #f9fafb;
            padding: 1em;
            border-radius: 0.5em;
            overflow-x: auto;
            margin: 1em 0;
        }
        .prose blockquote {
            border-left: 4px solid #32C77F;
            padding-left: 1em;
            margin: 1em 0;
            font-style: italic;
            color: #6b7280;
        }
        #editor-textarea {
            resize: none;
            font-family: 'Courier New', monospace;
        }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <!-- 侧边栏 -->
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
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchPage('recording')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">mic</span>
                    <span class="sidebar-text">录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchPage('ai')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">smart_toy</span>
                    <span class="sidebar-text">AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchPage('knowledge')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">book</span>
                    <span class="sidebar-text">知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchPage('report')">
                    <span class="material-icons-outlined mr-3 nav-item-icon">bar_chart</span>
                    <span class="sidebar-text">学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg nav-link" href="#" onclick="switchPage('settings')">
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

        <!-- 主要内容区域 -->
        <div class="flex-1 flex bg-bg-light-blue-gray" id="main-content">
            <!-- 文件结构面板 -->
            <div class="w-1/4 bg-white border-r border-gray-200 p-4 flex flex-col transition-all duration-300" id="file-structure">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold text-text-dark-brown">文件结构</h2>
                    <div class="space-x-2">
                        <button class="text-text-gray hover:text-primary" onclick="createNewFolder()">
                            <span class="material-icons-outlined">create_new_folder</span>
                        </button>
                        <button class="text-text-gray hover:text-primary" onclick="createNewNote()">
                            <span class="material-icons-outlined">note_add</span>
                        </button>
                    </div>
                </div>
                <div class="flex-1 overflow-y-auto pr-2" id="file-tree">
                    <!-- 文件树将在这里动态生成 -->
                </div>
            </div>

            <!-- 主编辑区域 -->
            <main class="flex-1 p-6 flex flex-col">
                <header class="flex justify-between items-center mb-4">
                    <h2 class="text-2xl font-bold text-text-dark-brown" id="current-file-title">选择一个文件开始编辑</h2>
                    <div class="flex items-center space-x-2" id="editor-controls" style="display: none;">
                        <button class="flex items-center bg-white border border-gray-300 px-3 py-1.5 rounded-lg text-text-gray hover:bg-gray-100" 
                                id="preview-btn" onclick="switchToPreview()">
                            <span class="material-icons-outlined text-sm mr-1">visibility</span>
                            <span>预览</span>
                        </button>
                        <button class="flex items-center bg-primary text-white px-3 py-1.5 rounded-lg hover:bg-green-600" 
                                id="edit-btn" onclick="switchToEdit()">
                            <span class="material-icons-outlined text-sm mr-1">edit</span>
                            <span>编辑</span>
                        </button>
                        <button class="flex items-center bg-blue-500 text-white px-3 py-1.5 rounded-lg hover:bg-blue-600" 
                                id="save-btn" onclick="saveCurrentFile()" style="display: none;">
                            <span class="material-icons-outlined text-sm mr-1">save</span>
                            <span>保存</span>
                        </button>
                    </div>
                </header>
                
                <div class="flex-1 bg-white rounded-xl shadow-sm p-6 overflow-y-auto">
                    <!-- 预览模式 -->
                    <div id="preview-content" class="prose max-w-none">
                        <div class="text-center text-text-gray py-20">
                            <span class="material-icons-outlined text-6xl mb-4 block">description</span>
                            <p class="text-xl">选择一个Markdown文件开始阅读</p>
                        </div>
                    </div>
                    
                    <!-- 编辑模式 -->
                    <div id="edit-content" style="display: none;" class="h-full">
                        <textarea id="editor-textarea" 
                                  class="w-full h-full border-none outline-none resize-none p-0 text-gray-800"
                                  placeholder="在这里编写Markdown内容..."></textarea>
                    </div>
                </div>
            </main>

            <!-- 知识点面板 -->
            <aside class="w-1/5 bg-white border-l border-gray-200 p-4 flex flex-col">
                <h2 class="text-lg font-semibold text-text-dark-brown mb-4">知识点列表</h2>
                <div class="flex-1 overflow-y-auto space-y-3" id="knowledge-points">
                    <div class="text-center text-text-gray py-10">
                        <span class="material-icons-outlined text-4xl mb-2 block">lightbulb</span>
                        <p>选择文件后显示知识点</p>
                    </div>
                </div>
            </aside>
        </div>
    </div>

    <script>
        let bridge = null;
        let currentFilePath = null;
        let isEditMode = false;
        let fileStructure = [];

        // 初始化WebChannel
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;
            console.log('WebChannel连接成功');
            loadFileStructure();
        });

        // 窗口控制函数
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
            }
        }

        // 侧边栏切换
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const fileStructure = document.getElementById('file-structure');
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
            chevron.textContent = isCollapsed ? 'chevron_right' : 'chevron_left';
        }

        // 加载文件结构
        function loadFileStructure() {
            if (bridge && bridge.getFileStructure) {
                bridge.getFileStructure().then(function(structureJson) {
                    fileStructure = JSON.parse(structureJson);
                    renderFileTree(fileStructure);
                });
            }
        }

        // 渲染文件树
        function renderFileTree(structure) {
            const container = document.getElementById('file-tree');
            container.innerHTML = '';
            
            function renderItems(items, container, level = 0) {
                items.forEach(item => {
                    const li = document.createElement('li');
                    const div = document.createElement('div');
                    div.className = 'flex items-center p-2 rounded-md hover:bg-bg-light-gray cursor-pointer';
                    div.style.paddingLeft = (level * 20 + 8) + 'px';
                    
                    if (item.type === 'folder') {
                        div.innerHTML = `
                            <span class="material-icons-outlined text-yellow-500 mr-2">folder</span>
                            <span class="text-text-dark-brown font-medium">${item.name}</span>
                            <span class="material-icons-outlined text-text-gray ml-auto folder-arrow">expand_more</span>
                        `;
                        
                        div.onclick = function() {
                            toggleFolder(this, item);
                        };
                    } else if (item.type === 'file') {
                        div.innerHTML = `
                            <span class="material-icons-outlined text-gray-500 mr-2">description</span>
                            <span class="text-text-medium-brown">${item.name}</span>
                        `;
                        
                        div.onclick = function() {
                            selectFile(item.path, item.name, this);
                        };
                    }
                    
                    li.appendChild(div);
                    
                    if (item.type === 'folder' && item.children && item.children.length > 0) {
                        const ul = document.createElement('ul');
                        ul.className = 'folder-children';
                        ul.style.display = 'none';
                        renderItems(item.children, ul, level + 1);
                        li.appendChild(ul);
                    }
                    
                    container.appendChild(li);
                });
            }
            
            const ul = document.createElement('ul');
            ul.className = 'space-y-1';
            renderItems(structure, ul);
            container.appendChild(ul);
        }

        // 切换文件夹展开/收起
        function toggleFolder(element, item) {
            const arrow = element.querySelector('.folder-arrow');
            const children = element.parentElement.querySelector('.folder-children');
            
            if (children) {
                if (children.style.display === 'none') {
                    children.style.display = 'block';
                    arrow.textContent = 'expand_less';
                } else {
                    children.style.display = 'none';
                    arrow.textContent = 'expand_more';
                }
            }
        }

        // 选择文件
        function selectFile(filePath, fileName, element) {
            // 清除之前的选中状态
            document.querySelectorAll('.file-selected').forEach(el => {
                el.classList.remove('file-selected', 'bg-bg-light-green');
                el.querySelector('span:last-child').classList.remove('text-primary', 'font-semibold');
                el.querySelector('span:last-child').classList.add('text-text-medium-brown');
            });
            
            // 设置当前选中状态
            element.classList.add('file-selected', 'bg-bg-light-green');
            element.querySelector('span:last-child').classList.add('text-primary', 'font-semibold');
            element.querySelector('span:last-child').classList.remove('text-text-medium-brown');
            
            currentFilePath = filePath;
            document.getElementById('current-file-title').textContent = fileName;
            document.getElementById('editor-controls').style.display = 'flex';
            
            loadFileContent(filePath);
        }

        // 加载文件内容
        function loadFileContent(filePath) {
            if (bridge && bridge.loadMarkdownFile) {
                bridge.loadMarkdownFile(filePath).then(function(htmlContent) {
                    document.getElementById('preview-content').innerHTML = htmlContent;
                    switchToPreview();
                });
            }
        }

        // 切换到预览模式
        function switchToPreview() {
            isEditMode = false;
            document.getElementById('preview-content').style.display = 'block';
            document.getElementById('edit-content').style.display = 'none';
            document.getElementById('save-btn').style.display = 'none';
            
            // 更新按钮状态
            document.getElementById('preview-btn').className = 'flex items-center bg-primary text-white px-3 py-1.5 rounded-lg';
            document.getElementById('edit-btn').className = 'flex items-center bg-white border border-gray-300 px-3 py-1.5 rounded-lg text-text-gray hover:bg-gray-100';
        }

        // 切换到编辑模式
        function switchToEdit() {
            if (!currentFilePath) return;
            
            isEditMode = true;
            document.getElementById('preview-content').style.display = 'none';
            document.getElementById('edit-content').style.display = 'block';
            document.getElementById('save-btn').style.display = 'flex';
            
            // 更新按钮状态
            document.getElementById('edit-btn').className = 'flex items-center bg-primary text-white px-3 py-1.5 rounded-lg';
            document.getElementById('preview-btn').className = 'flex items-center bg-white border border-gray-300 px-3 py-1.5 rounded-lg text-text-gray hover:bg-gray-100';
            
            // 加载原始Markdown内容
            if (bridge && bridge.loadMarkdownRaw) {
                bridge.loadMarkdownRaw(currentFilePath).then(function(rawContent) {
                    document.getElementById('editor-textarea').value = rawContent;
                });
            }
        }

        // 保存当前文件
        function saveCurrentFile() {
            if (!currentFilePath || !isEditMode) return;
            
            const content = document.getElementById('editor-textarea').value;
            if (bridge && bridge.saveMarkdownFile) {
                bridge.saveMarkdownFile(currentFilePath, content).then(function(success) {
                    if (success) {
                        // 保存成功后刷新预览
                        bridge.loadMarkdownFile(currentFilePath).then(function(htmlContent) {
                            document.getElementById('preview-content').innerHTML = htmlContent;
                        });
                        
                        // 显示保存成功提示
                        showNotification('文件保存成功！', 'success');
                    } else {
                        showNotification('文件保存失败！', 'error');
                    }
                });
            }
        }

        // 显示通知
        function showNotification(message, type) {
            const notification = document.createElement('div');
            notification.className = `fixed top-4 right-4 px-4 py-2 rounded-lg text-white z-50 ${
                type === 'success' ? 'bg-green-500' : 'bg-red-500'
            }`;
            notification.textContent = message;
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.remove();
            }, 3000);
        }

        // 创建新文件夹
        function createNewFolder() {
            const name = prompt('请输入文件夹名称:');
            if (name) {
                // TODO: 实现创建文件夹功能
                showNotification('创建文件夹功能待实现', 'info');
            }
        }

        // 创建新笔记
        function createNewNote() {
            const name = prompt('请输入笔记名称:');
            if (name) {
                // TODO: 实现创建笔记功能
                showNotification('创建笔记功能待实现', 'info');
            }
        }

        // 页面切换
        function switchToDashboard() {
            if (bridge && bridge.switchToDashboard) {
                bridge.switchToDashboard();
            }
        }
        
        function switchPage(page) {
            // TODO: 实现切换到其他页面
            console.log('切换到页面:', page);
        }
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
        
    def create_dashboard_html(self):
        """创建工作台页面的HTML内容"""
        with open('dashboard_template.html', 'r', encoding='utf-8') as f:
            return f.read()


def main():
                <a class="flex items-center px-4 py-2.5 bg-primary text-white rounded-lg card-shadow">
                    <span class="mr-3 text-lg">🏠</span>
                    <span>工作台</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">📝</span>
                    <span>笔记本</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">🎙️</span>
                    <span>录音室</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">🤖</span>
                    <span>AI伙伴</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">📚</span>
                    <span>知识库</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">📊</span>
                    <span>学习报告</span>
                </a>
                <a class="flex items-center px-4 py-2.5 text-text-gray hover:bg-bg-light-gray rounded-lg">
                    <span class="mr-3 text-lg">⚙️</span>
                    <span>设置</span>
                </a>
            </nav>
        </aside>
        
        <!-- 主内容区 -->
        <main class="flex-1 p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex justify-between items-center mb-8 fade-in">
                <div class="flex items-center">
                    <div class="w-12 h-12 mr-4 bg-bg-light-green rounded-full flex items-center justify-center">
                        <span class="text-2xl text-primary">🐕</span>
                    </div>
                    <h2 class="text-3xl font-bold text-text-dark-brown">柯基的学习乐园</h2>
                </div>
                <div class="flex items-center space-x-4">
                    <div class="text-right">
                        <p class="font-semibold text-text-dark-brown">☀️ 汪汪！欢迎回来！</p>
                        <p class="text-sm text-text-gray" id="currentDate">今天: 2024年9月18日</p>
                    </div>
                    <div class="flex space-x-2">
                        <button class="w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('minimizeWindow')" title="最小化">
                            −
                        </button>
                        <button class="w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('maximizeWindow')" title="最大化/还原">
                            □
                        </button>
                        <button class="w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('closeWindow')" title="关闭">
                            ×
                        </button>
                    </div>
                </div>
            </header>
            
            <!-- 统计卡片 -->
            <div class="grid grid-cols-4 gap-6 mb-8">
                <div class="bg-white p-6 rounded-xl card-shadow hover-scale">
                    <div class="flex items-start">
                        <div class="p-3 rounded-lg bg-bg-light-green mr-4">
                            <span class="text-xl">📚</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">今日笔记</p>
                            <p class="text-3xl font-bold text-primary">3 <span class="text-base font-normal text-text-medium-brown">篇</span></p>
                        </div>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl card-shadow hover-scale">
                    <div class="flex items-start">
                        <div class="p-3 rounded-lg bg-orange-100 mr-4">
                            <span class="text-xl">✅</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">练习完成</p>
                            <p class="text-3xl font-bold text-warning">15 <span class="text-base font-normal text-text-medium-brown">题</span></p>
                        </div>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl card-shadow hover-scale">
                    <div class="flex items-start">
                        <div class="p-3 rounded-lg bg-pink-100 mr-4">
                            <span class="text-xl">💡</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">新增知识点</p>
                            <p class="text-3xl font-bold text-pink-500">8 <span class="text-base font-normal text-text-medium-brown">个</span></p>
                        </div>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl card-shadow hover-scale">
                    <div class="flex items-start">
                        <div class="p-3 rounded-lg bg-red-100 mr-4">
                            <span class="text-xl">⏰</span>
                        </div>
                        <div>
                            <p class="text-sm text-text-gray mb-1">学习时长</p>
                            <p class="text-3xl font-bold text-danger">2h 35m</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 快速操作 -->
            <div class="mb-8">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">快速操作</h3>
                <div class="grid grid-cols-4 gap-6">
                    <button class="bg-primary hover:bg-green-600 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale">
                        <span class="text-2xl mb-2">➕</span>
                        <span>新建笔记</span>
                    </button>
                    <button class="bg-red-400 hover:bg-red-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale">
                        <span class="text-2xl mb-2">🎙️</span>
                        <span>开始录制</span>
                    </button>
                    <button class="bg-orange-400 hover:bg-orange-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale">
                        <span class="text-2xl mb-2">🤖</span>
                        <span>AI练习</span>
                    </button>
                    <button class="bg-gray-400 hover:bg-gray-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale">
                        <span class="text-2xl mb-2">📁</span>
                        <span>知识管理</span>
                    </button>
                </div>
            </div>
            
            <!-- 最近活动 -->
            <div>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">最近活动</h3>
                <div class="bg-white p-6 rounded-xl card-shadow">
                    <div class="space-y-4">
                        <div class="flex justify-between items-center hover:bg-gray-50 p-2 rounded-lg">
                            <div class="flex items-center">
                                <div class="w-8 h-8 rounded-full bg-bg-light-green flex items-center justify-center mr-4">
                                    <span class="text-sm">✅</span>
                                </div>
                                <p class="text-text-medium-brown">完成了《柯基学习法》笔记</p>
                            </div>
                            <span class="text-sm text-text-gray bg-bg-light-gray px-2 py-1 rounded-md">2分钟前</span>
                        </div>
                        <div class="flex justify-between items-center hover:bg-gray-50 p-2 rounded-lg">
                            <div class="flex items-center">
                                <div class="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center mr-4">
                                    <span class="text-sm">✏️</span>
                                </div>
                                <p class="text-text-medium-brown">进行了官僚学习练习</p>
                            </div>
                            <span class="text-sm text-text-gray bg-bg-light-gray px-2 py-1 rounded-md">15分钟前</span>
                        </div>
                        <div class="flex justify-between items-center hover:bg-gray-50 p-2 rounded-lg">
                            <div class="flex items-center">
                                <div class="w-8 h-8 rounded-full bg-yellow-100 flex items-center justify-center mr-4">
                                    <span class="text-sm">➕</span>
                                </div>
                                <p class="text-text-medium-brown">添加了新的知识点</p>
                            </div>
                            <span class="text-sm text-text-gray bg-bg-light-gray px-2 py-1 rounded-md">1小时前</span>
                        </div>
                        <div class="flex justify-between items-center hover:bg-gray-50 p-2 rounded-lg">
                            <div class="flex items-center">
                                <div class="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center mr-4">
                                    <span class="text-sm">🎙️</span>
                                </div>
                                <p class="text-text-medium-brown">录制了学习音频</p>
                            </div>
                            <span class="text-sm text-text-gray bg-bg-light-gray px-2 py-1 rounded-md">2小时前</span>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        let bridge;
        
        // 初始化Web通道
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            console.log('🐕 Python桥梁连接成功！');
        });
        
        // 调用Python函数
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName]();
                console.log(`调用Python方法: ${functionName}`);
            }
        }
    </script>
</body>
</html>'''
        
        html_file = Path("overlay_corgi_dashboard.html")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        file_url = QUrl.fromLocalFile(str(html_file.absolute()))
        self.web_view.load(file_url)

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    app.setApplicationName("柯基学习小助手")
    app.setApplicationVersion("2.2")
    
    window = OverlayDragCorgiApp()
    window.show()
    
    print("🐕 覆盖层拖拽版柯基学习小助手启动成功！")
    print("🎯 使用透明覆盖层实现拖拽功能")
    print("🖱️ 点击顶部区域拖拽窗口")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
