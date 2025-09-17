#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动脚本 - 运行严格复刻的界面
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from exact_replica_app import main
    
    if __name__ == "__main__":
        print("启动学习笔记助手界面...")
        print("界面已严格按照目标图片进行1:1复刻")
        main()
        
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖已安装: pip install PySide6")
except Exception as e:
    print(f"运行错误: {e}")
    import traceback
    traceback.print_exc()
