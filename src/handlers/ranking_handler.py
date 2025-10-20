from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.services.statistics_service import StatisticsService
from src.services.language_service import LanguageService
from src.utils.config import config
from src.utils.logger import bot_logger


class RankingHandler:
    """排行榜处理器"""

    @staticmethod
    async def handle_ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/ranking命令"""
        user_id = update.effective_user.id

        try:
            # 创建排行榜选择键盘
            title = await LanguageService.get_text(user_id, "ranking_title")

            keyboard = [
                [
                    InlineKeyboardButton(
                        await LanguageService.get_text(user_id, "ranking_total"),
                        callback_data="ranking_total_1"
                    )
                ],
                [
                    InlineKeyboardButton(
                        await LanguageService.get_text(user_id, "ranking_active"),
                        callback_data="ranking_active_1"
                    )
                ],
                [
                    InlineKeyboardButton("📊 My Stats", callback_data=f"my_stats_{user_id}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="ranking_menu")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"{title}\n\nPlease select a ranking type:",
                reply_markup=reply_markup
            )

            bot_logger.info(f"User {user_id} requested ranking menu")

        except Exception as e:
            bot_logger.error(f"Error handling ranking command for user {user_id}: {e}")
            await update.message.reply_text("❌ Error loading rankings. Please try again.")

    @staticmethod
    async def handle_ranking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理排行榜相关的回调查询"""
        query = update.callback_query
        await query.answer()

        callback_data = query.data
        user_id = update.effective_user.id

        try:
            if callback_data == "ranking_menu":
                await RankingHandler._show_ranking_menu(query, user_id)

            elif callback_data.startswith("ranking_"):
                # 解析回调数据：ranking_{type}_{page}
                parts = callback_data.split("_")
                ranking_type = parts[1]
                page = int(parts[2])

                await RankingHandler._show_ranking(query, user_id, ranking_type, page)

            elif callback_data.startswith("my_stats_"):
                # 显示用户个人统计
                await RankingHandler._show_user_stats(query, user_id)

        except Exception as e:
            bot_logger.error(f"Error handling ranking callback: {e}")
            await query.edit_message_text("❌ An error occurred. Please try again.")

    @staticmethod
    async def _show_ranking_menu(query, user_id: int):
        """显示排行榜菜单"""
        try:
            title = await LanguageService.get_text(user_id, "ranking_title")

            keyboard = [
                [
                    InlineKeyboardButton(
                        await LanguageService.get_text(user_id, "ranking_total"),
                        callback_data="ranking_total_1"
                    )
                ],
                [
                    InlineKeyboardButton(
                        await LanguageService.get_text(user_id, "ranking_active"),
                        callback_data="ranking_active_1"
                    )
                ],
                [
                    InlineKeyboardButton("📊 My Stats", callback_data=f"my_stats_{user_id}"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="ranking_menu")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"{title}\n\nPlease select a ranking type:",
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing ranking menu: {e}")
            await query.edit_message_text("❌ Error loading ranking menu.")

    @staticmethod
    async def _show_ranking(query, user_id: int, ranking_type: str, page: int = 1):
        """显示排行榜"""
        try:
            per_page = config.RANKINGS_PER_PAGE
            limit = per_page * page

            # 获取排行榜数据
            if ranking_type == "total":
                ranking_data = await StatisticsService.get_total_invitation_ranking(limit)
                title = await LanguageService.get_text(user_id, "ranking_total")
                emoji = "👥"
            elif ranking_type == "active":
                ranking_data = await StatisticsService.get_active_members_ranking(limit)
                title = await LanguageService.get_text(user_id, "ranking_active")
                emoji = "✅"
            else:
                await query.edit_message_text("❌ Invalid ranking type.")
                return

            if not ranking_data:
                no_data_text = await LanguageService.get_text(user_id, "no_ranking_data")
                await query.edit_message_text(no_data_text)
                return

            # 计算分页
            start_index = (page - 1) * per_page
            end_index = start_index + per_page
            page_data = ranking_data[start_index:end_index]

            # 构建消息
            message_lines = [f"🏆 {title}", ""]

            for entry in page_data:
                rank_emoji = RankingHandler._get_rank_emoji(entry['rank'])
                message_lines.append(
                    f"{rank_emoji} #{entry['rank']} - {entry['name']}: {emoji} {entry['count']}"
                )

            # 获取用户自己的排名
            user_ranking = await StatisticsService.get_user_ranking_position(user_id, ranking_type)
            if user_ranking and user_ranking['rank'] > end_index:
                message_lines.append("")
                message_lines.append(f"📍 Your position: #{user_ranking['rank']} - {emoji} {user_ranking['count']}")

            message = "\n".join(message_lines)

            # 创建键盘
            keyboard = []

            # 分页按钮
            nav_buttons = []
            if page > 1:
                nav_buttons.append(
                    InlineKeyboardButton("⬅️ Previous", callback_data=f"ranking_{ranking_type}_{page-1}")
                )
            if len(ranking_data) > end_index:
                nav_buttons.append(
                    InlineKeyboardButton("Next ➡️", callback_data=f"ranking_{ranking_type}_{page+1}")
                )
            if nav_buttons:
                keyboard.append(nav_buttons)

            # 控制按钮
            keyboard.append([
                InlineKeyboardButton("📊 My Stats", callback_data=f"my_stats_{user_id}"),
                InlineKeyboardButton("🔙 Back", callback_data="ranking_menu")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing ranking: {e}")
            await query.edit_message_text("❌ Error loading ranking data.")

    @staticmethod
    async def _show_user_stats(query, user_id: int):
        """显示用户个人统计"""
        try:
            # 获取用户综合统计
            stats = await StatisticsService.get_comprehensive_user_stats(user_id)

            message_lines = ["📊 Your Statistics:", ""]

            # 总邀请数排名
            if stats['total_ranking']:
                message_lines.append(
                    f"👥 Total Invitations: #{stats['total_ranking']['rank']} "
                    f"({stats['total_ranking']['count']} invites)"
                )
            else:
                message_lines.append("👥 Total Invitations: Not ranked yet")

            # 活跃成员数排名
            if stats['active_ranking']:
                message_lines.append(
                    f"✅ Active Members: #{stats['active_ranking']['rank']} "
                    f"({stats['active_ranking']['count']} active)"
                )
            else:
                message_lines.append("✅ Active Members: Not ranked yet")

            message = "\n".join(message_lines)

            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"my_stats_{user_id}"),
                    InlineKeyboardButton("🔙 Back", callback_data="ranking_menu")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing user stats: {e}")
            await query.edit_message_text("❌ Error loading your statistics.")

    @staticmethod
    def _get_rank_emoji(rank: int) -> str:
        """获取排名对应的emoji"""
        if rank == 1:
            return "🥇"
        elif rank == 2:
            return "🥈"
        elif rank == 3:
            return "🥉"
        elif rank <= 10:
            return "🏅"
        else:
            return "📊"

    @staticmethod
    async def handle_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/stats命令（显示个人统计）"""
        user_id = update.effective_user.id

        try:
            # 获取用户综合统计
            stats = await StatisticsService.get_comprehensive_user_stats(user_id)

            message_lines = ["📊 Your Statistics:", ""]

            # 总邀请数排名
            if stats['total_ranking']:
                message_lines.append(
                    f"👥 Total Invitations: #{stats['total_ranking']['rank']} "
                    f"({stats['total_ranking']['count']} invites)"
                )
            else:
                message_lines.append("👥 Total Invitations: Not ranked yet")

            # 活跃成员数排名
            if stats['active_ranking']:
                message_lines.append(
                    f"✅ Active Members: #{stats['active_ranking']['rank']} "
                    f"({stats['active_ranking']['count']} active)"
                )
            else:
                message_lines.append("✅ Active Members: Not ranked yet")

            message = "\n".join(message_lines)

            await update.message.reply_text(message)

            bot_logger.info(f"User {user_id} requested personal stats")

        except Exception as e:
            bot_logger.error(f"Error handling stats command for user {user_id}: {e}")
            await update.message.reply_text("❌ Error loading your statistics. Please try again.")