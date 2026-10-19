# Megatronics Bot

A bilingual (Arabic/English) Telegram bot that runs an engineering-student community end to end:
**moderation**, an **AI study window open to every Telegram user**, a **source-document → study-PDF
pipeline**, and **server-side charts and diagrams** — all in one Python process, on free-tier model
providers.

Built for a mechatronics student community; everything community-specific lives in `.env` and
`prompts/`, so another community can adopt it without touching the code.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![Tests](https://img.shields.io/badge/tests-137%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

**Contents**

- [What it does](#what-it-does)
- [Inputs and outputs](#inputs-and-outputs)
- [How it works](#how-it-works)
- [Setup](#setup)
- [Deploying to a server](#deploying-to-a-server)
- [Configuration](#configuration)
- [Commands](#commands)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Roadmap](#roadmap)
- [Contributing and security](#contributing-and-security)
- [License](#license)

---

## What it does

The bot is bound to one home community (a Telegram group) and can also serve guest groups. It
covers the two sides of running that community — keeping it clean and helping members study — in
a single process with no external services beyond the AI APIs.

### Moderation

- Filter for banned words in **English and Arabic** — whole-word matching for English, script-boundary matching for Arabic. No word list ships with the repository; it lives in the bot database and is curated live with `/block` and `/unblock`.
- **Dry-run first.** `DRY_RUN=true` (the default) logs what would be removed without touching messages. When enabled for real, the offending message is deleted and its author receives an ephemeral warning (visible only to them, auto-deletes after 60 s).
- **Strike ladder:** violations within `STRIKE_DECAY_DAYS` (30 by default) accumulate; the third strike escalates 15 min → 30 min → 24 h mute.
- The filter applies to **everyone, admins included** — their messages are removed and warned the same way, but exempt users (`ADMIN_IDS`, community admins) never collect strikes or get muted.
- **Edited messages and media captions are re-checked**, so a banned word cannot be slipped in after posting.
- Moderator tooling: `/warns` (member case file) and `/stats` (30-day report: per-day counts, top words, top offenders), available to admins in any group the bot serves.
- **Group mute:** `/groups` in a private chat lets an admin freeze a whole group (read-only) with a pinned notice; unmuting cleans it up.

### AI study window

- **Any Telegram user can message the bot privately**, whether or not they are in the community. First contact receives a one-time introduction (with the project link when `REPO_URL` is set).
- Study actions: `/summary`, `/notes`, `/explain`, `/exercise`, `/flash`. Answers are deterministic-format plain text, context is kept per chat, `/new` resets it, `/usage` shows the remaining allowance.
- **Photos and albums** are analyzed by a vision model (albums are debounced and processed together); **voice notes** are transcribed first and answered like text.
- **Fair-use quota** for public users: 10 messages per rolling hour (`DM_QUOTA_1H`), with optional 5-hour and 24-hour windows (`DM_QUOTA_5H`/`DM_QUOTA_24H`, 0 disables). Admins of the bound community and `ADMIN_IDS` are exempt.
- **Resilient model routing:** configured model → ordered fallback list → Groq free tier. Reasoning-only models are read from their reasoning field. OpenRouter ids must end in `:free` unless explicitly allowlisted in `PAID_MODELS`, so the bot cannot bill you by accident.

### Source → study document

- Send a **PDF** (or multiple page photos) and a durable job takes over: pages are transcribed by the vision model, structured into Arabic Markdown, converted to Typst, and rendered as a clean PDF with a cover page, page numbers, real RTL typography, and an **appendix of the original page images** so diagrams survive the conversion.
- With the **تلخيص (simplify) preset** pending, the output becomes a simplified study document: key ideas in plain language, icons allowed, and up to `SOURCE_WEB_IMAGE_LIMIT` (4) illustrations fetched from **Wikimedia Commons**, each credited with its licence and source.
- **Per-page routing:** pages with a solid text layer and no real raster images are read directly from the PDF (no model call); scanned or illustrated pages go to the vision model; a failed vision pass falls back to the text layer. Transcription runs with up to 4 pages in flight.
- **Operational guarantees:** live progress (`/source_status` → `3/10`), page ranges («أول 10 صفحات» / "first 10 pages"), retries, per-page skip, and output files named after the document title.
- Every artefact ships with **Publish** (a picker of every group/channel where the bot can post), **Request revision** («طلب تعديل»), and **Redo**. Publication is always a deliberate action. Public users can submit sources too — capped at `PUBLIC_SOURCE_PAGES` (10) — and receive the result privately without publishing buttons.

### Visuals

- «ارسم …» / «رسم …» / `/visual` / `/image` / `/draw` renders **matplotlib** plots or **Graphviz** diagrams server-side and returns the image. Arabic trigger words are matched as whole words; question prefixes («اشرح…», «ما هو…») go to the study chat instead.
- Illustration-style requests (logos, pictures) route to **free text-to-image generation** (Pollinations, no key, no cost) with an optional paid `IMAGE_MODEL` fallback.
- Generated render code is AST-validated and executed in an isolated interpreter with a timeout; a failed render feeds the traceback back to the model for up to 3 self-repair attempts.

### Operations

- Every inbound and outbound action is recorded in an audit trail (SQLite + daily JSONL files, pruned after `AUDIT_RETENTION_DAYS`). Media is hash-addressed and deduplicated.
- Rendering, Typst, and Graphviz run in subprocesses off the event loop, so the bot stays responsive on a 1-vCPU box.
- `deploy/` ships an idempotent installer (Oracle Linux/RHEL and Debian/Ubuntu), a hardened systemd unit, and a daily SQLite-safe backup with 7-day rotation.

### Access model

| Who | Can do |
|---|---|
| Owner (`ADMIN_IDS`) | Everything; exempt from strikes, mutes, and quotas (bad words are still removed, with a warning) |
| Community admins (`BOUND_COMMUNITY_ID`) | Full private window, `/groups` mute control, the source → PDF pipeline, `/block` `/unblock` `/reset`, moderation buttons; warning-only treatment for bad words |
| Any Telegram user (private chat) | The study window — text, photos, voice, visuals, and PDF/multi-image sources (up to 10 pages) — under the fair-use quota |
| Admins of a guest group | That group gets moderation, welcomes, and mute; its admins get `/warns` and `/stats`, plus `/groups` for their own groups |
| Members of any served group | Moderated and welcomed; no commands |

---

## Inputs and outputs

### What you can send it

| Input | Handling |
|---|---|
| **Text** (Arabic or English) | Answered with the configured chat model, with per-chat conversation context and token-budget trimming |
| **Photos** and **image albums** | Analyzed by the vision model; albums are debounced and analyzed together |
| **Voice notes** and **audio files** | Transcribed (Groq Whisper first when configured, OpenRouter audio models as fallback), then answered like text |
| **Text documents** (`.txt`, `.md`, `.csv`, `.log`, `.json`) | Read as study material, up to `MAX_TEXT_CHARS` (12 000 characters) |
| **PDFs** and **multi-page image sources** | Queued as a source job and rebuilt into a study PDF; admins up to 200 pages, public users up to `PUBLIC_SOURCE_PAGES` (10) |
| **Commands** | `/summary`, `/notes`, `/explain`, `/exercise`, `/flash`, `/visual`, `/source_status`, `/groups`, `/block`, … (full list below) |
| **Drawing requests** | «ارسم …» / "draw …" or `/visual` — rendered server-side |
| **Member activity** (in groups) | Messages, edits, and captions pass through the moderation filter; joins trigger the welcome flow |

Downloads are capped at `MAX_MEDIA_BYTES` (18 MB per file).

### What it sends back

| Output | Format |
|---|---|
| **Answers and study material** | Plain text, deterministic formatting (Telegram-safe, no markdown artifacts), split into 4 000-character messages |
| **Summaries / notes / exercises / flashcards** | Text generated by the study presets |
| **Charts** | PNG rendered with matplotlib |
| **Diagrams** | PNG rendered from Graphviz DOT |
| **Illustrations** | PNG via free Pollinations text-to-image, optional paid fallback |
| **Study documents** | PDF with cover page, page numbers, RTL Arabic typography, and an appendix of the source page images |
| **Revisions** | New PDF generated from your notes (`/revise` or the «طلب تعديل» button) |
| **Moderation actions** | Message deletion, ephemeral warnings, timed mutes, log-topic posts with «تجاهل» / «كتم ٢٤ ساعة» buttons |
| **Reports and status** | `/warns` case file, `/stats` 30-day report, `/source_status` job progress, `/usage` quota |
| **Community messages** | `/rules` posting and the welcome message for new members |

---

## How it works

```
Telegram ──long polling──▶ aiogram dispatcher
                              │
                     CommunityGuard (authorization on every update)
                              │
        ┌─────────────┬───────┴────────┬──────────────┐
   Moderation     Study window    Source pipeline   Visuals
        │             │                │              │
        └─────────────┴───────┬────────┴──────────────┘
                              ▼
                 Provider chain: OpenRouter / Groq
                              │
              SQLite (state, jobs, audit) + Typst / Graphviz / PyMuPDF
```

### Runtime

- **Python 3.12+, aiogram 3.x, long polling.** There is no web server and no inbound port — the bot asks Telegram for updates, which is why the process must stay running.
- **One asyncio process.** CPU-heavy work (rendering, Typst compilation, audio conversion, PDF text extraction) runs in subprocesses with timeouts, off the event loop.
- **Authorization** goes through a single middleware (`app/security.py`) on every update: chat registration, cached admin checks (`ADMIN_CACHE_SECONDS`), the `ADMIN_IDS` trust list, and the public quota service (`app/quota.py`).
- **State** lives in SQLite in WAL mode (`app/db.py`): settings, sessions, violations, media records, documents, API usage — plus a durable job queue (`app/ai/queue.py`) with `queued → running` states, page progress, and retries.
- **AI providers** (`app/ai/providers.py`): OpenRouter and Groq clients with ordered fallbacks, retry/backoff on 429/5xx, requests-per-minute pacing, per-user daily caps, and enforcement of the `:free` rule.
- **Media** (`app/media.py`): MIME validation, hash-addressed storage (the same file is never stored twice), and ffmpeg normalization for transcription.
- **Source pipeline** (`app/flows/clean.py`, `app/render/`): PyMuPDF for the text layer and page images, per-page routing between direct extraction and the vision model, bounded concurrency, Markdown → Typst → PDF assembly.
- **Visuals** (`app/flows/visuals.py`): generated code is parsed and checked (imports, unsafe calls), then executed with `python -I` in a temporary directory with a timeout; Graphviz accepts DOT source. Failed renders are retried with the error fed back to the model.
- **Audit** (`app/audit.py`): SQLite rows plus daily JSONL files, pruned on a retention schedule.

### Hosting

- Designed for a **small Linux VPS (1 vCPU)**. It also runs on Windows and macOS for development; the deploy scripts target Linux.
- The systemd unit (`deploy/megatronics-bot.service`) runs as a dedicated `megatronics` user with `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, and write access only to `/opt/megatronics/data`; `Restart=always` keeps it alive.
- `deploy/install.sh` is idempotent across `apt` and `dnf`: system packages, Python 3.12 virtualenv, Graphviz, Noto Naskh Arabic and emoji fonts, Typst, and ffmpeg (falling back to a static build). It creates the service user, installs the unit, and registers a **daily 03:00 backup** with 7-day rotation.
- Backups are SQLite-online-safe: a consistent `bot.db` snapshot plus `data/files` and `data/logs`, with no downtime.
- Runtime data stays in `DATA_DIR` (`data/` by default): `bot.db`, `files/` (media and generated artefacts), and `logs/`.

**Tech stack:** Python 3.12 · aiogram 3.x · SQLite (WAL) · OpenRouter / Groq APIs · PyMuPDF · Typst · Graphviz · matplotlib · Pillow · ffmpeg · python-dotenv.

---

## Setup

### Prerequisites

- **Python 3.12+**
- A **Telegram bot token** from [@BotFather](https://t.me/BotFather)
- An **OpenRouter API key** (free tier; the default models all end in `:free`)
- Optional: a **Groq API key** for Whisper voice transcription
- Optional system tools, for the features that use them: **Graphviz** (diagrams), **Typst** (PDF rendering), **ffmpeg** (voice conversion), **Noto Naskh Arabic** (RTL fonts). The server installer provides all of them.

### 1. Create the bot

1. In Telegram, open [@BotFather](https://t.me/BotFather) → `/newbot` and follow the prompts.
2. Copy the token (`123456789:AAE...`). Treat it as a password.
3. Run `/setprivacy` → select your bot → **Disable**. This is required: with privacy mode enabled, Telegram does not deliver normal group messages to the bot, so moderation cannot work.

### 2. Install

```bash
git clone https://github.com/1aliAhmed/Mechatronics-Bot.git
cd Mechatronics-Bot
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Windows, use `.venv\Scripts\` instead of `.venv/bin/` and `py -3.12` if `python3.12` is not on `PATH`.

### 3. Configure

```bash
cp .env.example .env
```

The bot loads `.env` from the project root automatically. Fill in the required keys:

```ini
TELEGRAM_TOKEN=123456789:AAE...
BOUND_COMMUNITY_ID=-1001234567890
OPENROUTER_API_KEY=sk-or-...
```

`BOUND_COMMUNITY_ID` is your group's numeric ID — negative, and usually starting with `-100` for supergroups. An ID helper bot such as [@userinfobot](https://t.me/userinfobot) reports it; the bot verifies it against Telegram at startup.

`COMMUNITY_NAME` and `REPO_URL` personalize the first-contact intro. Everything else has a default — see [Configuration](#configuration).

### 4. Run

```bash
.venv/bin/python -m app.main
```

A healthy startup ends with `Bot polling started`. Stop it with `Ctrl+C`.

### 5. First run in Telegram

1. Add the bot to your group and promote it to **administrator** with delete, restrict, and pin rights.
2. Send `/start` in the group — the bot registers the chat.
3. Send the bot a private message — as a community admin you get the full menu.
4. Seed banned words with `/block كلمة` (and `/unblock كلمة` to remove them).
5. Keep `DRY_RUN=true` while you review the logs, then set `DRY_RUN=false` and restart to enforce.
6. Optional: create a forum topic for the moderation log and set `LOG_TOPIC_ID`; violations will be posted there with moderation buttons.

### Common setup issues

| Symptom | Cause | Fix |
|---|---|---|
| `Missing required configuration: ...` | `.env` missing, incomplete, or in the wrong directory | Check the file name (`.env`, not `.env.txt`) and the three required keys |
| `BOUND_COMMUNITY_ID verification failed ...` | Wrong ID, or the bot is not in that group | Re-check the ID and add the bot to the group |
| The bot ignores normal group messages | Privacy mode still enabled, or the bot is not an administrator | BotFather → `/setprivacy` → **Disable**; re-check admin rights |
| `Conflict: terminated by other getUpdates request` | Two instances are polling with the same token | Stop the duplicate and run one |
| `Only :free models are allowed unless listed in PAID_MODELS` | A model name in `.env` is not free | Use a `:free` id, or explicitly allow the paid id in `PAID_MODELS` |

---

## Deploying to a server

For 24/7 operation, run the bot on a Linux server (Oracle Linux/RHEL or Debian/Ubuntu):

```bash
sudo bash deploy/install.sh
sudo nano /opt/megatronics/.env
sudo systemctl enable --now megatronics-bot
```

The installer uses two fixed conventions: `APP_DIR=/opt/megatronics` and the `megatronics` service user. To change either, update `deploy/install.sh`, `deploy/megatronics-bot.service`, and `deploy/backup.sh` together.

Operational notes:

- The unit sets `PrivateTmp=true`, so working files must stay under `DATA_DIR`, not `/tmp`.
- Heavy jobs are serialized by design; the queue assumes a small machine.
- Backups run daily at 03:00 and keep 7 days. They use SQLite's online backup API, so no downtime is needed.
- One process per bot token. Long polling plus SQLite means there is no multi-instance mode.

---

## Configuration

All settings live in `.env`; only the three keys from Setup are required. Defaults are shown where they exist.

**Telegram and access**

| Key | Default | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | — | BotFather token (required) |
| `BOUND_COMMUNITY_ID` | — | Home group's negative ID (required, verified at startup) |
| `BOUND_COMMUNITY_USERNAME` | — | Optional identity check (e.g. `mygroup`) |
| `BOUND_COMMUNITY_URL` | — | Optional display link |
| `COMMUNITY_NAME` | — | Community name used in the first-contact intro |
| `LOG_TOPIC_ID` | — | Forum topic ID for the moderation log |
| `ADMIN_IDS` | — | Comma-separated owner trust list; always allowed, never moderated |
| `ADMIN_CACHE_SECONDS` | `900` | Admin-status cache lifetime |
| `COMMUNITY_CHAT_ID` | — | Legacy alias for `BOUND_COMMUNITY_ID`; ignore unless migrating |

**AI providers**

| Key | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required; model ids must be `:free` or listed in `PAID_MODELS` |
| `CHAT_MODEL` | `inclusionai/ling-3.0-flash-sante:free` | Primary chat model |
| `CHAT_FALLBACK_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free,poolside/laguna-s-2.1:free` | Ordered fallback chain |
| `VISION_MODEL` | `dots-studio/dots-3-note-preview:free` | Image and PDF-page analysis |
| `VISION_FALLBACK_MODELS` | — | Optional vision fallbacks |
| `PAID_MODELS` | — | Paid OpenRouter ids you explicitly allow |
| `AUDIO_MODELS` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Audio transcription fallback chain |
| `GROQ_API_KEY` | — | Optional free tier: Whisper + `GROQ_CHAT_MODEL` |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Groq chat model |
| `GROQ_CHAT_FIRST` | `true` | Try Groq first for text-only turns |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Groq transcription model |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Proxy/endpoint override |
| `IMAGE_MODEL` | — | Optional paid image-generation fallback |
| `RATE_LIMIT_RPM` | `8` | Requests per minute |
| `DAILY_CAP` | `200` | Daily model-call budget per non-admin user |

**Moderation**

| Key | Default | Meaning |
|---|---|---|
| `DRY_RUN` | `true` | Log-only until set to `false` |
| `WARNING_DELETE_SECONDS` | `60` | Lifetime of the author-only warning |
| `WELCOME_ENABLED` | `true` | Welcome new members |
| `WELCOME_DELETE_SECONDS` | `60` | Lifetime of the welcome message |
| `MUTE_WARNING_SECONDS` | `15` | Lifetime of the private mute notice |
| `STRIKE_DECAY_DAYS` | `30` | Violations older than this stop counting |

**Sources and limits**

| Key | Default | Meaning |
|---|---|---|
| `MAX_MEDIA_BYTES` | `18874368` (18 MB) | Per-file download cap |
| `MAX_TEXT_CHARS` | `12000` | Text document cap |
| `SOURCE_IMAGE_LIMIT` | `30` | Page images embedded in generated PDFs |
| `PUBLIC_SOURCE_PAGES` | `10` | Page cap for non-admin source jobs (0 disables; admins use 200) |
| `SOURCE_WEB_IMAGE_LIMIT` | `4` | Wikimedia Commons illustrations in simplified documents |
| `CONTEXT_TOKEN_BUDGET` | `24000` | Per-chat context budget |
| `DATA_DIR` | `data` | Media, artefacts, and logs root |
| `AUDIT_RETENTION_DAYS` | `90` | Audit pruning window |

**Public window**

| Key | Default | Meaning |
|---|---|---|
| `REPO_URL` | — | Shown in the first-contact intro |
| `DM_QUOTA_1H` | `10` | Fair-use messages per rolling hour per public user (0 disables) |
| `DM_QUOTA_5H` | `0` | Optional 5-hour window (0 disables) |
| `DM_QUOTA_24H` | `0` | Optional 24-hour window (0 disables) |

---

## Commands

| Context | Command | What it does |
|---|---|---|
| Private chat (admins) | `/start` `/menu` `/help` | Window, main menu, guide |
| | `/summary` `/notes` `/explain` `/exercise` `/flash` | Study actions (reply to a message or send text/photo/voice) |
| | `/new` `/usage` | Reset context · daily budget |
| | `/visual …` `/image …` `/draw …` `/visual-dot …` | Generate a plot or diagram |
| | `/source_status [job]` | Queue/job progress (no argument = latest) |
| | `/revise TOKEN NOTES` | New revision of a processed document |
| | `/groups` | Pick a group you administer → mute/unmute, or per-topic mute in forums |
| Any chat | `/rules` | Post the community rules |
| Group (any managed) | `/warns` (reply or `@user`) · `/stats` | Member case file · 30-day report |
| Community (admin) | `/block WORD` `/unblock WORD` `/reset USER` | Curate the filter · clear a member's violations |
| Owner | `/ping` | Liveness check |

---

## Project layout

```
app/
  main.py            entry point: routers, middleware, command scopes
  security.py        authorization boundary for every update
  config.py          typed settings from environment (fails fast on :free violations)
  db.py              SQLite (WAL) schema, migrations, queries
  audit.py           SQLite + JSONL audit trail with daily pruning
  formatting.py      deterministic answer normalisation (Telegram-safe plain text)
  media.py           hash-addressed media store, validation, normalisation
  filters/engine.py  whole-word English + Arabic boundary matching
  ai/providers.py    OpenRouter/Groq clients, retries, pacing, daily caps
  ai/queue.py        durable job queue (source pipeline)
  flows/
    admin.py         private window: menus, study actions, media intake, quota, /groups
    community.py     rules, welcomes, group registration
    moderation.py    filter commands, warnings, strikes, mute enforcement, /warns, /stats
    clean.py         source → Markdown → Typst → PDF pipeline, revisions, publish
    visuals.py       draw intents, server-side rendering, self-repair loop
  quota.py           public fair-use windows (rolling hourly by default)
  render/            Typst conversion + PDF assembly
prompts/             study harness, source format spec, rules, welcome
deploy/              installer, systemd unit, backup script
tests/               137 offline tests — no secrets, no network
```

The Markdown files under `prompts/` (community rules, welcome text, study harness, source-document
style contract) are meant to be edited per community.

---

## Tests

The suite is fully offline — no tokens, no network, no hidden state. Every flow is exercised
against fakes, including moderation enforcement, the job queue, the provider fallback chain, and
the PDF page loop.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q        # 137 passed
```

---

## Roadmap

- Quiz mode with timed tests and grading
- Per-group settings (welcome text, rules, log target, moderation toggle)
- Spaced repetition for `/flash` cards with Anki/CSV export
- Flood/anti-spam heuristics on top of the strike ladder
- Appeal flow for muted members

---

## Contributing and security

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For security issues, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

MIT — see [LICENSE](LICENSE). The default configuration runs on Groq and OpenRouter free tiers;
paid ids work only when explicitly allowlisted in `PAID_MODELS`.
