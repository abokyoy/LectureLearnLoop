#!/usr/bin/env python3
"""
后端功能验证脚本
直接测试所有文件操作功能，不依赖GUI界面
"""

import sys
import os
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入必要的模块
from overlay_drag_corgi_app import CorgiWebBridge

def main():
    """主验证函数"""
    print("🚀 开始后端功能验证")
    print("=" * 80)
    
    # 创建bridge对象
    try:
        bridge = CorgiWebBridge()
        print("✅ Bridge对象创建成功")
    except Exception as e:
        print(f"❌ Bridge对象创建失败: {e}")
        return
    
    # 执行验证
    try:
        print("\n🔍 开始执行后端功能验证...")
        result = bridge.validateAllFileOperations()
        
        print("\n" + "=" * 80)
        print("📋 验证结果:")
        print("=" * 80)
        print(result)
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ 验证过程中发生异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
