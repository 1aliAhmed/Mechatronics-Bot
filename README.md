# Megatronics Bot

A free, open-source **Telegram bot** for student communities. It does two jobs:

1. **Looks after a group** — filters banned words, warns and time-outs repeat offenders, welcomes new members.
2. **Acts as a study assistant** — any member can privately send it questions, homework photos, or voice notes, and get explanations, summaries, practice problems, or a clean, well-formatted study PDF made from a source document.

Everything works in Arabic and English, and runs on free AI services — no paid subscriptions required.

Built for a mechatronics student community, structured so any community can adopt it.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![Tests](https://img.shields.io/badge/tests-137%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

**Never coded before? That is fine.** The [Quickstart](#quickstart) tells you exactly what to install, what to click, and what every command does. Any technical word is explained where it first appears, and collected again in [Words you will see](#words-you-will-see).

**Contents**

- [What you will need](#what-you-will-need)
- [Words you will see](#words-you-will-see)
- [Quickstart](#quickstart)
- [If something goes wrong](#if-something-goes-wrong)
- [What the bot can do](#what-the-bot-can-do)
  - [Moderation](#moderation)
  - [The AI study window](#the-ai-study-window)
  - [From source to study document](#from-source-to-study-document)
  - [Drawings and diagrams](#drawings-and-diagrams)
- [Who can use what](#who-can-use-what)
- [Settings explained](#settings-explained)
- [Commands](#commands)
- [How it works](#how-it-works)
- [Running the tests](#running-the-tests)
- [Deploying to a server](#deploying-to-a-server)
- [Roadmap](#roadmap)
- [Contributing and security](#contributing-and-security)
- [License](#license)

---

## What you will need

You run the bot yourself, on your own computer. Here is the shopping list:

- **A Telegram account** (free) and **admin rights in the group** where the bot will live. Admins are the members who manage a group — the bot needs those rights to delete messages and mute people. You can also create your own group for testing.
- **A computer** — Windows, macOS, or Linux. It can be the computer you use every day; the bot is not heavy. One catch: the bot only works **while it is running** on that computer. If you want it online all the time (even when your computer is off), you will later put it on a small server — see [Deploying to a server](#deploying-to-a-server).
- **Python 3.12 or newer** — Python is the programming language this bot is written in. It is free. Download it from [python.org/downloads](https://www.python.org/downloads/) (Windows/macOS) or install it from your software centre (Linux). To check whether you already have it, open your [terminal](#words-you-will-see) (the text window where you type commands) and type `python3.12 --version`. If you see `Python 3.12.x` or higher, you're set. On Windows the command may be `py -3.12 --version` or `python --version`.
- **The project files** — two ways to get them, both explained in [Step 2](#quickstart):
  - download a ZIP (easiest — no extra tools), or
  - use **Git** (a free tool that downloads and updates code from GitHub) — check with `git --version`, install from [git-scm.com](https://git-scm.com/) if missing.
- **A free OpenRouter account** — OpenRouter is a website that gives programs access to many different AI models, including free ones. You will create an "API key" (a secret string, like a password) there so the bot can talk to the AI.
- **Optional: a free Groq account** — makes voice-note transcription better. Without it, voice notes still work, just through a different service.
- **Optional: extra tools for PDFs and diagrams** — Graphviz (drawing diagrams), Typst (making PDFs), ffmpeg (converting audio), and an Arabic font. The server setup script installs all of them automatically; you can ignore them at first.

---

## Words you will see

No coding knowledge assumed — here is every word this guide uses, in plain language.

| Word | What it means |
|---|---|
| **Terminal** | The window where you type commands instead of clicking buttons. On Windows it is called "Terminal" or "PowerShell"; on macOS "Terminal"; on Linux your terminal app. |
| **Command** | One line of text you type in the terminal and run with the Enter key. |
| **Folder** / **directory** | The same thing — a container for files. |
| **Repository** ("repo") | The project's folder of files, kept on GitHub together with its full history of changes. |
| **GitHub** | The website (github.com) where the project lives so people can download it and contribute. |
| **Git** | The tool that copies ("clones") a repository from GitHub to your computer. |
| **Clone** | To download a copy of a repository. |
| **Python** | The programming language the bot is written in. |
| **Library** / **package** / **dependency** | Ready-made code written by other people that this project uses. "Installing dependencies" means downloading those libraries. |
| **pip** | Python's installer tool, used to download libraries. |
| **Virtual environment** ("venv") | A private toolbox folder for this project's libraries, so they cannot clash with anything else on your computer. |
| **Environment variable** / **`.env` file** | A way to give a program settings as plain text, in the form `NAME=value`. The bot reads its settings from a file named `.env` in the project folder. |
| **API** | A way for programs to talk to other services automatically (for example, the bot asking OpenRouter for an AI answer). |
| **API key** | A secret string that proves a request comes from you. Treat it like a password. |
| **Token** | The same idea as an API key; specifically, the password of your Telegram bot, given to you by BotFather. |
| **Bot** | A program that signs in to Telegram and behaves like a user account: people can chat with it. |
| **BotFather** | Telegram's official bot (@BotFather) for creating and managing bots. |
| **DM** | "Direct message" — a private one-to-one chat. |
| **Admin** (administrator) | A group member with extra powers, like deleting messages. The bot needs admin rights to moderate. |
| **Chat ID** | Telegram's internal number for a group. It is negative; for most groups it starts with `-100`. |
| **AI model** | The "brain" that produces answers. Different models have different names, like `...:free`. |
| **Free tier** | The free allowance of a service that also sells more. This project is designed to stay inside free allowances. |
| **Polling** | How the bot receives messages: it keeps asking Telegram "anything new?" — this is why it must stay running. |
| **Server** / **VPS** | A computer that stays on all the time. A VPS is one you rent (a "virtual private server") for a few dollars a month. |

---

## Quickstart

The whole setup, step by step. Commands are shown in grey boxes: copy a line, paste it into your terminal, press Enter, and wait for it to finish before the next one.

**Two notes before you start:**

- In these commands `/` is the folder separator on macOS and Linux; on **Windows** it is `\`. Wherever you see `.venv/bin/`, Windows users should run `.venv\Scripts\` instead.
- If `python3.12` is not recognised, on Windows try `py -3.12` instead, and on some systems plain `python`.

### Step 1 — Create your bot on Telegram

1. Open Telegram and search for **@BotFather** (it has a blue checkmark). Press **Start**.
2. Send `/newbot`. BotFather asks for a **name** (shown to users, anything you like) and a **username** (must be unique and end in `bot`, e.g. `MyStudyHelperBot`).
3. BotFather replies with a **token** that looks like `123456789:AAE...`. This token is the password of your bot. **Copy it somewhere safe and never share or post it.**
4. Still chatting with BotFather, send `/setprivacy`, pick your bot, and choose **Disable**.

> **Why disable privacy?** By default Telegram hides most group messages from bots — that is fine for toy bots, but this bot needs to *see* every message in order to filter banned words and answer questions. "Disable" means "allow the bot to receive all messages".

### Step 2 — Download the project

**Option A — ZIP (easiest, nothing to install):**

1. Open [github.com/1aliAhmed/Mechatronics-Bot](https://github.com/1aliAhmed/Mechatronics-Bot).
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip it somewhere easy to find (for example your Documents folder).
4. Open a terminal **inside that folder**. A terminal always works "in" some folder, and commands act on the folder it is in. To open one:
   - **Windows:** right-click inside the folder → **Open in Terminal**.
   - **macOS:** right-click the folder → **Services** → **New Terminal at Folder** (or drag the folder onto the Terminal icon in your Dock).
   - **Linux:** right-click inside the folder → **Open in Terminal**.

**Option B — with Git (if `git --version` works):**

```
git clone https://github.com/1aliAhmed/Mechatronics-Bot.git
cd Mechatronics-Bot
```

The first line makes a copy of the project on your computer; the second steps into the project folder (`cd` means "change directory"). If you are using your own copy or fork of the project, use its address instead.

### Step 3 — Create the project's private toolbox (a virtual environment)

```
python3.12 -m venv .venv
```

This creates a folder named `.venv` inside the project. It contains its own private copy of Python's tools so this project cannot interfere with anything else on your computer. You only do this once. Nothing will look different afterwards — a new folder simply appears.

### Step 4 — Install the project's libraries

```
.venv/bin/pip install -r requirements.txt
```

(On Windows: `.venv\Scripts\pip install -r requirements.txt`.)

`pip` reads the file `requirements.txt` — the shopping list of free libraries the bot needs — and downloads them. You will see a lot of text scrolling by; that is normal. It is done when the text stops.

### Step 5 — Get an AI key

The bot needs a key to talk to an AI service. The default choice is **OpenRouter** (free to sign up):

1. Go to [openrouter.ai](https://openrouter.ai) and create a free account.
2. In your account settings, open **Keys** and create a new API key. Copy it — it starts with `sk-or-`.
3. Treat this key like a password.

By default the bot only uses OpenRouter models whose names end in `:free`, so it cannot spend money on your account by accident. Paid models only work if you explicitly allow them (see `PAID_MODELS` in [Settings explained](#settings-explained)).

**Optional — Groq** (improves voice-note transcription): create a free account at [console.groq.com](https://console.groq.com), create an API key, and put it in the `.env` file as `GROQ_API_KEY`. If you skip this, voice notes still work through OpenRouter.

### Step 6 — Fill in the settings file

Inside the project folder there is a file called `.env.example`. It is a template. You make your own copy named `.env` and edit the copy:

```
cp .env.example .env
```

(On Windows Command Prompt: `copy .env.example .env`. In PowerShell and on macOS/Linux, `cp` works as shown. You can also copy the file in your file manager and rename the copy to exactly `.env`.)

> **Careful:** the file must be named exactly `.env` — not `.env.txt`. Windows sometimes adds `.txt` when saving; double-check the name after editing.

Open `.env` with any plain text editor (Notepad, TextEdit, or [VS Code](https://code.visualstudio.com/) if you have it) and fill in these three lines:

```ini
TELEGRAM_TOKEN=123456789:AAE...
BOUND_COMMUNITY_ID=-1001234567890
OPENROUTER_API_KEY=sk-or-...
```

- `TELEGRAM_TOKEN` — the token BotFather gave you in Step 1.
- `BOUND_COMMUNITY_ID` — the **numeric ID of your group** (explained right below).
- `OPENROUTER_API_KEY` — the key from Step 5.

Each line has the form `NAME=value`. Do not add spaces around the `=` sign. Lines starting with `#` are comments — the bot ignores them; they are there to explain things.

**How to find your group's ID:** add an ID helper bot — for example [@userinfobot](https://t.me/userinfobot) — to your group. It replies with the group's ID: a **negative number**, usually starting with `-100`. Copy that number into `BOUND_COMMUNITY_ID`, then remove the helper bot from the group. The bot double-checks this ID every time it starts, so a wrong number will be caught immediately.

Optional, right below those three: `COMMUNITY_NAME` (your community's name, shown in the bot's introduction to new users), `REPO_URL` (a link to your project, also shown in the intro). Everything else can be left as it is — all settings are explained in [Settings explained](#settings-explained).

### Step 7 — Start the bot

```
.venv/bin/python -m app.main
```

(On Windows: `.venv\Scripts\python -m app.main`.)

This runs the program. If everything is configured correctly, you will see log lines, ending with one that says **`Bot polling started`**. "Polling" means the bot keeps asking Telegram for new messages.

- **The bot runs only while this window stays open.** Closing the window, or pressing `Ctrl` and `C` together, stops it.
- Text scrolling by is normal. When you want to stop the bot, press `Ctrl+C`.

### Step 8 — First-run checklist (in Telegram)

1. **Add the bot to your group as an administrator:** open the group → tap the group name → **Administrators** → **Add Admin** → search your bot's username → add it. Make sure it can delete messages, restrict members, and pin messages.
2. If you skipped it in Step 1: in BotFather send `/setprivacy` → your bot → **Disable**. Without this, the bot cannot see normal group messages.
3. Send `/start` in the group. The bot registers the group and confirms.
4. Send the bot a private message (tap its name in the member list → **Send Message**). As a group admin you will get the full menu.
5. Teach it a banned word: send `/block كلمة` in the group. `/unblock كلمة` removes it. The word list starts empty — that is intentional, so every community chooses its own words.
6. **Practise before enforcing.** The default setting is `DRY_RUN=true`, which means the bot only writes into its log what it *would* do — it deletes nothing. Watch the logs for a day, then set `DRY_RUN=false` in `.env`, restart the bot, and moderation goes live.
7. Optional: if your group uses forum **topics**, create one for the moderation log and put its ID in `LOG_TOPIC_ID`. Violations will be posted there with «تجاهل» (ignore) and «كتم ٢٤ ساعة» (mute 24h) buttons.

---

## If something goes wrong

Find your symptom below. If it is not here, open an [issue](https://github.com/1aliAhmed/Mechatronics-Bot/issues) and paste the error text.

| What you see | What it means | What to do |
|---|---|---|
| `python3.12 is not recognized` or `command not found` | Python is not installed, or has a different command name | Install from [python.org](https://www.python.org/downloads/). On Windows try `py -3.12` instead of `python3.12` |
| `'cp' is not recognized` | You are in Windows Command Prompt, which spells it differently | Use `copy .env.example .env` instead |
| `Missing required configuration: TELEGRAM_TOKEN, ...` | The `.env` file is missing, incomplete, or not in the project folder | Check the file is named exactly `.env` (not `.env.txt`) and inside the project folder, with the three required lines filled in |
| `BOUND_COMMUNITY_ID must be ... negative numeric ID` or `BOUND_COMMUNITY_ID verification failed` | The group ID is wrong, or the bot has not been added to that group yet | Re-check the ID with the helper bot. Add the bot to the group first, then start it again |
| The bot ignores normal messages in the group | Telegram is still hiding messages from it, or it is not an admin | BotFather → `/setprivacy` → your bot → **Disable**; and make the bot an administrator |
| The bot does not reply in private chat | Check the terminal window — an error is probably printed there | Also note free AI models can be slow; give it a moment |
| `Only :free models are allowed unless listed in PAID_MODELS` | A model name in `.env` is not free | Use a name ending in `:free`, or add the model to `PAID_MODELS` if you truly want to pay |
| `Conflict: terminated by other getUpdates request` | The bot was started twice | Close all windows running it, then start one copy |
| Where are the files it saves? | Downloaded media, generated PDFs, and logs | In the `data` folder next to the code (change with `DATA_DIR`) |

---

## What the bot can do

A tour in plain language. You do not need any of this to finish the setup — it is here so you know what you have.

### Moderation

- Watches every group message for banned words, in **English and Arabic**. The list is yours: it starts empty and is managed live with `/block` and `/unblock` — no word list ships with the project.
- **Practice mode is the default.** With `DRY_RUN=true` the bot only records what it would do. Flip it to `false` when you are ready and it starts enforcing: the offending message is deleted, and its author sees a private note (only they can see it) that disappears by itself after a minute.
- **Strikes** are like warning marks. Three strikes lead to a time-out ladder: 15 minutes → 30 minutes → 24 hours. Strikes older than 30 days (`STRIKE_DECAY_DAYS`) are forgotten.
- **Fair to everyone:** admins and the owner are also warned and their messages are removed — but they are never muted. (Accounts listed in `ADMIN_IDS` never collect strikes.)
- Moderator tools: `/warns` shows one member's history; `/stats` gives a 30-day report (activity per day, most common bad words, top offenders).
- Edited messages and photo captions are re-checked, so a banned word cannot be sneaked in after posting.
- **Group mute:** from a private chat, `/groups` lets an admin freeze an entire group (read-only) with a pinned notice. Unfreezing removes it again.

### The AI study window

- **Anyone on Telegram can privately message the bot**, even without being in your group. First contact gets a friendly introduction (including your `REPO_URL` if you set one).
- It understands **text, photos, voice notes, and photo albums**. Voice notes are first converted to text (transcribed) — using Groq's free Whisper model when configured, otherwise OpenRouter's audio models.
- Study tools: `/summary` (short bullet summary), `/notes` (organised notes), `/explain` (step-by-step explanation), `/exercise` (practice problem with hint and solution), `/flash` (revision flashcards). `/new` starts a fresh conversation; `/usage` shows your remaining daily allowance.
- **Fair-use limits** protect the free service: by default 10 messages per rolling hour per public user (`DM_QUOTA_1H`), with optional 5-hour and 24-hour windows. Admins of your community and the `ADMIN_IDS` list have no limits.
- **Built to survive hiccups:** the bot tries your main AI model first, then a list of backup models, then Groq — so one provider being down does not take the bot down. Answers arrive as plain text, without weird formatting characters, so they read nicely in Telegram.

### From source to study document

- Send the bot a **PDF** (or photos of pages) and it builds a clean study document: every page is read with an AI vision model, the content is rewritten as organised Arabic notes, and the result is a proper PDF with a cover page, page numbers, right-to-left Arabic layout, and the original page images included at the end so diagrams and labels survive the conversion.
- Ask for the **تلخيص** (simplify) preset and the result becomes a simplified study sheet: plain-language key ideas, and up to four illustrations (`SOURCE_WEB_IMAGE_LIMIT`) automatically looked up on Wikimedia Commons — each one credited with its licence.
- **Progress and recovery:** `/source_status` shows live progress (like `3/10`), you can ask for a page range («أول 10 صفحات» / "first 10 pages"), failed pages are retried or skipped, and one bad scan cannot kill the whole document. Pages with clean selectable text are read directly (no AI needed); scanned or illustrated pages go to the vision model.
- **You publish, not the bot.** Every finished document comes with **Publish** (choose from a list of groups/channels), **Request revision** («طلب تعديل»), and **Redo** buttons. Nothing is posted anywhere until you press a button.
- Visitors can use this too, capped at 10 pages per document (`PUBLIC_SOURCE_PAGES`). Their result arrives privately without publishing buttons.

### Drawings and diagrams

- Ask in Arabic or English — «ارسم دائرة», "draw a sine wave" — or use `/visual`, `/image`, `/draw`. The bot writes and runs the drawing code on its own side, so nothing needs to be installed for members: it sends back a plot (charts via [matplotlib](https://matplotlib.org/)) or a diagram (via [Graphviz](https://graphviz.org/)).
- Requests for pictures rather than charts (a logo, an illustration) go to a free text-to-image service (Pollinations) first; an optional paid image model can be configured as a fallback.
- **Self-repair:** if the generated drawing code fails, the error is sent back to the AI, which tries again — up to three times.
- Study questions stay study questions: phrases like «اشرح...» (explain) are answered in the normal chat instead of being turned into a drawing.

---

## Who can use what

The access model is deliberately tiered — the study window is open to any Telegram user behind a fair-use quota, while community-management tools stay with the community's admins:

| Who | Can do |
|---|---|
| Owner (`ADMIN_IDS`) | Everything; exempt from strikes/mute and quota (bad words are still deleted, with a warning) |
| Admins of the bound community (`BOUND_COMMUNITY_ID`) | The full private window, `/groups` mute control, the sources → PDF pipeline, `/block` `/unblock` `/reset`, moderation buttons; same warning-only treatment for bad words |
| **Any Telegram user (private chat)** | The study window — text, photos, voice, drawings, and **PDF/multi-image sources** (up to `PUBLIC_SOURCE_PAGES`, 10 pages by default) — under the fair-use quota (10 per rolling hour by default) |
| Admins of a **guest group** (the bot is present, but it is not the home community) | Their group gets moderation, welcomes and mute; they get `/warns` and `/stats` there, plus `/groups` for their own groups |
| Members of any group the bot serves | Are moderated and welcomed; no commands |

---

## Settings explained

All settings live in the `.env` file you created in Step 6. **Only the three lines from the Quickstart are required** — everything below has a sensible default and can be ignored until you need it. (Use Ctrl+F / search to find a name.) Defaults are shown where they exist.

**Telegram and access**

| Key | Default | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | — | BotFather token (required) |
| `BOUND_COMMUNITY_ID` | — | Your home group's negative ID (required, verified at startup) |
| `BOUND_COMMUNITY_USERNAME` | — | Optional identity check (e.g. `mygroup`) |
| `BOUND_COMMUNITY_URL` | — | Optional display link |
| `COMMUNITY_NAME` | — | Community display name used in the first-contact intro |
| `LOG_TOPIC_ID` | — | Forum topic ID for the moderation log |
| `ADMIN_IDS` | — | Comma-separated owner trust list; always allowed, never moderated |
| `ADMIN_CACHE_SECONDS` | `900` | How long the bot remembers who is an admin before asking Telegram again (seconds) |
| `COMMUNITY_CHAT_ID` | — | Old name of `BOUND_COMMUNITY_ID`, kept for migrations — ignore unless you are migrating |

**AI providers**

| Key | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required; OpenRouter models must end in `:free` or be listed in `PAID_MODELS` |
| `CHAT_MODEL` | `inclusionai/ling-3.0-flash-sante:free` | Primary chat model (all study tools/actions) |
| `CHAT_FALLBACK_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free,poolside/laguna-s-2.1:free` | Backup models tried (in order) if the main one fails |
| `VISION_MODEL` | `dots-studio/dots-3-note-preview:free` | Model that reads photos and PDF pages (can share `CHAT_MODEL`) |
| `VISION_FALLBACK_MODELS` | — | Optional backup list for the vision model |
| `PAID_MODELS` | — | Comma list of paid OpenRouter ids you explicitly allow (e.g. `deepseek/deepseek-v4.1-flash`) |
| `AUDIO_MODELS` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Backup chain for audio transcription |
| `GROQ_API_KEY` | — | Optional free tier: Whisper transcription + `GROQ_CHAT_MODEL` |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Groq chat model |
| `GROQ_CHAT_FIRST` | `true` | `true` tries Groq first for text-only turns; `false` puts it last |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Groq transcription model |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Address override, for proxies |
| `IMAGE_MODEL` | — | Optional paid image-generation fallback (illustrations use free Pollinations first) |
| `RATE_LIMIT_RPM` | `8` | How many AI requests per minute the bot makes at most (keeps you inside free limits) |
| `DAILY_CAP` | `200` | Daily AI-request budget per non-admin user (admins unlimited) |

**Moderation**

| Key | Default | Meaning |
|---|---|---|
| `DRY_RUN` | `true` | Practice mode: only log what would be deleted, until you flip it to `false` |
| `WARNING_DELETE_SECONDS` | `60` | How long the author-only warning stays before it deletes itself (seconds) |
| `WELCOME_ENABLED` | `true` | Welcome new members |
| `WELCOME_DELETE_SECONDS` | `60` | How long the welcome message stays (seconds) |
| `MUTE_WARNING_SECONDS` | `15` | How long the private mute notice stays (seconds) |
| `STRIKE_DECAY_DAYS` | `30` | Violations older than this many days stop counting |

**Sources and limits**

| Key | Default | Meaning |
|---|---|---|
| `MAX_MEDIA_BYTES` | `18874368` (18 MB) | Largest file the bot will download |
| `MAX_TEXT_CHARS` | `12000` | Longest text document it will accept |
| `SOURCE_IMAGE_LIMIT` | `30` | How many source-page images are attached to a generated PDF |
| `PUBLIC_SOURCE_PAGES` | `10` | Page cap for non-admin source jobs (0 disables; admins use `MAX_SOURCE_PAGES` = 200) |
| `SOURCE_WEB_IMAGE_LIMIT` | `4` | Wikimedia Commons illustrations fetched for simplified documents |
| `CONTEXT_TOKEN_BUDGET` | `24000` | Roughly how much conversation the AI keeps in mind (in tokens — small chunks of text) |
| `DATA_DIR` | `data` | Folder for downloaded media, generated files and logs |
| `AUDIT_RETENTION_DAYS` | `90` | How long the activity log is kept (days) |

**Public window**

| Key | Default | Meaning |
|---|---|---|
| `REPO_URL` | — | Shown in the first-contact intro (e.g. your GitHub repo) |
| `DM_QUOTA_1H` | `10` | Fair-use messages per rolling hour per public user (0 disables) |
| `DM_QUOTA_5H` | `0` | Optional 5-hour window (0 disables) |
| `DM_QUOTA_24H` | `0` | Optional 24-hour window (0 disables) |

---

## Commands

Commands are messages that start with `/`. The bot knows they are instructions, not conversation. Type them in the group or in a private chat as shown.

| Context | Command | What it does |
|---|---|---|
| Private chat (admins) | `/start` `/menu` `/help` | Open the window, the main menu, the guide |
| | `/summary` `/notes` `/explain` `/exercise` `/flash` | Study actions (reply to a message, or send text/photo/voice) |
| | `/new` `/usage` | Start a fresh conversation · check your daily allowance |
| | `/visual …` `/image …` `/draw …` `/visual-dot …` | Generate a plot or diagram |
| | `/source_status [job]` | Progress of a PDF job (no argument = most recent) |
| | `/revise TOKEN NOTES` | Produce a revised version of a processed document |
| | `/groups` | Pick a group you administer → mute/unmute, or per-topic mute in forum groups |
| Any chat | `/rules` | Post the community rules |
| Group (any managed) | `/warns` (reply or `@user`) · `/stats` | One member's history · 30-day report |
| Community (admin) | `/block WORD` `/unblock WORD` `/reset USER` | Edit the word filter · clear a member's violations |
| Owner | `/ping` | Liveness check ("is the bot alive?") |

---

## How it works

Optional reading — this part is for developers and the curious; you can skip it.

```
app/
  main.py          entry point: routers, middleware, command scopes
  security.py      the single authorization boundary for every update
  config.py        typed settings from environment (fails fast on :free violations)
  db.py            SQLite (WAL) schema, migrations, queries
  audit.py         SQLite + JSONL audit trail with daily pruning
  formatting.py    deterministic answer normalisation (Telegram-safe plain text)
  media.py         hash-addressed media store, validation, normalisation
  filters/engine.py  whole-word English + Arabic boundary matching
  ai/providers.py  OpenRouter/Groq clients, retries, pacing, daily caps
  ai/queue.py      durable job queue (sources pipeline)
  flows/
    admin.py       DM window: menus, study actions, media intake, quota, /groups
    community.py   rules, welcomes, group registration
    moderation.py  filter commands, warnings, strikes, mute enforcement, /warns, /stats
    clean.py       sources → Markdown → Typst → PDF pipeline, revisions, publish
    visuals.py     draw intents, server-side rendering, self-repair loop
  quota.py         public fair-use windows (rolling hourly by default)
  render/          Typst conversion + PDF assembly
prompts/           study harness, source format spec, rules, welcome
deploy/            installer, systemd unit, backup script
tests/             137 offline tests — no secrets, no network
```

The files under `prompts/` — community rules, the welcome text, the study harness, and the
source-document style contract — are plain Markdown meant to be edited for your community.

**Moderation path:** update → `CommunityGuard` (auth, chat registration) → per-chat filter
match → violation row → strike (decayed) → delete + ephemeral warning + auto-mute when the
ladder says so → audit entry + log-topic post with moderation buttons.

**Study path:** DM → guard (bound-community admin) → context assembly within token budget →
provider chain (Groq → OpenRouter `:free` → fallbacks, retrying on error/empty) → formatter →
answer. Media takes the vision or transcription route first.

**Source path:** file/album → durable job (`queued` → `running` with page progress) → per page:
render JPEG → vision transcription → Markdown; document-level structuring under
`prompts/source_style.md` → Typst → PDF + image appendix → buttons for publish/revision/redo.

---

## Running the tests

Optional, for developers. The tests are automatic checks that every part of the bot still behaves correctly — they run entirely offline (no tokens, no network) against pretend services.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q        # 137 passed
```

---

## Deploying to a server

Everything above runs the bot on your own computer. If you want it online around the clock — so it keeps working when your computer is off — you need a small Linux server. People usually rent one (a "VPS") for a few dollars a month. This section assumes you are comfortable working on a server; skip it until you need it.

`deploy/install.sh` is a setup script that can be run more than once safely. It works on Oracle Linux / RHEL (`dnf`) and Debian/Ubuntu (`apt`) and installs: the system packages, a Python 3.12 environment, Graphviz, the Noto Naskh Arabic font, Typst, optionally a static ffmpeg, a dedicated `megatronics` system user, the service definition, and a daily backup job at 03:00 that keeps the last 7 backups.

```bash
sudo bash deploy/install.sh
sudo nano /opt/megatronics/.env
sudo systemctl enable --now megatronics-bot
```

(`sudo` runs a command as administrator; `nano` is a text editor that works inside the terminal; `systemctl` starts and controls background services.)

The installer pins two conventions: `APP_DIR=/opt/megatronics` and a `megatronics` service (systemd) user. To change either, edit `deploy/install.sh`, `deploy/megatronics-bot.service`, and `deploy/backup.sh` together.

Operational notes learned the hard way:

- The service runs with `PrivateTmp=true` (a Linux security setting that gives it its own empty `/tmp`) — files for the bot must live under its data folder, not `/tmp`.
- Keep heavy jobs serialised; the processing queue assumes a small machine (1 processor core).
- Backups are SQLite-safe snapshots of the database plus files and logs — no downtime needed.

---

## Roadmap

- Quiz mode with timed tests and grading
- Per-group settings (welcome text, rules, log target, moderation toggle)
- Spaced repetition for `/flash` cards with Anki/CSV export
- Flood/anti-spam heuristics on top of the strike ladder
- Appeal flow for muted members

---

## Contributing and security

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For security issues,
follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

MIT — see [LICENSE](LICENSE). The default configuration runs on Groq and OpenRouter free tiers;
paid ids work only when you explicitly allowlist them in `PAID_MODELS`.
