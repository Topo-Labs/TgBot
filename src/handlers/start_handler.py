from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.services.language_service import LanguageService
from src.services.invitation_service import InvitationService
from src.utils.logger import bot_logger


class StartHandler:
    """开始命令处理器"""

    @staticmethod
    async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or update.effective_user.username or "Unknown"

        try:
            # 检查是否有邀请码参数
            if context.args and len(context.args) > 0:
                start_param = context.args[0]
                invite_code = await InvitationService.get_invite_code_from_start_param(start_param)

                if invite_code:
                    # 处理邀请链接
                    from src.handlers.invitation_handler import InvitationHandler
                    await InvitationHandler.handle_start_with_invite(update, context, invite_code)
                    return

            # 普通的/start命令
            await StartHandler._show_help_menu(update, context, user_id)

            bot_logger.info(f"User {user_id} ({user_name}) used /start command")

        except Exception as e:
            bot_logger.error(f"Error handling start command for user {user_id}: {e}")
            await update.message.reply_text("❌ An error occurred. Please try again.")

    @staticmethod
    async def _show_help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """显示帮助菜单"""
        try:
            # 获取本地化文本
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            welcome_text = await LanguageService.get_text(user_id, "welcome")

            message_lines = [welcome_text, "", help_title, "", help_commands]

            message = "\n".join(message_lines)

            # 创建完整功能键盘（所有用户都能访问）
            keyboard = [
                [
                    InlineKeyboardButton("🔗 Get Invite Link", callback_data="help_get_link"),
                    InlineKeyboardButton("📊 My Stats", callback_data="help_my_stats")
                ],
                [
                    InlineKeyboardButton("🏆 Rankings", callback_data="help_rankings"),
                    InlineKeyboardButton("🌍 Language", callback_data="help_language")
                ],
                [
                    InlineKeyboardButton("❓ About Bot", callback_data="help_about"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="help_refresh")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing help menu: {e}")
            await update.message.reply_text("❌ Error loading help menu.")

    @staticmethod
    async def handle_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理帮助相关的回调查询"""
        query = update.callback_query
        await query.answer()

        callback_data = query.data
        user_id = update.effective_user.id

        try:
            if callback_data == "help_refresh":
                await StartHandler._refresh_help_menu(query, context, user_id)

            elif callback_data == "help_get_link":
                # 转到邀请链接功能
                from src.handlers.invitation_handler import InvitationHandler
                await query.edit_message_text("🔗 Getting your invite link...")
                # 这里需要模拟一个message对象来调用原有的link功能
                # 为了简化，我们直接在这里实现
                await StartHandler._handle_inline_link_request(query, context, user_id)

            elif callback_data == "help_my_stats":
                # 转到个人统计
                from src.handlers.ranking_handler import RankingHandler
                await RankingHandler._show_user_stats(query, user_id)

            elif callback_data == "help_rankings":
                # 转到排行榜
                from src.handlers.ranking_handler import RankingHandler
                await RankingHandler._show_ranking_menu(query, user_id)

            elif callback_data == "help_language":
                await StartHandler._show_language_selection(query, user_id)

            elif callback_data == "help_about":
                await StartHandler._show_about_info(query, user_id)

        except Exception as e:
            bot_logger.error(f"Error handling help callback: {e}")
            await query.edit_message_text("❌ An error occurred. Please try again.")

    @staticmethod
    async def _refresh_help_menu(query, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """刷新帮助菜单"""
        try:
            # 获取本地化文本
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")
            welcome_text = await LanguageService.get_text(user_id, "welcome")

            message_lines = [welcome_text, "", help_title, "", help_commands]

            message = "\n".join(message_lines)

            # 创建完整功能键盘（所有用户都能访问）
            keyboard = [
                [
                    InlineKeyboardButton("🔗 Get Invite Link", callback_data="help_get_link"),
                    InlineKeyboardButton("📊 My Stats", callback_data="help_my_stats")
                ],
                [
                    InlineKeyboardButton("🏆 Rankings", callback_data="help_rankings"),
                    InlineKeyboardButton("🌍 Language", callback_data="help_language")
                ],
                [
                    InlineKeyboardButton("❓ About Bot", callback_data="help_about"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="help_refresh")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error refreshing help menu: {e}")
            await query.edit_message_text("❌ Error refreshing menu.")

    @staticmethod
    async def _handle_inline_link_request(query, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """处理内联邀请链接请求"""
        try:
            from src.utils.config import config

            # 创建或获取邀请链接
            invitation = await InvitationService.create_or_get_invite_link(user_id, context.bot, config.GROUP_CHAT_ID)

            # 获取邀请统计
            stats = await InvitationService.get_user_invitation_stats(user_id)

            # 获取用户语言的文本
            copy_prompt = await LanguageService.get_text(user_id, "invite_copy_prompt")
            stats_text = await LanguageService.get_text(
                user_id,
                "invite_stats",
                total=stats['total_invited'],
                left=stats['total_left'],
                active=stats['active_members']
            )

            message = f"{copy_prompt}\n{invitation.invite_link}\n\n{stats_text}"

            # 创建键盘
            keyboard = [
                [
                    InlineKeyboardButton("📊 Details", callback_data=f"invite_details_{user_id}_1"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"invite_refresh_{user_id}")
                ],
                [
                    InlineKeyboardButton("🔙 Back to Menu", callback_data="help_refresh")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error handling inline link request: {e}")
            await query.edit_message_text("❌ Error generating invite link.")

    @staticmethod
    async def _show_language_selection(query, user_id: int):
        """显示语言选择"""
        try:
            languages = await LanguageService.get_available_languages()

            # 创建语言选择键盘（每行3个按钮）
            keyboard = []
            row = []
            for i, (code, name) in enumerate(languages.items()):
                row.append(InlineKeyboardButton(name, callback_data=f"lang_{code}"))
                if len(row) == 3 or i == len(languages) - 1:
                    keyboard.append(row)
                    row = []

            # 添加返回按钮
            keyboard.append([
                InlineKeyboardButton("🔙 Back to Menu", callback_data="help_refresh")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            choose_language_text = await LanguageService.get_text(user_id, "choose_language")

            await query.edit_message_text(
                choose_language_text,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing language selection: {e}")
            await query.edit_message_text("❌ Error loading language options.")

    @staticmethod
    async def _show_about_info(query, user_id: int):
        """显示关于机器人的信息"""
        try:
            about_text = """
🤖 **Telegram Group Management Bot**

**Features:**
• 🧮 Math challenge verification for new members
• 🌍 Multi-language support (20 languages)
• 🔗 Personal invite links with tracking
• 📊 Comprehensive invitation statistics
• 🏆 Real-time rankings and leaderboards
• 📈 Member activity tracking

**Commands:**
• `/start` - Show this help menu
• `/link` - Get your personal invite link
• `/stats` - View your invitation statistics
• `/ranking` - View invitation rankings
• `/lang` - Change language preference

**Security:**
• Automatic bot detection and removal
• 5-minute verification timeout
• Multiple attempt tracking
• Spam protection

**Support:**
For support, contact the group administrators.

**Version:** 1.0.0
**Powered by:** Python & PostgreSQL
            """

            keyboard = [
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="help_refresh")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                about_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing about info: {e}")
            await query.edit_message_text("❌ Error loading about information.")

    @staticmethod
    async def handle_lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/lang命令"""
        user_id = update.effective_user.id

        try:
            languages = await LanguageService.get_available_languages()

            # 创建语言选择键盘（每行3个按钮）
            keyboard = []
            row = []
            for i, (code, name) in enumerate(languages.items()):
                row.append(InlineKeyboardButton(name, callback_data=f"lang_{code}"))
                if len(row) == 3 or i == len(languages) - 1:
                    keyboard.append(row)
                    row = []

            reply_markup = InlineKeyboardMarkup(keyboard)

            choose_language_text = await LanguageService.get_text(user_id, "choose_language")

            await update.message.reply_text(
                choose_language_text,
                reply_markup=reply_markup
            )

            bot_logger.info(f"User {user_id} requested language selection")

        except Exception as e:
            bot_logger.error(f"Error handling lang command for user {user_id}: {e}")
            await update.message.reply_text("❌ Error loading language options. Please try again.")