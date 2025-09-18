#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
柯基学习小助手 - 现代化界面
基于HTML设计稿的一比一还原
使用沉稳配色方案
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QDateTime
from PySide6.QtGui import QFont

class ModernCorgiApp(QMainWindow):
    """现代化柯基学习小助手主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setup_window()
        self.setup_ui()
        self.setup_timer()
        
    def setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("柯基学习小助手")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 设置窗口背景
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F5F7F9;
            }
        """)
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
    def setup_ui(self):
        """设置用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 侧边栏
        sidebar = self.create_sidebar()
        main_layout.addWidget(sidebar)
        
        # 主内容区域
        main_content = self.create_main_content()
        main_layout.addWidget(main_content)
        
    def create_sidebar(self):
        """创建侧边栏"""
        sidebar = QFrame()
        sidebar.setFixedWidth(256)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: white;
                border-right: 1px solid #E5E7EB;
            }
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        
        # 顶部标题区域
        header = self.create_sidebar_header()
        layout.addWidget(header)
        
        # 用户信息区域
        user_info = self.create_user_info()
        layout.addWidget(user_info)
        
        # 导航菜单
        nav = self.create_navigation()
        layout.addWidget(nav)
        
        # 底部控制区域
        layout.addStretch()
        bottom_controls = self.create_bottom_controls()
        layout.addWidget(bottom_controls)
        
        return sidebar
        
    def create_sidebar_header(self):
        """创建侧边栏标题"""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 32)
        layout.setSpacing(12)
        
        # 柯基图标
        icon_container = QLabel()
        icon_container.setFixedSize(40, 40)
        icon_container.setStyleSheet("""
            QLabel {
                background-color: #32C77F;
                border-radius: 20px;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
        """)
        icon_container.setText("🐕")
        icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 标题文字
        title = QLabel("柯基学习小助手")
        title.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 18px;
                font-weight: bold;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        layout.addWidget(icon_container)
        layout.addWidget(title)
        layout.addStretch()
        
        return header
        
    def create_user_info(self):
        """创建用户信息区域"""
        user_info = QWidget()
        layout = QVBoxLayout(user_info)
        layout.setContentsMargins(0, 0, 0, 32)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 用户头像
        avatar = QLabel()
        avatar.setFixedSize(80, 80)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #E2F2EB;
                border-radius: 40px;
                color: #32C77F;
                font-size: 32px;
            }
        """)
        avatar.setText("👤")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 用户名
        username = QLabel("柯基的主人")
        username.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 16px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        username.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 等级信息
        level = QLabel("学习等级: Lv.5 ⭐")
        level.setStyleSheet("""
            QLabel {
                color: #9B8D7D;
                font-size: 14px;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        level.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(avatar)
        layout.addWidget(username)
        layout.addWidget(level)
        
        return user_info
        
    def create_navigation(self):
        """创建导航菜单"""
        nav = QWidget()
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 菜单项数据
        menu_items = [
            ("工作台", "🏠", True),
            ("笔记本", "📝", False),
            ("录音室", "🎙️", False),
            ("AI伙伴", "🤖", False),
            ("知识库", "📚", False),
            ("学习报告", "📊", False),
            ("设置", "⚙️", False),
        ]
        
        for name, icon, is_active in menu_items:
            item = self.create_nav_item(name, icon, is_active)
            layout.addWidget(item)
            
        return nav
        
    def create_nav_item(self, name, icon, is_active):
        """创建导航菜单项"""
        item = QPushButton()
        item.setFixedHeight(42)
        item.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 设置按钮样式
        if is_active:
            item.setStyleSheet("""
                QPushButton {
                    background-color: #32C77F;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                    font-weight: 500;
                    font-family: "Microsoft YaHei UI", sans-serif;
                }
                QPushButton:hover {
                    background-color: #2AB86F;
                }
            """)
        else:
            item.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #828282;
                    border: none;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                    font-weight: 500;
                    font-family: "Microsoft YaHei UI", sans-serif;
                }
                QPushButton:hover {
                    background-color: #F2F0ED;
                }
            """)
        
        # 设置按钮文本
        item.setText(f"{icon}  {name}")
        
        return item
        
    def create_bottom_controls(self):
        """创建底部控制区域"""
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(0)
        
        # 控制按钮
        buttons = ["◀", "⋯", "▶"]
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #828282;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #F2F0ED;
                }
            """)
            layout.addWidget(btn)
            
        return controls
        
    def create_main_content(self):
        """创建主内容区域"""
        main_content = QWidget()
        main_content.setStyleSheet("""
            QWidget {
                background-color: #F5F7F9;
            }
        """)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #F5F7F9;
            }
            QScrollBar:vertical {
                background-color: #F5F7F9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #D1D5DB;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #9CA3AF;
            }
        """)
        
        # 内容容器
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(32)
        
        # 页面标题
        header = self.create_page_header()
        layout.addWidget(header)
        
        # 统计卡片
        stats_cards = self.create_stats_cards()
        layout.addWidget(stats_cards)
        
        # 快速操作
        quick_actions = self.create_quick_actions()
        layout.addWidget(quick_actions)
        
        # 最近活动
        recent_activity = self.create_recent_activity()
        layout.addWidget(recent_activity)
        
        layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        
        # 主内容布局
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll_area)
        
        return main_content
        
    def create_page_header(self):
        """创建页面标题区域"""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 左侧标题
        left_section = QHBoxLayout()
        left_section.setSpacing(16)
        
        # 柯基图标
        corgi_icon = QLabel()
        corgi_icon.setFixedSize(48, 48)
        corgi_icon.setStyleSheet("""
            QLabel {
                background-color: #E2F2EB;
                border-radius: 24px;
                color: #32C77F;
                font-size: 24px;
            }
        """)
        corgi_icon.setText("🐕")
        corgi_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 标题文字
        title = QLabel("柯基的学习乐园")
        title.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 32px;
                font-weight: bold;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        left_section.addWidget(corgi_icon)
        left_section.addWidget(title)
        
        # 右侧信息
        right_section = QHBoxLayout()
        right_section.setSpacing(16)
        
        # 欢迎信息
        welcome_info = QWidget()
        welcome_layout = QVBoxLayout(welcome_info)
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.setSpacing(4)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        welcome_text = QLabel("☀️ 汪汪！欢迎回来！")
        welcome_text.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 16px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        welcome_text.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.date_text = QLabel("今天: 2024年9月17日")
        self.date_text.setStyleSheet("""
            QLabel {
                color: #828282;
                font-size: 14px;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        self.date_text.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        welcome_layout.addWidget(welcome_text)
        welcome_layout.addWidget(self.date_text)
        
        # 通知按钮
        notification_btn = QPushButton("🔔")
        notification_btn.setFixedSize(40, 40)
        notification_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 20px;
                font-size: 18px;
                color: #828282;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
        """)
        
        # 窗口控制按钮
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        
        # 三个圆点按钮
        colors = ["#D1D5DB", "#FF9B27", "#ED4B4B"]
        for color in colors:
            dot = QPushButton()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    border: none;
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    opacity: 0.8;
                }}
            """)
            controls_layout.addWidget(dot)
        
        right_section.addWidget(welcome_info)
        right_section.addWidget(notification_btn)
        right_section.addWidget(controls)
        
        layout.addLayout(left_section)
        layout.addStretch()
        layout.addLayout(right_section)
        
        return header
        
    def create_stats_cards(self):
        """创建统计卡片区域"""
        cards_container = QWidget()
        layout = QGridLayout(cards_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        
        # 卡片数据
        cards_data = [
            ("今日笔记", "3", "篇", "#32C77F", "#E2F2EB", "📚"),
            ("练习完成", "15", "题", "#FF9B27", "#FFF0D6", "✅"),
            ("新增知识点", "8", "个", "#EC4899", "#FCE7F3", "💡"),
            ("学习时长", "2h 35m", "", "#ED4B4B", "#FEE2E2", "⏰"),
        ]
        
        for i, (title, value, unit, color, bg_color, icon) in enumerate(cards_data):
            card = self.create_stat_card(title, value, unit, color, bg_color, icon)
            layout.addWidget(card, 0, i)
            
        return cards_container
        
    def create_stat_card(self, title, value, unit, color, bg_color, icon):
        """创建单个统计卡片"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 12px;
                border: none;
            }
        """)
        card.setFixedHeight(120)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 图标区域
        icon_container = QLabel()
        icon_container.setFixedSize(48, 48)
        icon_container.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                border-radius: 8px;
                font-size: 20px;
            }}
        """)
        icon_container.setText(icon)
        icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 文字区域
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        
        # 标题
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #828282;
                font-size: 14px;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        # 数值和单位
        value_container = QWidget()
        value_layout = QHBoxLayout(value_container)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(4)
        value_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 32px;
                font-weight: bold;
                font-family: "Microsoft YaHei UI", sans-serif;
            }}
        """)
        
        if unit:
            unit_label = QLabel(unit)
            unit_label.setStyleSheet("""
                QLabel {
                    color: #9B8D7D;
                    font-size: 16px;
                    font-family: "Microsoft YaHei UI", sans-serif;
                }
            """)
            value_layout.addWidget(value_label)
            value_layout.addWidget(unit_label)
        else:
            value_layout.addWidget(value_label)
            
        value_layout.addStretch()
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(value_container)
        text_layout.addStretch()
        
        layout.addWidget(icon_container)
        layout.addWidget(text_container)
        
        return card
        
    def create_quick_actions(self):
        """创建快速操作区域"""
        actions_container = QWidget()
        layout = QVBoxLayout(actions_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # 标题
        title = QLabel("快速操作")
        title.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 20px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        # 按钮网格
        buttons_container = QWidget()
        buttons_layout = QGridLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(24)
        
        # 按钮数据
        actions_data = [
            ("新建笔记", "➕", "#32C77F"),
            ("开始录制", "🎙️", "#EF4444"),
            ("AI练习", "🤖", "#F59E0B"),
            ("知识管理", "📁", "#6B7280"),
        ]
        
        for i, (name, icon, color) in enumerate(actions_data):
            btn = self.create_action_button(name, icon, color)
            buttons_layout.addWidget(btn, 0, i)
            
        layout.addWidget(title)
        layout.addWidget(buttons_container)
        
        return actions_container
        
    def create_action_button(self, name, icon, color):
        """创建快速操作按钮"""
        btn = QPushButton()
        btn.setFixedHeight(80)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", sans-serif;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        
        # 设置按钮文本
        btn.setText(f"{icon}\n{name}")
        
        return btn
        
    def create_recent_activity(self):
        """创建最近活动区域"""
        activity_container = QWidget()
        layout = QVBoxLayout(activity_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # 标题
        title = QLabel("最近活动")
        title.setStyleSheet("""
            QLabel {
                color: #715D46;
                font-size: 20px;
                font-weight: 600;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        # 活动列表容器
        activities_card = QFrame()
        activities_card.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 12px;
                border: none;
            }
        """)
        
        activities_layout = QVBoxLayout(activities_card)
        activities_layout.setContentsMargins(24, 24, 24, 24)
        activities_layout.setSpacing(16)
        
        # 活动数据
        activities_data = [
            ("完成了《柯基学习法》笔记", "✅", "#E2F2EB", "#32C77F", "2分钟前"),
            ("进行了官僚学习练习", "✏️", "#DBEAFE", "#3B82F6", "15分钟前"),
            ("添加了新的知识点", "➕", "#FEF3C7", "#F59E0B", "1小时前"),
            ("录制了学习音频", "🎙️", "#F3E8FF", "#8B5CF6", "2小时前"),
        ]
        
        for description, icon, bg_color, icon_color, time in activities_data:
            activity_item = self.create_activity_item(description, icon, bg_color, icon_color, time)
            activities_layout.addWidget(activity_item)
            
        layout.addWidget(title)
        layout.addWidget(activities_card)
        
        return activity_container
        
    def create_activity_item(self, description, icon, bg_color, icon_color, time):
        """创建活动项"""
        item = QWidget()
        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # 左侧图标和描述
        left_section = QHBoxLayout()
        left_section.setSpacing(16)
        
        # 图标
        icon_container = QLabel()
        icon_container.setFixedSize(32, 32)
        icon_container.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                border-radius: 16px;
                font-size: 14px;
            }}
        """)
        icon_container.setText(icon)
        icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 描述文字
        desc_label = QLabel(description)
        desc_label.setStyleSheet("""
            QLabel {
                color: #9B8D7D;
                font-size: 14px;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        left_section.addWidget(icon_container)
        left_section.addWidget(desc_label)
        
        # 右侧时间
        time_label = QLabel(time)
        time_label.setStyleSheet("""
            QLabel {
                color: #828282;
                font-size: 12px;
                background-color: #F2F0ED;
                padding: 4px 8px;
                border-radius: 4px;
                font-family: "Microsoft YaHei UI", sans-serif;
            }
        """)
        
        layout.addLayout(left_section)
        layout.addStretch()
        layout.addWidget(time_label)
        
        return item
        
    def setup_timer(self):
        """设置定时器更新时间"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_datetime)
        self.timer.start(60000)  # 每分钟更新一次
        self.update_datetime()
        
    def update_datetime(self):
        """更新日期时间显示"""
        current_time = QDateTime.currentDateTime()
        date_str = current_time.toString("今天: yyyy年M月d日")
        self.date_text.setText(date_str)

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用程序字体
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)
    
    # 创建主窗口
    window = ModernCorgiApp()
    window.show()
    
    print("🐕 现代化柯基学习小助手启动成功！")
    print("🎨 基于HTML设计稿的一比一还原")
    print("🌟 使用沉稳配色方案")
    print("✨ 现代化界面设计")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
