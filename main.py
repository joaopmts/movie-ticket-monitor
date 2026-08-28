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
# O httpx loga a URL completa de cada request, e a URL da API do Telegram
# inclui o token do bot no próprio caminho — deixar isso em INFO vaza o
# token pros logs (docker compose logs, arquivos de log, etc.).
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand('alerta', 'Cria um alerta pra um filme (ex: /alerta duna 3)'),
    BotCommand('alertas', 'Lista seus alertas ativos'),
    BotCommand('help', 'Mostra os comandos disponíveis'),
    BotCommand('start', 'Mensagem de boas-vindas'),
]


async def _post_init(application: Application):
    await application.bot.set_my_commands(BOT_COMMANDS)


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise SystemExit('TELEGRAM_BOT_TOKEN não configurado (veja .env.example).')

    interval_minutes = float(os.environ.get('ALERT_CHECK_INTERVAL_MINUTES', '30'))

    application = Application.builder().token(token).post_init(_post_init).build()
    register(application)
    application.job_queue.run_repeating(check_alerts, interval=interval_minutes * 60, first=10)

    logger.info('Bot iniciado, checando alertas a cada %s minuto(s).', interval_minutes)
    application.run_polling()


if __name__ == '__main__':
    main()
