from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import TelegramError
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select

from src.services.auth_service import AuthService
from src.services.language_service import LanguageService
from src.utils.config import config
from src.utils.logger import bot_logger
from src.utils.database import get_db_session

# 会话状态
WAITING_FOR_MATH_ANSWER, WAITING_FOR_LANGUAGE_SELECTION = range(2)


class AuthHandler:
    """认证处理器"""

    # 用于跟踪已处理的新成员，避免重复处理
    _processed_members = set()

    # 用于跟踪正在验证的用户上下文
    _verification_contexts = {}

    @staticmethod
    async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理新成员加入群组 - 使用Rose验证系统"""
        # 处理新成员加入消息
        if update.message and update.message.new_chat_members:
            for new_member in update.message.new_chat_members:
                if new_member.is_bot:
                    continue

                user_id = new_member.id
                user_name = new_member.first_name or new_member.username or "Unknown"

                # 创建唯一标识符来避免重复处理
                member_key = f"{update.effective_chat.id}_{user_id}_{int(datetime.utcnow().timestamp()//60)}"  # 按分钟分组

                # 检查是否已经处理过这个用户（在同一分钟内）
                if member_key in AuthHandler._processed_members:
                    bot_logger.info(f"User {user_id} already processed in this minute, skipping duplicate")
                    continue

                # 添加到已处理列表
                AuthHandler._processed_members.add(member_key)

                # 清理旧的缓存条目（保留最近5分钟的）
                current_time = int(datetime.utcnow().timestamp()//60)
                AuthHandler._processed_members = {
                    key for key in AuthHandler._processed_members
                    if int(key.split('_')[-1]) > current_time - 5
                }

                bot_logger.info(f"New member joined: {user_name} (ID: {user_id})")

                try:
                    # 立即限制新成员权限
                    await AuthHandler._restrict_new_member(context, user_id, update.effective_chat.id)

                    # 立即发送语言选择界面给新用户
                    await AuthHandler._send_language_selection_menu(context, user_id, update.effective_chat.id, user_name)
                    bot_logger.info(f"Sent language selection menu to new user {user_id}")

                    # 设置5分钟验证超时定时器
                    if context.job_queue:
                        job = context.job_queue.run_once(
                            AuthHandler._check_math_verification_timeout,
                            300,  # 5分钟 = 300秒
                            data={
                                'user_id': user_id,
                                'chat_id': update.effective_chat.id,
                                'user_name': user_name,
                                'join_time': datetime.utcnow().timestamp()
                            }
                        )
                        bot_logger.info(f"Set 5-minute verification timeout for user {user_id} - Job ID: {job.job_id if hasattr(job, 'job_id') else 'N/A'}")
                    else:
                        bot_logger.warning("Job queue not available, cannot set verification timeout")

                except Exception as e:
                    bot_logger.error(f"Error handling new member {user_id}: {e}")

        # 处理ChatMemberUpdated事件
        elif update.chat_member:
            chat_member_update = update.chat_member
            new_member = chat_member_update.new_chat_member
            old_member = chat_member_update.old_chat_member

            # 检查是否是新成员加入（从非成员状态变为成员状态）
            if (hasattr(old_member, 'status') and hasattr(new_member, 'status') and
                old_member.status in ['left', 'kicked'] and
                new_member.status in ['member', 'administrator', 'creator']):

                user = new_member.user
                if user.is_bot:
                    return

                user_id = user.id
                user_name = user.first_name or user.username or "Unknown"

                # 创建唯一标识符来避免重复处理
                member_key = f"{chat_member_update.chat.id}_{user_id}_{int(datetime.utcnow().timestamp()//60)}"  # 按分钟分组

                # 检查是否已经处理过这个用户（在同一分钟内）
                if member_key in AuthHandler._processed_members:
                    bot_logger.info(f"User {user_id} already processed in this minute via chat member update, skipping duplicate")
                    return

                # 添加到已处理列表
                AuthHandler._processed_members.add(member_key)

                # 清理旧的缓存条目（保留最近5分钟的）
                current_time = int(datetime.utcnow().timestamp()//60)
                AuthHandler._processed_members = {
                    key for key in AuthHandler._processed_members
                    if int(key.split('_')[-1]) > current_time - 5
                }

                bot_logger.info(f"New member joined via chat member update: {user_name} (ID: {user_id})")

                try:
                    # 立即限制新成员权限
                    await AuthHandler._restrict_new_member(context, user_id, chat_member_update.chat.id)

                    # 立即发送语言选择界面给新用户
                    await AuthHandler._send_language_selection_menu(context, user_id, chat_member_update.chat.id, user_name)
                    bot_logger.info(f"Sent language selection menu to new user {user_id} (chat member)")

                    # 设置5分钟验证超时定时器
                    if context.job_queue:
                        job = context.job_queue.run_once(
                            AuthHandler._check_math_verification_timeout,
                            300,  # 5分钟 = 300秒
                            data={
                                'user_id': user_id,
                                'chat_id': chat_member_update.chat.id,
                                'user_name': user_name,
                                'join_time': datetime.utcnow().timestamp()
                            }
                        )
                        bot_logger.info(f"Set 5-minute verification timeout for user {user_id} (chat member) - Job ID: {job.job_id if hasattr(job, 'job_id') else 'N/A'}")
                    else:
                        bot_logger.warning("Job queue not available, cannot set verification timeout")

                except Exception as e:
                    bot_logger.error(f"Error handling new member via chat update {user_id}: {e}")

    @staticmethod
    async def handle_message_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理用户在群组中输入的消息 - 现在使用4选1按钮，忽略文字输入"""
        # 添加调试日志
        bot_logger.info(f"Message received from user {update.effective_user.id}: '{update.message.text}' in chat {update.effective_chat.id}")

        # 只处理群组消息
        if not update.message or not update.message.chat.type in ['group', 'supergroup']:
            bot_logger.info(f"Ignoring non-group message")
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        user_message = update.message.text

        # 检查是否是机器人消息
        if update.effective_user.is_bot:
            bot_logger.info(f"Ignoring bot message")
            return

        try:
            # 检查用户是否有正在进行的验证
            if user_id in AuthHandler._verification_contexts:
                # 用户正在验证中，但现在使用4选1按钮，删除文字消息并提示使用按钮
                bot_logger.info(f"User {user_id} is in verification but sent text message, deleting and ignoring (using 4-choice buttons now)")

                # 删除用户输入的消息
                try:
                    await context.bot.delete_message(chat_id, update.message.message_id)
                except:
                    pass
                return

            # 如果用户不在验证上下文中，正常处理其他消息（不做任何处理）
            bot_logger.info(f"User {user_id} not in verification contexts, ignoring message")

        except Exception as e:
            bot_logger.error(f"Error handling message: {e}")
            # 删除用户输入的消息
            try:
                await context.bot.delete_message(chat_id, update.message.message_id)
            except:
                pass

    @staticmethod
    async def _send_verification_expired_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, verification_context: dict):
        """发送验证超时消息"""
        try:
            # 更新验证消息
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=verification_context['verification_message_id'],
                text="⏰ 验证已超时，请重新加入群组。"
            )

            # 设置5分钟后自动删除验证超时消息
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': verification_context['verification_message_id']
                    }
                )

            # 删除验证码图片
            if 'image_message_id' in verification_context:
                try:
                    await context.bot.delete_message(chat_id, verification_context['image_message_id'])
                except:
                    pass

            # 清理验证上下文
            if user_id in AuthHandler._verification_contexts:
                del AuthHandler._verification_contexts[user_id]

        except Exception as e:
            bot_logger.error(f"Error sending verification expired message: {e}")

    @staticmethod
    async def _send_verification_success_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, verification_context: dict):
        """发送验证成功消息"""
        try:
            # 首先取消原来的自动删除任务
            if 'auto_delete_job' in verification_context:
                try:
                    verification_context['auto_delete_job'].schedule_removal()
                    bot_logger.info(f"🔄 CANCEL: Cancelled original auto-delete job for message {verification_context['verification_message_id']}")
                except Exception as cancel_e:
                    bot_logger.warning(f"🔄 CANCEL: Could not cancel original delete job: {cancel_e}")

            # 获取本地化文本
            success_text = await LanguageService.get_text(user_id, "correct_answer")
            welcome_text = await LanguageService.get_text(user_id, "welcome", username=f"user{user_id}")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                f"🎉 {success_text}",
                "",
                welcome_text,
                "",
                help_title,
                "",
                help_commands,
                "",
                "📱 Send /start to the bot for private interactive menu."
            ]

            message = "\n".join(message_lines)

            # 更新验证消息
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=verification_context['verification_message_id'],
                text=message
            )

            # 设置5分钟后自动删除验证成功消息
            if context.job_queue:
                new_job = context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': verification_context['verification_message_id']
                    }
                )
                bot_logger.info(f"🚀 NEW-SCHEDULE: Created new auto-delete job for success message {verification_context['verification_message_id']}")

            # 删除验证码图片
            if 'image_message_id' in verification_context:
                try:
                    await context.bot.delete_message(chat_id, verification_context['image_message_id'])
                except:
                    pass

            # 删除选择按钮消息
            if 'choice_message_id' in verification_context:
                try:
                    await context.bot.delete_message(chat_id, verification_context['choice_message_id'])
                except:
                    pass

            # 授予用户完整权限
            await AuthHandler._grant_full_permissions(context, user_id, chat_id)

            bot_logger.info(f"Sent verification success message for user {user_id}")

        except Exception as e:
            bot_logger.error(f"Error sending verification success message: {e}")

    @staticmethod
    async def _send_wrong_answer_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, challenge_id: int, remaining_attempts: int, verification_context: dict):
        """发送答案错误消息"""
        try:
            # 获取挑战信息
            challenge_record = await AuthService.get_challenge(challenge_id)
            if not challenge_record:
                await AuthHandler._send_verification_expired_message(context, user_id, chat_id, verification_context)
                return

            # 获取本地化文本
            wrong_answer_text = await LanguageService.get_text(user_id, "wrong_answer")
            time_left_text = await LanguageService.get_text(user_id, "time_left", time="5")

            # 构建更新后的消息 - 不显示文字版问题
            message_lines = [
                f"❌ {wrong_answer_text}",
                "",
                f"⏰ {time_left_text}",
                f"🎯 剩余机会：{remaining_attempts}/3",
                "",
                "💬 请重新输入答案数字"
            ]

            message = "\n".join(message_lines)

            # 更新验证消息
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=verification_context['verification_message_id'],
                text=message
            )

        except Exception as e:
            bot_logger.error(f"Error sending wrong answer message: {e}")

    @staticmethod
    async def _send_verification_failed_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, verification_context: dict):
        """发送验证失败消息"""
        try:
            # 更新验证消息
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=verification_context['verification_message_id'],
                text="❌ 验证失败，答案错误。"
            )

            # 设置5分钟后自动删除验证失败消息
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': verification_context['verification_message_id']
                    }
                )

            # 删除验证码图片
            if 'image_message_id' in verification_context:
                try:
                    await context.bot.delete_message(chat_id, verification_context['image_message_id'])
                except:
                    pass

            # 删除选择按钮消息
            if 'choice_message_id' in verification_context:
                try:
                    await context.bot.delete_message(chat_id, verification_context['choice_message_id'])
                except:
                    pass

        except Exception as e:
            bot_logger.error(f"Error sending verification failed message: {e}")

    @staticmethod
    async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理语言选择和数学验证答案"""
        query = update.callback_query
        await query.answer()

        bot_logger.info(f"Received callback query: {query.data} from user {update.effective_user.id}")

        if query.data.startswith("lang_"):
            # 处理语言选择
            bot_logger.info(f"Processing language selection: {query.data}")
            await AuthHandler._handle_language_selection(query, update, context)
        elif query.data.startswith("answer_"):
            # 处理数学验证答案
            bot_logger.info(f"Processing math answer: {query.data}")
            await AuthHandler._handle_math_answer(query, update, context)
        else:
            # 未知的回调数据
            bot_logger.warning(f"Unknown callback data: {query.data}")
            await query.answer("❌ Unknown action.", show_alert=True)

    @staticmethod
    async def _handle_language_selection(query, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理语言选择"""
        parts = query.data.split("_")
        if len(parts) >= 3:
            # 新格式：lang_{language_code}_{user_id}
            language_code = parts[1]
            target_user_id = int(parts[2])
            user_id = update.effective_user.id

            # 只允许目标用户自己选择语言
            if user_id != target_user_id:
                await query.answer("❌ You can only select language for yourself.", show_alert=True)
                return

            # 检查是否是新用户验证流程（通过检查用户是否刚加入且未验证）
            is_new_member_verification = await AuthHandler._is_new_member_verification(user_id)
        else:
            # 旧格式：lang_{language_code}（普通语言选择，如/lang命令）
            language_code = parts[1]
            user_id = update.effective_user.id
            is_new_member_verification = False

        try:
            # 保存用户语言偏好
            await LanguageService.set_user_language(user_id, language_code)

            # 获取语言名称
            languages = await LanguageService.get_available_languages()
            language_name = languages.get(language_code, language_code)

            bot_logger.info(f"User {user_id} selected language: {language_code}")

            if is_new_member_verification:
                # 新用户验证流程：生成数学验证码
                bot_logger.info(f"New member {user_id} selected language, sending verification challenge")
                await AuthHandler._send_math_challenge_in_group(query, user_id, language_code, update.effective_chat.id, context)
            else:
                # 普通语言选择：只更新语言设置，显示确认
                bot_logger.info(f"User {user_id} changed language preference to {language_code}")
                await AuthHandler._send_language_change_confirmation(query, user_id, language_code, update.effective_chat.id)

        except Exception as e:
            bot_logger.error(f"Error setting language for user {user_id}: {e}")
            await query.edit_message_text("❌ Error setting language. Please try again.")

    @staticmethod
    async def _handle_math_answer(query, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理4选1数学验证答案"""
        try:
            # 解析回调数据：answer_{answer}_{user_id}_{challenge_id}
            parts = query.data.split("_")
            if len(parts) != 4:
                await query.answer("❌ Invalid answer format.", show_alert=True)
                return

            answer = parts[1]  # A, B, C, D
            target_user_id = int(parts[2])
            challenge_id = int(parts[3])
            user_id = update.effective_user.id

            # 只允许目标用户自己答题
            if user_id != target_user_id:
                await query.answer("❌ You can only answer your own challenge.", show_alert=True)
                return

            # 检查用户是否在验证上下文中
            if user_id not in AuthHandler._verification_contexts:
                await query.answer("❌ Verification context not found.", show_alert=True)
                return

            verification_context = AuthHandler._verification_contexts[user_id]

            # 验证答案（仅一次机会）
            is_correct, remaining_attempts, is_expired = await AuthService.verify_answer(challenge_id, answer)

            if is_expired:
                await AuthHandler._send_verification_expired_message(
                    context, user_id, update.effective_chat.id, verification_context
                )
                # 清理验证上下文
                if user_id in AuthHandler._verification_contexts:
                    del AuthHandler._verification_contexts[user_id]
                return

            if is_correct:
                # 答案正确，标记用户已验证
                bot_logger.info(f"User {user_id} answered correctly with choice {answer}!")
                await AuthService.mark_user_verified(user_id)
                await AuthHandler._send_verification_success_message(
                    context, user_id, update.effective_chat.id, verification_context
                )
                # 清理验证上下文
                if user_id in AuthHandler._verification_contexts:
                    del AuthHandler._verification_contexts[user_id]
                bot_logger.info(f"User {user_id} passed 4-choice captcha verification")
            else:
                # 答案错误，立即踢出用户（仅一次机会）
                bot_logger.info(f"User {user_id} answered incorrectly with choice {answer}! Kicking immediately...")
                await AuthHandler._send_verification_failed_message(
                    context, user_id, update.effective_chat.id, verification_context
                )
                await AuthHandler._kick_unverified_user(
                    update.effective_chat.id,
                    user_id,
                    context,
                    "Failed 4-choice captcha verification - incorrect answer",
                    f"user{user_id}",
                    exclude_from_stats=True
                )
                # 清理验证上下文
                if user_id in AuthHandler._verification_contexts:
                    del AuthHandler._verification_contexts[user_id]
                bot_logger.info(f"User {user_id} failed 4-choice captcha verification - kicked immediately")

        except Exception as e:
            bot_logger.error(f"Error handling 4-choice answer: {e}")
            await query.answer("❌ Error processing answer. Please try again.", show_alert=True)

    @staticmethod
    async def _send_math_challenge_in_group(query, user_id: int, language_code: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """在群组中生成并发送图形验证码"""
        try:
            # 获取语言名称确认
            languages = await LanguageService.get_available_languages()
            language_name = languages.get(language_code, language_code)

            # 生成图形验证码
            challenge = await AuthService.generate_math_challenge()
            challenge_record = await AuthService.create_challenge(user_id, challenge)

            # 获取本地化文本
            verification_text = await LanguageService.get_text(user_id, "verification_question")
            time_left_text = await LanguageService.get_text(user_id, "time_left", time="5")

            # 构建消息 - 不显示文字版问题，只有一次机会，4选1格式
            message_lines = [
                f"✅ Language set to {language_name}",
                "",
                f"👋 验证开始！@user{user_id}",
                "",
                verification_text,
                "",
                f"⏰ {time_left_text}",
                f"🎯 机会：1/1 (仅一次机会)",
                "",
                "💬 请看图片并从下面选项中选择正确答案"
            ]

            message = "\n".join(message_lines)

            # 先编辑消息内容
            await query.edit_message_text(message)

            # 初始化上下文数据（无论是否有图片都要创建）
            context_data = {
                'user_id': user_id,
                'challenge_id': challenge_record.id,
                'chat_id': chat_id,
                'verification_message_id': query.message.message_id,
            }

            # 如果之前有auto_delete_job，保留它
            if user_id in AuthHandler._verification_contexts and 'auto_delete_job' in AuthHandler._verification_contexts[user_id]:
                context_data['auto_delete_job'] = AuthHandler._verification_contexts[user_id]['auto_delete_job']

            # 发送图形验证码（如果有图片数据）
            if challenge.get('image_data') and len(challenge['image_data']) > 0:
                from io import BytesIO

                # 发送验证码图片
                image_buffer = BytesIO(challenge['image_data'])
                sent_photo = await query.message.reply_photo(
                    photo=image_buffer,
                    caption=f"🔢 验证码图片 - @user{user_id}\n\n请从下面的选项中选择正确答案："
                )

                # 添加图片消息ID到上下文
                context_data['image_message_id'] = sent_photo.message_id

                # 创建4选1按钮
                options = challenge.get('options', [])
                keyboard = []
                option_letters = ['A', 'B', 'C', 'D']
                for i, option_value in enumerate(options):
                    letter = option_letters[i]
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{letter}. {option_value}",
                            callback_data=f"answer_{letter}_{user_id}_{challenge_record.id}"
                        )
                    ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # 发送选择按钮
                choice_message = await query.message.reply_text(
                    f"请选择正确答案 (仅一次机会):",
                    reply_markup=reply_markup
                )

                # 添加选择按钮消息ID到上下文
                context_data['choice_message_id'] = choice_message.message_id

                # 设置5分钟后自动删除CAPTCHA图片
                if context.job_queue:
                    context.job_queue.run_once(
                        AuthHandler._delete_group_message,
                        300,  # 5分钟 = 300秒
                        data={
                            'chat_id': chat_id,
                            'message_id': sent_photo.message_id
                        }
                    )

                # 设置5分钟后自动删除选择按钮
                if context.job_queue:
                    context.job_queue.run_once(
                        AuthHandler._delete_group_message,
                        300,  # 5分钟 = 300秒
                        data={
                            'chat_id': chat_id,
                            'message_id': choice_message.message_id
                        }
                    )

                bot_logger.info(f"Sent image captcha challenge in group for user {user_id} - Challenge ID: {challenge_record.id}")

            else:
                # 没有图片，创建文字选择题
                options = challenge.get('options', [])
                keyboard = []
                option_letters = ['A', 'B', 'C', 'D']
                for i, option_value in enumerate(options):
                    letter = option_letters[i]
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{letter}. {option_value}",
                            callback_data=f"answer_{letter}_{user_id}_{challenge_record.id}"
                        )
                    ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # 发送选择按钮（附加到原消息）
                choice_message = await query.message.reply_text(
                    f"数学题：{challenge['question']}\n\n请选择正确答案 (仅一次机会):",
                    reply_markup=reply_markup
                )

                # 添加选择按钮消息ID到上下文
                context_data['choice_message_id'] = choice_message.message_id

                # 设置5分钟后自动删除选择按钮
                if context.job_queue:
                    context.job_queue.run_once(
                        AuthHandler._delete_group_message,
                        300,  # 5分钟 = 300秒
                        data={
                            'chat_id': chat_id,
                            'message_id': choice_message.message_id
                        }
                    )

                bot_logger.info(f"Sent text math challenge in group for user {user_id} - Challenge ID: {challenge_record.id}")

            # 设置5分钟后自动删除验证消息（如果用户未完成验证）
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._auto_delete_verification_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'user_id': user_id,
                        'chat_id': chat_id,
                        'message_id': query.message.message_id
                    }
                )

            # 将验证信息存储到用户上下文中（在所有情况下都存储）
            AuthHandler._verification_contexts[user_id] = context_data
            bot_logger.info(f"Created verification context for user {user_id}: {context_data}")

        except Exception as e:
            bot_logger.error(f"Error sending image captcha challenge in group for user {user_id}: {e}")
            import traceback
            bot_logger.error(f"Full traceback: {traceback.format_exc()}")
            await query.edit_message_text("❌ Error generating verification challenge. Please try again.")

    @staticmethod
    async def _update_challenge_attempts(query, user_id: int, challenge_id: int, remaining_attempts: int):
        """更新挑战尝试次数"""
        try:
            # 获取挑战信息
            challenge_record = await AuthService.get_challenge(challenge_id)
            if not challenge_record:
                await query.edit_message_text("❌ 验证挑战已过期。")
                return

            # 获取本地化文本
            wrong_answer_text = await LanguageService.get_text(user_id, "wrong_answer")
            time_left_text = await LanguageService.get_text(user_id, "time_left", time="5")

            # 构建更新后的消息
            message_lines = [
                f"❌ {wrong_answer_text}",
                "",
                f"📝 问题：{challenge_record.question}",
                "",
                f"⏰ {time_left_text}",
                f"🎯 剩余机会：{remaining_attempts}/3"
            ]

            message = "\n".join(message_lines)

            # 重新生成答案选项键盘
            keyboard = []
            import json
            options = json.loads(challenge_record.options) if challenge_record.options else []
            for i, option in enumerate(options):
                keyboard.append([
                    InlineKeyboardButton(
                        f"{chr(65 + i)}. {option}",
                        callback_data=f"answer_{chr(65 + i)}_{user_id}_{challenge_id}"
                    )
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup)

        except Exception as e:
            bot_logger.error(f"Error updating challenge attempts: {e}")
            await query.edit_message_text("❌ Error updating challenge.")

    @staticmethod
    async def _send_verification_success_in_group(query, user_id: int, chat_id: int):
        """在群组中显示验证成功和start界面"""
        try:
            # 获取本地化文本
            success_text = await LanguageService.get_text(user_id, "correct_answer")
            welcome_text = await LanguageService.get_text(user_id, "welcome", username=f"user{user_id}")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                f"🎉 {success_text}",
                "",
                welcome_text,
                "",
                help_title,
                "",
                help_commands,
                "",
                "📱 Send /start to the bot for private interactive menu."
            ]

            message = "\n".join(message_lines)

            # 编辑消息内容，移除键盘
            await query.edit_message_text(message)

            bot_logger.info(f"Sent verification success in group for user {user_id}")

        except Exception as e:
            bot_logger.error(f"Error sending verification success in group for user {user_id}: {e}")
            await query.edit_message_text("🎉 验证成功！欢迎加入群组！")

    @staticmethod
    async def _send_start_menu_in_group_after_language_selection(query, user_id: int, language_code: str, chat_id: int):
        """语言选择后在群组中显示 start 菜单界面"""
        try:
            # 获取本地化文本
            welcome_text = await LanguageService.get_text(user_id, "welcome", username=f"user{user_id}")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            # 获取语言名称确认
            languages = await LanguageService.get_available_languages()
            language_name = languages.get(language_code, language_code)

            message_lines = [
                f"✅ Language set to {language_name}",
                "",
                welcome_text,
                "",
                help_title,
                "",
                help_commands,
                "",
                "📱 Send /start to the bot for private interactive menu."
            ]

            message = "\n".join(message_lines)

            # 编辑消息内容，移除键盘
            await query.edit_message_text(message)

            bot_logger.info(f"Sent start menu in group for user {user_id} after language selection")

        except Exception as e:
            bot_logger.error(f"Error sending start menu in group after language selection for user {user_id}: {e}")
            await query.edit_message_text("❌ Error loading menu. Please try again.")

    @staticmethod
    async def _send_start_menu_after_language_selection(query, user_id: int, language_code: str):
        """语言选择后发送 start 菜单界面"""
        try:
            # 获取本地化文本
            welcome_text = await LanguageService.get_text(user_id, "welcome", username=f"user{user_id}")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            # 获取语言名称确认
            languages = await LanguageService.get_available_languages()
            language_name = languages.get(language_code, language_code)

            message_lines = [
                f"✅ Language set to {language_name}",
                "",
                welcome_text,
                "",
                help_title,
                "",
                help_commands
            ]

            message = "\n".join(message_lines)

            # 创建完整功能键盘（不依赖验证状态）
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

            bot_logger.info(f"Sent start menu to user {user_id} after language selection")

        except Exception as e:
            bot_logger.error(f"Error sending start menu after language selection for user {user_id}: {e}")
            await query.edit_message_text("❌ Error loading menu. Please try again.")

    @staticmethod
    async def _check_math_verification_timeout(context: ContextTypes.DEFAULT_TYPE):
        """检查数学验证超时的定时任务 - 5分钟后检查用户是否完成验证"""
        job_data = context.job.data
        user_id = job_data['user_id']
        chat_id = job_data['chat_id']
        user_name = job_data.get('user_name', 'Unknown')
        join_time = job_data.get('join_time')

        try:
            # 检查用户是否已经通过验证
            is_verified = await AuthService.is_user_verified(user_id)

            if is_verified:
                bot_logger.info(f"User {user_id} ({user_name}) has already passed verification")
                return

            # 检查用户是否还在群组中
            try:
                chat_member = await context.bot.get_chat_member(chat_id, user_id)
                if chat_member.status in ['left', 'kicked', 'banned']:
                    bot_logger.info(f"User {user_id} no longer in group (status: {chat_member.status}) - timeout cleanup")
                    await AuthHandler._remove_from_invitation_stats(user_id)
                    return
            except Exception as e:
                bot_logger.warning(f"Could not get chat member status for user {user_id}: {e}")
                await AuthHandler._remove_from_invitation_stats(user_id)
                return

            # 用户未通过验证且仍在群组中，踢出用户
            bot_logger.info(f"User {user_id} ({user_name}) failed to complete math verification within 5 minutes")
            await AuthHandler._kick_unverified_user(
                chat_id,
                user_id,
                context,
                "Failed to complete math verification within 5 minutes",
                user_name,
                exclude_from_stats=True
            )

        except Exception as e:
            bot_logger.error(f"Error in math verification timeout check for user {user_id}: {e}")
            # 如果无法获取用户状态，从统计中移除
            await AuthHandler._remove_from_invitation_stats(user_id)

    @staticmethod
    async def _send_immediate_welcome_menu(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, user_name: str):
        """立即在群组中发送欢迎start菜单给新加入的用户"""
        try:
            # 获取本地化文本，使用用户名格式化欢迎消息
            welcome_text = await LanguageService.get_text(user_id, "welcome", username=user_name)
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                welcome_text,
                "",
                help_title,
                "",
                help_commands,
                "",
                "📱 Send /start to the bot for interactive menu."
            ]

            message = "\n".join(message_lines)

            # 创建基础功能键盘（在群组中显示）
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = [
                [
                    InlineKeyboardButton("🌍 Language", callback_data="help_language"),
                    InlineKeyboardButton("❓ About Bot", callback_data="help_about")
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="help_refresh")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            # 在群组中发送消息
            sent_message = await context.bot.send_message(
                chat_id=chat_id,  # 发送到群组
                text=message,
                reply_markup=reply_markup
            )

            # 设置5分钟后自动删除消息的定时任务
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': sent_message.message_id
                    }
                )

        except Exception as e:
            bot_logger.error(f"Error sending immediate welcome menu to group for user {user_id}: {e}")

    @staticmethod
    async def _send_language_selection_menu(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, user_name: str):
        """向新用户在群组中发送语言选择菜单"""
        try:
            # 获取可用语言列表
            languages = await LanguageService.get_available_languages()

            # 创建语言选择键盘 - 显示所有可用语言，每行2个按钮
            keyboard = []
            row = []
            for lang_code, lang_name in languages.items():
                # 为新用户验证流程添加用户ID到回调数据中
                button = InlineKeyboardButton(
                    f"{lang_name}",
                    callback_data=f"lang_{lang_code}_{user_id}"
                )
                row.append(button)

                # 每行2个按钮
                if len(row) == 2:
                    keyboard.append(row)
                    row = []

            # 如果最后一行还有按钮，添加到键盘
            if row:
                keyboard.append(row)

            reply_markup = InlineKeyboardMarkup(keyboard)

            # 发送语言选择消息到群组
            message_text = f"👋 Welcome @{user_name}!\n\nPlease choose your preferred language:\n请选择您的首选语言："

            sent_message = await context.bot.send_message(
                chat_id=chat_id,  # 发送到群组
                text=message_text,
                reply_markup=reply_markup
            )

            # 设置5分钟后自动删除消息的定时任务
            if context.job_queue:
                job = context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': sent_message.message_id
                    }
                )
                bot_logger.info(f"🚀 SCHEDULE: Auto-deletion job created for message {sent_message.message_id}")
                bot_logger.info(f"🚀 SCHEDULE: Job ID: {job.job_id if hasattr(job, 'job_id') else 'N/A'}")
                bot_logger.info(f"🚀 SCHEDULE: Will execute in 300 seconds (5 minutes)")
                bot_logger.info(f"🚀 SCHEDULE: Job data: chat_id={chat_id}, message_id={sent_message.message_id}")

                # 将job存储到verification_contexts中，以便后续取消
                if user_id in AuthHandler._verification_contexts:
                    AuthHandler._verification_contexts[user_id]['auto_delete_job'] = job
                else:
                    AuthHandler._verification_contexts[user_id] = {'auto_delete_job': job}
            else:
                bot_logger.error("❌ SCHEDULE: Job queue not available! Cannot schedule message deletion!")

            bot_logger.info(f"Sent language selection menu to group for user {user_id} with {len(languages)} languages")

        except Exception as e:
            bot_logger.error(f"Error sending language selection menu to group for user {user_id}: {e}")

    @staticmethod
    async def _send_group_verification_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, user_name: str):
        """在群组中发送验证通过的简单通知"""
        try:
            message = f"🎉 Congratulations @{user_name}! You have successfully passed the verification. Send /start to the bot for all available features."

            # 在群组中发送简单通知
            sent_message = await context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

            # 设置5分钟后自动删除消息的定时任务
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': sent_message.message_id
                    }
                )

        except Exception as e:
            bot_logger.error(f"Error sending group verification notification for user {user_id}: {e}")

    @staticmethod
    async def _send_verification_passed_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """发送验证通过通知给用户"""
        try:
            # 获取本地化文本
            welcome_text = await LanguageService.get_text(user_id, "welcome")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                "🎉 Verification Successful!",
                "",
                "Congratulations! You have successfully passed the verification.",
                "You now have access to all bot features.",
                "",
                help_title,
                "",
                help_commands
            ]

            message = "\n".join(message_lines)

            # 创建完整功能键盘（已验证用户）
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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

            # 发送私信消息给用户
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error sending verification passed notification to user {user_id}: {e}")

    @staticmethod
    async def _send_welcome_start_menu(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int):
        """发送欢迎start菜单给通过验证的用户"""
        try:
            # 获取本地化文本
            welcome_text = await LanguageService.get_text(user_id, "welcome")
            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                welcome_text,
                "",
                "🎉 Congratulations! You have successfully passed the verification!",
                "",
                help_title,
                "",
                help_commands
            ]

            message = "\n".join(message_lines)

            # 创建功能键盘（已验证用户显示完整功能）
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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

            # 发送私信消息给用户
            await context.bot.send_message(
                chat_id=user_id,  # 发送到用户的私聊
                text=message,
                reply_markup=reply_markup
            )

        except Exception as e:
            bot_logger.error(f"Error sending welcome start menu to user {user_id}: {e}")
            # 如果无法发送私信，尝试在群组中提及用户
            try:
                mention_text = f"🎉 Welcome @{user_id}! You have passed verification. Please send /start to the bot for available commands."
                await context.bot.send_message(chat_id=chat_id, text=mention_text)
            except Exception as e2:
                bot_logger.error(f"Error sending group mention for user {user_id}: {e2}")

    @staticmethod
    async def _kick_unverified_user(
        chat_id: int,
        user_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        reason: str,
        user_name: str = "Unknown",
        exclude_from_stats: bool = False
    ):
        """踢出未验证的用户，可选择是否排除在统计之外"""
        try:
            # 踢出用户
            await context.bot.ban_chat_member(chat_id, user_id)

            # 立即解除封禁（这样用户可以再次被邀请）
            await context.bot.unban_chat_member(chat_id, user_id)

            # 发送踢出通知
            kick_message = f"👋 {user_name} has been removed from the group due to: {reason}"
            sent_message = await context.bot.send_message(chat_id, kick_message)

            # 设置5分钟后自动删除消息的定时任务
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': sent_message.message_id
                    }
                )

            if exclude_from_stats:
                # 如果需要排除在统计之外，从邀请统计中移除此用户
                # 这里需要实现从KOL邀请统计中移除的逻辑
                await AuthHandler._remove_from_invitation_stats(user_id)
                bot_logger.info(f"User {user_id} excluded from invitation statistics")

            bot_logger.info(f"User {user_id} ({user_name}) kicked for: {reason}")

        except TelegramError as e:
            if "Not enough rights" in str(e):
                bot_logger.warning(f"Bot doesn't have permission to kick user {user_id}")
            else:
                bot_logger.error(f"Error kicking user {user_id}: {e}")
        except Exception as e:
            bot_logger.error(f"Error kicking user {user_id}: {e}")

    @staticmethod
    async def _remove_from_invitation_stats(user_id: int):
        """从邀请统计中移除用户（不计入KOL邀请数量）"""
        try:
            from src.services.invitation_service import InvitationService

            # 查找是通过哪个邀请链接加入的
            async with get_db_session() as session:
                # 查找该用户的邀请记录
                from src.models import InvitationMember
                result = await session.execute(
                    select(InvitationMember).where(
                        InvitationMember.invited_user_id == user_id
                    )
                )
                invitation_member = result.scalar_one_or_none()

                if invitation_member:
                    # 删除邀请记录
                    await session.delete(invitation_member)

                    # 更新邀请链接的统计
                    await InvitationService.update_invitation_stats(invitation_member.invite_code)

                    await session.commit()
                    bot_logger.info(f"Removed user {user_id} from invitation statistics for invite {invitation_member.invite_code}")

        except Exception as e:
            bot_logger.error(f"Error removing user {user_id} from invitation stats: {e}")

    @staticmethod
    async def _kick_user_for_failed_verification(
        chat_id: int,
        user_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        reason: str,
        message_id: int = None
    ):
        """踢出验证失败的用户"""
        try:
            # 踢出用户
            await context.bot.ban_chat_member(chat_id, user_id)

            # 立即解除封禁（这样用户可以再次被邀请）
            await context.bot.unban_chat_member(chat_id, user_id)

            # 发送踢出通知
            kick_message = f"👋 User has been removed from the group due to: {reason}"
            sent_message = await context.bot.send_message(chat_id, kick_message)

            # 设置5分钟后自动删除消息的定时任务
            if context.job_queue:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    300,  # 5分钟 = 300秒
                    data={
                        'chat_id': chat_id,
                        'message_id': sent_message.message_id
                    }
                )

            # 删除验证消息（如果有）
            if message_id:
                try:
                    await context.bot.delete_message(chat_id, message_id)
                except:
                    pass

            bot_logger.info(f"User {user_id} kicked for: {reason}")

        except TelegramError as e:
            if "Not enough rights" in str(e):
                bot_logger.warning(f"Bot doesn't have permission to kick user {user_id}")
            else:
                bot_logger.error(f"Error kicking user {user_id}: {e}")
        except Exception as e:
            bot_logger.error(f"Error kicking user {user_id}: {e}")

    @staticmethod
    async def handle_left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理成员离开群组"""
        left_member = update.message.left_chat_member
        if left_member and not left_member.is_bot:
            user_id = left_member.id
            user_name = left_member.first_name or left_member.username or "Unknown"

            bot_logger.info(f"Member left: {user_name} (ID: {user_id})")

            # 这里可以更新统计数据
            # TODO: 实现离开统计功能

    @staticmethod
    async def _send_group_message_with_auto_delete(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        text: str = None,
        reply_markup = None,
        photo = None,
        caption: str = None,
        edit_message_id: int = None,
        delete_after_minutes: int = 5
    ):
        """统一的群组消息发送函数，自动设置5分钟后删除

        Args:
            context: Telegram上下文
            chat_id: 群组ID
            text: 消息文本
            reply_markup: 键盘标记
            photo: 图片数据 (BytesIO对象)
            caption: 图片说明
            edit_message_id: 如果提供，则编辑此消息而不是发送新消息
            delete_after_minutes: 多少分钟后删除（默认5分钟）

        Returns:
            发送的消息对象
        """
        try:
            sent_message = None

            if edit_message_id:
                # 编辑现有消息
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=edit_message_id,
                    text=text,
                    reply_markup=reply_markup
                )
                # 对于编辑的消息，使用原消息ID
                message_id_to_delete = edit_message_id

            elif photo:
                # 发送图片消息
                sent_message = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    reply_markup=reply_markup
                )
                message_id_to_delete = sent_message.message_id

            else:
                # 发送文本消息
                sent_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup
                )
                message_id_to_delete = sent_message.message_id

            # 设置自动删除定时任务
            if context.job_queue and delete_after_minutes > 0:
                context.job_queue.run_once(
                    AuthHandler._delete_group_message,
                    delete_after_minutes * 60,  # 转换为秒
                    data={
                        'chat_id': chat_id,
                        'message_id': message_id_to_delete
                    }
                )
                bot_logger.info(f"Scheduled auto-deletion for message {message_id_to_delete} in {delete_after_minutes} minutes")

            return sent_message

        except Exception as e:
            bot_logger.error(f"Error sending group message with auto-delete: {e}")
            raise

    @staticmethod
    async def _delete_group_message(context: ContextTypes.DEFAULT_TYPE):
        """删除群组消息的定时任务（5分钟后自动执行）"""
        job_data = context.job.data
        chat_id = job_data['chat_id']
        message_id = job_data['message_id']

        bot_logger.info(f"🔥 AUTO-DELETE: Job triggered for message {message_id} in chat {chat_id}")
        bot_logger.info(f"🔥 AUTO-DELETE: Job data: {job_data}")

        try:
            # 先检查bot的权限
            try:
                chat_member = await context.bot.get_chat_member(chat_id, context.bot.id)
                bot_logger.info(f"🔥 AUTO-DELETE: Bot status in chat: {chat_member.status}")
                if hasattr(chat_member, 'can_delete_messages'):
                    bot_logger.info(f"🔥 AUTO-DELETE: Can delete messages: {chat_member.can_delete_messages}")
            except Exception as perm_e:
                bot_logger.warning(f"🔥 AUTO-DELETE: Could not check bot permissions: {perm_e}")

            # 尝试删除消息
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            bot_logger.info(f"✅ AUTO-DELETE: Successfully deleted group message {message_id} in chat {chat_id}")
        except Exception as e:
            bot_logger.error(f"❌ AUTO-DELETE: Failed to delete message {message_id} in chat {chat_id}: {e}")
            bot_logger.error(f"❌ AUTO-DELETE: Error type: {type(e).__name__}")
            import traceback
            bot_logger.error(f"❌ AUTO-DELETE: Full traceback: {traceback.format_exc()}")

    @staticmethod
    async def _auto_delete_verification_message(context: ContextTypes.DEFAULT_TYPE):
        """自动删除验证消息的定时任务（5分钟后自动执行，仅当用户未完成验证时）"""
        job_data = context.job.data
        user_id = job_data['user_id']
        chat_id = job_data['chat_id']
        message_id = job_data['message_id']

        try:
            # 检查用户是否还在验证过程中
            if user_id in AuthHandler._verification_contexts:
                # 用户仍在验证中，删除消息
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                bot_logger.info(f"Auto-deleted unfinished verification message {message_id} for user {user_id}")

                # 清理验证上下文
                del AuthHandler._verification_contexts[user_id]
            else:
                # 用户已完成验证，消息可能已被其他处理流程删除
                bot_logger.info(f"Verification message {message_id} for user {user_id} already handled")

        except Exception as e:
            # 消息可能已被手动删除或由于其他原因无法删除
            bot_logger.warning(f"Could not auto-delete verification message {message_id} for user {user_id}: {e}")

    @staticmethod
    async def _restrict_new_member(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int):
        """限制新成员权限 - 只允许阅读消息"""
        try:
            from telegram import ChatPermissions

            # 创建限制权限 - 只允许读取消息
            restricted_permissions = ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False
            )

            # 限制用户权限
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=restricted_permissions
            )

            bot_logger.info(f"Restricted permissions for new member {user_id} in chat {chat_id}")

        except Exception as e:
            bot_logger.error(f"Error restricting permissions for user {user_id}: {e}")

    @staticmethod
    async def _grant_full_permissions(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int):
        """授予验证通过用户完整权限"""
        try:
            from telegram import ChatPermissions

            # 创建完整权限
            full_permissions = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,  # 通常不给普通成员修改群信息的权限
                can_invite_users=True,
                can_pin_messages=False,  # 通常不给普通成员置顶权限
                can_manage_topics=False  # 通常不给普通成员管理话题权限
            )

            # 授予用户完整权限
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=full_permissions
            )

            bot_logger.info(f"Granted full permissions to verified user {user_id} in chat {chat_id}")

        except Exception as e:
            bot_logger.error(f"Error granting permissions to user {user_id}: {e}")

    @staticmethod
    async def _is_new_member_verification(user_id: int) -> bool:
        """检查是否是新用户验证流程"""
        try:
            # 检查用户是否在验证上下文中（说明是新加入的用户）
            # 并且用户还未通过验证
            if user_id in AuthHandler._verification_contexts:
                # 用户在验证上下文中，说明是新用户验证流程
                return True

            # 检查用户是否已经验证过
            is_verified = await AuthService.is_user_verified(user_id)
            if not is_verified:
                # 用户未验证，可能是新用户
                return True

            return False
        except Exception as e:
            bot_logger.error(f"Error checking if user {user_id} is in new member verification: {e}")
            return False

    @staticmethod
    async def _send_language_change_confirmation(query, user_id: int, language_code: str, chat_id: int):
        """发送语言更改确认消息（不触发验证）"""
        try:
            # 获取语言名称
            languages = await LanguageService.get_available_languages()
            language_name = languages.get(language_code, language_code)

            # 获取本地化文本
            success_text = await LanguageService.get_text(user_id, "language_changed", language=language_name)
            if not success_text:
                success_text = f"✅ Language changed to {language_name}"

            help_title = await LanguageService.get_text(user_id, "help_title")
            help_commands = await LanguageService.get_text(user_id, "help_commands")

            message_lines = [
                success_text,
                "",
                help_title,
                "",
                help_commands,
                "",
                "📱 Send /start to the bot for private interactive menu."
            ]

            message = "\n".join(message_lines)

            # 编辑消息内容，移除键盘
            await query.edit_message_text(message)

            bot_logger.info(f"Sent language change confirmation for user {user_id}")

        except Exception as e:
            bot_logger.error(f"Error sending language change confirmation for user {user_id}: {e}")
            await query.edit_message_text(f"✅ Language changed to {language_code}")