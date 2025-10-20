from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from contextlib import asynccontextmanager
from src.utils.config import config
from src.utils.logger import bot_logger
from src.models import Base

# 创建异步引擎 (SQLite)
engine = create_async_engine(
    config.DATABASE_URL,
    poolclass=NullPool,
    echo=False
)

# 创建会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_database():
    """初始化数据库表"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        bot_logger.info("Database tables created successfully")
    except Exception as e:
        bot_logger.error(f"Failed to create database tables: {e}")
        raise


@asynccontextmanager
async def get_db_session():
    """获取数据库会话的上下文管理器"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            bot_logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


async def close_database():
    """关闭数据库连接"""
    await engine.dispose()
    bot_logger.info("Database connections closed")