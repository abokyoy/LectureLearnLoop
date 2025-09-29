// 练习助手欢迎界面功能

// 创建练习欢迎界面
function createPracticeWelcome() {
    // 检查是否已经存在欢迎界面
    const existingWelcome = document.getElementById('practiceWelcomePanel');
    if (existingWelcome) {
        console.log('欢迎界面已存在，跳过创建');
        return;
    }
    
    const practiceTabContent = document.getElementById('practiceTabContent');
    const aiPracticeMessages = document.getElementById('aiPracticeMessages');
    
    console.log('创建练习欢迎界面 - practiceTabContent:', !!practiceTabContent, 'aiPracticeMessages:', !!aiPracticeMessages);
    
    if (practiceTabContent && aiPracticeMessages) {
        const welcomeHTML = `
        <div class="practice-welcome-panel" id="practiceWelcomePanel" style="display: block;">
            <div class="flex flex-col items-center justify-center h-full p-8 text-center">
                <div class="mb-8">
                    <span class="material-icons-outlined text-6xl text-primary mb-4 block">quiz</span>
                    <h2 class="text-2xl font-bold text-text-dark-brown mb-2">AI练习助手</h2>
                    <p class="text-text-medium-brown mb-6">智能生成练习题目，提升学习效果</p>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-md">
                    <button class="practice-action-btn flex flex-col items-center p-6 bg-white rounded-xl shadow-sm hover:shadow-md transition-shadow border border-gray-100" id="welcomeNewPracticeBtn">
                        <span class="material-icons-outlined text-3xl text-primary mb-2">add_circle_outline</span>
                        <span class="font-medium text-text-dark-brown">开始新练习</span>
                        <span class="text-sm text-text-medium-brown mt-1">生成新的练习题目</span>
                    </button>
                    
                    <button class="practice-action-btn flex flex-col items-center p-6 bg-white rounded-xl shadow-sm hover:shadow-md transition-shadow border border-gray-100" id="welcomePracticeHistoryBtn">
                        <span class="material-icons-outlined text-3xl text-blue-500 mb-2">history</span>
                        <span class="font-medium text-text-dark-brown">练习历史</span>
                        <span class="text-sm text-text-medium-brown mt-1">查看历史练习记录</span>
                    </button>
                </div>
                
                <div class="mt-8 text-sm text-text-medium-brown">
                    <p>💡 提示：您可以通过AI对话生成个性化练习题目</p>
                </div>
            </div>
        </div>
        `;
        
        // 在消息面板前插入欢迎界面
        addDebugLog('📝 插入欢迎界面HTML');
        aiPracticeMessages.insertAdjacentHTML('beforebegin', welcomeHTML);
        
        // 隐藏消息面板，显示欢迎界面
        addDebugLog('👁️ 隐藏消息面板，显示欢迎界面');
        aiPracticeMessages.style.display = 'none';
        
        // 验证欢迎界面是否成功创建
        const createdWelcome = document.getElementById('practiceWelcomePanel');
        addDebugLog(`✅ 欢迎界面创建结果: ${!!createdWelcome}`);
        
        if (createdWelcome) {
            addDebugLog(`🎨 欢迎界面样式: display=${createdWelcome.style.display}`);
        }
        
        // 绑定按钮事件
        bindPracticeWelcomeEvents();
    }
}

// 绑定练习欢迎界面的事件
function bindPracticeWelcomeEvents() {
    const welcomeNewPracticeBtn = document.getElementById('welcomeNewPracticeBtn');
    const welcomePracticeHistoryBtn = document.getElementById('welcomePracticeHistoryBtn');
    
    if (welcomeNewPracticeBtn) {
        welcomeNewPracticeBtn.addEventListener('click', function() {
            console.log('点击开始新练习');
            // 隐藏欢迎界面，显示消息面板
            showPracticeMessages();
            // 添加提示消息
            if (typeof addPracticeMessage === 'function') {
                addPracticeMessage('请通过AI对话描述您想要练习的内容，我将为您生成个性化的练习题目。\n\n例如：\n• "请为我生成5道关于机器学习的选择题"\n• "帮我出几道Python编程练习题"\n• "生成一些数学应用题"', 'ai');
            }
        });
    }
    
    if (welcomePracticeHistoryBtn) {
        welcomePracticeHistoryBtn.addEventListener('click', function() {
            console.log('点击练习历史');
            // 调用练习历史功能
            if (typeof showPracticeHistory === 'function') {
                showPracticeHistory();
            } else {
                // 隐藏欢迎界面，显示消息面板
                showPracticeMessages();
                if (typeof addPracticeMessage === 'function') {
                    addPracticeMessage('正在加载练习历史...', 'ai');
                    
                    // 模拟加载练习历史
                    setTimeout(() => {
                        addPracticeMessage('练习历史功能正在开发中！\n\n目前您可以：\n• 通过对话生成新的练习题目\n• 完成练习后查看评估结果\n• 将错题添加到错题库', 'ai');
                    }, 1000);
                }
            }
        });
    }
}

// 显示练习消息面板
function showPracticeMessages() {
    const welcomePanel = document.getElementById('practiceWelcomePanel');
    const messagesPanel = document.getElementById('aiPracticeMessages');
    
    if (welcomePanel) welcomePanel.style.display = 'none';
    if (messagesPanel) messagesPanel.style.display = 'block';
}

// 显示练习欢迎界面
function showPracticeWelcome() {
    const welcomePanel = document.getElementById('practiceWelcomePanel');
    const messagesPanel = document.getElementById('aiPracticeMessages');
    const practiceContainer = document.getElementById('practiceContainer');
    
    if (welcomePanel) {
        welcomePanel.style.display = 'block';
    } else {
        // 如果欢迎界面不存在，创建它
        createPracticeWelcome();
        return;
    }
    
    if (messagesPanel) messagesPanel.style.display = 'none';
    if (practiceContainer) practiceContainer.style.display = 'none';
}

// 初始化练习欢迎界面
function initPracticeWelcome() {
    // 检查是否已经存在欢迎界面
    const existingWelcome = document.getElementById('practiceWelcomePanel');
    if (!existingWelcome) {
        createPracticeWelcome();
    }
}

// 当页面加载完成时初始化
document.addEventListener('DOMContentLoaded', function() {
    // 延迟初始化，确保其他组件已加载
    setTimeout(initPracticeWelcome, 1000);
});

// 创建可见的调试面板
function createDebugPanel() {
    // 移除已存在的调试面板
    const existingDebug = document.getElementById('practice-debug-panel');
    if (existingDebug) {
        existingDebug.remove();
    }
    
    const debugPanel = document.createElement('div');
    debugPanel.id = 'practice-debug-panel';
    debugPanel.style.cssText = `
        position: fixed;
        bottom: 20px;
        left: 20px;
        background: rgba(0, 0, 0, 0.9);
        color: #00ff00;
        padding: 15px;
        border-radius: 8px;
        font-family: monospace;
        font-size: 12px;
        z-index: 10000;
        max-width: 400px;
        max-height: 300px;
        overflow-y: auto;
        border: 1px solid #333;
    `;
    
    debugPanel.innerHTML = `
        <div style="font-weight: bold; margin-bottom: 10px; color: #ffff00;">
            🔧 练习助手调试面板
            <button onclick="this.parentElement.parentElement.remove()" style="
                float: right;
                background: none;
                border: none;
                color: #ff6666;
                cursor: pointer;
                font-size: 14px;
            ">×</button>
        </div>
        <div id="debug-log" style="line-height: 1.4;"></div>
    `;
    
    document.body.appendChild(debugPanel);
    return debugPanel;
}

// 添加调试日志
function addDebugLog(message) {
    console.log(message);
    
    let debugPanel = document.getElementById('practice-debug-panel');
    if (!debugPanel) {
        debugPanel = createDebugPanel();
    }
    
    const logContainer = debugPanel.querySelector('#debug-log');
    if (logContainer) {
        const timestamp = new Date().toLocaleTimeString();
        logContainer.innerHTML += `<div>[${timestamp}] ${message}</div>`;
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}

// 更积极的初始化策略
function forceInitPracticeWelcome() {
    addDebugLog('🔄 强制初始化练习欢迎界面');
    const practiceTabContent = document.getElementById('practiceTabContent');
    const aiPracticeMessages = document.getElementById('aiPracticeMessages');
    
    addDebugLog(`📋 元素检查: practiceTabContent=${!!practiceTabContent}, aiPracticeMessages=${!!aiPracticeMessages}`);
    
    if (practiceTabContent) {
        addDebugLog('✅ 找到practiceTabContent，开始创建欢迎界面');
        createPracticeWelcome();
    } else {
        addDebugLog('❌ 未找到practiceTabContent，1秒后重试');
        setTimeout(forceInitPracticeWelcome, 1000);
    }
}

// 立即尝试初始化
setTimeout(forceInitPracticeWelcome, 500);

// 导出函数到全局作用域
window.createPracticeWelcome = createPracticeWelcome;
window.showPracticeWelcome = showPracticeWelcome;
window.showPracticeMessages = showPracticeMessages;
window.initPracticeWelcome = initPracticeWelcome;
