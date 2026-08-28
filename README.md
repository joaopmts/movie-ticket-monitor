# movie-ticket-monitor

Telegram bot that searches for movie showtimes on Ingresso.com and can
monitor a movie until it opens a showtime, automatically notifying you when
that happens.

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How it works (flows)](#how-it-works-flows)
- [File structure](#file-structure)
- [Requirements and where to download them](#requirements-and-where-to-download-them)
- [Files that aren't version-controlled (security)](#files-that-arent-version-controlled-security)
- [Step-by-step to run it at home](#step-by-step-to-run-it-at-home)
- [Configurable parameters](#configurable-parameters)
- [Bot commands](#bot-commands)
- [Day-to-day operation](#day-to-day-operation)

## Overview

Send the bot a movie name and it returns the dates with showtimes (from
today onward, in ascending order); picking a date lists the theaters and
showtimes. If the movie doesn't have any showtime yet (presale or not
released yet), you can ask for `/alert <movie>` — the bot stores that
request and keeps checking in the background, notifying you in the chat as
soon as it opens.

Access is restricted by a list of authorized users (`TELEGRAM_ALLOWED_USER_IDS`
in `.env`), so even if someone finds the bot, they can't use it.

## Architecture

```
Telegram  <-- long polling -->  main.py
                                   |
                                   |-- registers handlers -----> bot/handlers.py
                                   |-- registers periodic job -> bot/monitor.py
                                   |
bot/handlers.py  ---------------> bot/ingresso.py  ---------> Ingresso.com API
      |                                 |                      + Playwright/Chromium
      |                                 |
      +----> bot/storage.py <-----------+
                   |
                   v
           data/alerts.json
```

- **`main.py`** — entry point. Reads `.env`, builds the `python-telegram-bot`
  application, registers the commands/callbacks (`bot/handlers.py`) and the
  periodic alert job (`bot/monitor.py`), and starts long polling (the bot
  pulls messages from Telegram; no port is ever exposed).
- **`bot/ingresso.py`** — source of truth for the search logic. Queries
  Ingresso.com's public API to find the movie, and uses Playwright (headless
  Chromium) to open the movie page and capture, by intercepting network
  requests, the showtime URLs for each available date. It has no dependency
  on Telegram at all.
- **`bot/handlers.py`** — Telegram commands and buttons (`/start`, `/help`,
  `/alert`, `/alerts`, free text, button taps). This is the layer that
  decides *what* the bot replies and formats the messages; it knows nothing
  about how the search is done internally.
- **`bot/storage.py`** — simple alert persistence in `data/alerts.json`, with
  a lock (`asyncio.Lock`) to avoid a race between the monitoring job and the
  user's commands, since both run in the same process.
- **`bot/monitor.py`** — runs periodically (configurable interval) and, for
  each pending alert, checks whether a showtime is already available. If so,
  it sends a message in the chat and marks the alert as resolved (it's a
  one-time notification, it doesn't keep repeating).

## How it works (flows)

**Search (free text, or a date that already has showtimes in `/alert`)**
1. User sends the movie name.
2. `find_movies()` searches Ingresso.com's API and filters titles that match
   every word typed. If there's more than one result, the bot shows buttons
   to choose from.
3. `find_sessions()` opens the movie page with Playwright, goes through the
   site's date selector and captures the showtime URLs for each day,
   filtering to dates from today onward and sorting them in ascending order.
4. The bot shows one button per available date. When one is picked,
   `fetch_theaters()` queries that date's API and the bot lists theater,
   room, showtime type and time.

**Alert (`/alert <movie>`)**
1. Same search as above. If a showtime already exists, the bot shows the
   dates (it won't create a redundant alert).
2. If there's no showtime yet, the request is saved to `data/alerts.json`
   with status `pending`.
3. Every `ALERT_CHECK_INTERVAL_MINUTES` minutes, `bot/monitor.py` runs
   `find_sessions()` again for each pending alert. As soon as it finds a
   showtime, it sends the message in the chat and marks the alert as
   `resolved`.

## File structure

```
movie-ticket-monitor/
├── bot/
│   ├── __init__.py
│   ├── ingresso.py       # movie/showtime search (Playwright + public API)
│   ├── storage.py        # alert persistence (data/alerts.json)
│   ├── monitor.py        # periodic job that checks pending alerts
│   └── handlers.py       # Telegram commands and buttons
├── data/
│   ├── .gitkeep           # keeps the folder tracked even when empty
│   └── alerts.json         # created at runtime (NOT version-controlled)
├── main.py                  # bot entry point
├── requirements.txt           # Python dependencies
├── Dockerfile                   # bot image
├── docker-compose.yml             # orchestrates the container + data volume
├── .env.example                     # template for the environment variables
├── .env                               # your real variables (NOT version-controlled)
├── .gitignore
└── README.md
```

## Requirements and where to download them

Always download from the official sources below:

| Requirement | Needed for | Where to download (official) |
|---|---|---|
| Python 3.13+ | Running locally, without Docker | https://www.python.org/downloads/ |
| Docker Desktop | Running the bot in a container (recommended) | https://www.docker.com/products/docker-desktop/ |
| WSL2 (Windows only, required by Docker Desktop) | Docker Desktop's backend on Windows | https://learn.microsoft.com/windows/wsl/install (or run `wsl --install` in PowerShell as Administrator) |
| Telegram account and app | Creating/talking to the bot | https://telegram.org/ |
| @BotFather | Creating the bot and getting the token | https://t.me/BotFather (Telegram's official bot, inside the app itself) |
| Git (optional) | Cloning/version-controlling the project | https://git-scm.com/downloads |

The Python dependencies (`requirements.txt`) are installed via `pip` and all
come from the official [PyPI](https://pypi.org/) — no manual download
needed:

- `playwright` — drives the headless Chromium that opens the movie page.
- `requests` — HTTP calls to the Ingresso.com API.
- `python-telegram-bot[job-queue]` — the officially recommended library for
  Telegram bots in Python, with periodic-job support.
- `python-dotenv` — loads `.env` when running without Docker.

If you're running **without Docker**, after installing the dependencies you
also need to download Playwright's browser (not a manual download, it's a
command that fetches it straight from Playwright's official servers):

```powershell
python -m playwright install chromium
```

## Files that aren't version-controlled (security)

These files exist in a running instance of the project, but **don't go into
git** (they're in `.gitignore`) because they hold secrets or data generated
at runtime. Each person running the bot needs to create their own `.env` —
it's never shared and never pushed to the repository.

| File | Why it isn't version-controlled | How to create it |
|---|---|---|
| `.env` | Holds the bot token — whoever has this file controls the bot | Copy `.env.example` and fill it in (see the step-by-step below) |
| `data/alerts.json` | Auto-generated with each installation's alerts; doesn't make sense to share across different environments | Created automatically the first time an alert is saved |
| `__pycache__/`, `*.pyc` | Compiled Python bytecode, specific to each machine | Generated automatically when running |
| `.venv/`, `venv/` | Local Python virtual environment | Created by you if you choose to use `venv` |

### `.env` structure

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
ALERT_CHECK_INTERVAL_MINUTES=30
```

- `TELEGRAM_BOT_TOKEN` — the token @BotFather gives you when you create the
  bot. **Never** share this value or paste it anywhere public (chat,
  screenshot, GitHub issue, etc.) — whoever has the token controls the whole
  bot.
- `TELEGRAM_ALLOWED_USER_IDS` — see the [parameters](#configurable-parameters)
  table below.
- `ALERT_CHECK_INTERVAL_MINUTES` — same.

## Step-by-step to run it at home

### 1. Install the requirements

- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  (recommended) **or** [Python 3.13+](https://www.python.org/downloads/) if
  you'd rather run it without Docker.
- On Windows, Docker Desktop requires WSL2. If it complains about
  "virtualisation support wasn't detected" when it starts, open
  **PowerShell as Administrator** and run `wsl --install`, then restart the
  computer.

### 2. Create the bot on Telegram

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, pick a name and a username (it needs to end in `bot`).
3. Save the token it gives you back — you'll use it in `.env`.

### 3. Find your Telegram user ID

Talk to [@userinfobot](https://t.me/userinfobot) (or any equivalent bot) —
it returns your numeric ID. You'll use that number to lock the bot down to
your own use.

### 4. Get the project

Copy the `movie-ticket-monitor` folder to the machine where the bot will
run (or clone it via Git, if the project lives in a remote repository).

### 5. Create the `.env`

Copy the template and fill it in:

```powershell
copy .env.example .env
```

Edit `.env` with the token from step 2 and your ID from step 3:

```dotenv
TELEGRAM_BOT_TOKEN=put_the_token_here
TELEGRAM_ALLOWED_USER_IDS=put_your_id_here
ALERT_CHECK_INTERVAL_MINUTES=30
```

### 6. Start the bot

**Recommended option — Docker:**

```powershell
docker compose up -d --build
```

`docker-compose.yml` mounts `./data` as a volume, so alerts survive
container rebuilds/restarts.

**Alternative — without Docker:**

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

### 7. Test it

On Telegram, send `/start` to your bot, then `/help` to see the commands,
and the name of a movie currently in theaters to check the search.

## Configurable parameters

All of them live in `.env` (or in the container's environment variables, if
you'd rather configure them directly in `docker-compose.yml`):

| Variable | What it does | Default | Example |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token, given by @BotFather | *(required, no default)* | `8926034628:AAFUJg...` |
| `TELEGRAM_ALLOWED_USER_IDS` | Telegram user IDs authorized to use the bot, comma-separated. **If left empty, anyone who finds the bot can use it** (each search spins up a headless Chromium, so this has a resource cost) | *(empty = no restriction)* | `383108252` or `383108252,111222333` |
| `ALERT_CHECK_INTERVAL_MINUTES` | How often (in minutes) the alert job checks whether new showtimes have opened | `30` | `10` (more frequent checks) |

Other things you can adjust directly in the code, if needed:

- **Search city**: `get_sessions()`/`find_sessions()` in `bot/ingresso.py`
  take `city='sao-paulo'` as the default — it's the city slug used in
  Ingresso.com's URL. For a different city, change that value (or expose it
  as a command parameter, if you want to evolve the bot further).
- **Movie search result limit**: `search_movie(query, limit=10)` in
  `bot/ingresso.py`.

## Bot commands

- Send a movie name (free text) — searches for showtimes.
- `/alert <movie>` — creates a monitoring alert (or shows the dates if the
  movie already has showtimes).
- `/alerts` — lists your active alerts, with a button to cancel each one.
- `/help` — shows the list of commands.
- `/start` — welcome message.

## Day-to-day operation

With the bot running via Docker:

```powershell
docker compose logs -f          # follow the logs in real time
docker compose restart          # restart the bot (e.g. after changing .env)
docker compose up -d --build    # rebuild and restart after changing the code
docker compose down             # stop and remove the container (data in ./data is kept)
```
