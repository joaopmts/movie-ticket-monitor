"""Persistência simples dos alertas de monitoramento em um arquivo JSON."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
ALERTS_PATH = os.path.join(DATA_DIR, 'alerts.json')

_lock = asyncio.Lock()


def _load():
    if not os.path.exists(ALERTS_PATH):
        return []
    with open(ALERTS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(alerts):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


async def add_alert(chat_id, movie_title, url_key):
    async with _lock:
        alerts = _load()
        alert = {
            'id': uuid.uuid4().hex,
            'chat_id': chat_id,
            'movie_title': movie_title,
            'url_key': url_key,
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


async def find_pending_by_url_key(chat_id, url_key):
    pending = await list_pending(chat_id=chat_id)
    return next((a for a in pending if a['url_key'] == url_key), None)
