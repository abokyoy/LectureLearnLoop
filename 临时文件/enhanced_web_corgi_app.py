#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
柯基学习小助手 - 增强Web版本
支持Python与JavaScript双向通信
集成真实功能模块
"""

import sys
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, Qt, QObject, Slot, Signal, QPoint
from PySide6.QtGui import QFont, QMouseEvent

class CorgiWebBridge(QObject):
    """Python与JavaScript通信桥梁"""
    
    # 信号定义
    pageChanged = Signal(str)
    dataUpdated = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = "dashboard"
        self.main_window = parent
        
    @Slot(str)
    def switchPage(self, page):
        """切换页面"""
        self.current_page = page
        self.pageChanged.emit(page)
        print(f"🐕 切换到页面: {page}")
        
    @Slot()
    def createNote(self):
        """创建新笔记"""
        print("📝 创建新笔记")
        # 这里可以调用实际的笔记创建功能
        return "新笔记创建成功！"
        
    @Slot()
    def startRecording(self):
        """开始录制"""
        print("🎙️ 开始录制")
        # 这里可以调用实际的录音功能
        return "录制已开始！"
        
    @Slot()
    def startAIPractice(self):
        """开始AI练习"""
        print("🤖 开始AI练习")
        # 这里可以调用实际的AI练习功能
        return "AI练习模式已启动！"
        
    @Slot()
    def manageKnowledge(self):
        """管理知识"""
        print("📚 管理知识")
        # 这里可以调用实际的知识管理功能
        return "知识管理系统已打开！"
        
    @Slot(result=str)
    def getStats(self):
        """获取统计数据"""
        stats = {
            "notes": {"count": 3, "unit": "篇"},
            "exercises": {"count": 15, "unit": "题"},
            "knowledge": {"count": 8, "unit": "个"},
            "time": {"count": "2h 35m", "unit": ""}
        }
        return json.dumps(stats)
        
    @Slot(result=str)
    def getRecentActivities(self):
        """获取最近活动"""
        activities = [
            {"id": "1", "text": "完成了《柯基学习法》笔记", "time": "2分钟前", "icon": "done", "color": "green"},
            {"id": "2", "text": "进行了官僚学习练习", "time": "15分钟前", "icon": "edit", "color": "blue"},
            {"id": "3", "text": "添加了新的知识点", "time": "1小时前", "icon": "add", "color": "yellow"},
            {"id": "4", "text": "录制了学习音频", "time": "2小时前", "icon": "mic", "color": "purple"}
        ]
        return json.dumps(activities)
        
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
            if self.main_window.isMaximized():
                self.main_window.showNormal()
                print("🔄 窗口已还原")
            else:
                self.main_window.showMaximized()
                print("🔼 窗口已最大化")
                
    @Slot()
    def closeWindow(self):
        """关闭窗口"""
        if self.main_window:
            self.main_window.close()
            print("❌ 窗口已关闭")

class EnhancedWebCorgiApp(QMainWindow):
    """增强版Web柯基学习小助手"""
    
    def __init__(self):
        super().__init__()
        self.bridge = CorgiWebBridge(self)
        self.drag_position = QPoint()
        self.setup_window()
        self.setup_web_view()
        self.setup_web_channel()
        self.load_html_content()
        
    def setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("柯基学习小助手 - 增强Web版")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 设置无边框窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
    def setup_web_view(self):
        """设置Web视图"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.web_view = QWebEngineView()
        
        # 配置WebEngine设置
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        
        # 重要：允许鼠标事件传递到父窗口
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        layout.addWidget(self.web_view)
        
    def setup_web_channel(self):
        """设置Web通道"""
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
    def load_html_content(self):
        """加载HTML内容"""
        html_content = self.create_enhanced_html()
        
        html_file = Path("enhanced_corgi_dashboard.html")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        file_url = QUrl.fromLocalFile(str(html_file.absolute()))
        self.web_view.load(file_url)
        
    def mousePressEvent(self, event):
        """鼠标按下事件 - 用于窗口拖拽"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 检查点击位置是否在标题栏区域（顶部100像素）
            if event.position().y() <= 100:
                self.drag_position = event.globalPosition().toPoint() - self.pos()
                print(f"🖱️ 开始拖拽: 点击位置({event.position().x()}, {event.position().y()})")
                event.accept()
                return
        super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 执行窗口拖拽"""
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull():
            new_pos = event.globalPosition().toPoint() - self.drag_position
            self.move(new_pos)
            print(f"🖱️ 拖拽移动: 新位置({new_pos.x()}, {new_pos.y()})")
            event.accept()
            return
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.drag_position.isNull():
                print("🖱️ 结束拖拽")
                self.drag_position = QPoint()
                event.accept()
                return
        super().mouseReleaseEvent(event)
            
    @Slot(int, int)
    def startDrag(self, global_x, global_y):
        """开始拖拽窗口 - 使用全局坐标"""
        if self.main_window:
            self.drag_position = QPoint(global_x, global_y) - self.main_window.pos()
            print(f"🖱️ 开始拖拽: 全局坐标({global_x}, {global_y}), 窗口位置{self.main_window.pos()}")
        
    @Slot(int, int)
    def dragWindow(self, global_x, global_y):
        """拖拽窗口 - 使用全局坐标"""
        if self.main_window and not self.drag_position.isNull():
            new_pos = QPoint(global_x, global_y) - self.drag_position
            self.main_window.move(new_pos)
            print(f"🖱️ 拖拽窗口: 全局坐标({global_x}, {global_y}), 新位置{new_pos}")
        
    def create_enhanced_html(self):
        """创建增强HTML内容"""
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>柯基学习小助手 - 增强版</title>
    <script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
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
                        "bg-light-blue-gray": "#F5F7F9",
                        "bg-light-green": "#E2F2EB",
                        "bg-light-gray": "#F2F0ED",
                    }
                }
            }
        };
    </script>
    <style>
        /* 禁用全局文本选择 */
        * {
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }
        
        /* 动画效果 */
        .fade-in { animation: fadeIn 0.5s ease-in; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
        .hover-scale:hover { transform: scale(1.02); transition: transform 0.2s ease; }
        .card-shadow { box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
        .card-shadow:hover { box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); transition: box-shadow 0.3s ease; }
        
        /* 拖拽区域 */
        .drag-area {
            cursor: move;
        }
        
        /* 窗口控制按钮 */
        .window-control {
            cursor: pointer;
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            user-select: none;
        }
    </style>
</head>
<body class="bg-bg-light-blue-gray font-sans">
    <div class="flex h-screen bg-white">
        <!-- 侧边栏 -->
        <aside class="w-64 flex flex-col p-4 bg-white border-r border-gray-200">
            <div class="flex items-center mb-8">
                <div class="w-10 h-10 rounded-full bg-primary flex items-center justify-center mr-3">
                    <span class="text-white text-xl">🐕</span>
                </div>
                <h1 class="text-lg font-bold text-text-dark-brown">柯基学习小助手</h1>
            </div>
            
            <div class="flex flex-col items-center mb-8">
                <div class="w-20 h-20 rounded-full mb-2 bg-bg-light-green flex items-center justify-center">
                    <span class="text-3xl text-primary">👤</span>
                </div>
                <p class="font-semibold text-text-dark-brown">柯基的主人</p>
                <p class="text-sm text-text-medium-brown">学习等级: Lv.5 ⭐</p>
            </div>
            
            <nav class="flex-1 space-y-2" id="navigation">
                <!-- 导航项将通过JavaScript动态生成 -->
            </nav>
        </aside>
        
        <!-- 主内容区 -->
        <main class="flex-1 p-8 bg-bg-light-blue-gray overflow-y-auto">
            <header class="flex justify-between items-center mb-8 fade-in">
                <div class="flex items-center drag-area" onmousedown="startWindowDrag(event)">
                    <div class="w-12 h-12 mr-4 bg-bg-light-green rounded-full flex items-center justify-center">
                        <span class="text-2xl text-primary">🐕</span>
                    </div>
                    <h2 class="text-3xl font-bold text-text-dark-brown">柯基的学习乐园</h2>
                </div>
                <div class="flex items-center space-x-4">
                    <div class="text-right drag-area" onmousedown="startWindowDrag(event)">
                        <p class="font-semibold text-text-dark-brown">☀️ 汪汪！欢迎回来！</p>
                        <p class="text-sm text-text-gray" id="currentDate"></p>
                    </div>
                    <div class="flex space-x-2">
                        <button class="window-control w-8 h-8 bg-gray-300 hover:bg-gray-400 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('minimizeWindow')" title="最小化">
                            −
                        </button>
                        <button class="window-control w-8 h-8 bg-warning hover:bg-yellow-500 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('maximizeWindow')" title="最大化/还原">
                            □
                        </button>
                        <button class="window-control w-8 h-8 bg-danger hover:bg-red-600 rounded-full flex items-center justify-center text-white text-sm font-bold transition-colors duration-200" onclick="callPythonFunction('closeWindow')" title="关闭">
                            ×
                        </button>
                    </div>
                </div>
            </header>
            
            <!-- 统计卡片 -->
            <div class="grid grid-cols-4 gap-6 mb-8" id="statsCards">
                <!-- 统计卡片将通过JavaScript动态生成 -->
            </div>
            
            <!-- 快速操作 -->
            <div class="mb-8">
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">快速操作</h3>
                <div class="grid grid-cols-4 gap-6">
                    <button class="bg-primary hover:bg-green-600 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale" onclick="callPythonFunction('createNote')">
                        <span class="text-2xl mb-2">➕</span>
                        <span>新建笔记</span>
                    </button>
                    <button class="bg-red-400 hover:bg-red-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale" onclick="callPythonFunction('startRecording')">
                        <span class="text-2xl mb-2">🎙️</span>
                        <span>开始录制</span>
                    </button>
                    <button class="bg-orange-400 hover:bg-orange-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale" onclick="callPythonFunction('startAIPractice')">
                        <span class="text-2xl mb-2">🤖</span>
                        <span>AI练习</span>
                    </button>
                    <button class="bg-gray-400 hover:bg-gray-500 text-white font-semibold py-4 rounded-xl flex flex-col items-center justify-center transition duration-300 card-shadow hover-scale" onclick="callPythonFunction('manageKnowledge')">
                        <span class="text-2xl mb-2">📁</span>
                        <span>知识管理</span>
                    </button>
                </div>
            </div>
            
            <!-- 最近活动 -->
            <div>
                <h3 class="text-xl font-semibold text-text-dark-brown mb-4">最近活动</h3>
                <div class="bg-white p-6 rounded-xl card-shadow" id="recentActivities">
                    <!-- 活动列表将通过JavaScript动态生成 -->
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
            initializeApp();
        });
        
        // 初始化应用
        function initializeApp() {
            updateCurrentDate();
            loadNavigation();
            loadStats();
            loadRecentActivities();
            
            setInterval(updateCurrentDate, 60000);
        }
        
        // 更新当前日期
        function updateCurrentDate() {
            const now = new Date();
            const dateStr = `今天: ${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日`;
            document.getElementById('currentDate').textContent = dateStr;
        }
        
        // 加载导航
        function loadNavigation() {
            const navItems = [
                {name: '工作台', icon: '🏠', page: 'dashboard', active: true},
                {name: '笔记本', icon: '📝', page: 'notebook', active: false},
                {name: '录音室', icon: '🎙️', page: 'recording', active: false},
                {name: 'AI伙伴', icon: '🤖', page: 'ai', active: false},
                {name: '知识库', icon: '📚', page: 'knowledge', active: false},
                {name: '学习报告', icon: '📊', page: 'report', active: false},
                {name: '设置', icon: '⚙️', page: 'settings', active: false}
            ];
            
            const nav = document.getElementById('navigation');
            nav.innerHTML = navItems.map(item => `
                <a class="nav-item flex items-center px-4 py-2.5 rounded-lg cursor-pointer hover-scale ${item.active ? 'bg-primary text-white card-shadow' : 'text-text-gray hover:bg-bg-light-gray'}" 
                   onclick="switchPage('${item.page}', this)">
                    <span class="mr-3 text-lg">${item.icon}</span>
                    <span>${item.name}</span>
                </a>
            `).join('');
        }
        
        // 加载统计数据
        function loadStats() {
            if (bridge && bridge.getStats) {
                bridge.getStats(function(result) {
                    const stats = JSON.parse(result);
                    const statsContainer = document.getElementById('statsCards');
                    
                    const statsData = [
                        {title: '今日笔记', value: stats.notes.count, unit: stats.notes.unit, color: 'primary', bgColor: 'bg-bg-light-green', icon: '📚'},
                        {title: '练习完成', value: stats.exercises.count, unit: stats.exercises.unit, color: 'warning', bgColor: 'bg-orange-100', icon: '✅'},
                        {title: '新增知识点', value: stats.knowledge.count, unit: stats.knowledge.unit, color: 'pink-500', bgColor: 'bg-pink-100', icon: '💡'},
                        {title: '学习时长', value: stats.time.count, unit: stats.time.unit, color: 'danger', bgColor: 'bg-red-100', icon: '⏰'}
                    ];
                    
                    statsContainer.innerHTML = statsData.map(stat => `
                        <div class="bg-white p-6 rounded-xl card-shadow hover-scale cursor-pointer">
                            <div class="flex items-start">
                                <div class="p-3 rounded-lg ${stat.bgColor} mr-4">
                                    <span class="text-xl">${stat.icon}</span>
                                </div>
                                <div>
                                    <p class="text-sm text-text-gray mb-1">${stat.title}</p>
                                    <p class="text-3xl font-bold text-${stat.color}">${stat.value} <span class="text-base font-normal text-text-medium-brown">${stat.unit}</span></p>
                                </div>
                            </div>
                        </div>
                    `).join('');
                });
            }
        }
        
        // 加载最近活动
        function loadRecentActivities() {
            if (bridge && bridge.getRecentActivities) {
                bridge.getRecentActivities(function(result) {
                    const activities = JSON.parse(result);
                    const container = document.getElementById('recentActivities');
                    
                    container.innerHTML = activities.map(activity => `
                        <div class="flex justify-between items-center hover:bg-gray-50 p-2 rounded-lg cursor-pointer hover-scale mb-4">
                            <div class="flex items-center">
                                <div class="w-8 h-8 rounded-full bg-${activity.color}-100 flex items-center justify-center mr-4">
                                    <span class="text-sm">${getActivityIcon(activity.icon)}</span>
                                </div>
                                <p class="text-text-medium-brown">${activity.text}</p>
                            </div>
                            <span class="text-sm text-text-gray bg-bg-light-gray px-2 py-1 rounded-md">${activity.time}</span>
                        </div>
                    `).join('');
                });
            }
        }
        
        // 获取活动图标
        function getActivityIcon(iconType) {
            const icons = {
                'done': '✅',
                'edit': '✏️',
                'add': '➕',
                'mic': '🎙️'
            };
            return icons[iconType] || '📝';
        }
        
        // 切换页面
        function switchPage(page, element) {
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('bg-primary', 'text-white', 'card-shadow');
                item.classList.add('text-text-gray');
            });
            
            element.classList.add('bg-primary', 'text-white', 'card-shadow');
            element.classList.remove('text-text-gray');
            
            if (bridge && bridge.switchPage) {
                bridge.switchPage(page);
            }
        }
        
        // 调用Python函数
        function callPythonFunction(functionName) {
            if (bridge && bridge[functionName]) {
                bridge[functionName](function(result) {
                    console.log(`Python返回: ${result}`);
                    showNotification(result);
                });
            }
        }
        
        // 显示通知
        function showNotification(message) {
            // 创建简单的通知
            const notification = document.createElement('div');
            notification.className = 'fixed top-4 right-4 bg-primary text-white px-4 py-2 rounded-lg card-shadow z-50';
            notification.textContent = message;
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.remove();
            }, 3000);
        }
        
        // 窗口拖拽功能
        let isDragging = false;
        let dragStartX = 0;
        let dragStartY = 0;
        
        function startWindowDrag(event) {
            if (event.button === 0) { // 左键
                isDragging = true;
                dragStartX = event.screenX;
                dragStartY = event.screenY;
                
                console.log('开始拖拽:', event.screenX, event.screenY);
                
                if (bridge && bridge.startDrag) {
                    bridge.startDrag(event.screenX, event.screenY);
                }
                
                event.preventDefault();
                event.stopPropagation();
            }
        }
        
        
        // 全局鼠标事件监听
        document.addEventListener('mouseup', function(event) {
            if (isDragging) {
                isDragging = false;
                console.log('结束拖拽');
                event.preventDefault();
            }
        });
        
        document.addEventListener('mousemove', function(event) {
            if (isDragging) {
                console.log('拖拽移动:', event.screenX, event.screenY);
                
                if (bridge && bridge.dragWindow) {
                    bridge.dragWindow(event.screenX, event.screenY);
                }
                event.preventDefault();
            }
        });
        
        // 防止拖拽时选中文本
        document.addEventListener('selectstart', function(event) {
            if (isDragging) {
                event.preventDefault();
            }
        });
        
        // 防止默认拖拽行为
        document.addEventListener('dragstart', function(event) {
            event.preventDefault();
        });
    </script>
</body>
</html>'''

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    app.setApplicationName("柯基学习小助手")
    app.setApplicationVersion("2.1")
    
    window = EnhancedWebCorgiApp()
    window.show()
    
    print("🐕 增强版柯基学习小助手启动成功！")
    print("🌐 QWebEngineView + Chromium内核")
    print("🔗 Python ↔ JavaScript 双向通信")
    print("⚡ 真实功能集成支持")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
