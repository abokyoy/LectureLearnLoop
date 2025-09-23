#!/usr/bin/env python3
"""
练习历史数据库初始化脚本
用于创建数据库表结构并迁移现有的JSON数据
"""
import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from services.practice_service import PracticeService

def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('database_init.log', encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)

def main():
    """主函数"""
    logger = setup_logging()
    logger.info("🚀 开始初始化练习历史数据库...")
    
    try:
        # 初始化练习服务（会自动创建数据库表）
        practice_service = PracticeService()
        logger.info("✅ 数据库表结构创建完成")
        
        # 检查是否需要迁移JSON文件
        json_dir = project_root / "practice_sessions"
        if json_dir.exists():
            json_files = list(json_dir.glob("*.json"))
            if json_files:
                logger.info(f"📁 发现 {len(json_files)} 个JSON文件，开始数据迁移...")
                
                # 执行数据迁移
                migration_result = practice_service.migrate_from_json_files(str(json_dir))
                
                if migration_result["success"]:
                    migrated_count = migration_result["migrated_count"]
                    logger.info(f"✅ 数据迁移完成：{migrated_count} 条记录")
                else:
                    logger.error(f"❌ 数据迁移失败：{migration_result['error']}")
            else:
                logger.info("📂 JSON目录为空，无需迁移数据")
        else:
            logger.info("📂 JSON目录不存在，无需迁移数据")
        
        # 获取统计信息
        stats_result = practice_service.get_practice_statistics()
        if stats_result["success"]:
            stats = stats_result["statistics"]
            logger.info("📊 数据库统计信息：")
            logger.info(f"   - 总练习数：{stats['total_practices']}")
            logger.info(f"   - 已评估练习数：{stats['evaluated_practices']}")
            logger.info(f"   - 平均提交次数：{stats['avg_submissions_per_practice']}")
            logger.info(f"   - 平均最佳分数：{stats['avg_best_score']}")
        
        # 测试获取练习历史
        history_result = practice_service.get_practice_history_list(limit=5)
        if history_result["success"]:
            practices = history_result["practices"]
            logger.info(f"🎯 成功获取到 {len(practices)} 条练习历史记录")
            
            if practices:
                logger.info("📋 最近的练习记录：")
                for i, practice in enumerate(practices[:3], 1):
                    logger.info(f"   {i}. ID: {practice['id']}, 状态: {practice['status']}, 时间: {practice['timestamp']}")
        
        logger.info("🎉 数据库初始化完成！")
        return True
        
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败：{e}")
        import traceback
        logger.error(f"错误详情：{traceback.format_exc()}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)