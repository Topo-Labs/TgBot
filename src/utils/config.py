import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Config:
    """配置类"""

    # Telegram Bot 配置
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

    # 数据库配置 (SQLite)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./telegram_bot.db")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./telegram_bot.db")

    # Bot 设置
    CHALLENGE_TIMEOUT: int = int(os.getenv("CHALLENGE_TIMEOUT", "300"))  # 5分钟
    MAX_CHALLENGE_ATTEMPTS: int = int(os.getenv("MAX_CHALLENGE_ATTEMPTS", "3"))
    ADMIN_USER_IDS: List[int] = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]
    GROUP_CHAT_ID: int = int(os.getenv("GROUP_CHAT_ID", "0"))

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

    # 分页设置
    MEMBERS_PER_PAGE: int = int(os.getenv("MEMBERS_PER_PAGE", "10"))
    RANKINGS_PER_PAGE: int = int(os.getenv("RANKINGS_PER_PAGE", "20"))

    @classmethod
    def validate(cls) -> bool:
        """验证配置是否完整"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.GROUP_CHAT_ID:
            raise ValueError("GROUP_CHAT_ID is required")
        return True


config = Config()