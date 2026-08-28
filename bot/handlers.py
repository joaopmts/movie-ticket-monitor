"""Telegram bot commands and callbacks."""

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
from .ingresso import fetch_theaters, find_cities, find_movies, find_sessions

logger = logging.getLogger(__name__)

_MESSAGE_LIMIT = 4000

_allowed_ids_raw = os.environ.get('TELEGRAM_ALLOWED_USER_IDS', '').strip()
ALLOWED_USER_IDS = {
    int(x) for x in _allowed_ids_raw.split(',') if x.strip().isdigit()
} if _allowed_ids_raw else set()

CANCEL_BUTTON_ROW = [InlineKeyboardButton("Cancel", callback_data="cancel")]


def _clear_pending(context: ContextTypes.DEFAULT_TYPE):
    for key in ('pending_movies', 'pending_intent', 'current_dates', 'current_movie', 'pending_cities'):
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
        f"Showtimes for {day['dayOfWeek']}, {day['dateFormatted']}: found "
        f"{len(day['theaters'])} theater(s) with available times.",
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
            "This bot is for personal use and you're not on the list of authorized "
            "users, so I can't continue with this request."
        )
    return False


async def _resolve_movie(chat_id, context: ContextTypes.DEFAULT_TYPE, movie):
    """Search flow: shows the dates, or offers to create an alert if there are none."""
    context.chat_data['current_movie'] = movie
    city_url_key, city_label = await storage.get_city(chat_id)
    await context.bot.send_message(
        chat_id,
        f"Looking up showtimes for *{movie['title']}* in {city_label}. This can "
        "take a few seconds, since I need to query the Ingresso.com site directly.",
        parse_mode='Markdown',
    )
    dated = await asyncio.to_thread(find_sessions, movie['urlKey'], city_url_key)

    if not dated:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Monitor this movie", callback_data="alert_new")], CANCEL_BUTTON_ROW]
        )
        await context.bot.send_message(
            chat_id,
            f"I couldn't find any showtimes for *{movie['title']}* in {city_label} "
            "yet. That usually means the movie hasn't been released yet or is "
            "still in presale. If you'd like, I can keep an eye on it and let you "
            "know as soon as showtimes open.",
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
        f"I found showtimes for *{movie['title']}* on these dates. Pick one and "
        "I'll show you the theaters and available times:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _resolve_for_alert(chat_id, context: ContextTypes.DEFAULT_TYPE, movie):
    """/alert flow: creates the alert if there's no showtime yet, or shows the dates if there already is."""
    city_url_key, city_label = await storage.get_city(chat_id)
    dated = await asyncio.to_thread(find_sessions, movie['urlKey'], city_url_key)

    if dated:
        context.chat_data['current_dates'] = dated
        buttons = [
            [InlineKeyboardButton(f"{weekday} - {value}", callback_data=f"date:{i}")]
            for i, (value, weekday, _) in enumerate(dated)
        ]
        buttons.append(CANCEL_BUTTON_ROW)
        await context.bot.send_message(
            chat_id,
            f"*{movie['title']}* already has showtimes available in {city_label}, "
            "so there's no point creating an alert now. Pick a date below to see "
            "where to watch it:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    existing = await storage.find_pending_by_url_key(chat_id, movie['urlKey'], city_url_key)
    if existing:
        existing_city = existing.get('city_label', storage.DEFAULT_CITY_LABEL)
        await context.bot.send_message(
            chat_id,
            f"You already have an alert in progress for *{movie['title']}* in "
            f"{existing_city}. As soon as showtimes open, I'll let you know "
            "here — no need to create another one.",
            parse_mode='Markdown',
        )
        return

    await storage.add_alert(chat_id, movie['title'], movie['urlKey'], city_url_key, city_label)
    await context.bot.send_message(
        chat_id,
        f"Alert created for *{movie['title']}* in {city_label}. I'll check "
        "periodically, and as soon as showtimes are available, you'll get a "
        "notification right here.",
        parse_mode='Markdown',
    )


async def _search_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, phrase, intent):
    chat_id = update.effective_chat.id
    matches = await asyncio.to_thread(find_movies, phrase)

    if not matches:
        await context.bot.send_message(
            chat_id,
            "I couldn't find any movie with that name on Ingresso.com. Double-check "
            "the spelling and try again.",
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
        "I found more than one movie with that name. Pick the one you meant:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


HELP_TEXT = (
    "Here's what I can do:\n\n"
    "Send me a movie name in any message, no command needed, and I'll look up the "
    "available showtimes for you.\n\n"
    "/alert <movie name> — use this when the movie doesn't have any showtime open "
    "yet. I'll save that request and keep checking periodically; as soon as it "
    "opens, I'll let you know here.\n\n"
    "/alerts — shows every alert you currently have in progress, with the option "
    "to cancel each one.\n\n"
    "/city <city name> — sets which city I search in (defaults to São Paulo - SP). "
    "Send /city with no name to see your current city.\n\n"
    "/help — shows this message again, in case you need a reminder of the commands.\n\n"
    "Whenever I show you a list of movies, cities, or dates to pick from, there'll "
    "be a \"Cancel\" button on it — use it if you change your mind. You can also "
    "just ignore it and send a new search whenever you want; the previous one is "
    "replaced automatically."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Hello! {HELP_TEXT}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    phrase = ' '.join(context.args)
    if not phrase:
        await update.effective_message.reply_text(
            "To create an alert, tell me the movie name too, like this: "
            "/alert movie name"
        )
        return
    await _search_flow(update, context, phrase, intent='alert')


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    chat_id = update.effective_chat.id
    pending = await storage.list_pending(chat_id=chat_id)
    if not pending:
        await update.effective_message.reply_text(
            "You don't have any alerts in progress right now. When you want to "
            "monitor a movie that doesn't have showtimes yet, use /alert <movie name>."
        )
        return
    for alert in pending:
        city_label = alert.get('city_label', storage.DEFAULT_CITY_LABEL)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel this alert", callback_data=f"alert_cancel:{alert['id']}")]]
        )
        await update.effective_message.reply_text(
            f"Active alert for {alert['movie_title']} in {city_label}. As soon as "
            "showtimes are available, I'll let you know here.",
            reply_markup=keyboard,
        )


async def cmd_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_allowed(update):
        return
    chat_id = update.effective_chat.id
    phrase = ' '.join(context.args)

    if not phrase:
        _, city_label = await storage.get_city(chat_id)
        await update.effective_message.reply_text(
            f"Your current city is {city_label}. To change it, use: /city city name"
        )
        return

    matches = await asyncio.to_thread(find_cities, phrase)
    if not matches:
        await update.effective_message.reply_text(
            "I couldn't find any city with that name on Ingresso.com. Double-check "
            "the spelling and try again."
        )
        return

    if len(matches) == 1:
        city = matches[0]
        await storage.set_city(chat_id, city['urlKey'], f"{city['name']} - {city['uf']}")
        await update.effective_message.reply_text(
            f"Got it, your city is now set to {city['name']} - {city['uf']}. "
            "Searches and alerts will use this city from now on."
        )
        return

    context.chat_data['pending_cities'] = matches
    buttons = [
        [InlineKeyboardButton(f"{c['name']} - {c['uf']}", callback_data=f"city:{i}")]
        for i, c in enumerate(matches)
    ]
    buttons.append(CANCEL_BUTTON_ROW)
    await update.effective_message.reply_text(
        "I found more than one city with that name. Pick the one you meant:",
        reply_markup=InlineKeyboardMarkup(buttons),
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
            "This bot is for personal use and you're not on the list of authorized "
            "users, so I can't continue with this request."
        )
        return

    chat_id = query.message.chat_id
    data = query.data

    if data == 'cancel':
        _clear_pending(context)
        await query.edit_message_text("No problem, I canceled that search. Whenever you want, just send another movie name.")

    elif data.startswith('movie:'):
        idx = int(data.split(':', 1)[1])
        candidates = context.chat_data.get('pending_movies') or []
        if idx >= len(candidates):
            await query.edit_message_text(
                "That movie list isn't valid anymore. Send the movie name again "
                "and I'll search for everything once more."
            )
            return
        movie = candidates[idx]
        intent = context.chat_data.get('pending_intent', 'search')
        await query.edit_message_text(f"You picked {movie['title']}.")
        if intent == 'alert':
            await _resolve_for_alert(chat_id, context, movie)
        else:
            await _resolve_movie(chat_id, context, movie)

    elif data.startswith('date:'):
        idx = int(data.split(':', 1)[1])
        dated = context.chat_data.get('current_dates') or []
        if idx >= len(dated):
            await query.edit_message_text(
                "That date list isn't valid anymore. Send the movie name again "
                "so I can fetch the latest showtimes."
            )
            return
        value, weekday, url = dated[idx]
        await query.edit_message_text(f"Looking up theaters and showtimes for {weekday}, {value}...")
        day = await asyncio.to_thread(fetch_theaters, url)
        if not day:
            await context.bot.send_message(
                chat_id,
                "Looks like showtimes for that date sold out or are no longer "
                "available. Try picking another date or search for the movie again.",
            )
            return
        text = _format_theaters(day)
        for chunk in _chunk_text(text):
            await context.bot.send_message(chat_id, chunk, parse_mode='Markdown')

    elif data == 'alert_new':
        movie = context.chat_data.get('current_movie')
        if not movie:
            await query.edit_message_text(
                "I don't remember which movie you were looking at anymore. Send "
                "the name again and I'll ask if you want to create the alert."
            )
            return
        city_url_key, city_label = await storage.get_city(chat_id)
        existing = await storage.find_pending_by_url_key(chat_id, movie['urlKey'], city_url_key)
        if existing:
            existing_city = existing.get('city_label', storage.DEFAULT_CITY_LABEL)
            await query.edit_message_text(
                f"You already have an alert in progress for *{movie['title']}* in "
                f"{existing_city}. As soon as showtimes open, I'll let you know here.",
                parse_mode='Markdown',
            )
            return
        await storage.add_alert(chat_id, movie['title'], movie['urlKey'], city_url_key, city_label)
        await query.edit_message_text(
            f"Alert created for *{movie['title']}* in {city_label}. I'll check "
            "periodically, and as soon as showtimes are available, you'll get a "
            "notification right here.",
            parse_mode='Markdown',
        )

    elif data.startswith('city:'):
        idx = int(data.split(':', 1)[1])
        candidates = context.chat_data.get('pending_cities') or []
        if idx >= len(candidates):
            await query.edit_message_text(
                "That city list isn't valid anymore. Send /city <name> again."
            )
            return
        city = candidates[idx]
        await storage.set_city(chat_id, city['urlKey'], f"{city['name']} - {city['uf']}")
        await query.edit_message_text(
            f"Got it, your city is now set to {city['name']} - {city['uf']}. "
            "Searches and alerts will use this city from now on."
        )

    elif data.startswith('alert_cancel:'):
        alert_id = data.split(':', 1)[1]
        await storage.cancel_alert(alert_id)
        await query.edit_message_text(
            "Alert canceled. If you change your mind, just create a new one with "
            "/alert <movie name>."
        )


def register(application: Application):
    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('help', cmd_help))
    application.add_handler(CommandHandler('alert', cmd_alert))
    application.add_handler(CommandHandler('alerts', cmd_alerts))
    application.add_handler(CommandHandler('city', cmd_city))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
