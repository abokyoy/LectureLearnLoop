#!/usr/bin/env python3
"""
TUI Editor 本地资源下载脚本
下载 @toast-ui/editor 的必要文件到本地 static 目录
"""

import os
import requests
import json
from pathlib import Path

# 基础配置
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TUI_EDITOR_VERSION = "3.2.2"  # 使用稳定版本

# 需要下载的文件列表
FILES_TO_DOWNLOAD = {
    # CSS 文件
    "css": [
        {
            "url": f"https://cdn.jsdelivr.net/npm/@toast-ui/editor@{TUI_EDITOR_VERSION}/dist/toastui-editor.min.css",
            "path": "css/tui-editor/toastui-editor.min.css"
        },
        {
            "url": f"https://cdn.jsdelivr.net/npm/@toast-ui/editor@{TUI_EDITOR_VERSION}/dist/theme/toastui-editor-dark.min.css",
            "path": "css/tui-editor/toastui-editor-dark.min.css"
        }
    ],
    # JavaScript 文件
    "js": [
        {
            "url": f"https://cdn.jsdelivr.net/npm/@toast-ui/editor@{TUI_EDITOR_VERSION}/dist/toastui-editor.min.js",
            "path": "js/tui-editor/toastui-editor.min.js"
        }
    ]
}

def download_file(url, local_path):
    """下载单个文件"""
    try:
        print(f"📥 下载: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # 确保目录存在
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(local_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ 保存到: {local_path}")
        return True
        
    except Exception as e:
        print(f"❌ 下载失败 {url}: {e}")
        return False

def main():
    """主函数"""
    print("🚀 开始下载 TUI Editor 本地资源...")
    print(f"📁 目标目录: {STATIC_DIR}")
    print(f"📦 版本: {TUI_EDITOR_VERSION}")
    print("-" * 50)
    
    success_count = 0
    total_count = 0
    
    # 下载所有文件
    for category, files in FILES_TO_DOWNLOAD.items():
        print(f"\n📂 下载 {category.upper()} 文件:")
        
        for file_info in files:
            total_count += 1
            url = file_info["url"]
            local_path = STATIC_DIR / file_info["path"]
            
            if download_file(url, local_path):
                success_count += 1
    
    # 下载完成统计
    print("\n" + "=" * 50)
    print(f"📊 下载完成: {success_count}/{total_count} 个文件")
    
    if success_count == total_count:
        print("🎉 所有文件下载成功！")
        
        # 创建配置文件
        create_config_file()
        
        # 显示下一步提示
        print_next_steps()
    else:
        print("⚠️  部分文件下载失败，请检查网络连接")

def create_config_file():
    """创建 TUI Editor 配置文件"""
    config = {
        "version": TUI_EDITOR_VERSION,
        "files": {
            "css": [
                "/static/css/tui-editor/toastui-editor.min.css"
            ],
            "js": [
                "/static/js/tui-editor/toastui-editor-all.min.js"
            ]
        },
        "cdn_fallback": {
            "css": f"https://cdn.jsdelivr.net/npm/@toast-ui/editor@{TUI_EDITOR_VERSION}/dist/toastui-editor.min.css",
            "js": f"https://cdn.jsdelivr.net/npm/@toast-ui/editor@{TUI_EDITOR_VERSION}/dist/toastui-editor-all.min.js"
        }
    }
    
    config_path = STATIC_DIR / "tui-editor-config.json"
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"📝 配置文件已创建: {config_path}")

def print_next_steps():
    """显示下一步操作提示"""
    print("\n🎯 下一步操作:")
    print("1. 运行集成脚本: python integrate_tui_editor.py")
    print("2. 或者手动修改 online_course_notes.html")
    print("3. 测试编辑器功能")

if __name__ == "__main__":
    main()
