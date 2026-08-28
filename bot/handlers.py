"""Comandos e callbacks do bot do Telegram."""

import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import storage
from .ingresso import fetch_theaters, find_movies, find_sessions

logger = logging.getLogger(__name__)

_MESSAGE_LIMIT = 4000

_allowed_ids_raw = os.environ.get('TELEGRAM_ALLOWED_USER_IDS', '').strip()
ALLOWED_USER_IDS = {
    int(x) for x in _allowed_ids_raw.split(',') if x.strip().isdigit()
} if _allowed_ids_raw else set()

CANCEL_BUTTON_ROW = [InlineKeyboardButton("Cancelar", callback_data="cancel")]


def _clear_pending(context: ContextTypes.DEFAULT_TYPE):
    for key in ('pending_movies', 'pending_intent', 'current_dates', 'current_movie'):
        context.chat_data.pop(key, None)


def _is_allowed(user_id):
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def _chunk_text(text, limit=_MESSAGE_LIMIT):
    lines = text.split('\n')
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > limit and current:
            chunks.append('\n'.join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append('\n'.join(current))
    return chunks


def _format_theaters(day):
    lines = [
        f"Sessões de {day['dayOfWeek']}, {day['dateFormatted']}: encontrei "
        f"{len(day['theaters'])} cinema(s) com horários disponíveis.",
        "",
    ]
    for t in day['theaters']:
        lines.append(f"*{t['name']}* ({t.get('neighborhood', '')})")
        for st in t['sessionTypes']:
            label = '/'.join(st['type'])
            times = ', '.join(s['time'] for s in st['sessions'])
            lines.append(f"  [{label}] {times}")
        lines.append("")
    return "\n".join(lines)


async def _require_allowed(update: Update) -> bool:
    user = update.effective_user
    if user and _is_allowed(user.id):
        return True
    if update.effective_message:
        await update.effective_message.reply_text(
            "Este bot é de uso pessoal e você não está na lista de pessoas autorizadas, "
            "então não posso continuar com esse pedido."
        )
    return False


async def _resolve_movie(chat_id, context: ContextTypes.DEFAULT_TYPE, movie):
    """Fluxo de busca: mostra as datas, ou oferece criar alerta se não houver nenhuma."""
    context.chat_data['current_movie'] = movie
    await context.bot.send_message(
        chat_id,
        f"Procurando as sessões de *{movie['title']}*. Isso pode levar alguns segundos, "
        "porque preciso consultar o site do Ingresso.com diretamente.",
        parse_mode='Markdown',
    )
    dated = await asyncio.to_thread(find_sessions, movie['urlKey'])

    if not dated:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Monitorar este filme", callback_data="alert_new")], CANCEL_BUTTON_ROW]
        )
        await context.bot.send_message(
            chat_id,
            f"Não encontrei nenhuma sessão disponível ainda para *{movie['title']}*. Isso costuma "
            "significar que o filme ainda não estreou ou está em pré-venda. Se quiser, eu posso "
            "ficar de olho e te avisar assim que as sessões abrirem.",
            parse_mode='Markdown',
            reply_markup=keyboard,
        )
        return

    context.chat_data['current_dates'] = dated
    buttons = [
        [InlineKeyboardButton(f"{weekday} - {value}", callback_data=f"date:{i}")]
        for i, (value, weekday, _) in enumerate(dated)
    ]
    buttons.append(CANCEL_BUTTON_ROW)
    await context.bot.send_message(
        chat_id,
        f"Encontrei sessões de *{movie['title']}* nestas datas. Escolha uma para eu te mostrar "
        "os cinemas e horários disponíveis:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _resolve_for_alert(chat_id, context: ContextTypes.DEFAULT_TYPE, movie):
    """Fluxo de /alerta: cria o alerta se não houver sessão, ou mostra as datas se já houver."""
    dated = await asyncio.to_thread(find_sessions, movie['urlKey'])

    if dated:
        context.chat_data['current_dates'] = dated
        buttons = [
            [InlineKeyboardButton(f"{weekday} - {value}", callback_data=f"date:{i}")]
            for i, (value, weekday, _) in enumerate(dated)
        ]
        buttons.append(CANCEL_BUTTON_ROW)
        await context.bot.send_message(
            chat_id,
            f"*{movie['title']}* já tem sessões disponíveis, então não faz sentido criar um "
            "alerta agora. Escolha uma data abaixo para ver onde assistir:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    existing = await storage.find_pending_by_url_key(chat_id, movie['urlKey'])
    if existing:
        await context.bot.send_message(
            chat_id,
            f"Você já tem um alerta em andamento para *{movie['title']}*. Assim que abrirem "
            "sessões, eu aviso por aqui — não precisa criar outro.",
            parse_mode='Markdown',
        )
        return

    await storage.add_alert(chat_id, movie['title'], movie['urlKey'])
    await context.bot.send_message(
        chat_id,
        f"Alerta criado para *{movie['title']}*. Vou verificar periodicamente e, assim que "
        "houver sessões disponíveis, você recebe um aviso aqui mesmo.",
        parse_mode='Markdown',
    )


async def _search_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, phrase, intent):
    chat_id = update.effective_chat.id
    matches = await asyncio.to_thread(find_movies, phrase)

    if not matches:
        await context.bot.send_message(
            chat_id,
            "Não encontrei nenhum filme com esse nome no Ingresso.com. Confira se digitou "
            "certo e tente novamente.",
        )
        return

    if len(matches) == 1:
        movie = matches[0]
        if intent == 'alert':
            await _resolve_for_alert(chat_id, context, movie)
        else:
            await _resolve_movie(chat_id, context, movie)
        return

    context.chat_data['pending_movies'] = matches
    context.chat_data['pending_intent'] = intent
    buttons = [
        [InlineKeyboardButton(m['title'], callback_data=f"movie:{i}")]
        for i, m in enumerate(matches)
    ]
    buttons.append(CANCEL_BUTTON_ROW)
    await context.bot.send_message(
        chat_id,
        "Encontrei mais de um filme com esse nome. Escolha qual deles você quis dizer:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


HELP_TEXT = (
    "Aqui está o que eu sei fazer:\n\n"
    "Manda o nome de um filme em qualquer mensagem, sem precisar de comando nenhum, e eu "
    "procuro as sessões disponíveis pra você.\n\n"
    "/alerta <nome do filme> — use quando o filme ainda não tiver nenhuma sessão aberta. Eu "
    "guardo esse pedido e fico verificando periodicamente; assim que abrir, aviso você por "
    "aqui.\n\n"
    "/alertas — mostra todos os alertas que você tem em andamento no momento, com a opção de "
    "cancelar cada um.\n\n"
    "/help — mostra esta mensagem de novo, caso precise se lembrar dos comandos.\n\n"
    "Sempre que eu te mostrar uma lista de filmes ou de datas pra escolher, vai ter um botão "
    "\"Cancelar\" nela — use se mudar de ideia. Também dá pra simplesmente ignorar e mandar "
    "uma busca nova quando quiser; a anterior é substituída automaticamente."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Olá, tudo bem? {HELP_TEXT}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)


async def cmd_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    phrase = ' '.join(context.args)
    if not phrase:
        await update.effective_message.reply_text(
            "Pra criar um alerta, me diga também o nome do filme, assim: "
            "/alerta nome do filme"
        )
        return
    await _search_flow(update, context, phrase, intent='alert')


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    chat_id = update.effective_chat.id
    pending = await storage.list_pending(chat_id=chat_id)
    if not pending:
        await update.effective_message.reply_text(
            "Você não tem nenhum alerta em andamento no momento. Quando quiser monitorar um "
            "filme que ainda não tem sessão, use /alerta <nome do filme>."
        )
        return
    for alert in pending:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancelar este alerta", callback_data=f"alert_cancel:{alert['id']}")]]
        )
        await update.effective_message.reply_text(
            f"Alerta ativo para {alert['movie_title']}. Assim que houver sessões disponíveis, "
            "aviso você por aqui.",
            reply_markup=keyboard,
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    phrase = update.effective_message.text
    await _search_flow(update, context, phrase, intent='search')


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.from_user or not _is_allowed(query.from_user.id):
        await query.edit_message_text(
            "Este bot é de uso pessoal e você não está na lista de pessoas autorizadas, "
            "então não posso continuar com esse pedido."
        )
        return

    chat_id = query.message.chat_id
    data = query.data

    if data == 'cancel':
        _clear_pending(context)
        await query.edit_message_text("Tudo bem, cancelei essa busca. Quando quiser, é só mandar o nome de outro filme.")

    elif data.startswith('movie:'):
        idx = int(data.split(':', 1)[1])
        candidates = context.chat_data.get('pending_movies') or []
        if idx >= len(candidates):
            await query.edit_message_text(
                "Essa lista de filmes não está mais válida. Manda o nome do filme de novo "
                "que eu busco tudo outra vez."
            )
            return
        movie = candidates[idx]
        intent = context.chat_data.get('pending_intent', 'search')
        await query.edit_message_text(f"Você escolheu {movie['title']}.")
        if intent == 'alert':
            await _resolve_for_alert(chat_id, context, movie)
        else:
            await _resolve_movie(chat_id, context, movie)

    elif data.startswith('date:'):
        idx = int(data.split(':', 1)[1])
        dated = context.chat_data.get('current_dates') or []
        if idx >= len(dated):
            await query.edit_message_text(
                "Essa lista de datas não está mais válida. Manda o nome do filme de novo "
                "pra eu buscar as sessões atualizadas."
            )
            return
        value, weekday, url = dated[idx]
        await query.edit_message_text(f"Buscando os cinemas e horários de {weekday}, {value}...")
        day = await asyncio.to_thread(fetch_theaters, url)
        if not day:
            await context.bot.send_message(
                chat_id,
                "Parece que as sessões dessa data esgotaram ou não estão mais disponíveis. "
                "Tente escolher outra data ou busque o filme novamente.",
            )
            return
        text = _format_theaters(day)
        for chunk in _chunk_text(text):
            await context.bot.send_message(chat_id, chunk, parse_mode='Markdown')

    elif data == 'alert_new':
        movie = context.chat_data.get('current_movie')
        if not movie:
            await query.edit_message_text(
                "Não lembro mais qual filme você estava vendo. Manda o nome de novo que eu "
                "já pergunto se você quer criar o alerta."
            )
            return
        existing = await storage.find_pending_by_url_key(chat_id, movie['urlKey'])
        if existing:
            await query.edit_message_text(
                f"Você já tem um alerta em andamento para *{movie['title']}*. Assim que "
                "abrirem sessões, eu aviso por aqui.",
                parse_mode='Markdown',
            )
            return
        await storage.add_alert(chat_id, movie['title'], movie['urlKey'])
        await query.edit_message_text(
            f"Alerta criado para *{movie['title']}*. Vou verificar periodicamente e, assim "
            "que houver sessões disponíveis, você recebe um aviso aqui mesmo.",
            parse_mode='Markdown',
        )

    elif data.startswith('alert_cancel:'):
        alert_id = data.split(':', 1)[1]
        await storage.cancel_alert(alert_id)
        await query.edit_message_text(
            "Alerta cancelado. Se mudar de ideia, é só criar de novo com /alerta <nome do filme>."
        )


def register(application: Application):
    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('help', cmd_help))
    application.add_handler(CommandHandler('alerta', cmd_alerta))
    application.add_handler(CommandHandler('alertas', cmd_alertas))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
