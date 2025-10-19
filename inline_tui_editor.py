#!/usr/bin/env python3
"""
TUI Editor 内联集成脚本
将 TUI Editor 的 CSS 和 JS 内容直接内联到 HTML 中
避免静态文件路径问题
"""

import os
from pathlib import Path

# 配置
BASE_DIR = Path(__file__).parent
TEMPLATE_PATH = BASE_DIR / "templates" / "pages" / "online_course_notes.html"
STATIC_DIR = BASE_DIR / "static"

def read_static_file(relative_path):
    """读取静态文件内容"""
    file_path = STATIC_DIR / relative_path
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        print(f"⚠️ 静态文件不存在: {file_path}")
        return ""

def inline_tui_editor_resources():
    """将 TUI Editor 资源内联到 HTML 中"""
    
    # 读取模板文件
    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 读取 TUI Editor 文件
    css_content = read_static_file("css/tui-editor/toastui-editor.min.css")
    js_content = read_static_file("js/tui-editor/toastui-editor.min.js")
    
    if not css_content or not js_content:
        print("❌ 无法读取 TUI Editor 文件，请先运行 download_tui_editor.py")
        return False
    
    # 替换外部引用为内联内容
    # 替换 CSS 链接
    css_link = '<link rel="stylesheet" href="/static/css/tui-editor/toastui-editor.min.css">'
    css_inline = f'<style>\n/* TUI Editor CSS */\n{css_content}\n</style>'
    content = content.replace(css_link, css_inline)
    
    # 替换 JS 链接
    js_link = '<script src="/static/js/tui-editor/toastui-editor.min.js"></script>'
    js_inline = f'<script>\n/* TUI Editor JS */\n{js_content}\n</script>'
    content = content.replace(js_link, js_inline)
    
    # 写回文件
    with open(TEMPLATE_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ TUI Editor 资源已内联到 HTML 中")
    return True

def main():
    """主函数"""
    print("🚀 开始内联 TUI Editor 资源...")
    
    if inline_tui_editor_resources():
        print("🎉 内联完成！现在可以重启应用测试了。")
    else:
        print("❌ 内联失败，请检查文件是否存在。")

if __name__ == "__main__":
    main()
