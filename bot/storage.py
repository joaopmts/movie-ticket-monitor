"""Simple JSON-file-based persistence for monitoring alerts."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
ALERTS_PATH = os.path.join(DATA_DIR, 'alerts.json')
PREFERENCES_PATH = os.path.join(DATA_DIR, 'preferences.json')

DEFAULT_CITY_URL_KEY = 'sao-paulo'
DEFAULT_CITY_LABEL = 'São Paulo - SP'

_lock = asyncio.Lock()
_prefs_lock = asyncio.Lock()


def _load():
    if not os.path.exists(ALERTS_PATH):
        return []
    with open(ALERTS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(alerts):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


async def add_alert(chat_id, movie_title, url_key, city_url_key, city_label):
    async with _lock:
        alerts = _load()
        alert = {
            'id': uuid.uuid4().hex,
            'chat_id': chat_id,
            'movie_title': movie_title,
            'url_key': url_key,
            'city_url_key': city_url_key,
            'city_label': city_label,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'status': 'pending',
        }
        alerts.append(alert)
        _save(alerts)
        return alert


async def list_pending(chat_id=None):
    async with _lock:
        alerts = _load()
    pending = [a for a in alerts if a['status'] == 'pending']
    if chat_id is not None:
        pending = [a for a in pending if a['chat_id'] == chat_id]
    return pending


async def resolve_alert(alert_id):
    async with _lock:
        alerts = _load()
        for a in alerts:
            if a['id'] == alert_id:
                a['status'] = 'resolved'
        _save(alerts)


async def cancel_alert(alert_id):
    async with _lock:
        alerts = _load()
        alerts = [a for a in alerts if a['id'] != alert_id]
        _save(alerts)


async def find_pending_by_url_key(chat_id, url_key, city_url_key):
    """Finds a pending alert for the same chat, movie AND city.

    Alerts for the same movie in different cities are independent — this
    only counts as a duplicate when the city also matches (falling back to
    the default city for older alerts saved before city pinning existed).
    """
    pending = await list_pending(chat_id=chat_id)
    return next(
        (
            a for a in pending
            if a['url_key'] == url_key
            and a.get('city_url_key', DEFAULT_CITY_URL_KEY) == city_url_key
        ),
        None,
    )


def _load_prefs():
    if not os.path.exists(PREFERENCES_PATH):
        return {}
    with open(PREFERENCES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_prefs(prefs):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PREFERENCES_PATH, 'w', encoding='utf-8') as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


async def set_city(chat_id, url_key, label):
    async with _prefs_lock:
        prefs = _load_prefs()
        prefs[str(chat_id)] = {'city_url_key': url_key, 'city_label': label}
        _save_prefs(prefs)


async def get_city(chat_id):
    """Returns (city_url_key, city_label) for the chat, or the default city."""
    async with _prefs_lock:
        prefs = _load_prefs()
    entry = prefs.get(str(chat_id))
    if entry:
        return entry['city_url_key'], entry['city_label']
    return DEFAULT_CITY_URL_KEY, DEFAULT_CITY_LABEL
