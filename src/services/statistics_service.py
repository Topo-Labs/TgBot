from datetime import datetime, timedelta, date
from typing import List, Dict, Optional
from sqlalchemy import select, func, and_, desc, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, Invitation, InvitationMember, Statistic
from src.utils.database import get_db_session
from src.utils.config import config
from src.utils.logger import bot_logger


class StatisticsService:
    """统计服务类"""

    @staticmethod
    async def get_total_invitation_ranking(limit: int = 20) -> List[Dict]:
        """获取总邀请数排行榜

        Args:
            limit: 返回条数限制

        Returns:
            List[Dict]: 排行榜数据
        """
        async with get_db_session() as session:
            # 查询每个用户的总邀请数
            query = select(
                User.user_id,
                User.first_name,
                User.username,
                func.coalesce(func.sum(Invitation.total_invited), 0).label('total_invited')
            ).select_from(
                User
            ).outerjoin(
                Invitation, User.user_id == Invitation.user_id
            ).group_by(
                User.user_id, User.first_name, User.username
            ).order_by(
                desc('total_invited')
            ).limit(limit)

            result = await session.execute(query)
            rows = result.all()

            ranking = []
            for i, row in enumerate(rows, 1):
                ranking.append({
                    'rank': i,
                    'user_id': row.user_id,
                    'name': row.username or row.first_name or f"User {row.user_id}",
                    'count': row.total_invited
                })

            return ranking

    @staticmethod
    async def get_active_members_ranking(limit: int = 20) -> List[Dict]:
        """获取活跃成员数排行榜（总邀请数 - 退群数）

        Args:
            limit: 返回条数限制

        Returns:
            List[Dict]: 排行榜数据
        """
        async with get_db_session() as session:
            # 查询每个用户的活跃成员数（总邀请 - 退群）
            query = select(
                User.user_id,
                User.first_name,
                User.username,
                (func.coalesce(func.sum(Invitation.total_invited), 0) -
                 func.coalesce(func.sum(Invitation.total_left), 0)).label('active_members')
            ).select_from(
                User
            ).outerjoin(
                Invitation, User.user_id == Invitation.user_id
            ).group_by(
                User.user_id, User.first_name, User.username
            ).order_by(
                desc('active_members')
            ).limit(limit)

            result = await session.execute(query)
            rows = result.all()

            ranking = []
            for i, row in enumerate(rows, 1):
                ranking.append({
                    'rank': i,
                    'user_id': row.user_id,
                    'name': row.username or row.first_name or f"User {row.user_id}",
                    'count': max(0, row.active_members)  # 确保不是负数
                })

            return ranking

    @staticmethod
    async def get_period_invitation_ranking(days: int, limit: int = 20) -> List[Dict]:
        """获取指定时间段的邀请排行榜

        Args:
            days: 天数（例如7天、30天）
            limit: 返回条数限制

        Returns:
            List[Dict]: 排行榜数据
        """
        async with get_db_session() as session:
            start_date = datetime.utcnow() - timedelta(days=days)

            # 查询指定时间段内的邀请数
            query = select(
                User.user_id,
                User.first_name,
                User.username,
                func.count(InvitationMember.id).label('period_invited')
            ).select_from(
                User
            ).outerjoin(
                Invitation, User.user_id == Invitation.user_id
            ).outerjoin(
                InvitationMember, Invitation.invite_code == InvitationMember.invite_code
            ).where(
                InvitationMember.joined_at >= start_date
            ).group_by(
                User.user_id, User.first_name, User.username
            ).order_by(
                desc('period_invited')
            ).limit(limit)

            result = await session.execute(query)
            rows = result.all()

            ranking = []
            for i, row in enumerate(rows, 1):
                ranking.append({
                    'rank': i,
                    'user_id': row.user_id,
                    'name': row.username or row.first_name or f"User {row.user_id}",
                    'count': row.period_invited
                })

            return ranking

    @staticmethod
    async def update_daily_statistics():
        """更新每日统计数据"""
        async with get_db_session() as session:
            today = date.today()

            # 获取所有用户的邀请统计
            query = select(
                User.user_id,
                func.coalesce(func.sum(Invitation.total_invited), 0).label('total_invited'),
                func.coalesce(func.sum(Invitation.total_left), 0).label('total_left')
            ).select_from(
                User
            ).outerjoin(
                Invitation, User.user_id == Invitation.user_id
            ).group_by(
                User.user_id
            )

            result = await session.execute(query)
            user_stats = result.all()

            for stat in user_stats:
                # 删除今天的旧统计（如果存在）
                await session.execute(
                    select(Statistic).where(
                        and_(
                            Statistic.user_id == stat.user_id,
                            Statistic.date == today
                        )
                    )
                )
                existing_stats = await session.execute(
                    select(Statistic).where(
                        and_(
                            Statistic.user_id == stat.user_id,
                            Statistic.date == today
                        )
                    )
                )
                for existing_stat in existing_stats.scalars():
                    await session.delete(existing_stat)

                # 添加新的统计记录
                stats_to_add = [
                    Statistic(
                        user_id=stat.user_id,
                        metric_type='total_invited',
                        value=stat.total_invited,
                        date=today
                    ),
                    Statistic(
                        user_id=stat.user_id,
                        metric_type='total_left',
                        value=stat.total_left,
                        date=today
                    ),
                    Statistic(
                        user_id=stat.user_id,
                        metric_type='active_members',
                        value=max(0, stat.total_invited - stat.total_left),
                        date=today
                    )
                ]

                for new_stat in stats_to_add:
                    session.add(new_stat)

            await session.commit()
            bot_logger.info(f"Updated daily statistics for {len(user_stats)} users")

    @staticmethod
    async def get_user_ranking_position(user_id: int, ranking_type: str) -> Optional[Dict]:
        """获取用户在指定排行榜中的位置

        Args:
            user_id: 用户ID
            ranking_type: 排行榜类型 ('total', 'active')

        Returns:
            Optional[Dict]: 用户排名信息
        """
        async with get_db_session() as session:
            if ranking_type == 'total':
                # 总邀请数排行
                query = select(
                    User.user_id,
                    User.first_name,
                    User.username,
                    func.coalesce(func.sum(Invitation.total_invited), 0).label('count')
                ).select_from(
                    User
                ).outerjoin(
                    Invitation, User.user_id == Invitation.user_id
                ).group_by(
                    User.user_id, User.first_name, User.username
                ).order_by(
                    desc('count')
                )

            elif ranking_type == 'active':
                # 活跃成员数排行
                query = select(
                    User.user_id,
                    User.first_name,
                    User.username,
                    (func.coalesce(func.sum(Invitation.total_invited), 0) -
                     func.coalesce(func.sum(Invitation.total_left), 0)).label('count')
                ).select_from(
                    User
                ).outerjoin(
                    Invitation, User.user_id == Invitation.user_id
                ).group_by(
                    User.user_id, User.first_name, User.username
                ).order_by(
                    desc('count')
                )

            else:
                return None

            result = await session.execute(query)
            all_users = result.all()

            # 查找用户位置
            for rank, row in enumerate(all_users, 1):
                if row.user_id == user_id:
                    return {
                        'rank': rank,
                        'user_id': row.user_id,
                        'name': row.username or row.first_name or f"User {row.user_id}",
                        'count': max(0, row.count) if ranking_type == 'active' else row.count,
                        'total_users': len(all_users)
                    }

            return None

    @staticmethod
    async def get_comprehensive_user_stats(user_id: int) -> Dict:
        """获取用户的综合统计信息

        Args:
            user_id: 用户ID

        Returns:
            Dict: 综合统计信息
        """
        # 获取用户在各排行榜中的位置
        total_ranking = await StatisticsService.get_user_ranking_position(user_id, 'total')
        active_ranking = await StatisticsService.get_user_ranking_position(user_id, 'active')

        return {
            'total_ranking': total_ranking,
            'active_ranking': active_ranking
        }