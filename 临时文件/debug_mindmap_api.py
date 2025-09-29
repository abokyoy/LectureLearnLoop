#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_mindmap_api():
    """测试脑图API功能"""
    print("🧪 开始测试脑图API功能...")
    
    try:
        # 导入必要的模块
        from knowledge_management import KnowledgeManagementSystem
        from config import Config
        
        # 初始化配置和系统
        config = Config()
        km_system = KnowledgeManagementSystem(config)
        
        # 测试学科
        test_subjects = ["机器学习", "数据结构", "Python编程"]
        
        for subject_name in test_subjects:
            print(f"\n📊 测试学科: {subject_name}")
            print("-" * 50)
            
            # 1. 检查知识点数据
            try:
                conn = km_system.db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM knowledge_points WHERE subject_name = ?",
                    (subject_name,)
                )
                kp_count = cursor.fetchone()[0]
                print(f"📋 知识点数量: {kp_count}")
                
                if kp_count == 0:
                    print(f"⚠️ 学科 '{subject_name}' 没有知识点数据")
                    conn.close()
                    continue
                
                # 获取前5个知识点
                cursor.execute(
                    "SELECT id, point_name, mastery_score FROM knowledge_points WHERE subject_name = ? LIMIT 5",
                    (subject_name,)
                )
                sample_points = cursor.fetchall()
                print("📝 示例知识点:")
                for point in sample_points:
                    print(f"  - ID:{point[0]} | {point[1]} | 熟练度:{point[2]}")
                
                conn.close()
                
            except Exception as e:
                print(f"❌ 查询知识点失败: {e}")
                continue
            
            # 2. 测试脑图生成
            try:
                print(f"\n🧠 测试脑图生成...")
                mindmap = km_system.generate_or_get_mindmap(subject_name)
                
                if mindmap:
                    print(f"✅ 脑图生成成功")
                    print(f"📊 版本: {mindmap.get('version', 'N/A')}")
                    print(f"📅 更新时间: {mindmap.get('updated_time', 'N/A')}")
                    print(f"💾 缓存状态: {mindmap.get('cache_status', 'N/A')}")
                    
                    # 检查数据结构
                    data = mindmap.get('data', {})
                    nodes = data.get('nodes', [])
                    edges = data.get('edges', [])
                    
                    print(f"🔢 节点数: {len(nodes)}")
                    print(f"🔗 边数: {len(edges)}")
                    
                    # 检查知识点节点
                    kp_nodes = [n for n in nodes if n.get('type') == 'knowledge_point']
                    print(f"📍 知识点节点数: {len(kp_nodes)}")
                    
                    if kp_nodes:
                        print("📝 前3个知识点节点:")
                        for i, node in enumerate(kp_nodes[:3]):
                            print(f"  {i+1}. ID:{node.get('id')} | {node.get('name')} | 熟练度:{node.get('mastery_score', 'N/A')}")
                    
                    # 验证数据格式
                    required_fields = ['nodes', 'edges']
                    missing_fields = [field for field in required_fields if field not in data]
                    if missing_fields:
                        print(f"⚠️ 缺少必要字段: {missing_fields}")
                    else:
                        print("✅ 数据格式验证通过")
                    
                else:
                    print(f"❌ 脑图生成失败")
                
            except Exception as e:
                print(f"❌ 脑图生成异常: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n🎉 API测试完成！")
        
    except ImportError as e:
        print(f"❌ 模块导入失败: {e}")
        print("请确保所有依赖模块都已正确安装")
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_api_response_format():
    """测试API响应格式"""
    print("\n🔍 测试API响应格式...")
    
    try:
        from overlay_drag_corgi_app import OverlayDragCorgiApp
        from config import Config
        
        # 创建应用实例
        config = Config()
        app = OverlayDragCorgiApp(config)
        
        # 测试API调用
        subject_name = "机器学习"
        response = app.getOrGenerateMindmap(subject_name)
        
        print(f"📡 API响应长度: {len(response)}")
        print(f"📄 API响应预览: {response[:200]}...")
        
        # 解析响应
        try:
            result = json.loads(response)
            print(f"✅ JSON解析成功")
            print(f"🔑 响应字段: {list(result.keys())}")
            
            if result.get('success'):
                mindmap = result.get('mindmap', {})
                print(f"📊 脑图字段: {list(mindmap.keys())}")
                
                data = mindmap.get('data', {})
                if data:
                    print(f"📋 数据字段: {list(data.keys())}")
                    print(f"🔢 节点数: {len(data.get('nodes', []))}")
                    print(f"🔗 边数: {len(data.get('edges', []))}")
                else:
                    print("⚠️ 脑图数据为空")
            else:
                print(f"❌ API返回失败: {result.get('error', 'Unknown error')}")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            
    except Exception as e:
        print(f"❌ API测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 脑图API调试工具")
    print("=" * 60)
    
    test_mindmap_api()
    test_api_response_format()
