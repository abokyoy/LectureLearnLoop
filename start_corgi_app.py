#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
柯基学习小助手 - 启动脚本
轻松活泼的卡通化风格学习笔记软件
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    try:
        print("🐕 正在启动柯基学习小助手...")
        print("=" * 50)
        print("🌟 特色功能：")
        print("   • 轻松活泼的卡通化风格界面")
        print("   • 浅绿米白等低饱和度配色")
        print("   • 明显的圆角设计，柔和舒适")
        print("   • 可爱的柯基犬元素装饰")
        print("   • 爪印、骨头等宠物相关图形")
        print("   • 类似休闲游戏的视觉体验")
        print("=" * 50)
        
        from exact_replica_app import main as run_app
        run_app()
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("💡 请确保已安装 PySide6: pip install PySide6")
    except Exception as e:
        print(f"❌ 运行错误: {e}")
        import traceback
        traceback.print_exc()
        input("按回车键退出...")

if __name__ == "__main__":
    main()
