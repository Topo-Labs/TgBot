import uuid
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, Invitation, InvitationMember
from src.utils.database import get_db_session
from src.utils.config import config
from src.utils.logger import bot_logger


class InvitationService:
    """邀请服务类"""

    @staticmethod
    def generate_invite_code(user_id: int) -> str:
        """生成邀请码

        Args:
            user_id: 用户ID

        Returns:
            str: 邀请码
        """
        # 使用用户ID和时间戳生成唯一邀请码
        timestamp = str(int(datetime.utcnow().timestamp()))
        raw_string = f"{user_id}_{timestamp}_{uuid.uuid4().hex[:8]}"
        return hashlib.md5(raw_string.encode()).hexdigest()[:12].upper()

    @staticmethod
    async def create_or_get_invite_link(user_id: int, bot, group_chat_id: int) -> Invitation:
        """创建或获取用户的邀请链接

        Args:
            user_id: 用户ID
            bot: 机器人实例
            group_chat_id: 群组聊天ID

        Returns:
            Invitation: 邀请对象
        """
        async with get_db_session() as session:
            # 检查用户是否已有活跃的邀请链接
            result = await session.execute(
                select(Invitation).where(
                    and_(
                        Invitation.user_id == user_id,
                        Invitation.is_active == True
                    )
                )
            )
            existing_invitation = result.scalar_one_or_none()

            if existing_invitation:
                bot_logger.info(f"Returning existing invite link for user {user_id}")
                return existing_invitation

            # 创建新的邀请链接
            invite_code = InvitationService.generate_invite_code(user_id)

            try:
                # 获取群组信息以生成更有意义的邀请链接名称
                chat_info = await bot.get_chat(group_chat_id)
                group_name = chat_info.title or "Group"

                # 获取邀请者信息
                try:
                    async with get_db_session() as session:
                        result = await session.execute(
                            select(User).where(User.user_id == user_id)
                        )
                        user = result.scalar_one_or_none()
                        if user and user.username:
                            inviter_name = f"@{user.username}"
                        elif user and user.first_name:
                            inviter_name = user.first_name
                        else:
                            inviter_name = f"User{user_id}"
                except Exception:
                    inviter_name = f"User{user_id}"

                # 创建群组邀请链接，名称包含群组名和邀请者信息
                invite_name = f"Join {group_name} (via {inviter_name})"
                # Telegram 邀请链接名称有长度限制，截断到合适长度
                if len(invite_name) > 32:
                    invite_name = f"Join {group_name}"
                    if len(invite_name) > 32:
                        invite_name = invite_name[:29] + "..."

                telegram_invite_link = await bot.create_chat_invite_link(
                    chat_id=group_chat_id,
                    name=invite_name,
                    creates_join_request=False  # 直接加入，不需要审批
                )
                invite_link = telegram_invite_link.invite_link
                bot_logger.info(f"Created Telegram group invite link for user {user_id} with name: {invite_name}")
            except Exception as e:
                bot_logger.error(f"Failed to create Telegram invite link: {e}")
                # 如果创建群组邀请链接失败，回退到bot链接
                bot_info = await bot.get_me()
                invite_link = f"https://t.me/{bot_info.username}?start={invite_code}"
                bot_logger.info(f"Using fallback bot invite link for user {user_id}")

            invitation = Invitation(
                invite_code=invite_code,
                user_id=user_id,
                invite_link=invite_link,
                total_invited=0,
                total_left=0,
                is_active=True
            )

            session.add(invitation)
            await session.commit()
            await session.refresh(invitation)

            bot_logger.info(f"Created new invite link for user {user_id}: {invite_code}")
            return invitation

    @staticmethod
    async def process_invite_join(invite_code: str, invited_user_id: int) -> bool:
        """处理通过邀请链接加入的用户

        Args:
            invite_code: 邀请码
            invited_user_id: 被邀请用户ID

        Returns:
            bool: 是否成功处理
        """
        async with get_db_session() as session:
            # 查找邀请链接
            result = await session.execute(
                select(Invitation).where(
                    and_(
                        Invitation.invite_code == invite_code,
                        Invitation.is_active == True
                    )
                )
            )
            invitation = result.scalar_one_or_none()

            if not invitation:
                bot_logger.warning(f"Invalid or inactive invite code: {invite_code}")
                return False

            # 检查用户是否已经通过此邀请码加入过
            existing_member_result = await session.execute(
                select(InvitationMember).where(
                    and_(
                        InvitationMember.invite_code == invite_code,
                        InvitationMember.invited_user_id == invited_user_id
                    )
                )
            )
            existing_member = existing_member_result.scalar_one_or_none()

            if existing_member:
                if not existing_member.has_left:
                    bot_logger.info(f"User {invited_user_id} already joined via invite {invite_code}")
                    return True
                else:
                    # 用户之前离开过，现在重新加入
                    existing_member.has_left = False
                    existing_member.joined_at = datetime.utcnow()
                    existing_member.left_at = None
                    invitation.total_left = max(0, invitation.total_left - 1)
                    bot_logger.info(f"User {invited_user_id} rejoined via invite {invite_code}")
            else:
                # 新的邀请成员
                invitation_member = InvitationMember(
                    invite_code=invite_code,
                    invited_user_id=invited_user_id,
                    has_left=False
                )
                session.add(invitation_member)
                invitation.total_invited += 1
                bot_logger.info(f"User {invited_user_id} joined via invite {invite_code}")

            # 更新被邀请用户的invited_by字段
            invited_user_result = await session.execute(
                select(User).where(User.user_id == invited_user_id)
            )
            invited_user = invited_user_result.scalar_one_or_none()

            if invited_user:
                invited_user.invited_by_user_id = invitation.user_id
            else:
                # 创建新用户记录
                new_user = User(
                    user_id=invited_user_id,
                    invited_by_user_id=invitation.user_id
                )
                session.add(new_user)

            await session.commit()
            return True

    @staticmethod
    async def process_member_left(user_id: int):
        """处理成员离开群组

        Args:
            user_id: 离开的用户ID
        """
        async with get_db_session() as session:
            # 查找用户的邀请记录
            result = await session.execute(
                select(InvitationMember).where(
                    and_(
                        InvitationMember.invited_user_id == user_id,
                        InvitationMember.has_left == False
                    )
                )
            )
            invitation_members = result.scalars().all()

            for member in invitation_members:
                # 标记为已离开
                member.has_left = True
                member.left_at = datetime.utcnow()

                # 更新邀请统计
                invitation_result = await session.execute(
                    select(Invitation).where(Invitation.invite_code == member.invite_code)
                )
                invitation = invitation_result.scalar_one_or_none()

                if invitation:
                    invitation.total_left += 1

                bot_logger.info(f"User {user_id} left, updated invite {member.invite_code}")

            await session.commit()

    @staticmethod
    async def get_user_invitation_stats(user_id: int) -> Dict:
        """获取用户的邀请统计

        Args:
            user_id: 用户ID

        Returns:
            Dict: 邀请统计数据
        """
        async with get_db_session() as session:
            # 获取用户的邀请链接
            invitation_result = await session.execute(
                select(Invitation).where(
                    and_(
                        Invitation.user_id == user_id,
                        Invitation.is_active == True
                    )
                )
            )
            invitation = invitation_result.scalar_one_or_none()

            if not invitation:
                return {
                    'invite_link': None,
                    'total_invited': 0,
                    'total_left': 0,
                    'active_members': 0,
                    'members': []
                }

            # 获取邀请成员列表
            members_result = await session.execute(
                select(InvitationMember, User).join(
                    User, InvitationMember.invited_user_id == User.user_id
                ).where(
                    InvitationMember.invite_code == invitation.invite_code
                ).order_by(InvitationMember.joined_at.desc())
            )
            members_data = members_result.all()

            members = []
            for member, user in members_data:
                members.append({
                    'user_id': user.user_id,
                    'name': user.username or user.first_name or f"User {user.user_id}",
                    'has_left': member.has_left,
                    'joined_at': member.joined_at,
                    'left_at': member.left_at
                })

            active_members = len([m for m in members if not m['has_left']])

            return {
                'invite_link': invitation.invite_link,
                'invite_code': invitation.invite_code,
                'total_invited': invitation.total_invited,
                'total_left': invitation.total_left,
                'active_members': active_members,
                'members': members
            }

    @staticmethod
    async def get_paginated_members(user_id: int, page: int = 1) -> Dict:
        """获取分页的邀请成员列表

        Args:
            user_id: 用户ID
            page: 页码（从1开始）

        Returns:
            Dict: 分页数据
        """
        stats = await InvitationService.get_user_invitation_stats(user_id)
        members = stats['members']

        per_page = config.MEMBERS_PER_PAGE
        total_members = len(members)
        total_pages = max(1, (total_members + per_page - 1) // per_page)

        # 确保页码在有效范围内
        page = max(1, min(page, total_pages))

        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        page_members = members[start_index:end_index]

        return {
            'members': page_members,
            'current_page': page,
            'total_pages': total_pages,
            'total_members': total_members,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'invite_link': stats['invite_link'],
            'total_invited': stats['total_invited'],
            'total_left': stats['total_left'],
            'active_members': stats['active_members']
        }

    @staticmethod
    async def deactivate_user_invites(user_id: int):
        """停用用户的邀请链接

        Args:
            user_id: 用户ID
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(Invitation).where(
                    and_(
                        Invitation.user_id == user_id,
                        Invitation.is_active == True
                    )
                )
            )
            invitations = result.scalars().all()

            for invitation in invitations:
                invitation.is_active = False

            await session.commit()

            if invitations:
                bot_logger.info(f"Deactivated {len(invitations)} invite links for user {user_id}")

    @staticmethod
    async def update_invitation_stats(invite_code: str):
        """更新邀请链接的统计数据

        Args:
            invite_code: 邀请码
        """
        async with get_db_session() as session:
            # 获取邀请链接
            invitation_result = await session.execute(
                select(Invitation).where(Invitation.invite_code == invite_code)
            )
            invitation = invitation_result.scalar_one_or_none()

            if not invitation:
                bot_logger.warning(f"Invitation not found for code: {invite_code}")
                return

            # 重新计算统计数据
            members_result = await session.execute(
                select(InvitationMember).where(InvitationMember.invite_code == invite_code)
            )
            members = members_result.scalars().all()

            total_invited = len(members)
            total_left = sum(1 for member in members if member.has_left)

            # 更新统计
            invitation.total_invited = total_invited
            invitation.total_left = total_left

            await session.commit()
            bot_logger.info(f"Updated stats for invite {invite_code}: {total_invited} invited, {total_left} left")

    @staticmethod
    async def find_invitation_by_telegram_link(invite_link: str) -> Optional[Invitation]:
        """通过Telegram邀请链接查找邀请记录

        Args:
            invite_link: Telegram群组邀请链接

        Returns:
            Optional[Invitation]: 邀请对象或None
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(Invitation).where(
                    and_(
                        Invitation.invite_link == invite_link,
                        Invitation.is_active == True
                    )
                )
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def process_group_join(invited_user_id: int, invite_link: str = None) -> bool:
        """处理通过群组加入的用户

        Args:
            invited_user_id: 被邀请用户ID
            invite_link: 可选的邀请链接

        Returns:
            bool: 是否成功处理
        """
        if not invite_link:
            # 如果没有邀请链接信息，无法追踪
            return False

        invitation = await InvitationService.find_invitation_by_telegram_link(invite_link)
        if not invitation:
            bot_logger.warning(f"No invitation found for link: {invite_link}")
            return False

        async with get_db_session() as session:
            # 检查用户是否已经通过此邀请码加入过
            existing_member_result = await session.execute(
                select(InvitationMember).where(
                    and_(
                        InvitationMember.invite_code == invitation.invite_code,
                        InvitationMember.invited_user_id == invited_user_id
                    )
                )
            )
            existing_member = existing_member_result.scalar_one_or_none()

            if existing_member:
                if not existing_member.has_left:
                    bot_logger.info(f"User {invited_user_id} already joined via invite {invitation.invite_code}")
                    return True
                else:
                    # 用户之前离开过，现在重新加入
                    existing_member.has_left = False
                    existing_member.joined_at = datetime.utcnow()
                    existing_member.left_at = None
                    invitation.total_left = max(0, invitation.total_left - 1)
                    bot_logger.info(f"User {invited_user_id} rejoined via invite {invitation.invite_code}")
            else:
                # 新的邀请成员
                invitation_member = InvitationMember(
                    invite_code=invitation.invite_code,
                    invited_user_id=invited_user_id,
                    has_left=False
                )
                session.add(invitation_member)
                invitation.total_invited += 1
                bot_logger.info(f"User {invited_user_id} joined via invite {invitation.invite_code}")

            # 更新被邀请用户的invited_by字段
            invited_user_result = await session.execute(
                select(User).where(User.user_id == invited_user_id)
            )
            invited_user = invited_user_result.scalar_one_or_none()

            if invited_user:
                invited_user.invited_by_user_id = invitation.user_id
            else:
                # 创建新用户记录
                new_user = User(
                    user_id=invited_user_id,
                    invited_by_user_id=invitation.user_id
                )
                session.add(new_user)

            await session.commit()
            return True

    @staticmethod
    async def get_invite_code_from_start_param(start_param: str) -> Optional[str]:
        """从start参数中提取邀请码

        Args:
            start_param: /start命令的参数

        Returns:
            Optional[str]: 邀请码或None
        """
        if not start_param:
            return None

        # 验证邀请码格式（12位大写字母数字）
        if len(start_param) == 12 and start_param.isupper() and start_param.isalnum():
            return start_param

        return None