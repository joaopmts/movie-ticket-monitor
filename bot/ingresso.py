"""Busca de filmes e sessões no Ingresso.com.

Fonte de verdade compartilhada entre o bot do Telegram e o notebook de teste
(teste.ipynb importa daqui em vez de duplicar a lógica).
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

DIAS_SEMANA = ['segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo']


def search_movie(query, limit=10):
    r = requests.get(
        f'https://api-content.ingresso.com/v0/events/search/{query}',
        params={'limit': limit},
        headers=HEADERS,
    )
    r.raise_for_status()
    return r.json()


def find_movies(phrase):
    """Retorna os filmes cujo título contém todas as palavras da frase."""
    words = phrase.lower().split()
    if not words:
        return []
    results = search_movie(words[0])
    return [m for m in results if all(w in m['title'].lower() for w in words)]


def _get_sessions_sync(url_key, city, result_holder):
    # No Windows, o Jupyter/asyncio padrão usa a policy Selector (não
    # suporta subprocessos). Trocamos a policy desta thread para Proactor
    # ANTES de entrar no sync_playwright, que cria seu próprio loop via
    # asyncio.new_event_loop() usando a policy corrente.
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

        # O site tem um <select aria-label="Datas"> com as datas disponíveis.
        # A resposta da API só é disparada quando a data selecionada muda,
        # então percorremos todas as opções pra capturar as sessões de cada dia.
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
    """Abre o filme no site e captura as URLs de sessão via Playwright (bloqueante)."""
    result = {}
    t = threading.Thread(target=_get_sessions_sync, args=(url_key, city, result))
    t.start()
    t.join()
    return result.get('urls', [])


def extract_dates(urls):
    """Extrai (data, url) de cada URL de sessão capturada."""
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
    """Remove duplicadas, mantém só datas >= hoje e ordena crescente.
    Retorna lista de (data, dia_da_semana, url)."""
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
    return [(value, DIAS_SEMANA[d.weekday()], url) for d, value, url in parsed]


def find_sessions(url_key, city='sao-paulo'):
    """Encadeia get_sessions + extract_dates + filter_and_sort_dates.

    Retorna lista de (data, dia_da_semana, url), já filtrada e ordenada.
    """
    urls = get_sessions(url_key, city=city)
    return filter_and_sort_dates(extract_dates(urls))


def fetch_theaters(url):
    """Busca a API da data escolhida e retorna a estrutura do dia (ou None)."""
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 204 or not r.text.strip():
        return None
    r.raise_for_status()
    data = r.json()
    day = data[0] if isinstance(data, list) and data else None
    if not day or not day.get('theaters'):
        return None
    return day
