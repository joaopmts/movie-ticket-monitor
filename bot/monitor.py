"""Periodic job that checks pending alerts and notifies when showtimes open."""

import asyncio
import logging

from telegram.ext import ContextTypes

from . import storage
from .ingresso import find_sessions

logger = logging.getLogger(__name__)


def _format_dates_message(movie_title, dated):
    lines = [
        f"Good news: showtimes just opened for *{movie_title}*. This alert is now "
        "complete and I won't check this movie anymore.",
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
        try:
            city_url_key, _ = await storage.get_city(alert['chat_id'])
            dated = await asyncio.to_thread(find_sessions, alert['url_key'], city_url_key)
        except Exception:
            logger.exception("Failed to check alert %s (%s)", alert['id'], alert['url_key'])
            continue

        if not dated:
            continue

        try:
            await context.bot.send_message(
                chat_id=alert['chat_id'],
                text=_format_dates_message(alert['movie_title'], dated),
                parse_mode='Markdown',
            )
        except Exception:
            logger.exception("Failed to send notification for alert %s", alert['id'])
            continue

        await storage.resolve_alert(alert['id'])
