from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime

from src.services.invitation_service import InvitationService
from src.services.language_service import LanguageService
from src.utils.logger import bot_logger


class InvitationHandler:
    """邀请处理器"""

    @staticmethod
    async def handle_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/link命令"""
        user_id = update.effective_user.id

        try:
            from src.utils.config import config

            # 创建或获取邀请链接
            invitation = await InvitationService.create_or_get_invite_link(
                user_id,
                context.bot,
                config.GROUP_CHAT_ID
            )

            # 获取邀请统计
            stats = await InvitationService.get_user_invitation_stats(user_id)

            # 获取群组信息以显示更友好的消息
            try:
                chat_info = await context.bot.get_chat(config.GROUP_CHAT_ID)
                group_name = chat_info.title or "群组"
            except:
                group_name = "群组"

            # 获取用户语言的文本
            copy_prompt = await LanguageService.get_text(user_id, "invite_copy_prompt")
            stats_text = await LanguageService.get_text(
                user_id,
                "invite_stats",
                total=stats['total_invited'],
                left=stats['total_left'],
                active=stats['active_members']
            )

            # 构建更友好的消息
            group_info = f"🏠 群组: {group_name}\n"
            link_info = f"🔗 专属邀请链接:\n{invitation.invite_link}\n"
            user_info = f"👤 邀请者: {update.effective_user.first_name or update.effective_user.username}\n"

            message = f"{group_info}{user_info}\n{copy_prompt}\n{link_info}\n{stats_text}"

            # 创建键盘，添加更多功能按钮
            keyboard = [
                [
                    InlineKeyboardButton("📊 Details", callback_data=f"invite_details_{user_id}_1"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"invite_refresh_{user_id}")
                ],
                [
                    InlineKeyboardButton("🏆 Rankings", callback_data="ranking_menu"),
                    InlineKeyboardButton("📈 My Stats", callback_data="my_stats_show")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                message,
                reply_markup=reply_markup
            )

            bot_logger.info(f"User {user_id} requested invite link for group: {group_name}")

        except Exception as e:
            bot_logger.error(f"Error handling link command for user {user_id}: {e}")
            error_text = "❌ Error generating invite link. Please try again."
            await update.message.reply_text(error_text)

    @staticmethod
    async def handle_invite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理邀请相关的回调查询"""
        query = update.callback_query
        await query.answer()

        callback_data = query.data
        user_id = update.effective_user.id

        try:
            if callback_data.startswith("invite_details_"):
                # 解析回调数据：invite_details_{user_id}_{page}
                parts = callback_data.split("_")
                target_user_id = int(parts[2])
                page = int(parts[3])

                # 只允许用户查看自己的详情
                if user_id != target_user_id:
                    await query.edit_message_text("❌ You can only view your own invitation details.")
                    return

                await InvitationHandler._show_invite_details(query, user_id, page)

            elif callback_data.startswith("invite_refresh_"):
                # 刷新邀请统计
                parts = callback_data.split("_")
                target_user_id = int(parts[2])

                if user_id != target_user_id:
                    await query.edit_message_text("❌ You can only refresh your own invitation data.")
                    return

                await InvitationHandler._refresh_invite_stats(query, user_id, context)

            elif callback_data.startswith("invite_page_"):
                # 分页导航：invite_page_{user_id}_{page}
                parts = callback_data.split("_")
                target_user_id = int(parts[2])
                page = int(parts[3])

                if user_id != target_user_id:
                    return

                await InvitationHandler._show_invite_details(query, user_id, page)

        except Exception as e:
            bot_logger.error(f"Error handling invite callback: {e}")
            await query.edit_message_text("❌ An error occurred. Please try again.")

    @staticmethod
    async def _show_invite_details(query, user_id: int, page: int = 1):
        """显示邀请详情"""
        try:
            # 获取分页数据
            data = await InvitationService.get_paginated_members(user_id, page)

            # 构建消息
            title = await LanguageService.get_text(
                user_id,
                "invite_members_title",
                page=data['current_page'],
                total_pages=data['total_pages']
            )

            stats_text = await LanguageService.get_text(
                user_id,
                "invite_stats",
                total=data['total_invited'],
                left=data['total_left'],
                active=data['active_members']
            )

            message_lines = [title, "", stats_text, ""]

            if not data['members']:
                no_members_text = await LanguageService.get_text(user_id, "no_members")
                message_lines.append(no_members_text)
            else:
                for member in data['members']:
                    if member['has_left']:
                        status_text = await LanguageService.get_text(
                            user_id,
                            "member_status_left",
                            name=member['name']
                        )
                    else:
                        status_text = await LanguageService.get_text(
                            user_id,
                            "member_status_active",
                            name=member['name']
                        )
                    message_lines.append(status_text)

            message = "\n".join(message_lines)

            # 创建分页键盘
            keyboard = []

            # 分页按钮
            if data['total_pages'] > 1:
                nav_buttons = []
                if data['has_previous']:
                    nav_buttons.append(
                        InlineKeyboardButton("⬅️ Previous", callback_data=f"invite_page_{user_id}_{page-1}")
                    )
                if data['has_next']:
                    nav_buttons.append(
                        InlineKeyboardButton("Next ➡️", callback_data=f"invite_page_{user_id}_{page+1}")
                    )
                if nav_buttons:
                    keyboard.append(nav_buttons)

            # 控制按钮
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data=f"invite_refresh_{user_id}"),
                InlineKeyboardButton("🔙 Back", callback_data=f"invite_back_{user_id}")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error showing invite details: {e}")
            await query.edit_message_text("❌ Error loading invitation details.")

    @staticmethod
    async def _refresh_invite_stats(query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """刷新邀请统计"""
        try:
            from src.utils.config import config

            # 获取邀请链接
            invitation = await InvitationService.create_or_get_invite_link(
                user_id,
                context.bot,
                config.GROUP_CHAT_ID
            )
            stats = await InvitationService.get_user_invitation_stats(user_id)

            # 获取群组信息
            try:
                chat_info = await context.bot.get_chat(config.GROUP_CHAT_ID)
                group_name = chat_info.title or "群组"
            except:
                group_name = "群组"

            # 获取用户信息
            try:
                user_info_text = query.from_user.first_name or query.from_user.username or "用户"
            except:
                user_info_text = "用户"

            # 获取用户语言的文本
            copy_prompt = await LanguageService.get_text(user_id, "invite_copy_prompt")
            stats_text = await LanguageService.get_text(
                user_id,
                "invite_stats",
                total=stats['total_invited'],
                left=stats['total_left'],
                active=stats['active_members']
            )

            # 构建更友好的消息
            group_info = f"🏠 群组: {group_name}\n"
            link_info = f"🔗 专属邀请链接:\n{invitation.invite_link}\n"
            user_info = f"👤 邀请者: {user_info_text}\n"

            message = f"{group_info}{user_info}\n{copy_prompt}\n{link_info}\n{stats_text}"

            # 创建键盘，添加更多功能按钮
            keyboard = [
                [
                    InlineKeyboardButton("📊 Details", callback_data=f"invite_details_{user_id}_1"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"invite_refresh_{user_id}")
                ],
                [
                    InlineKeyboardButton("🏆 Rankings", callback_data="ranking_menu"),
                    InlineKeyboardButton("📈 My Stats", callback_data="my_stats_show")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error refreshing invite stats: {e}")
            await query.edit_message_text("❌ Error refreshing data.")

    @staticmethod
    async def handle_start_with_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, invite_code: str):
        """处理带邀请码的/start命令"""
        user_id = update.effective_user.id

        try:
            # 处理邀请加入
            success = await InvitationService.process_invite_join(invite_code, user_id)

            if success:
                welcome_text = await LanguageService.get_text(user_id, "welcome")
                invite_info = f"👥 You joined via invitation code: {invite_code}"
                message = f"{welcome_text}\n\n{invite_info}"

                await update.message.reply_text(message)
                bot_logger.info(f"User {user_id} joined via invite code {invite_code}")
            else:
                error_text = "❌ Invalid or expired invitation code."
                await update.message.reply_text(error_text)

        except Exception as e:
            bot_logger.error(f"Error handling start with invite: {e}")
            error_text = "❌ Error processing invitation. Please try again."
            await update.message.reply_text(error_text)