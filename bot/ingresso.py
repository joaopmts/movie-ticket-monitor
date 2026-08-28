"""Movie and showtime search on Ingresso.com.

Single source of truth for the search logic, used by the Telegram bot.
"""

import asyncio
import threading
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs

import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
    'Origin': 'https://www.ingresso.com',
    'Referer': 'https://www.ingresso.com/',
}

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def search_movie(query, limit=10):
    r = requests.get(
        f'https://api-content.ingresso.com/v0/events/search/{query}',
        params={'limit': limit},
        headers=HEADERS,
    )
    r.raise_for_status()
    return r.json()


def find_movies(phrase):
    """Returns the movies whose title contains every word in the phrase."""
    words = phrase.lower().split()
    if not words:
        return []
    results = search_movie(words[0])
    return [m for m in results if all(w in m['title'].lower() for w in words)]


def _get_sessions_sync(url_key, city, result_holder):
    # On Windows, Jupyter/asyncio default to the Selector policy (which
    # doesn't support subprocesses). We switch this thread's policy to
    # Proactor BEFORE entering sync_playwright, which creates its own loop
    # via asyncio.new_event_loop() using the current policy.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from playwright.sync_api import sync_playwright

    captured_urls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale='pt-BR')

        def handle_response(response):
            if 'sessionType' in response.url and 'date' in response.url:
                captured_urls.append(response.url)

        page.on('response', handle_response)
        page.goto(f'https://www.ingresso.com/filme/{url_key}?city={city}')
        page.wait_for_timeout(2500)

        # The site has a <select aria-label="Datas"> with the available dates.
        # The API response only fires when the selected date changes, so we
        # go through every option to capture each day's showtimes.
        date_select = page.locator('select[aria-label="Datas"]')
        if date_select.count() > 0:
            date_values = [
                opt.get_attribute('value')
                for opt in date_select.locator('option').all()
            ]
            for value in date_values:
                if value:
                    date_select.select_option(value)
                    page.wait_for_timeout(1500)

        browser.close()

    result_holder['urls'] = list(dict.fromkeys(captured_urls))


def get_sessions(url_key, city='sao-paulo'):
    """Opens the movie page and captures showtime URLs via Playwright (blocking)."""
    result = {}
    t = threading.Thread(target=_get_sessions_sync, args=(url_key, city, result))
    t.start()
    t.join()
    return result.get('urls', [])


def extract_dates(urls):
    """Extracts (date, url) from each captured showtime URL."""
    result = []
    for url in urls:
        qs = parse_qs(urlparse(url).query)
        value = qs.get('date', [None])[0]
        if value:
            result.append((value, url))
    return result


def _parse_date(value):
    text = value.split('T')[0]
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def filter_and_sort_dates(dated_urls):
    """Deduplicates, keeps only dates >= today and sorts ascending.
    Returns a list of (date, weekday, url)."""
    today = date.today()
    seen = set()
    parsed = []
    for value, url in dated_urls:
        if value in seen:
            continue
        d = _parse_date(value)
        if d and d >= today:
            seen.add(value)
            parsed.append((d, value, url))
    parsed.sort(key=lambda item: item[0])
    return [(value, WEEKDAYS[d.weekday()], url) for d, value, url in parsed]


def find_sessions(url_key, city='sao-paulo'):
    """Chains get_sessions + extract_dates + filter_and_sort_dates.

    Returns a list of (date, weekday, url), already filtered and sorted.
    """
    urls = get_sessions(url_key, city=city)
    return filter_and_sort_dates(extract_dates(urls))


def fetch_theaters(url):
    """Queries the API for the chosen date and returns the day's data structure (or None)."""
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 204 or not r.text.strip():
        return None
    r.raise_for_status()
    data = r.json()
    day = data[0] if isinstance(data, list) and data else None
    if not day or not day.get('theaters'):
        return None
    return day
