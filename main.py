import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import Application

from bot.handlers import register
from bot.monitor import check_alerts

load_dotenv()

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    level=logging.INFO,
)
# httpx logs the full URL of every request, and the Telegram API URL includes
# the bot token right in the path — leaving this at INFO leaks the token into
# the logs (docker compose logs, log files, etc.).
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand('alert', 'Create an alert for a movie (e.g. /alert dune 3)'),
    BotCommand('alerts', 'List your active alerts'),
    BotCommand('city', 'Set which city to search in (default: São Paulo)'),
    BotCommand('help', 'Show the available commands'),
    BotCommand('start', 'Welcome message'),
]


async def _post_init(application: Application):
    await application.bot.set_my_commands(BOT_COMMANDS)


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise SystemExit('TELEGRAM_BOT_TOKEN is not set (see .env.example).')

    interval_minutes = float(os.environ.get('ALERT_CHECK_INTERVAL_MINUTES', '30'))

    application = Application.builder().token(token).post_init(_post_init).build()
    register(application)
    application.job_queue.run_repeating(check_alerts, interval=interval_minutes * 60, first=10)

    logger.info('Bot started, checking alerts every %s minute(s).', interval_minutes)
    application.run_polling()


if __name__ == '__main__':
    main()
