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
from template_manager import TemplateManager
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
        # 菜单状态管理
        self.menu_state = {
            "dashboard": {"expanded": False, "children": []},
            "learn": {"expanded": False, "children": ["learn_from_materials", "learn_from_audio"]},
            "practice": {"expanded": False, "children": ["practice_materials", "practice_knowledge", "practice_errors"]},
            "memory": {"expanded": False, "children": ["memory_knowledge", "memory_errors"]},
            "knowledge_base": {"expanded": False, "children": []},
            "settings": {"expanded": False, "children": []}
        }

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
        return json.dumps(self.menu_state, ensure_ascii=False)
    
    @Slot(str)
    def loadContent(self, content_id):
        """加载指定内容"""
        self.current_page = content_id
        if self.main_window:
            content_html = self.main_window.generate_content_html(content_id)
            # 转义HTML内容中的反引号和反斜杠
            escaped_html = content_html.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            # 通过JavaScript更新右侧内容区域
            self.main_window.web_view.page().runJavaScript(f"""
                updateContentArea(`{escaped_html}`);
            """)
            print(f"📄 已加载内容: {content_id}")
            
            # 更新页面标题和活动菜单项
            title_map = {
                "dashboard": "柯基的学习乐园",
                "learn_from_materials": "从资料学习",
                "learn_from_audio": "从音视频学习",
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
    
    @Slot(str, result=bool)
    def createNewNote(self, folder_path="vault"):
        """创建新的Markdown笔记"""
        try:
            vault_path = Path(folder_path)
            vault_path.mkdir(exist_ok=True)
            
            # 生成新文件名
            counter = 1
            while True:
                new_file_name = f"新笔记{counter}.md"
                new_file_path = vault_path / new_file_name
                if not new_file_path.exists():
                    break
                counter += 1
            
            # 创建模板内容
            template_content = f"""# {new_file_name.replace('.md', '')}

## 概述
在这里写下你的学习笔记...

## 要点
- 要点1
- 要点2
- 要点3

## 总结
总结你学到的内容...
"""
            
            with open(new_file_path, 'w', encoding='utf-8') as f:
                f.write(template_content)
            
            print(f"创建新笔记: {new_file_path}")
            return True
        except Exception as e:
            print(f"创建新笔记失败: {e}")
            return False
    
    @Slot(str, result=bool)
    def createNewFolder(self, parent_path="vault"):
        """创建新文件夹"""
        try:
            parent = Path(parent_path)
            parent.mkdir(exist_ok=True)
            
            # 生成新文件夹名
            counter = 1
            while True:
                new_folder_name = f"新文件夹{counter}"
                new_folder_path = parent / new_folder_name
                if not new_folder_path.exists():
                    break
                counter += 1
            
            new_folder_path.mkdir()
            print(f"创建新文件夹: {new_folder_path}")
            return True
        except Exception as e:
            print(f"创建新文件夹失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def renameFileOrFolder(self, old_path, new_name):
        """重命名文件或文件夹"""
        try:
            old_path_obj = Path(old_path)
            new_path_obj = old_path_obj.parent / new_name
            
            if new_path_obj.exists():
                print(f"重命名失败: {new_name} 已存在")
                return False
            
            old_path_obj.rename(new_path_obj)
            print(f"重命名成功: {old_path} -> {new_path_obj}")
            return True
        except Exception as e:
            print(f"重命名失败: {e}")
            return False
    
    @Slot(str, str, result=bool)
    def moveFileOrFolder(self, source_path, target_folder):
        """移动文件或文件夹"""
        try:
            source = Path(source_path)
            target_dir = Path(target_folder)
            target_path = target_dir / source.name
            
            if target_path.exists():
                print(f"移动失败: {target_path} 已存在")
                return False
            
            target_dir.mkdir(parents=True, exist_ok=True)
            source.rename(target_path)
            print(f"移动成功: {source_path} -> {target_path}")
            return True
        except Exception as e:
            print(f"移动失败: {e}")
            return False
    
    @Slot(str, result=str)
    def extractKnowledgePoints(self, file_path):
        """提取文档中的知识点"""
        try:
            # 这里可以调用之前实现的知识点提取功能
            # 暂时返回模拟数据
            knowledge_points = [
                {"id": "1", "title": "线性回归基础", "content": "线性回归是机器学习中的基础算法"},
                {"id": "2", "title": "损失函数", "content": "均方误差是线性回归常用的损失函数"},
                {"id": "3", "title": "梯度下降", "content": "用于优化线性回归模型参数的算法"}
            ]
            return json.dumps(knowledge_points, ensure_ascii=False)
        except Exception as e:
            print(f"提取知识点失败: {e}")
            return json.dumps([], ensure_ascii=False)

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
            print(f"⚠️ 模板渲染失败，使用备用生成器: {content_id} - {e}")
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
        """生成从音视频学习内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <div class="text-center py-16">
                <span class="material-icons-outlined text-6xl text-gray-400 mb-4">headphones</span>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-2">从音视频学习</h3>
                <p class="text-text-gray mb-6">上传音频或视频文件，AI将自动转写并生成学习笔记</p>
                <button class="bg-primary text-white px-6 py-3 rounded-lg hover:bg-green-600">
                    <span class="material-icons-outlined mr-2">upload</span>
                    上传音视频文件
                </button>
            </div>
        </div>
        '''
    
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
        """生成设置内容"""
        return '''
        <div class="bg-white rounded-xl shadow-sm p-6">
            <h3 class="text-xl font-semibold text-text-dark-brown mb-6">设置</h3>
            <div class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-text-dark-brown mb-2">LLM模型选择</label>
                    <select class="w-full p-3 border border-gray-300 rounded-lg">
                        <option>Gemini Pro</option>
                        <option>Ollama</option>
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
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
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
        let bridge = null;
        let isRecording = false;

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

        // 录音功能
        document.addEventListener('DOMContentLoaded', function() {
            const startBtn = document.getElementById('start-recording');
            const pauseBtn = document.getElementById('pause-recording');
            const saveBtn = document.getElementById('save-notes');
            const summaryBtn = document.getElementById('manual-summary');
            const screenshotBtn = document.getElementById('screenshot-notes');
            const volumeBar = document.getElementById('volume-bar');

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
                
                const randomVolume = Math.random() * 100;
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
    print("📝 支持工作台和笔记本功能切换")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
