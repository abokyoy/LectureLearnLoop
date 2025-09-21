#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习笔记软件 - 柯基犬主题卡通化风格
轻松活泼的可爱宠物元素界面，浅绿米白配色，圆角设计
"""

import sys
import os
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

class CorgiTitleBar(QWidget):
    """柯基犬主题标题栏 - 卡通化风格"""
    closeClicked = Signal()
    minimizeClicked = Signal()
    
    def __init__(self):
        super().__init__()
        self.setFixedHeight(45)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)
        
        # 柯基犬图标 + 标题
        icon_title_layout = QHBoxLayout()
        icon_title_layout.setSpacing(8)
        
        # 柯基犬头像图标
        corgi_icon = QLabel("🐕")
        corgi_icon.setStyleSheet("""
            QLabel {
                font-size: 20px;
                background-color: #a8e6a3;
                border-radius: 15px;
                padding: 3px;
            }
        """)
        corgi_icon.setFixedSize(30, 30)
        corgi_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 应用标题 - 卡通化风格
        title_label = QLabel("柯基学习小助手")
        title_label.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 16px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", "微软雅黑";
            }
        """)
        
        icon_title_layout.addWidget(corgi_icon)
        icon_title_layout.addWidget(title_label)
        
        layout.addLayout(icon_title_layout)
        layout.addStretch()
        
        # 窗口控制按钮 - 圆角卡通风格
        self.minimize_btn = self.create_cute_button("−", "#828282")
        self.close_btn = self.create_cute_button("×", "#ED4B4B")
        
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.close_btn)
        
        # 连接信号
        self.minimize_btn.clicked.connect(self.minimizeClicked.emit)
        self.close_btn.clicked.connect(self.closeClicked.emit)
        
    def create_cute_button(self, text, color):
        """创建沉稳的圆角按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(32, 32)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                color: #715D46;
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
            }}
            QPushButton:pressed {{
                background-color: {color};
            }}
        """)
        return btn

class CorgiSidebarWidget(QWidget):
    """柯基犬主题侧边栏 - 卡通化风格"""
    menuClicked = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.current_item = "🏠 工作台"
        self.setup_ui()
        
    def setup_ui(self):
        self.setFixedWidth(200)  # 稍微宽一点适应卡通元素
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 侧边栏背景色 - 沉稳的浅色渐变，无边框
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F5F7F9, stop:1 #F2F0ED);
            }
        """)
        
        # 柯基犬头像区域
        corgi_section = self.create_corgi_section()
        layout.addWidget(corgi_section)
        
        # 可爱的分隔线 - 爪印装饰
        separator = QLabel("🐾 🐾 🐾")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator.setStyleSheet("""
            QLabel {
                color: #a8e6a3;
                font-size: 12px;
                padding: 8px;
                background-color: transparent;
            }
        """)
        layout.addWidget(separator)
        
        # 菜单区域
        menu_widget = QWidget()
        menu_layout = QVBoxLayout(menu_widget)
        menu_layout.setContentsMargins(12, 16, 12, 16)
        menu_layout.setSpacing(8)
        
        # 菜单数据 - 柯基犬主题的可爱菜单项
        menu_items = [
            ("🏠 工作台", "🐕"),
            ("📝 笔记本", "📖"),
            ("🎙️ 录音室", "🎵"),
            ("🤖 AI伙伴", "🤖"),
            ("📚 知识库", "💡"),
            ("📊 学习报告", "📈"),
            ("⚙️ 设置", "🔧")
        ]
        
        # 创建菜单项
        for name, decoration in menu_items:
            is_active = (name == self.current_item)
            menu_item = self.create_cute_menu_item(name, decoration, is_active)
            menu_layout.addWidget(menu_item)
        
        menu_layout.addStretch()
        
        # 底部装饰 - 骨头图案
        bottom_decoration = QLabel("🦴 🦴 🦴")
        bottom_decoration.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_decoration.setStyleSheet("""
            QLabel {
                color: #d4b896;
                font-size: 14px;
                padding: 12px;
            }
        """)
        menu_layout.addWidget(bottom_decoration)
        
        layout.addWidget(menu_widget)
        
    def create_corgi_section(self):
        """创建柯基犬主题用户区域"""
        section = QWidget()
        section.setFixedHeight(100)
        
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        
        # 柯基犬头像区域
        avatar_layout = QHBoxLayout()
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        
        # 柯基犬头像 - 沉稳配色设计
        corgi_avatar = QLabel("🐕‍🦺")
        corgi_avatar.setFixedSize(50, 50)
        corgi_avatar.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #E2F2EB, stop:1 #32C77F);
                border-radius: 25px;
                font-size: 24px;
            }
        """)
        corgi_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 用户信息
        user_info = QVBoxLayout()
        user_info.setContentsMargins(0, 0, 0, 0)
        user_info.setSpacing(4)
        
        username = QLabel("小柯基的主人")
        username.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 13px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        level = QLabel("学习等级: Lv.5 🌟")
        level.setStyleSheet("""
            QLabel {
                color: #9B8D7D;
                font-size: 11px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        user_info.addWidget(username)
        user_info.addWidget(level)
        
        avatar_layout.addWidget(corgi_avatar)
        avatar_layout.addLayout(user_info)
        avatar_layout.addStretch()
        
        layout.addLayout(avatar_layout)
        
        return section
        
    def create_cute_menu_item(self, name, decoration, is_active):
        """创建可爱的卡通风格菜单项"""
        item = QPushButton()
        item.setFixedHeight(45)
        item.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 设置按钮样式 - 沉稳配色风格
        if is_active:
            item.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #E2F2EB, stop:1 #32C77F);
                    border: none;
                    border-radius: 18px;
                    text-align: left;
                    padding-left: 15px;
                    color: #715D46;
                    font-size: 13px;
                    font-weight: 700;
                    font-family: "Microsoft YaHei UI";
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #32C77F, stop:1 #E2F2EB);
                }
            """)
        else:
            item.setStyleSheet("""
                QPushButton {
                    background-color: rgba(245, 247, 249, 0.8);
                    border: none;
                    border-radius: 18px;
                    text-align: left;
                    padding-left: 15px;
                    color: #9B8D7D;
                    font-size: 13px;
                    font-weight: 600;
                    font-family: "Microsoft YaHei UI";
                }
                QPushButton:hover {
                    background-color: rgba(242, 240, 237, 0.9);
                }
            """)
        
        # 设置按钮文本，包含装饰元素
        display_text = f"{decoration} {name}"
        item.setText(display_text)
        
        # 连接点击事件
        item.clicked.connect(lambda: self.select_item(name))
        
        return item
        
    def select_item(self, name):
        """选择菜单项"""
        self.current_item = name
        self.menuClicked.emit(name)
        # 更新菜单项样式而不重新创建布局
        self.update_menu_styles()
        
    def update_menu_styles(self):
        """更新菜单项样式"""
        # 这里可以添加样式更新逻辑，暂时保持简单
        pass

class CorgiContentWidget(QWidget):
    """柯基犬主题的卡通化主内容区域"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        # 内容区背景色 - 沉稳的浅色渐变
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F5F7F9, stop:1 #D5F8FF);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 内容堆栈
        self.content_stack = QStackedWidget()
        
        # 添加工作台页面
        self.add_dashboard_page()
        
        # 添加其他页面占位符
        self.add_placeholder_pages()
        
        layout.addWidget(self.content_stack)
        
    def add_dashboard_page(self):
        """添加柯基犬主题工作台页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(24)
        
        # 页面标题区域 - 可爱的柯基犬主题
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # 标题区域
        title_layout = QHBoxLayout()
        title_layout.setSpacing(12)
        
        # 柯基犬图标
        corgi_icon = QLabel("🐕‍🦺")
        corgi_icon.setStyleSheet("""
            QLabel {
                font-size: 28px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffeb9c, stop:1 #ffd93d);
                border-radius: 20px;
                padding: 8px;
                border: 3px solid #a8e6a3;
            }
        """)
        corgi_icon.setFixedSize(40, 40)
        corgi_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("柯基的学习乐园")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 26px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(corgi_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # 欢迎信息 - 可爱风格
        welcome_layout = QVBoxLayout()
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.setSpacing(4)
        
        welcome_text = QLabel("🌟 汪汪！欢迎回来！")
        welcome_text.setStyleSheet("""
            QLabel {
                color: #5d8233;
                font-size: 16px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        date_text = QLabel("📅 今天是 2024年9月17日")
        date_text.setStyleSheet("""
            QLabel {
                color: #8fbc8f;
                font-size: 13px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        welcome_layout.addWidget(welcome_text)
        welcome_layout.addWidget(date_text)
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addLayout(welcome_layout)
        
        layout.addLayout(header_layout)
        
        # 统计卡片区域 - 沉稳配色
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(16)
        
        # 创建统计卡片 - 使用沉稳配色方案
        cards_data = [
            ("今日笔记", "3", "篇", "#32C77F", "#E2F2EB", "📝"),
            ("练习完成", "15", "题", "#FF9B27", "#FFF0D6", "🎯"),
            ("新增知识点", "8", "个", "#828282", "#F5F7F9", "🧠"),
            ("学习时长", "2h 35m", "", "#ED4B4B", "#FFE6E6", "⏱️")
        ]
        
        for title_text, value, unit, color, bg_color, icon in cards_data:
            card = self.create_cute_card(title_text, value, unit, color, bg_color, icon)
            stats_layout.addWidget(card)
        
        layout.addLayout(stats_layout)
        
        # 快速操作区域
        quick_actions = self.create_quick_actions_widget()
        layout.addWidget(quick_actions)
        
        # 最近活动区域
        recent_activity = self.create_recent_activity_widget()
        layout.addWidget(recent_activity)
        
        layout.addStretch()
        self.content_stack.addWidget(page)
        
    def create_cute_card(self, title, value, unit, color, bg_color, icon):
        """创建柯基犬主题的可爱统计卡片 - 无边框设计"""
        card = QFrame()
        card.setFixedHeight(120)
        card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_color}, stop:1 #ffffff);
                border: none;
                border-radius: 20px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        
        # 顶部图标和标题
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 可爱图标 - 无边框设计
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,0.8), stop:1 {color});
                border-radius: 15px;
                padding: 5px;
            }}
        """)
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: #715D46;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        
        top_layout.addWidget(icon_label)
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        
        # 数值区域 - 大号可爱数字
        value_layout = QHBoxLayout()
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6)
        
        # 数值显示
        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 24px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        
        # 单位显示
        unit_label = QLabel(unit)
        unit_label.setStyleSheet(f"""
            QLabel {{
                color: #9B8D7D;
                font-size: 14px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        
        value_layout.addWidget(value_label)
        value_layout.addWidget(unit_label)
        value_layout.addStretch()
        
        layout.addLayout(top_layout)
        layout.addLayout(value_layout)
        layout.addStretch()
        
        return card
        
    def create_quick_actions_widget(self):
        """创建柯基犬主题快速操作区域 - 沉稳配色设计"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F2F0ED, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        
        # 标题 - 柯基犬主题
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("🚀")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 18px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #E2F2EB);
                border-radius: 12px;
                padding: 4px;
            }
        """)
        title_icon.setFixedSize(24, 24)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("快速操作")
        title.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 16px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 操作按钮 - 可爱风格
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(16)
        
        actions = [
            ("新建笔记", "📝", "#32C77F"),
            ("开始录制", "🎙️", "#ED4B4B"),
            ("AI练习", "🤖", "#FF9B27"),
            ("知识管理", "📚", "#828282")
        ]
        
        for name, icon, color in actions:
            action_btn = self.create_cute_action_button(name, icon, color)
            actions_layout.addWidget(action_btn)
        
        layout.addLayout(actions_layout)
        
        return widget
        
    def create_cute_action_button(self, name, icon, color):
        """创建可爱的操作按钮"""
        btn = QPushButton()
        btn.setFixedHeight(70)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                border: none;
                border-radius: 16px;
                text-align: center;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
            }}
        """)
        
        # 按钮内容
        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(8, 8, 8, 8)
        btn_layout.setSpacing(4)
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
            }
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        text_label = QLabel(name)
        text_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 11px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_layout.addWidget(icon_label)
        btn_layout.addWidget(text_label)
        
        return btn
        
    def create_action_button(self, name, icon, color):
        """创建操作按钮"""
        btn = QPushButton()
        btn.setFixedHeight(60)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: #f9fafb;
                border-color: {color};
            }}
        """)
        
        # 按钮内容
        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(8, 8, 8, 8)
        btn_layout.setSpacing(4)
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("""
            QLabel {
                font-size: 20px;
            }
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        text_label = QLabel(name)
        text_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 11px;
                font-weight: 500;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_layout.addWidget(icon_label)
        btn_layout.addWidget(text_label)
        
        return btn
        
    def create_recent_activity_widget(self):
        """创建柯基犬主题最近活动区域 - 无边框设计"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        
        # 标题 - 柯基犬主题
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("📋")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 18px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #e8f5e8);
                border-radius: 12px;
                padding: 4px;
            }
        """)
        title_icon.setFixedSize(24, 24)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("最近活动")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 16px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 活动列表 - 可爱风格
        activities = [
            ("🐕 完成了《柯基学习法》笔记", "2分钟前", "#a8e6a3"),
            ("🎵 进行了音频学习练习", "15分钟前", "#ffb3ba"),
            ("💡 添加了新的知识点", "1小时前", "#ffd93d"),
            ("🎙️ 录制了学习音频", "2小时前", "#b19cd9")
        ]
        
        for activity, time, color in activities:
            activity_item = self.create_cute_activity_item(activity, time, color)
            layout.addWidget(activity_item)
        
        return widget
        
    def create_cute_activity_item(self, activity, time, color):
        """创建可爱的活动项目"""
        item = QWidget()
        item.setFixedHeight(45)
        
        # 设置项目背景
        item.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(255, 255, 255, 0.6);
                border-radius: 15px;
                margin: 2px;
            }}
        """)
        
        layout = QHBoxLayout(item)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # 活动描述 - 包含可爱图标
        activity_label = QLabel(activity)
        activity_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 13px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        
        # 时间标签 - 可爱风格
        time_label = QLabel(f"⏰ {time}")
        time_label.setStyleSheet("""
            QLabel {
                color: #8fbc8f;
                font-size: 11px;
                font-weight: 500;
                font-family: "Microsoft YaHei UI";
                background-color: rgba(168, 230, 163, 0.3);
                border-radius: 8px;
                padding: 2px 6px;
            }
        """)
        
        layout.addWidget(activity_label)
        layout.addStretch()
        layout.addWidget(time_label)
        
        return item
        
    def add_placeholder_pages(self):
        """添加其他功能页面"""
        # 添加笔记本页面
        notebook_page = self.create_notebook_page()
        self.content_stack.addWidget(notebook_page)
        
        # 添加录音室页面
        recording_page = self.create_recording_page()
        self.content_stack.addWidget(recording_page)
        
        # 添加其他占位符页面
        page_names = ["AI伙伴", "知识库", "学习报告", "设置"]
        
        for i, name in enumerate(page_names):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(40, 40, 40, 40)
            
            # 可爱的占位符
            placeholder_layout = QVBoxLayout()
            placeholder_layout.setSpacing(20)
            
            # 柯基犬图标
            corgi_placeholder = QLabel("🐕‍🦺")
            corgi_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            corgi_placeholder.setStyleSheet("""
                QLabel {
                    font-size: 80px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #ffeb9c, stop:1 #ffd93d);
                    border-radius: 50px;
                    padding: 20px;
                    border: 5px solid #a8e6a3;
                }
            """)
            
            # 提示文字
            placeholder_text = QLabel(f"🚧 {name}功能开发中...")
            placeholder_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder_text.setStyleSheet("""
                QLabel {
                    color: #2d5016;
                    font-size: 20px;
                    font-weight: 700;
                    font-family: "Microsoft YaHei UI";
                }
            """)
            
            # 副标题
            subtitle = QLabel("🐾 敬请期待柯基的新功能！")
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle.setStyleSheet("""
                QLabel {
                    color: #8fbc8f;
                    font-size: 14px;
                    font-family: "Microsoft YaHei UI";
                }
            """)
            
            placeholder_layout.addWidget(corgi_placeholder)
            placeholder_layout.addWidget(placeholder_text)
            placeholder_layout.addWidget(subtitle)
            
            layout.addStretch()
            layout.addLayout(placeholder_layout)
            layout.addStretch()
            
            self.content_stack.addWidget(page)
            
    def create_notebook_page(self):
        """创建柯基犬主题笔记本页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(20)
        
        # 页面标题区域
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # 标题区域
        title_layout = QHBoxLayout()
        title_layout.setSpacing(12)
        
        # 笔记本图标
        notebook_icon = QLabel("📝")
        notebook_icon.setStyleSheet("""
            QLabel {
                font-size: 28px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fff4e6, stop:1 #ffeb9c);
                border-radius: 20px;
                padding: 8px;
            }
        """)
        notebook_icon.setFixedSize(40, 40)
        notebook_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("📚 柯基的笔记本")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 26px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(notebook_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # 操作按钮区域
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(12)
        
        # 新建笔记按钮
        new_note_btn = self.create_notebook_button("📄 新建笔记", "#a8e6a3")
        search_btn = self.create_notebook_button("🔍 搜索笔记", "#ffb3ba")
        export_btn = self.create_notebook_button("📤 导出笔记", "#b19cd9")
        
        actions_layout.addWidget(new_note_btn)
        actions_layout.addWidget(search_btn)
        actions_layout.addWidget(export_btn)
        actions_layout.addStretch()
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addLayout(actions_layout)
        
        layout.addLayout(header_layout)
        
        # 分类筛选区域
        filter_widget = self.create_filter_widget()
        layout.addWidget(filter_widget)
        
        # 笔记列表区域
        notes_list = self.create_notes_list()
        layout.addWidget(notes_list)
        
        layout.addStretch()
        return page
        
    def create_notebook_button(self, text, color):
        """创建笔记本操作按钮"""
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                border: none;
                border-radius: 18px;
                color: #2d5016;
                font-size: 13px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
            }}
        """)
        return btn
        
    def create_filter_widget(self):
        """创建分类筛选区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(12)
        
        # 筛选标签
        filter_label = QLabel("🏷️ 分类筛选:")
        filter_label.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 14px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        # 分类按钮
        categories = ["全部", "机器学习", "深度学习", "数据结构", "算法", "Python"]
        
        layout.addWidget(filter_label)
        
        for i, category in enumerate(categories):
            is_active = (i == 0)  # 第一个为激活状态
            category_btn = self.create_category_button(category, is_active)
            layout.addWidget(category_btn)
            
        layout.addStretch()
        
        return widget
        
    def create_category_button(self, text, is_active):
        """创建分类按钮"""
        btn = QPushButton(text)
        btn.setFixedHeight(32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if is_active:
            btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #e8f5e8, stop:1 #d4edda);
                    border: none;
                    border-radius: 16px;
                    color: #2d5016;
                    font-size: 12px;
                    font-weight: 700;
                    font-family: "Microsoft YaHei UI";
                    padding: 6px 12px;
                }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.6);
                    border: none;
                    border-radius: 16px;
                    color: #495057;
                    font-size: 12px;
                    font-weight: 600;
                    font-family: "Microsoft YaHei UI";
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: rgba(248, 249, 250, 0.9);
                }
            """)
        return btn
        
    def create_notes_list(self):
        """创建笔记列表"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        
        # 列表标题
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("📂")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 18px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #e8f5e8);
                border-radius: 12px;
                padding: 4px;
            }
        """)
        title_icon.setFixedSize(24, 24)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("我的笔记")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 16px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 示例笔记项
        notes_data = [
            {
                "title": "🐕 机器学习基础概念",
                "content": "监督学习、无监督学习、强化学习的核心概念...",
                "date": "2024-09-17 14:30",
                "category": "机器学习",
                "knowledge_points": 2,
                "errors": 3,
                "starred": True
            },
            {
                "title": "🧠 神经网络原理详解", 
                "content": "前向传播、反向传播算法的数学原理...",
                "date": "2024-09-16 16:45",
                "category": "深度学习",
                "knowledge_points": 5,
                "errors": 7,
                "starred": False
            },
            {
                "title": "🔧 数据预处理技巧总结",
                "content": "数据清洗、特征工程、标准化处理方法...",
                "date": "2024-09-15 10:20", 
                "category": "数据科学",
                "knowledge_points": 3,
                "errors": 1,
                "starred": False
            }
        ]
        
        for note_data in notes_data:
            note_item = self.create_note_item(note_data)
            layout.addWidget(note_item)
            
        return widget
        
    def create_note_item(self, note_data):
        """创建笔记项"""
        item = QFrame()
        item.setFixedHeight(120)
        item.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.8);
                border: none;
                border-radius: 12px;
                margin: 2px;
            }
        """)
        
        layout = QVBoxLayout(item)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # 标题行
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel(note_data["title"])
        title_label.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 15px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        date_label = QLabel(f"📅 {note_data['date']}")
        date_label.setStyleSheet("""
            QLabel {
                color: #8fbc8f;
                font-size: 11px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(date_label)
        
        # 内容预览
        content_label = QLabel(note_data["content"])
        content_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 12px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        content_label.setWordWrap(True)
        
        # 标签和统计信息
        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(12)
        
        category_label = QLabel(f"🏷️ {note_data['category']}")
        category_label.setStyleSheet("""
            QLabel {
                color: #a8e6a3;
                font-size: 11px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        stats_label = QLabel(f"📊 {note_data['knowledge_points']}个知识点  ❌ {note_data['errors']}个错题")
        stats_label.setStyleSheet("""
            QLabel {
                color: #8fbc8f;
                font-size: 11px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        # 操作按钮
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        
        view_btn = QPushButton("📖 查看")
        edit_btn = QPushButton("✏️ 编辑")
        
        for btn in [view_btn, edit_btn]:
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #ffffff, stop:1 #e8f5e8);
                    border: none;
                    border-radius: 14px;
                    color: #2d5016;
                    font-size: 10px;
                    font-weight: 600;
                    font-family: "Microsoft YaHei UI";
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #e8f5e8, stop:1 #ffffff);
                }
            """)
            
        actions_layout.addWidget(view_btn)
        actions_layout.addWidget(edit_btn)
        actions_layout.addStretch()
        
        info_layout.addWidget(category_label)
        info_layout.addWidget(stats_label)
        info_layout.addStretch()
        info_layout.addLayout(actions_layout)
        
        layout.addLayout(title_layout)
        layout.addWidget(content_label)
        layout.addLayout(info_layout)
        
        return item
        
    def create_recording_page(self):
        """创建柯基犬主题录音室页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(20)
        
        # 页面标题区域
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # 标题区域
        title_layout = QHBoxLayout()
        title_layout.setSpacing(12)
        
        # 录音室图标
        recording_icon = QLabel("🎙️")
        recording_icon.setStyleSheet("""
            QLabel {
                font-size: 28px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fff0f0, stop:1 #ffb3ba);
                border-radius: 20px;
                padding: 8px;
            }
        """)
        recording_icon.setFixedSize(40, 40)
        recording_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("🎵 柯基的录音室")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 26px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(recording_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # 设置按钮区域
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(12)
        
        settings_btn = self.create_recording_button("⚙️ 录制设置", "#b19cd9")
        history_btn = self.create_recording_button("📁 录制历史", "#ffd93d")
        
        settings_layout.addWidget(settings_btn)
        settings_layout.addWidget(history_btn)
        settings_layout.addStretch()
        
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addLayout(settings_layout)
        
        layout.addLayout(header_layout)
        
        # 录制控制区域
        control_widget = self.create_recording_control()
        layout.addWidget(control_widget)
        
        # 实时转写区域
        transcription_widget = self.create_transcription_area()
        layout.addWidget(transcription_widget)
        
        # 笔记总结区域
        summary_widget = self.create_summary_area()
        layout.addWidget(summary_widget)
        
        layout.addStretch()
        return page
        
    def create_recording_button(self, text, color):
        """创建录音室操作按钮"""
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                border: none;
                border-radius: 18px;
                color: #2d5016;
                font-size: 13px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
            }}
        """)
        return btn
        
    def create_recording_control(self):
        """创建录制控制区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        
        # 标题
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("🎤")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #ffb3ba);
                border-radius: 15px;
                padding: 6px;
            }
        """)
        title_icon.setFixedSize(30, 30)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("录制控制")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 18px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 控制按钮区域
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(16)
        
        # 录制按钮
        record_btn = self.create_control_button("🔴 开始录制", "#ff6b6b", 120)
        stop_btn = self.create_control_button("⏹️ 停止录制", "#6c757d", 120)
        pause_btn = self.create_control_button("⏸️ 暂停", "#ffd93d", 100)
        
        controls_layout.addWidget(record_btn)
        controls_layout.addWidget(stop_btn)
        controls_layout.addWidget(pause_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
        # 状态信息区域
        status_layout = QHBoxLayout()
        status_layout.setSpacing(24)
        
        # 音量显示
        volume_layout = QVBoxLayout()
        volume_layout.setSpacing(4)
        
        volume_label = QLabel("📊 音量")
        volume_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        volume_bar = self.create_volume_bar()
        
        volume_layout.addWidget(volume_label)
        volume_layout.addWidget(volume_bar)
        
        # 录制时长
        time_layout = QVBoxLayout()
        time_layout.setSpacing(4)
        
        time_label = QLabel("⏱️ 录制时长")
        time_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        time_display = QLabel("00:05:23")
        time_display.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 16px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #e8f5e8);
                border-radius: 8px;
                padding: 4px 8px;
            }
        """)
        
        time_layout.addWidget(time_label)
        time_layout.addWidget(time_display)
        
        # 设备信息
        device_layout = QVBoxLayout()
        device_layout.setSpacing(4)
        
        device_label = QLabel("🎧 录制设备")
        device_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        device_name = QLabel("默认麦克风")
        device_name.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 13px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        device_layout.addWidget(device_label)
        device_layout.addWidget(device_name)
        
        # 保存位置
        save_layout = QVBoxLayout()
        save_layout.setSpacing(4)
        
        save_label = QLabel("📁 保存位置")
        save_label.setStyleSheet("""
            QLabel {
                color: #495057;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        save_path = QLabel("柯基学习笔记.md")
        save_path.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 13px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        save_layout.addWidget(save_label)
        save_layout.addWidget(save_path)
        
        status_layout.addLayout(volume_layout)
        status_layout.addLayout(time_layout)
        status_layout.addLayout(device_layout)
        status_layout.addLayout(save_layout)
        status_layout.addStretch()
        
        layout.addLayout(status_layout)
        
        return widget
        
    def create_control_button(self, text, color, width):
        """创建控制按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(width, 50)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                border: none;
                border-radius: 25px;
                color: white;
                font-size: 14px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
                color: #2d5016;
            }}
        """)
        return btn
        
    def create_volume_bar(self):
        """创建音量条"""
        volume_widget = QWidget()
        volume_widget.setFixedHeight(20)
        
        layout = QHBoxLayout(volume_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 创建音量条
        for i in range(10):
            bar = QLabel()
            bar.setFixedSize(12, 16)
            if i < 8:  # 80% 音量
                bar.setStyleSheet("""
                    QLabel {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                            stop:0 #a8e6a3, stop:1 #7dd87a);
                        border-radius: 2px;
                    }
                """)
            else:
                bar.setStyleSheet("""
                    QLabel {
                        background-color: rgba(200, 200, 200, 0.5);
                        border-radius: 2px;
                    }
                """)
            layout.addWidget(bar)
            
        # 音量百分比
        volume_percent = QLabel("80%")
        volume_percent.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        layout.addWidget(volume_percent)
        
        return volume_widget
        
    def create_transcription_area(self):
        """创建实时转写区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        
        # 标题
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("📝")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #e8f5e8);
                border-radius: 15px;
                padding: 6px;
            }
        """)
        title_icon.setFixedSize(30, 30)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("实时转写区域")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 18px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 转写内容区域
        transcription_text = QTextEdit()
        transcription_text.setFixedHeight(150)
        transcription_text.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.8);
                border: none;
                border-radius: 12px;
                color: #2d5016;
                font-size: 14px;
                font-family: "Microsoft YaHei UI";
                padding: 12px;
                line-height: 1.5;
            }
        """)
        
        # 示例转写内容
        sample_text = """🐕 今天我们来学习机器学习的基础概念。机器学习是人工智能的一个重要分支，它让计算机能够从数据中学习规律，而不需要明确的编程指令。

主要分为三大类：监督学习、无监督学习和强化学习。监督学习使用标记的训练数据来学习输入和输出之间的映射关系..."""
        
        transcription_text.setPlainText(sample_text)
        
        layout.addWidget(transcription_text)
        
        return widget
        
    def create_summary_area(self):
        """创建笔记总结区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f8fdf8, stop:1 #ffffff);
                border: none;
                border-radius: 16px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        
        # 标题和操作按钮
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)
        
        title_icon = QLabel("📋")
        title_icon.setStyleSheet("""
            QLabel {
                font-size: 20px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 #e8f5e8);
                border-radius: 15px;
                padding: 6px;
            }
        """)
        title_icon.setFixedSize(30, 30)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("笔记总结区域")
        title.setStyleSheet("""
            QLabel {
                color: #2d5016;
                font-size: 18px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        # 操作按钮
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(12)
        
        ai_summary_btn = self.create_summary_button("🤖 AI总结", "#a8e6a3")
        save_btn = self.create_summary_button("💾 保存", "#ffb3ba")
        
        actions_layout.addWidget(ai_summary_btn)
        actions_layout.addWidget(save_btn)
        actions_layout.addStretch()
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title)
        title_layout.addStretch()
        title_layout.addLayout(actions_layout)
        
        layout.addLayout(title_layout)
        
        # 总结内容区域
        summary_text = QTextEdit()
        summary_text.setFixedHeight(200)
        summary_text.setStyleSheet("""
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.8);
                border: none;
                border-radius: 12px;
                color: #2d5016;
                font-size: 14px;
                font-family: "Microsoft YaHei UI";
                padding: 12px;
                line-height: 1.5;
            }
        """)
        
        # 示例总结内容
        sample_summary = """# 🐕 机器学习基础概念

## 核心分类
- **监督学习**: 使用标记数据训练模型
- **无监督学习**: 从无标记数据中发现模式  
- **强化学习**: 通过奖励机制学习最优策略

## 关键要点
1. 数据质量决定模型效果
2. 特征工程是成功的关键
3. 模型选择需要根据具体问题

## 🎯 学习重点
- 理解不同学习方式的适用场景
- 掌握基本的算法原理
- 实践中注重数据预处理"""
        
        summary_text.setPlainText(sample_summary)
        
        layout.addWidget(summary_text)
        
        return widget
        
    def create_summary_button(self, text, color):
        """创建总结区域按钮"""
        btn = QPushButton(text)
        btn.setFixedHeight(35)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffffff, stop:1 {color});
                border: none;
                border-radius: 16px;
                color: #2d5016;
                font-size: 12px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, stop:1 #ffffff);
            }}
        """)
        return btn
        
    def show_page(self, menu_name):
        """显示指定页面"""
        page_map = {
            "🏠 工作台": 0,
            "📝 笔记本": 1,
            "🎙️ 录音室": 2,
            "🤖 AI伙伴": 3,
            "📚 知识库": 4,
            "📊 学习报告": 5,
            "⚙️ 设置": 6
        }
        
        page_index = page_map.get(menu_name, 0)
        self.content_stack.setCurrentIndex(page_index)

class CorgiCuteApp(QWidget):
    """柯基犬主题的卡通化学习笔记软件"""
    
    def __init__(self):
        super().__init__()
        self.setup_window()
        self.setup_ui()
        
    def setup_window(self):
        """设置窗口属性 - 柯基犬卡通风格"""
        self.setWindowTitle("柯基学习小助手")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        
        # 去除系统默认窗口边框
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 设置窗口背景 - 沉稳的无边框风格
        self.setStyleSheet("""
            CorgiCuteApp {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F5F7F9, stop:1 #F2F0ED);
                border: none;
                border-radius: 20px;
            }
        """)
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
        # 启用拖拽移动窗口
        self.drag_position = None
        
    def setup_ui(self):
        """设置用户界面 - 柯基犬卡通风格布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 柯基犬主题标题栏
        self.title_bar = CorgiTitleBar()
        self.title_bar.closeClicked.connect(self.close)
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        layout.addWidget(self.title_bar)
        
        # 主内容区域
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 柯基犬主题侧边栏
        self.sidebar = CorgiSidebarWidget()
        self.sidebar.menuClicked.connect(self.on_menu_clicked)
        
        # 柯基犬主题内容区域
        self.content_widget = CorgiContentWidget()
        
        # 添加到布局
        content_layout.addWidget(self.sidebar)
        content_layout.addWidget(self.content_widget)
        
        layout.addWidget(content_widget)
        
        # 应用全局字体 - 可爱风格
        font = QFont("Microsoft YaHei UI", 9)
        self.setFont(font)
        
    def on_menu_clicked(self, menu_name):
        """处理菜单点击事件"""
        print(f"菜单点击: {menu_name}")
        self.content_widget.show_page(menu_name)
        
    def mousePressEvent(self, event):
        """鼠标按下事件 - 用于拖拽窗口"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 拖拽窗口"""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用属性 - 柯基犬主题
    app.setApplicationName("柯基学习小助手")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("柯基工作室")
    
    # 设置应用图标（如果有的话）
    # app.setWindowIcon(QIcon("corgi_icon.png"))
    
    # 创建柯基犬主题主窗口
    window = CorgiCuteApp()
    window.show()
    
    print("🐕 柯基学习小助手启动成功！")
    print("🌟 轻松活泼的卡通化风格界面")
    print("🎨 浅绿米白配色，圆角设计")
    print("🐾 可爱的柯基犬元素装饰")
    
    # 运行应用
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
