#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复脑图页面导航问题

问题现象：
1. 第一次进入脑图页面正常
2. 点击知识点详情后正常
3. 返回科目选择页面，再次点击机器学习时，脑图无法显示

可能原因：
1. 页面状态管理问题
2. WebChannel连接丢失
3. DOM元素状态异常
4. 脑图渲染冲突
"""

def analyze_navigation_issue():
    """分析页面导航问题"""
    print("🔍 分析脑图页面导航问题")
    print("=" * 50)
    
    print("📋 问题现象:")
    print("1. ✅ 第一次进入脑图页面 - 正常")
    print("2. ✅ 点击知识点详情 - 正常")
    print("3. ✅ 知识点详情显示正确内容 - 正常")
    print("4. ❌ 返回科目选择后再次进入 - 脑图无法显示")
    
    print("\n🔍 可能的原因分析:")
    print("1. 页面状态管理问题:")
    print("   - DOM元素状态没有正确重置")
    print("   - 全局变量状态混乱")
    print("   - 事件监听器重复绑定")
    
    print("2. WebChannel连接问题:")
    print("   - 页面切换后WebChannel连接丢失")
    print("   - bridge对象状态异常")
    
    print("3. D3.js渲染冲突:")
    print("   - 之前的SVG元素没有清理")
    print("   - 力导向图simulation没有停止")
    print("   - 事件监听器冲突")
    
    print("4. 缓存或数据问题:")
    print("   - 脑图数据缓存异常")
    print("   - API调用失败但没有错误提示")

def create_navigation_fix():
    """创建导航修复方案"""
    print("\n🔧 创建导航修复方案")
    
    fix_code = '''
// 在selectSubject函数开始时添加清理逻辑
function selectSubject(subjectName) {
    log(`🎯 点击了学科: ${subjectName}`);
    
    // === 新增：页面状态清理 ===
    try {
        // 1. 清理之前的脑图渲染
        if (simulation) {
            simulation.stop();
            simulation = null;
            log(`🧹 已停止之前的simulation`);
        }
        
        // 2. 清理SVG内容
        const svg = d3.select("#mindmapSvg");
        if (!svg.empty()) {
            svg.selectAll("*").remove();
            log(`🧹 已清理SVG内容`);
        }
        
        // 3. 重置全局变量
        currentMindmapData = null;
        g = null;
        zoom = null;
        log(`🧹 已重置全局变量`);
        
        // 4. 清理详情面板状态
        const detailPanel = document.getElementById('knowledgePointDetail');
        if (detailPanel) {
            detailPanel.classList.add('hidden');
            log(`🧹 已隐藏详情面板`);
        }
        
        // 5. 重置加载状态
        hideLoading();
        log(`🧹 已重置加载状态`);
        
    } catch (error) {
        log(`⚠️ 清理过程中出现错误: ${error.message}`);
    }
    // === 清理逻辑结束 ===
    
    // 原有逻辑继续...
    currentSubjectName = subjectName;
    // ... 其他代码保持不变
}

// 在generateMindmap函数开始时也添加检查
async function generateMindmap(subjectName) {
    log(`🧠 开始生成 ${subjectName} 的知识脑图`);
    
    // === 新增：生成前检查 ===
    try {
        // 检查页面状态
        const mindmapPage = document.getElementById('mindmapPage');
        const subjectPage = document.getElementById('subjectSelectionPage');
        
        if (!mindmapPage || mindmapPage.classList.contains('hidden')) {
            log(`❌ 脑图页面状态异常，尝试修复`);
            if (mindmapPage) {
                mindmapPage.classList.remove('hidden');
            }
            if (subjectPage) {
                subjectPage.classList.add('hidden');
            }
        }
        
        // 检查SVG容器
        const svgContainer = document.getElementById('mindmapSvg');
        if (!svgContainer) {
            log(`❌ SVG容器不存在`);
            hideLoading();
            return;
        }
        
        log(`✅ 页面状态检查通过`);
        
    } catch (error) {
        log(`❌ 页面状态检查失败: ${error.message}`);
        hideLoading();
        return;
    }
    // === 检查逻辑结束 ===
    
    showLoading();
    // ... 原有逻辑继续
}
'''
    
    print("📝 修复代码已生成")
    return fix_code

def create_debug_instructions():
    """创建调试指导"""
    print("\n📋 调试指导:")
    print("1. 在浏览器中打开开发者工具 (F12)")
    print("2. 切换到Console标签")
    print("3. 重现问题步骤:")
    print("   a. 进入脑图页面 (正常)")
    print("   b. 点击知识点查看详情 (正常)")
    print("   c. 返回科目选择页面")
    print("   d. 再次点击机器学习")
    print("4. 观察Console中的日志输出")
    
    print("\n🔍 关键日志检查:")
    print("- 是否显示: '🎯 点击了学科: 机器学习'")
    print("- 是否显示: '✅ 已进入 机器学习 脑图页面'")
    print("- 是否显示: '🧠 开始生成 机器学习 的知识脑图'")
    print("- 是否显示: '🔍 检查WebChannel连接状态'")
    print("- 是否显示: '📡 调用后端API获取脑图数据'")
    
    print("\n❌ 如果在某个步骤停止，说明问题出现在该步骤")
    
    print("\n🔧 临时解决方案:")
    print("如果问题持续存在，可以尝试:")
    print("1. 刷新整个页面 (Ctrl+F5)")
    print("2. 重启应用程序")
    print("3. 清除浏览器缓存")

if __name__ == "__main__":
    analyze_navigation_issue()
    fix_code = create_navigation_fix()
    create_debug_instructions()
    
    print(f"\n🎯 下一步行动:")
    print(f"1. 请在浏览器开发者工具中观察Console日志")
    print(f"2. 确定问题出现在哪个步骤")
    print(f"3. 根据日志信息进行针对性修复")
    print(f"4. 如需要，我可以应用上述修复代码")
