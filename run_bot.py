#!/usr/bin/env python3
"""
Simple bot runner script
"""
import asyncio
import logging
from src.utils.config import config
from src.utils.logger import bot_logger
from src.utils.database import init_database, close_database
from src.services.language_service import LanguageService

# Import telegram bot components
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ChatMemberHandler, MessageHandler, filters
from src.handlers.start_handler import StartHandler
from src.handlers.auth_handler import AuthHandler
from src.handlers.invitation_handler import InvitationHandler
from src.handlers.ranking_handler import RankingHandler
from src.services.auth_service import AuthService

async def setup_bot():
    """Setup and return configured bot application"""
    # Validate config
    config.validate()

    # Initialize database
    await init_database()

    # Load translations
    await LanguageService.load_translations()
    await LanguageService.sync_languages_to_db()

    # Create application with job_queue enabled
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    bot_logger.info(f"Application created. Job queue available: {application.job_queue is not None}")

    # Register handlers
    application.add_handler(CommandHandler("start", StartHandler.handle_start_command))
    application.add_handler(CommandHandler("link", InvitationHandler.handle_link_command))
    application.add_handler(CommandHandler("ranking", RankingHandler.handle_ranking_command))
    application.add_handler(CommandHandler("stats", RankingHandler.handle_stats_command))
    application.add_handler(CommandHandler("lang", StartHandler.handle_lang_command))

    # Callback query handler
    async def handle_callback_query(update, context):
        callback_data = update.callback_query.data
        bot_logger.info(f"Received callback query: {callback_data} from user {update.effective_user.id}")

        try:
            # Language selection and verification answers
            if callback_data.startswith("lang_") or callback_data.startswith("answer_"):
                bot_logger.info(f"Routing to auth handler (language/answer)")
                await AuthHandler.handle_language_selection(update, context)
            elif callback_data.startswith("invite_"):
                bot_logger.info(f"Routing to invitation handler")
                await InvitationHandler.handle_invite_callback(update, context)
            elif callback_data.startswith("ranking_") or callback_data.startswith("my_stats_"):
                bot_logger.info(f"Routing to ranking handler")
                await RankingHandler.handle_ranking_callback(update, context)
            elif callback_data.startswith("help_"):
                bot_logger.info(f"Routing to help handler")
                await StartHandler.handle_help_callback(update, context)
            else:
                bot_logger.warning(f"Unknown callback data: {callback_data}")
                await update.callback_query.answer("Unknown action")
        except Exception as e:
            bot_logger.error(f"Error handling callback query {callback_data}: {e}")
            import traceback
            bot_logger.error(f"Full traceback: {traceback.format_exc()}")
            await update.callback_query.answer("An error occurred")

    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Group member handlers
    application.add_handler(ChatMemberHandler(
        AuthHandler.handle_new_member,
        ChatMemberHandler.CHAT_MEMBER
    ))

    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        AuthHandler.handle_new_member
    ))

    application.add_handler(MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER,
        AuthHandler.handle_left_member
    ))

    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUP,
        AuthHandler.handle_message_answer
    ))

    # Error handler
    async def error_handler(update, context):
        bot_logger.error(f"Update {update} caused error {context.error}")
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ An unexpected error occurred. Please try again later."
                )
            except:
                pass

    application.add_error_handler(error_handler)

    bot_logger.info("Bot setup completed successfully")
    return application

async def cleanup_task(application):
    """Background cleanup task"""
    while True:
        try:
            await AuthService.cleanup_expired_challenges()
            await asyncio.sleep(300)  # 5 minutes
        except Exception as e:
            bot_logger.error(f"Error in cleanup task: {e}")
            await asyncio.sleep(60)

async def main():
    """Main function"""
    try:
        bot_logger.info("Starting Telegram bot...")

        # Setup bot
        application = await setup_bot()

        # Start cleanup task
        cleanup_task_handle = asyncio.create_task(cleanup_task(application))

        bot_logger.info("Starting polling...")

        # Run polling
        async with application:
            await application.start()
            await application.updater.start_polling(
                allowed_updates=['message', 'callback_query', 'chat_member'],
                drop_pending_updates=True
            )

            bot_logger.info("Bot is running... Press Ctrl+C to stop")

            # Keep running until interrupted
            try:
                await asyncio.Future()  # Run forever
            except asyncio.CancelledError:
                pass
            finally:
                cleanup_task_handle.cancel()
                await application.updater.stop()
                await application.stop()
                await close_database()
                bot_logger.info("Bot stopped")

    except KeyboardInterrupt:
        bot_logger.info("Bot stopped by user")
    except Exception as e:
        bot_logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        bot_logger.info("Received keyboard interrupt")
    except Exception as e:
        bot_logger.error(f"Fatal error: {e}")