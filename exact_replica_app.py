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
        self.minimize_btn = self.create_cute_button("−", "#a8e6a3")
        self.close_btn = self.create_cute_button("×", "#ffb3ba")
        
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.close_btn)
        
        # 连接信号
        self.minimize_btn.clicked.connect(self.minimizeClicked.emit)
        self.close_btn.clicked.connect(self.closeClicked.emit)
        
    def create_cute_button(self, text, color):
        """创建可爱的圆角按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(32, 32)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.2);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 0, 0, 0.1);
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
        
        # 侧边栏背景色 - 柔和的浅绿色
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f0f8f0, stop:1 #e8f5e8);
                border-right: 2px solid #a8e6a3;
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
        
        # 可爱的柯基犬头像
        corgi_avatar = QLabel("🐕‍🦺")
        corgi_avatar.setFixedSize(50, 50)
        corgi_avatar.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ffeb9c, stop:1 #ffd93d);
                border-radius: 25px;
                font-size: 24px;
                border: 3px solid #a8e6a3;
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
                color: #2d5016;
                font-size: 14px;
                font-weight: 700;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        status = QLabel("🌟 快乐学习中")
        status.setStyleSheet("""
            QLabel {
                color: #5d8233;
                font-size: 11px;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        # 学习等级
        level = QLabel("Lv.5 📚")
        level.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                font-size: 10px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI";
            }
        """)
        
        user_info.addWidget(username)
        user_info.addWidget(status)
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
        
        # 设置按钮样式 - 圆角卡通风格
        if is_active:
            item.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #a8e6a3, stop:1 #7dd87a);
                    border: 2px solid #5cb85c;
                    border-radius: 20px;
                    text-align: left;
                    padding-left: 15px;
                    color: white;
                    font-size: 13px;
                    font-weight: 700;
                    font-family: "Microsoft YaHei UI";
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #7dd87a, stop:1 #5cb85c);
                }
            """)
        else:
            item.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.7);
                    border: 2px solid transparent;
                    border-radius: 20px;
                    text-align: left;
                    padding-left: 15px;
                    color: #2d5016;
                    font-size: 13px;
                    font-weight: 600;
                    font-family: "Microsoft YaHei UI";
                }
                QPushButton:hover {
                    background-color: rgba(168, 230, 163, 0.3);
                    border: 2px solid #a8e6a3;
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
        # 刷新样式
        self.setup_ui()

class CorgiContentWidget(QWidget):
    """柯基犬主题的卡通化主内容区域"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        # 内容区背景色 - 柔和的米白色渐变
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fefefe, stop:1 #f8f8f0);
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
        
        # 统计卡片区域 - 柯基犬主题可爱卡片
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)
        
        stats_data = [
            ("🐾 今日学习", "5", "次", "#a8e6a3", "#f0f8f0", "🐕"),
            ("⏰ 学习时长", "3.2", "小时", "#ffb3ba", "#fff0f0", "⏱️"),
            ("🎯 完成任务", "12", "个", "#ffd93d", "#fffacd", "🏆"),
            ("💡 新知识", "8", "个", "#b19cd9", "#f3f0ff", "🧠")
        ]
        
        for title_text, value, unit, color, bg_color, icon in stats_data:
            card = self.create_cute_card(title_text, value, unit, color, bg_color, icon)
            cards_layout.addWidget(card)
        
        layout.addLayout(cards_layout)
        
        # 快速操作区域
        quick_actions = self.create_quick_actions_widget()
        layout.addWidget(quick_actions)
        
        # 最近活动区域
        recent_activity = self.create_recent_activity_widget()
        layout.addWidget(recent_activity)
        
        layout.addStretch()
        self.content_stack.addWidget(page)
        
    def create_cute_card(self, title, value, unit, color, bg_color, icon):
        """创建柯基犬主题的可爱统计卡片"""
        card = QFrame()
        card.setFixedHeight(120)
        card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg_color}, stop:1 white);
                border: 3px solid {color};
                border-radius: 25px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        
        # 顶部图标和标题
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 可爱图标
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-size: 20px;
                background-color: {color};
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
                color: {color};
                font-size: 13px;
                font-weight: 700;
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
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 28px;
                font-weight: 800;
                font-family: "Microsoft YaHei UI";
            }}
        """)
        
        unit_label = QLabel(unit)
        unit_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
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
        """创建柯基犬主题快速操作区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f0f8f0, stop:1 #ffffff);
                border: 3px solid #a8e6a3;
                border-radius: 20px;
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
                background-color: #a8e6a3;
                border-radius: 12px;
                padding: 4px;
            }
        """)
        title_icon.setFixedSize(24, 24)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("快速操作")
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
        
        # 操作按钮 - 可爱风格
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(16)
        
        actions = [
            ("新建笔记", "📝", "#a8e6a3"),
            ("开始录制", "🎙️", "#ffb3ba"),
            ("AI练习", "🤖", "#ffd93d"),
            ("知识管理", "📚", "#b19cd9")
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
                    stop:0 {color}, stop:1 white);
                border: 2px solid {color};
                border-radius: 18px;
                text-align: center;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 white, stop:1 {color});
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
        """创建柯基犬主题最近活动区域"""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f0f8f0, stop:1 #ffffff);
                border: 3px solid #a8e6a3;
                border-radius: 20px;
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
                background-color: #a8e6a3;
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
        """添加其他功能页面的占位符 - 柯基犬主题"""
        page_names = ["笔记本", "录音室", "AI伙伴", "知识库", "学习报告", "设置"]
        
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
        
        # 设置窗口背景和边框 - 柔和的圆角风格
        self.setStyleSheet("""
            CorgiCuteApp {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fefefe, stop:1 #f8f8f0);
                border: 4px solid #a8e6a3;
                border-radius: 25px;
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
