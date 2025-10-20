import json
import os
from typing import Dict, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, Language
from src.utils.database import get_db_session
from src.utils.logger import bot_logger


class LanguageService:
    """语言服务类"""

    _translations_cache: Dict[str, Dict] = {}
    _languages_cache: Dict[str, str] = {}

    @classmethod
    async def load_translations(cls):
        """从配置文件加载翻译数据"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "../../config/languages.json")
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cls._translations_cache = data.get('languages', {})

            # 同时缓存语言列表
            cls._languages_cache = {
                code: lang_data.get('name', code)
                for code, lang_data in cls._translations_cache.items()
            }

            bot_logger.info(f"Loaded translations for {len(cls._translations_cache)} languages")

        except Exception as e:
            bot_logger.error(f"Error loading translations: {e}")
            # 使用默认英语翻译
            cls._translations_cache = {
                'en': {
                    'name': 'English',
                    'welcome': 'Welcome to our group! 🎉',
                    'verification_needed': 'Please solve this math problem to verify you\'re human:',
                    'time_left': 'You have {time} minutes left to answer.',
                    'correct_answer': 'Correct! Welcome to the group! 🎉',
                    'wrong_answer': 'Incorrect answer. Try again.',
                    'verification_timeout': 'Verification timeout. You have been removed from the group.',
                    'choose_language': 'Please choose your preferred language:',
                    'language_set': 'Language set to {language}',
                    'invite_link_generated': 'Your personal invite link:',
                    'invite_stats': '📊 Invitation Statistics:\n👥 Total invited: {total}\n🚪 Left the group: {left}\n✅ Active members: {active}',
                    'invite_members_title': '📋 Invited Members (Page {page}/{total_pages}):',
                    'no_members': 'No members found.',
                    'member_status_active': '✅ {name} - Active',
                    'member_status_left': '❌ {name} - Left',
                    'ranking_title': '🏆 Invitation Rankings',
                    'ranking_total': '📈 Total Invitations',
                    'ranking_kicked': '📉 Members Who Left',
                    'ranking_active': '✅ Active Members',
                    'no_ranking_data': 'No ranking data available.',
                    'help_title': '🤖 Bot Commands Help',
                    'help_commands': '/start - Show this help\n/link - Get your invite link\n/stats - View your invitation stats\n/ranking - View invitation rankings\n/lang - Change language'
                }
            }
            cls._languages_cache = {'en': 'English'}

    @classmethod
    async def get_available_languages(cls) -> Dict[str, str]:
        """获取可用语言列表

        Returns:
            Dict[str, str]: {language_code: language_name}
        """
        if not cls._languages_cache:
            await cls.load_translations()
        return cls._languages_cache.copy()

    @classmethod
    async def get_user_language(cls, user_id: int) -> str:
        """获取用户的语言偏好

        Args:
            user_id: 用户ID

        Returns:
            str: 语言代码，默认为'en'
        """
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(User.language_code).where(User.user_id == user_id)
                )
                language_code = result.scalar_one_or_none()
                return language_code or 'en'
        except Exception as e:
            bot_logger.error(f"Error getting user language for {user_id}: {e}")
            return 'en'

    @classmethod
    async def set_user_language(cls, user_id: int, language_code: str):
        """设置用户的语言偏好

        Args:
            user_id: 用户ID
            language_code: 语言代码
        """
        try:
            # 验证语言代码是否有效
            if language_code not in cls._languages_cache:
                raise ValueError(f"Invalid language code: {language_code}")

            async with get_db_session() as session:
                # 检查用户是否存在
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()

                if user:
                    # 更新现有用户
                    user.language_code = language_code
                else:
                    # 创建新用户
                    user = User(
                        user_id=user_id,
                        language_code=language_code
                    )
                    session.add(user)

                await session.commit()
                bot_logger.info(f"Set language {language_code} for user {user_id}")

        except Exception as e:
            bot_logger.error(f"Error setting language for user {user_id}: {e}")
            raise

    @classmethod
    async def get_text(cls, user_id: int, key: str, **kwargs) -> str:
        """获取用户语言的文本

        Args:
            user_id: 用户ID
            key: 文本键
            **kwargs: 格式化参数

        Returns:
            str: 翻译后的文本
        """
        if not cls._translations_cache:
            await cls.load_translations()

        user_language = await cls.get_user_language(user_id)

        # 获取用户语言的翻译，如果不存在则使用英语
        translations = cls._translations_cache.get(user_language, cls._translations_cache.get('en', {}))

        # 获取文本，如果不存在则使用键名
        text = translations.get(key, key)

        # 格式化文本
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                bot_logger.warning(f"Missing format parameter {e} for key {key}")

        return text

    @classmethod
    async def get_text_by_language(cls, language_code: str, key: str, **kwargs) -> str:
        """根据语言代码获取文本

        Args:
            language_code: 语言代码
            key: 文本键
            **kwargs: 格式化参数

        Returns:
            str: 翻译后的文本
        """
        if not cls._translations_cache:
            await cls.load_translations()

        # 获取指定语言的翻译，如果不存在则使用英语
        translations = cls._translations_cache.get(language_code, cls._translations_cache.get('en', {}))

        # 获取文本，如果不存在则使用键名
        text = translations.get(key, key)

        # 格式化文本
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                bot_logger.warning(f"Missing format parameter {e} for key {key}")

        return text

    @classmethod
    async def sync_languages_to_db(cls):
        """同步语言数据到数据库"""
        try:
            if not cls._translations_cache:
                await cls.load_translations()

            async with get_db_session() as session:
                for code, lang_data in cls._translations_cache.items():
                    # 检查语言是否已存在
                    result = await session.execute(
                        select(Language).where(Language.code == code)
                    )
                    existing_language = result.scalar_one_or_none()

                    if existing_language:
                        # 更新现有语言
                        existing_language.name = lang_data.get('name', code)
                        existing_language.translations = json.dumps(lang_data, ensure_ascii=False)
                    else:
                        # 创建新语言
                        new_language = Language(
                            code=code,
                            name=lang_data.get('name', code),
                            translations=json.dumps(lang_data, ensure_ascii=False),
                            is_active=True
                        )
                        session.add(new_language)

                await session.commit()
                bot_logger.info("Synchronized languages to database")

        except Exception as e:
            bot_logger.error(f"Error syncing languages to database: {e}")

    @classmethod
    async def get_language_keyboard_data(cls) -> list:
        """获取语言选择键盘数据

        Returns:
            list: 适用于InlineKeyboardMarkup的数据
        """
        languages = await cls.get_available_languages()

        # 创建语言选择键盘（每行3个按钮）
        keyboard = []
        row = []
        for i, (code, name) in enumerate(languages.items()):
            row.append({'text': name, 'callback_data': f'lang_{code}'})
            if len(row) == 3 or i == len(languages) - 1:
                keyboard.append(row)
                row = []

        return keyboard