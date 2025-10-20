from loguru import logger
import sys
from src.utils.config import config


def setup_logger():
    """设置日志配置"""
    logger.remove()  # 移除默认handler

    # 控制台输出
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=config.LOG_LEVEL
    )

    # 文件输出
    logger.add(
        f"logs/{config.LOG_FILE}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=config.LOG_LEVEL
    )

    return logger


# 全局logger实例
bot_logger = setup_logger()