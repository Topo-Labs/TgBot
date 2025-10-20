import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, Challenge
from src.utils.database import get_db_session
from src.utils.config import config
from src.utils.logger import bot_logger


class AuthService:
    """认证服务类，处理用户验证相关功能"""

    @staticmethod
    async def generate_math_challenge() -> Dict:
        """生成图形数学验证码 - 4选1格式

        Returns:
            Dict: 包含问题、正确答案、选项和图片数据的字典
        """
        from src.services.captcha_service import CaptchaService

        try:
            # 生成图形验证码
            captcha_data = await CaptchaService.generate_captcha()

            # 生成正确答案和3个错误选项
            correct_answer = int(captcha_data['answer'])
            wrong_options = AuthService._generate_wrong_options(correct_answer)

            # 随机选择正确答案的位置（A, B, C, D）
            import random
            correct_position = random.randint(0, 3)
            option_letters = ['A', 'B', 'C', 'D']
            correct_letter = option_letters[correct_position]

            # 创建最终选项列表，将正确答案放在指定位置
            final_options = wrong_options.copy()
            final_options.insert(correct_position, correct_answer)

            # 确保只有4个选项
            final_options = final_options[:4]

            return {
                'question': captcha_data['question'],
                'correct_answer': correct_letter,  # 现在是A、B、C、D
                'correct_number': correct_answer,  # 保留数字答案用于日志
                'options': final_options,
                'image_data': captcha_data['image_data']
            }

        except Exception as e:
            bot_logger.error(f"Error generating captcha challenge: {e}")
            # 备用简单数学题
            return {
                'question': "2 + 3 = ?",
                'correct_answer': "A",
                'correct_number': 5,
                'options': [5, 7, 3, 8],
                'image_data': b''
            }

    @staticmethod
    def _generate_wrong_options(correct_answer: int) -> List[int]:
        """生成3个错误答案选项

        Args:
            correct_answer: 正确答案

        Returns:
            List[int]: 包含3个错误选项的列表
        """
        import random

        wrong_options = []

        # 生成3个不同的错误答案
        while len(wrong_options) < 3:
            # 生成在正确答案附近的错误选项
            if correct_answer <= 10:
                # 小数字：在±5范围内生成
                wrong_answer = correct_answer + random.randint(-5, 5)
            elif correct_answer <= 50:
                # 中等数字：在±15范围内生成
                wrong_answer = correct_answer + random.randint(-15, 15)
            else:
                # 大数字：在±30范围内生成
                wrong_answer = correct_answer + random.randint(-30, 30)

            # 确保错误答案是正数、不等于正确答案、且不重复
            if wrong_answer > 0 and wrong_answer != correct_answer and wrong_answer not in wrong_options:
                wrong_options.append(wrong_answer)

        return wrong_options

    @staticmethod
    def _generate_answer_options(correct_answer: int) -> List[int]:
        """生成4个答案选项，包含1个正确答案和3个错误答案

        Args:
            correct_answer: 正确答案

        Returns:
            List[int]: 包含4个选项的列表
        """
        import random

        options = [correct_answer]

        # 生成3个不同的错误答案
        while len(options) < 4:
            # 生成在正确答案附近的错误选项
            if correct_answer <= 10:
                # 小数字：在±5范围内生成
                wrong_answer = correct_answer + random.randint(-5, 5)
            elif correct_answer <= 50:
                # 中等数字：在±15范围内生成
                wrong_answer = correct_answer + random.randint(-15, 15)
            else:
                # 大数字：在±30范围内生成
                wrong_answer = correct_answer + random.randint(-30, 30)

            # 确保错误答案是正数且不重复
            if wrong_answer > 0 and wrong_answer not in options:
                options.append(wrong_answer)

        # 打乱顺序（除了第一个正确答案，它会被后面重新放置）
        wrong_options = options[1:]
        random.shuffle(wrong_options)

        return [correct_answer] + wrong_options

    @staticmethod
    async def create_challenge(user_id: int, challenge_data: Dict) -> Challenge:
        """为用户创建验证挑战

        Args:
            user_id: 用户ID
            challenge_data: 挑战数据字典

        Returns:
            Challenge: 创建的挑战对象
        """
        expires_at = datetime.utcnow() + timedelta(seconds=config.CHALLENGE_TIMEOUT)

        async with get_db_session() as session:
            # 删除用户之前未完成的挑战
            existing_challenges = await session.execute(
                select(Challenge).where(
                    and_(
                        Challenge.user_id == user_id,
                        Challenge.is_solved == False
                    )
                )
            )
            for challenge in existing_challenges.scalars():
                await session.delete(challenge)

            # 序列化选项为JSON
            import json
            options_json = json.dumps(challenge_data.get('options', []))

            # 创建新挑战
            challenge = Challenge(
                user_id=user_id,
                question=challenge_data['question'],
                correct_answer=challenge_data['correct_answer'],
                options=options_json,  # 存储选项
                image_data=challenge_data.get('image_data'),  # 存储图片数据
                expires_at=expires_at,
                attempts=0  # 初始化尝试次数
            )
            session.add(challenge)
            await session.commit()
            await session.refresh(challenge)

            bot_logger.info(f"Created 4-choice captcha challenge for user {user_id}: {challenge_data['question']} (correct: {challenge_data['correct_answer']})")
            return challenge

    @staticmethod
    async def verify_answer(challenge_id: int, user_answer: str) -> Tuple[bool, int, bool]:
        """验证用户答案 - 仅一次机会

        Args:
            challenge_id: 挑战ID
            user_answer: 用户答案

        Returns:
            Tuple[bool, int, bool]: (是否正确, 剩余尝试次数, 是否过期)
        """
        async with get_db_session() as session:
            # 获取挑战
            result = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            challenge = result.scalar_one_or_none()

            if not challenge:
                bot_logger.warning(f"Challenge not found: {challenge_id}")
                return False, 0, True

            # 检查是否过期
            if challenge.expires_at <= datetime.utcnow():
                bot_logger.warning(f"Challenge {challenge_id} has expired")
                return False, 0, True

            # 检查是否已解决
            if challenge.is_solved:
                bot_logger.info(f"Challenge {challenge_id} already solved")
                return True, 0, False

            # 检查是否已经尝试过（仅一次机会）
            if challenge.attempts > 0:
                bot_logger.warning(f"Challenge {challenge_id} already attempted - single attempt only")
                return False, 0, False

            # 增加尝试次数（设为1，因为仅一次机会）
            challenge.attempts = 1
            challenge.user_answer = user_answer

            # 检查答案是否正确
            is_correct = user_answer.strip().lower() == challenge.correct_answer.lower()

            if is_correct:
                challenge.is_solved = True
                challenge.solved_at = datetime.utcnow()
                bot_logger.info(f"Challenge {challenge_id} solved correctly on single attempt")
                remaining_attempts = 0
            else:
                # 答案错误，无剩余机会（仅一次机会）
                remaining_attempts = 0
                bot_logger.info(f"Challenge {challenge_id} answered incorrectly: {user_answer} vs {challenge.correct_answer}, single attempt failed")

            await session.commit()
            return is_correct, remaining_attempts, False

    @staticmethod
    async def get_challenge(challenge_id: int) -> Optional[Challenge]:
        """根据ID获取挑战

        Args:
            challenge_id: 挑战ID

        Returns:
            Optional[Challenge]: 挑战对象或None
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(Challenge).where(Challenge.id == challenge_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def check_challenge_expired(user_id: int) -> bool:
        """检查用户挑战是否过期

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否过期
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(Challenge).where(
                    and_(
                        Challenge.user_id == user_id,
                        Challenge.is_solved == False
                    )
                ).order_by(Challenge.created_at.desc())
            )
            challenge = result.scalar_one_or_none()

            if not challenge:
                return False

            return challenge.expires_at <= datetime.utcnow()

    @staticmethod
    async def get_active_challenge(user_id: int) -> Optional[Challenge]:
        """获取用户当前活跃的挑战

        Args:
            user_id: 用户ID

        Returns:
            Optional[Challenge]: 当前挑战或None
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(Challenge).where(
                    and_(
                        Challenge.user_id == user_id,
                        Challenge.is_solved == False,
                        Challenge.expires_at > datetime.utcnow()
                    )
                ).order_by(Challenge.created_at.desc())
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_challenge_options(challenge: Challenge) -> List[Dict[str, str]]:
        """获取挑战的选项列表

        Args:
            challenge: 挑战对象

        Returns:
            List[Dict[str, str]]: 选项列表
        """
        if challenge.options:
            import json
            return json.loads(challenge.options)
        return []

    @staticmethod
    async def cleanup_expired_challenges():
        """清理过期的挑战"""
        async with get_db_session() as session:
            result = await session.execute(
                select(Challenge).where(
                    and_(
                        Challenge.is_solved == False,
                        Challenge.expires_at <= datetime.utcnow()
                    )
                )
            )
            expired_challenges = result.scalars().all()

            for challenge in expired_challenges:
                await session.delete(challenge)

            await session.commit()

            if expired_challenges:
                bot_logger.info(f"Cleaned up {len(expired_challenges)} expired challenges")

    @staticmethod
    async def mark_user_verified(user_id: int):
        """标记用户为已验证

        Args:
            user_id: 用户ID
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            if user:
                user.is_verified = True
                await session.commit()
                bot_logger.info(f"User {user_id} marked as verified")
            else:
                # 如果用户不存在，创建新用户
                user = User(
                    user_id=user_id,
                    is_verified=True
                )
                session.add(user)
                await session.commit()
                bot_logger.info(f"Created new verified user {user_id}")

    @staticmethod
    async def is_user_verified(user_id: int) -> bool:
        """检查用户是否已验证

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否已验证
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()

            return user.is_verified if user else False