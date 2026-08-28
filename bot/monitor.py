"""Periodic job that checks pending alerts and notifies when showtimes open."""

import asyncio
import logging

from telegram.ext import ContextTypes

from . import storage
from .ingresso import find_sessions

logger = logging.getLogger(__name__)


def _format_dates_message(movie_title, city_label, dated):
    lines = [
        f"Good news: showtimes just opened for *{movie_title}* in {city_label}. "
        "This alert is now complete and I won't check this movie anymore.",
        "",
        "Available dates:",
    ]
    for value, weekday, _ in dated:
        lines.append(f"- {weekday}, {value}")
    lines.append("")
    lines.append(
        "Send the movie name again here whenever you want to pick a date and see "
        "the theaters and showtimes."
    )
    return "\n".join(lines)


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    pending = await storage.list_pending()
    for alert in pending:
        city_url_key = alert.get('city_url_key', storage.DEFAULT_CITY_URL_KEY)
        city_label = alert.get('city_label', storage.DEFAULT_CITY_LABEL)
        try:
            dated = await asyncio.to_thread(find_sessions, alert['url_key'], city_url_key)
        except Exception:
            logger.exception("Failed to check alert %s (%s)", alert['id'], alert['url_key'])
            continue

        if not dated:
            continue

        try:
            await context.bot.send_message(
                chat_id=alert['chat_id'],
                text=_format_dates_message(alert['movie_title'], city_label, dated),
                parse_mode='Markdown',
            )
        except Exception:
            logger.exception("Failed to send notification for alert %s", alert['id'])
            continue

        await storage.resolve_alert(alert['id'])
