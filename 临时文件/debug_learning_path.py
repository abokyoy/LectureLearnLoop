#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
调试学习路径功能
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def debug_learning_path():
    """调试学习路径功能"""
    print("🔍 调试学习路径功能")
    print("=" * 50)
    
    try:
        # 导入必要的模块
        from overlay_drag_corgi_app import CorgiWebBridge
        from knowledge_management import KnowledgeManagementSystem
        
        # 模拟配置
        config = {
            "llm_provider": "DeepSeek",
            "deepseek_api_key": "sk-test",  # 使用测试密钥
            "deepseek_model": "deepseek-chat"
        }
        
        print("✅ 模块导入成功")
        
        # 创建WebBridge实例
        bridge = CorgiWebBridge()
        bridge.config = config
        print("✅ CorgiWebBridge 创建成功")
        
        # 测试学习路径API
        print(f"\n🧪 测试学习路径API...")
        subject_name = "机器学习"
        
        try:
            result = bridge.getOrGenerateLearningPath(subject_name)
            print(f"📡 API返回结果长度: {len(result)}")
            print(f"📡 API返回结果预览: {result[:200]}...")
            
            # 解析结果
            result_data = json.loads(result)
            if result_data.get("success"):
                print(f"✅ 学习路径生成成功")
                learning_path = result_data.get("learningPath", {})
                data = learning_path.get("data", {})
                nodes = data.get("nodes", [])
                edges = data.get("edges", [])
                print(f"   节点数: {len(nodes)}")
                print(f"   边数: {len(edges)}")
            else:
                print(f"❌ 学习路径生成失败: {result_data.get('error', 'Unknown error')}")
                
        except Exception as api_error:
            print(f"❌ API调用异常: {api_error}")
            import traceback
            traceback.print_exc()
        
        print(f"\n✅ 调试完成")
        
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_learning_path()
