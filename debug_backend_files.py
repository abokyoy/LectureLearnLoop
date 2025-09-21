#!/usr/bin/env python3
"""
调试后端文件读取问题
验证后端是否正确读取了不同文件的内容
"""

import sys
import os
import json
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overlay_drag_corgi_app import CorgiWebBridge

def test_specific_files():
    """测试用户提到的具体文件"""
    print("🔍 调试后端文件读取问题")
    print("=" * 60)
    
    # 用户测试的两个文件
    test_files = [
        "vault/subfolder/【機器學習2021】機器學習任務攻略 纯笔记.md",
        "vault/柯基学习法.md"
    ]
    
    try:
        bridge = CorgiWebBridge()
        print("✅ Bridge对象创建成功")
        
        for i, file_path in enumerate(test_files):
            print(f"\n📄 测试文件 {i+1}: {file_path}")
            
            # 检查文件是否存在
            path = Path(file_path)
            if not path.exists():
                print(f"   ❌ 文件不存在: {path.absolute()}")
                continue
            
            print(f"   ✅ 文件存在")
            
            # 直接读取文件内容
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                print(f"   📊 文件大小: {len(content)} 字符")
                print(f"   📝 内容开头: {content[:150]}...")
                print(f"   📝 内容结尾: ...{content[-150:] if len(content) > 150 else content}")
                
                # 检查关键词
                keywords_found = []
                if "机器学习" in content or "Machine Learning" in content:
                    keywords_found.append("机器学习")
                if "柯基" in content:
                    keywords_found.append("柯基")
                if "学习法" in content:
                    keywords_found.append("学习法")
                if "线性回归" in content:
                    keywords_found.append("线性回归")
                if "梯度下降" in content:
                    keywords_found.append("梯度下降")
                
                print(f"   🔍 包含关键词: {keywords_found}")
                
            except Exception as e:
                print(f"   ❌ 直接读取失败: {e}")
                continue
            
            # 通过Bridge调用extractKnowledgePoints
            print(f"   🚀 调用Bridge.extractKnowledgePoints...")
            try:
                result_json = bridge.extractKnowledgePoints(str(path))
                print(f"   📤 Bridge返回长度: {len(result_json)} 字符")
                print(f"   📤 Bridge返回内容: {result_json}")
                
                # 解析结果
                try:
                    result = json.loads(result_json)
                    
                    if isinstance(result, list):
                        print(f"   📋 返回数组格式，包含 {len(result)} 个元素:")
                        for j, item in enumerate(result):
                            title = item.get('title', item.get('name', '未命名'))
                            content_snippet = item.get('content', item.get('description', '无内容'))
                            print(f"     {j+1}. {title}: {content_snippet}")
                    elif isinstance(result, dict):
                        if result.get("success", False):
                            points = result.get("knowledge_points", [])
                            print(f"   📋 返回对象格式，包含 {len(points)} 个知识点:")
                            for j, point in enumerate(points):
                                name = point.get('name', '未命名')
                                desc = point.get('description', '无描述')
                                print(f"     {j+1}. {name}: {desc}")
                        else:
                            error = result.get('error', '未知错误')
                            print(f"   ❌ 提取失败: {error}")
                    else:
                        print(f"   ❓ 未知格式: {type(result)}")
                        
                except json.JSONDecodeError as e:
                    print(f"   ❌ JSON解析失败: {e}")
                    print(f"   原始内容: {result_json}")
                    
            except Exception as e:
                print(f"   ❌ Bridge调用失败: {e}")
                import traceback
                traceback.print_exc()
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

def compare_file_contents():
    """比较两个文件的内容差异"""
    print("\n🔍 比较文件内容差异")
    print("=" * 60)
    
    files = [
        "vault/subfolder/【機器學習2021】機器學習任務攻略 纯笔记.md",
        "vault/柯基学习法.md"
    ]
    
    contents = []
    
    for file_path in files:
        path = Path(file_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                contents.append((file_path, content))
                print(f"📄 {path.name}: {len(content)} 字符")
            except Exception as e:
                print(f"❌ 读取 {file_path} 失败: {e}")
        else:
            print(f"❌ 文件不存在: {file_path}")
    
    if len(contents) == 2:
        file1_path, file1_content = contents[0]
        file2_path, file2_content = contents[1]
        
        print(f"\n📊 内容对比:")
        print(f"文件1长度: {len(file1_content)} 字符")
        print(f"文件2长度: {len(file2_content)} 字符")
        print(f"内容相同: {file1_content == file2_content}")
        
        if file1_content == file2_content:
            print("⚠️ 两个文件内容完全相同！这可能是问题的原因。")
        else:
            print("✅ 两个文件内容不同，应该产生不同的知识点。")

def main():
    """主函数"""
    print("🚀 开始后端文件读取调试")
    print("=" * 80)
    
    # 比较文件内容
    compare_file_contents()
    
    # 测试具体文件
    test_specific_files()
    
    print("\n📋 调试完成")
    print("=" * 80)

if __name__ == "__main__":
    main()
