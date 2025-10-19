#!/usr/bin/env python3
"""
TUI Editor 集成脚本
将 TUI Editor 无缝集成到网课学习页面中，替换现有的 textarea 编辑器
保持现有的三栏布局和所有功能不变
"""

import os
import re
from pathlib import Path

# 配置
BASE_DIR = Path(__file__).parent
TEMPLATE_PATH = BASE_DIR / "templates" / "pages" / "online_course_notes.html"
BACKUP_PATH = BASE_DIR / "templates" / "pages" / "online_course_notes_backup.html"

def backup_original_file():
    """备份原始文件"""
    if TEMPLATE_PATH.exists():
        import shutil
        shutil.copy2(TEMPLATE_PATH, BACKUP_PATH)
        print(f"✅ 原始文件已备份到: {BACKUP_PATH}")
        return True
    else:
        print(f"❌ 找不到模板文件: {TEMPLATE_PATH}")
        return False

def read_template():
    """读取模板文件"""
    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()

def write_template(content):
    """写入模板文件"""
    with open(TEMPLATE_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

def add_tui_editor_resources(content):
    """添加 TUI Editor 的 CSS 和 JS 资源"""
    
    # 在 head 部分添加 TUI Editor CSS
    css_insert = '''
<!-- TUI Editor 本地资源 -->
<link rel="stylesheet" href="/static/css/tui-editor/toastui-editor.min.css">
<script src="/static/js/tui-editor/toastui-editor.min.js"></script>

<!-- TUI Editor 自定义样式 -->
<style>
    /* TUI Editor 容器样式 */
    #tui-editor-container {
        width: 100%;
        height: 100%;
        min-height: 500px;
    }
    
    /* 确保编辑器适应容器 */
    .toastui-editor-defaultUI {
        border: 1px solid #d1d5db;
        border-radius: 0.5rem;
    }
    
    /* 编辑器工具栏样式 */
    .toastui-editor-toolbar {
        border-bottom: 1px solid #e5e7eb;
        background-color: #f9fafb;
    }
    
    /* 预览模式样式适配 */
    .toastui-editor-preview {
        padding: 1rem;
    }
    
    /* 隐藏传统编辑器 */
    #edit-content.hidden-by-tui {
        display: none !important;
    }
    
    /* TUI Editor 在编辑模式下的显示 */
    #tui-editor-container.edit-mode {
        display: block !important;
    }
    
    #tui-editor-container.preview-mode {
        display: none !important;
    }
</style>'''
    
    # 在 Material Icons 之后插入
    content = content.replace(
        '<!-- Material Icons 字体 - 直接引用 -->\n<link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined">',
        '<!-- Material Icons 字体 - 直接引用 -->\n<link rel="stylesheet" href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined">' + css_insert
    )
    
    return content

def replace_textarea_with_tui_editor(content):
    """将 textarea 替换为 TUI Editor 容器"""
    
    # 找到原始的 textarea
    textarea_pattern = r'<textarea id="edit-content"[^>]*>.*?</textarea>'
    
    # TUI Editor 容器
    tui_editor_html = '''<textarea id="edit-content" class="w-full h-full border border-gray-300 rounded-lg p-4 font-mono text-sm resize-none hidden" placeholder="在此编辑Markdown内容..."></textarea>
                <div id="tui-editor-container" class="w-full h-full hidden"></div>'''
    
    # 替换
    content = re.sub(textarea_pattern, tui_editor_html, content, flags=re.DOTALL)
    
    return content

def add_tui_editor_javascript(content):
    """添加 TUI Editor 的 JavaScript 初始化代码"""
    
    js_code = '''
// TUI Editor 全局变量
let tuiEditor = null;
let isTuiEditorMode = false;

// 初始化 TUI Editor
function initTuiEditor(initialContent = '') {
    console.log('🎯 初始化 TUI Editor...');
    
    try {
        // 销毁现有编辑器
        if (tuiEditor) {
            tuiEditor.destroy();
            tuiEditor = null;
        }
        
        const container = document.getElementById('tui-editor-container');
        if (!container) {
            console.error('❌ TUI Editor 容器未找到');
            return false;
        }
        
        // 清空容器
        container.innerHTML = '';
        
        // 创建 TUI Editor 实例
        tuiEditor = new toastui.Editor({
            el: container,
            previewStyle: 'tab', // 'tab' 或 'vertical'
            height: 'calc(100vh - 200px)',
            initialValue: initialContent || '',
            initialEditType: 'markdown',
            useCommandShortcut: true,
            usageStatistics: false,
            toolbarItems: [
                ['heading', 'bold', 'italic', 'strike'],
                ['hr', 'quote'],
                ['ul', 'ol', 'task', 'indent', 'outdent'],
                ['table', 'image', 'link'],
                ['code', 'codeblock'],
                ['scrollSync']
            ],
            events: {
                change: function() {
                    // 标记内容已修改
                    if (window.UnsavedChangesGuard) {
                        window.UnsavedChangesGuard.markAsModified();
                    }
                    hasUnsavedChanges = true;
                    showUnsavedIndicator();
                }
            }
        });
        
        console.log('✅ TUI Editor 初始化成功');
        isTuiEditorMode = true;
        return true;
        
    } catch (error) {
        console.error('❌ TUI Editor 初始化失败:', error);
        return false;
    }
}

// 获取 TUI Editor 内容
function getTuiEditorContent() {
    if (tuiEditor && isTuiEditorMode) {
        return tuiEditor.getMarkdown();
    }
    return '';
}

// 设置 TUI Editor 内容
function setTuiEditorContent(content) {
    if (tuiEditor && isTuiEditorMode) {
        tuiEditor.setMarkdown(content || '');
    }
}

// 切换到 TUI Editor 模式
function switchToTuiEditor() {
    const container = document.getElementById('tui-editor-container');
    const textarea = document.getElementById('edit-content');
    
    if (container && textarea) {
        // 隐藏传统编辑器
        textarea.classList.add('hidden-by-tui');
        
        // 显示 TUI Editor
        container.classList.remove('hidden');
        container.classList.add('edit-mode');
        
        // 如果还没有初始化，则初始化
        if (!tuiEditor) {
            const content = textarea.value || '';
            initTuiEditor(content);
        }
        
        console.log('✅ 已切换到 TUI Editor 模式');
    }
}

// 切换到预览模式
function switchToPreviewMode() {
    const container = document.getElementById('tui-editor-container');
    const textarea = document.getElementById('edit-content');
    
    if (container && textarea) {
        // 隐藏 TUI Editor
        container.classList.add('hidden');
        container.classList.remove('edit-mode');
        
        // 显示传统编辑器（但实际上会被预览内容替代）
        textarea.classList.remove('hidden-by-tui');
        
        console.log('✅ 已切换到预览模式');
    }
}

// 修改原有的编辑模式切换函数
const originalToggleEditMode = window.toggleEditMode;
window.toggleEditMode = function() {
    console.log('🔄 切换编辑模式，当前状态:', isEditMode);
    
    if (!isEditMode) {
        // 切换到编辑模式
        switchToTuiEditor();
        isEditMode = true;
        
        // 更新UI
        document.getElementById('preview-content').classList.add('hidden');
        document.getElementById('save-btn').classList.remove('hidden');
        
        // 更新按钮状态
        const editBtn = document.getElementById('edit-btn');
        const previewBtn = document.getElementById('preview-btn');
        if (editBtn && previewBtn) {
            editBtn.classList.add('bg-primary', 'text-white');
            editBtn.classList.remove('text-gray-600');
            previewBtn.classList.remove('bg-primary', 'text-white');
            previewBtn.classList.add('text-gray-600');
        }
        
        console.log('✅ 已切换到 TUI Editor 编辑模式');
    } else {
        // 切换到预览模式
        switchToPreviewMode();
        isEditMode = false;
        
        // 更新UI
        document.getElementById('preview-content').classList.remove('hidden');
        document.getElementById('save-btn').classList.add('hidden');
        
        // 更新按钮状态
        const editBtn = document.getElementById('edit-btn');
        const previewBtn = document.getElementById('preview-btn');
        if (editBtn && previewBtn) {
            previewBtn.classList.add('bg-primary', 'text-white');
            previewBtn.classList.remove('text-gray-600');
            editBtn.classList.remove('bg-primary', 'text-white');
            editBtn.classList.add('text-gray-600');
        }
        
        console.log('✅ 已切换到预览模式');
    }
};

// 修改保存函数以支持 TUI Editor
const originalSaveFile = window.saveFile;
window.saveFile = function() {
    console.log('💾 保存文件，TUI Editor 模式:', isTuiEditorMode);
    
    if (isTuiEditorMode && tuiEditor) {
        // 从 TUI Editor 获取内容
        const content = getTuiEditorContent();
        
        // 同步到传统 textarea（保持兼容性）
        const textarea = document.getElementById('edit-content');
        if (textarea) {
            textarea.value = content;
        }
        
        console.log('📝 TUI Editor 内容已同步到 textarea');
    }
    
    // 调用原始保存函数
    if (originalSaveFile) {
        return originalSaveFile();
    }
};

// 在文件加载时初始化 TUI Editor
const originalLoadFileForEdit = window.loadFileForEdit;
window.loadFileForEdit = function(filePath) {
    console.log('📂 加载文件进行编辑:', filePath);
    
    // 调用原始加载函数
    if (originalLoadFileForEdit) {
        const result = originalLoadFileForEdit(filePath);
        
        // 延迟初始化 TUI Editor
        setTimeout(() => {
            const textarea = document.getElementById('edit-content');
            if (textarea && textarea.value) {
                initTuiEditor(textarea.value);
                console.log('📝 TUI Editor 已加载文件内容');
            }
        }, 500);
        
        return result;
    }
};

console.log('🎯 TUI Editor 集成脚本已加载');
'''
    
    # 在文件末尾的 </script> 标签前插入
    script_end_pattern = r'(console\.log\(\'🎯.*?\'\);?\s*</script>\s*</body>)'
    replacement = js_code + r'\n\1'
    
    if re.search(script_end_pattern, content, re.DOTALL):
        content = re.sub(script_end_pattern, replacement, content, flags=re.DOTALL)
    else:
        # 如果找不到特定模式，在最后一个 </script> 前插入
        last_script_pattern = r'(</script>\s*(?=.*</body>))'
        content = re.sub(last_script_pattern, js_code + r'\n\1', content, flags=re.DOTALL)
    
    return content

def main():
    """主集成函数"""
    print("🚀 开始集成 TUI Editor...")
    print(f"📁 目标文件: {TEMPLATE_PATH}")
    print("-" * 50)
    
    # 1. 备份原始文件
    if not backup_original_file():
        return False
    
    # 2. 读取模板内容
    print("📖 读取模板文件...")
    content = read_template()
    
    # 3. 添加 TUI Editor 资源
    print("📦 添加 TUI Editor 资源...")
    content = add_tui_editor_resources(content)
    
    # 4. 替换 textarea 为 TUI Editor 容器
    print("🔄 替换编辑器容器...")
    content = replace_textarea_with_tui_editor(content)
    
    # 5. 添加 JavaScript 集成代码
    print("⚙️ 添加 JavaScript 集成代码...")
    content = add_tui_editor_javascript(content)
    
    # 6. 写入修改后的文件
    print("💾 保存修改后的文件...")
    write_template(content)
    
    print("\n" + "=" * 50)
    print("🎉 TUI Editor 集成完成！")
    print("\n📋 集成内容:")
    print("✅ 添加了 TUI Editor CSS 和 JS 资源")
    print("✅ 替换了传统 textarea 编辑器")
    print("✅ 保持了现有的三栏布局")
    print("✅ 集成了编辑/预览模式切换")
    print("✅ 保持了保存功能兼容性")
    print("✅ 保持了文件加载功能")
    
    print("\n🎯 下一步:")
    print("1. 重启应用程序")
    print("2. 打开网课学习页面")
    print("3. 选择一个 Markdown 文件")
    print("4. 点击编辑按钮测试 TUI Editor")
    
    print(f"\n💡 如需恢复原版本，请使用: {BACKUP_PATH}")
    
    return True

if __name__ == "__main__":
    main()
