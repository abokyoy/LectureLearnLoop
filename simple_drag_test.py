#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
简单拖拽测试版本
用于测试拖拽功能是否正常工作
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, Qt, QObject, Slot, Signal, QPoint
from PySide6.QtGui import QFont

class DragTestBridge(QObject):
    """拖拽测试桥梁"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.drag_position = QPoint()
        
    @Slot(int, int)
    def startDrag(self, screen_x, screen_y):
        """开始拖拽"""
        if self.main_window:
            current_pos = self.main_window.pos()
            self.drag_position = QPoint(screen_x, screen_y) - current_pos
            print(f"🖱️ 开始拖拽: 屏幕坐标({screen_x}, {screen_y}), 窗口位置{current_pos}, 偏移{self.drag_position}")
        
    @Slot(int, int)
    def dragWindow(self, screen_x, screen_y):
        """拖拽窗口"""
        if self.main_window and not self.drag_position.isNull():
            new_pos = QPoint(screen_x, screen_y) - self.drag_position
            self.main_window.move(new_pos)
            print(f"🖱️ 移动窗口: 屏幕坐标({screen_x}, {screen_y}), 新位置{new_pos}")
            
    @Slot()
    def testConnection(self):
        """测试连接"""
        print("✅ JavaScript与Python连接正常！")
        return "连接成功"

class SimpleDragTest(QMainWindow):
    """简单拖拽测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.bridge = DragTestBridge(self)
        self.setup_window()
        self.setup_web_view()
        self.setup_web_channel()
        self.load_test_html()
        
    def setup_window(self):
        """设置窗口"""
        self.setWindowTitle("拖拽测试")
        self.setMinimumSize(800, 600)
        self.resize(800, 600)
        
        # 无边框窗口
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
        
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        
        layout.addWidget(self.web_view)
        
    def setup_web_channel(self):
        """设置Web通道"""
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
    def load_test_html(self):
        """加载测试HTML"""
        html_content = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>拖拽测试</title>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            user-select: none;
        }
        .drag-area {
            background: rgba(255,255,255,0.2);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
            cursor: move;
            border: 2px dashed rgba(255,255,255,0.5);
        }
        .drag-area:hover {
            background: rgba(255,255,255,0.3);
        }
        .controls {
            background: rgba(0,0,0,0.3);
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
        }
        button {
            background: #ff6b6b;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 5px;
        }
        button:hover {
            background: #ff5252;
        }
        .status {
            background: rgba(0,0,0,0.5);
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <h1>🖱️ 拖拽功能测试</h1>
    
    <div class="drag-area" id="dragArea" onmousedown="startDrag(event)">
        <h2>📱 拖拽区域</h2>
        <p>点击这里并拖拽来移动窗口</p>
        <p>这个区域应该可以拖拽整个窗口</p>
    </div>
    
    <div class="controls">
        <h3>🎮 控制面板</h3>
        <button onclick="testConnection()">测试连接</button>
        <button onclick="closeWindow()">关闭窗口</button>
    </div>
    
    <div class="status" id="status">
        <h3>📊 状态信息</h3>
        <p id="statusText">等待连接...</p>
    </div>

    <script>
        let bridge;
        let isDragging = false;
        
        // 初始化Web通道
        new QWebChannel(qt.webChannelTransport, function(channel) {
            bridge = channel.objects.bridge;
            updateStatus('✅ 连接成功！可以开始测试拖拽功能');
            console.log('Bridge connected:', bridge);
        });
        
        // 开始拖拽
        function startDrag(event) {
            if (event.button === 0) { // 左键
                isDragging = true;
                
                const screenX = event.screenX;
                const screenY = event.screenY;
                
                updateStatus(`🖱️ 开始拖拽: 屏幕坐标(${screenX}, ${screenY})`);
                console.log('开始拖拽:', screenX, screenY);
                
                if (bridge && bridge.startDrag) {
                    bridge.startDrag(screenX, screenY);
                } else {
                    updateStatus('❌ 桥梁未连接或方法不存在');
                }
                
                event.preventDefault();
                event.stopPropagation();
            }
        }
        
        // 拖拽移动
        function dragMove(event) {
            if (isDragging) {
                const screenX = event.screenX;
                const screenY = event.screenY;
                
                updateStatus(`🖱️ 拖拽中: 屏幕坐标(${screenX}, ${screenY})`);
                
                if (bridge && bridge.dragWindow) {
                    bridge.dragWindow(screenX, screenY);
                }
                
                event.preventDefault();
            }
        }
        
        // 结束拖拽
        function endDrag(event) {
            if (isDragging) {
                isDragging = false;
                updateStatus('✅ 拖拽结束');
                event.preventDefault();
            }
        }
        
        // 全局事件监听
        document.addEventListener('mousemove', dragMove);
        document.addEventListener('mouseup', endDrag);
        
        // 测试连接
        function testConnection() {
            if (bridge && bridge.testConnection) {
                bridge.testConnection();
                updateStatus('🔗 测试连接命令已发送');
            } else {
                updateStatus('❌ 桥梁未连接');
            }
        }
        
        // 关闭窗口
        function closeWindow() {
            window.close();
        }
        
        // 更新状态
        function updateStatus(message) {
            const statusText = document.getElementById('statusText');
            if (statusText) {
                statusText.textContent = message;
            }
            console.log(message);
        }
        
        // 防止默认拖拽行为
        document.addEventListener('dragstart', function(e) {
            e.preventDefault();
        });
        
        document.addEventListener('selectstart', function(e) {
            if (isDragging) {
                e.preventDefault();
            }
        });
    </script>
</body>
</html>'''
        
        html_file = Path("drag_test.html")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        file_url = QUrl.fromLocalFile(str(html_file.absolute()))
        self.web_view.load(file_url)

def main():
    app = QApplication(sys.argv)
    
    window = SimpleDragTest()
    window.show()
    
    print("🧪 拖拽测试程序启动")
    print("📱 请点击拖拽区域测试拖拽功能")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
