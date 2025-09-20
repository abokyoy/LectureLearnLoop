#!/usr/bin/env python3
"""
专门调试Bridge类的extractKnowledgePoints方法
"""

import sys
import os
import json
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_bridge_method():
    """测试Bridge的extractKnowledgePoints方法"""
    print("🔍 调试Bridge的extractKnowledgePoints方法")
    print("=" * 60)
    
    try:
        from overlay_drag_corgi_app import CorgiWebBridge
        
        # 创建Bridge对象
        bridge = CorgiWebBridge()
        print("✅ Bridge对象创建成功")
        
        # 查找测试文件
        vault_path = Path("vault")
        md_files = list(vault_path.glob("**/*.md"))
        if not md_files:
            print("❌ 未找到测试文件")
            return False
        
        test_file = md_files[0]
        print(f"📄 使用测试文件: {test_file}")
        
        # 直接调用_extract_knowledge_with_llm方法进行调试
        print("\n🔬 直接测试_extract_knowledge_with_llm方法")
        
        # 读取文件内容
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"文件内容长度: {len(content)} 字符")
        
        # 调用内部方法
        result = bridge._extract_knowledge_with_llm(content)
        
        print(f"✅ _extract_knowledge_with_llm调用成功")
        print(f"返回结果类型: {type(result)}")
        print(f"返回结果: {result}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_bridge_method()
