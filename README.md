# Megatronics Bot

A bilingual (Arabic/English) Telegram bot that runs an engineering student community end to end:
**moderation**, an **AI study window open to everyone**, a **source → study-PDF pipeline**,
**visual rendering**, and **audit trails** — all on free-tier model providers, all in one Python
process.

Built for a mechatronics student community, structured so any community can adopt it.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0)
![Tests](https://img.shields.io/badge/tests-137%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

**Community moderation (bilingual, per group)**
- English whole-word matching and Arabic script-boundary matching — no word list ships in the
  repository. The list lives in the bot database and is curated live with `/block` and `/unblock`.
- `DRY_RUN=true` is the default: matched text is only *logged*. Flip to `false` after the bot has
  admin rights and moderation goes live: offending message deleted, author warned with an
  ephemeral notice (auto-deletes, default 60 s).
- Strikes are counted from the violation log within a decay window (`STRIKE_DECAY_DAYS`, default
  30) — old violations stop counting. Third strike down the ladder: 15 min → 30 min → 24 h mute.
- The filter and the warning apply to **everyone — admins and the owner included**: their
  offending messages are deleted and warned the same way, but exempt users never accumulate
  strikes and are never muted (the log topic still records the event).
- Moderator tooling: `/warns` member case file and `/stats` 30-day report (per-day counts, top
  words, top offenders), usable by admins in any group the bot serves.
- States that used to evade filters are closed: **edited messages are re-checked**, and posted
  media captions are inspected.
- Group mute (admin tool, DM): pick a group you administer → the bot goes read-only — every
  non-admin message is deleted and its sender sees a private notice that evaporates in 15 s
  («هذه المجموعة مقفلة مؤقتاً؛ لا يمكن إرسال الرسائل الآن…»). A pinned notice announces the
  closure; unmuting cleans both up.

**AI study window (open to everyone, fair-use quota)**
- **Anyone on Telegram can DM the bot** — first contact gets a one-time intro explaining the bot
  (with the GitHub link when `REPO_URL` is set) and the fair-use quota: `DM_QUOTA_1H` messages per
  rolling hour (default 10; optional 5-hour and 24-hour windows via `DM_QUOTA_5H`/`DM_QUOTA_24H`,
  0 disables one). The over-limit reply is explicit that this is a temporary limit. Admins of the
  bound community and the `ADMIN_IDS` list are exempt — no request limits at all.
- `/summary`, `/notes`, `/explain`, `/exercise`, `/flash` — plain-text, deterministic-format
  answers (no markdown junk in Telegram), context kept per chat, `/new` resets it, `/usage` shows
  the remaining quota.
- Photos and albums go through a vision model (albums are debounced and analysed together);
  voice notes are transcribed (Groq free-tier Whisper first, OpenRouter audio models as
  fallback) and answered like text.
- Model routing is resilient by design: the configured model first → ordered fallback list →
  Groq free tier last (`GROQ_CHAT_FIRST=true` puts Groq in front for text-only turns). Reasoning-only
  models are read from their reasoning field. OpenRouter ids must be `:free` unless explicitly
  allowlisted in `PAID_MODELS`, so the bot can't bill you by accident.

**Source → study document pipeline**
- Send a PDF (or photo pages) and the job queue takes over: pages are transcribed by the vision
  model → structured into Arabic Markdown → converted to Typst → rendered as a clean PDF with a
  cover page, page numbers, real RTL typography, and an **appendix of the source page images**
  so diagrams survive the conversion.
- With the **تلخيص (summary) preset pending, the output becomes a simplified study document**:
  key ideas in plain language, icons/emoji allowed, and up to `SOURCE_WEB_IMAGE_LIMIT` (default 4)
  illustrations fetched automatically from **Wikimedia Commons** with license and source credited
  under each image (no invented links).
- Durable SQLite job queue with live progress (`/source_status` → `3/10`), page-range support
  («أول 10 صفحات» / "first 10 pages"), retries, and per-page skip so one bad scan can't kill a
  document. Pages are routed per page: a page with a solid text layer and **no real raster
  images** is read directly from the PDF (no model call), while scanned or illustrated pages go
  to the vision model; a failed vision pass falls back to the text layer. Transcription itself
  runs with bounded concurrency (up to 4 pages in flight), and delivered files are named after
  the document title.
- Every artifact carries **Publish** (opens one picker of every group and channel where the bot
  can post — channels require the bot to be an admin, and the main community is labelled first),
  **Request revision** («طلب تعديل» → send notes → revised document), and **Redo** — publication
  is always a deliberate action.

**Visuals**
- «ارسم …» / «رسم …» / `/visual` / `/image` / `/draw` generates matplotlib plots or Graphviz
  diagrams *server-side* and returns the image. Illustration-style requests (logos, pictures)
  route to **free text-to-image generation** (Pollinations, no key, no cost) with an optional
  paid `IMAGE_MODEL` fallback. Arabic triggers are matched as whole words, and question prefixes
  («اشرح…», «ما هو…») are left to the study chat instead of hijacking them. If a render fails,
  the traceback is fed back to the model (up to 3 self-repair attempts); if code leaks into a
  chat answer, a server-side safety net renders it anyway.

**Operations**
- Every inbound/outbound action is audited (SQLite + daily JSONL files, pruned to
  `AUDIT_RETENTION_DAYS`), media is hash-addressed and deduplicated, and renders/typst/graphviz
  run off the event loop so the bot stays responsive on a 1-vCPU box.
- `deploy/` ships an idempotent installer (Oracle Linux / Debian families), a hardened systemd
  unit, and a daily SQLite-safe backup script with rotation.

---

## Who can use it

The access model is deliberately tiered — the study window is open to any Telegram user behind a
fair-use quota, while community-management tools stay with the community's admins:

| Who | Can do |
|---|---|
| Owner (`ADMIN_IDS`) | Everything; exempt from strikes/mute and quota (bad words are still deleted with a warning) |
| Admins of the bound community (`BOUND_COMMUNITY_ID`) | The full DM window, `/groups` mute control, the sources → PDF pipeline, `/block` `/unblock` `/reset`, moderation buttons; same warning-only treatment for bad words |
| **Any Telegram user (DM)** | The study window — text, photos, voice, visual renders, and **PDF/multi-image sources** (capped at `PUBLIC_SOURCE_PAGES`, default 10 pages) — under the fair-use quota (10 per rolling hour by default; the over-limit reply notes it is temporary). Public documents arrive without publish/revision buttons |
| Admins of a **guest group** (bot present, not the home community) | That group gets moderation, welcome and mute; its admins get `/warns` and `/stats` there, plus `/groups` for their own groups |
| Members of any group the bot serves | Are moderated, receive welcome/rules; no commands |

Authorization runs through one middleware (`app/security.py`) on **every** update, with cached
admin status (refreshed every `ADMIN_CACHE_SECONDS`) and a trust-list override; the public quota
lives in `app/quota.py` and counts rolling windows per user (hourly by default).

---

## Quickstart

### 1. Create the bot
Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.

### 2. Get the project

```bash
git clone https://github.com/<you>/megatronics-bot.git
cd megatronics-bot
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python **3.12+** is required. Optional system tools unlock features when present:
`graphviz` (diagrams), `typst` (PDF rendering — the installer fetches it), `ffmpeg` (voice
conversion), Noto Naskh Arabic (RTL fonts — the installer installs it).

### 3. Configure

```bash
cp .env.example .env
```

The bot loads `.env` from the project root automatically at startup. Minimum to boot:

```ini
TELEGRAM_TOKEN=123456:ABC...
BOUND_COMMUNITY_ID=-1001234567890
OPENROUTER_API_KEY=sk-or-...
```

Optional: `REPO_URL=https://github.com/<you>/megatronics-bot` shows up in the first-contact
intro, `COMMUNITY_NAME` personalises that intro, and `DM_QUOTA_1H` (with optional
`DM_QUOTA_5H`/`DM_QUOTA_24H`) tunes the public fair-use quota.

### 4. First run

```bash
.venv/bin/python -m app.main
```

First-run checklist:

1. Add the bot to your community group **as an administrator** (delete + restrict + pin rights).
2. In [@BotFather](https://t.me/BotFather) run `/setprivacy`, pick your bot, and choose
   **Disable** — moderation needs the bot to see every group message; with privacy mode on it
   only receives commands and replies.
3. Send `/start` in the group — the bot registers the chat and confirms.
4. DM the bot — as a community admin you'll get the menu.
5. Seed a few blocked words: `/block كلمة` in the community (or check the filter with
   `/unblock`).
6. Watch `DRY_RUN=true` logs for a day, then set `DRY_RUN=false` and restart to enforce.
7. Optional: create a forum **topic** for the log and set `LOG_TOPIC_ID` — violations get posted
   there with «تجاهل» / «كتم ٢٤ ساعة» buttons.

---

## Configuration

Every key lives in `.env` (see `.env.example`). Defaults shown where they exist.

**Telegram & access**

| Key | Default | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | — | BotFather token (required) |
| `BOUND_COMMUNITY_ID` | — | Your home group's negative ID (required, verified at startup) |
| `BOUND_COMMUNITY_USERNAME` | — | Optional identity check (e.g. `mygroup`) |
| `BOUND_COMMUNITY_URL` | — | Optional display link |
| `COMMUNITY_NAME` | — | Community display name used in the first-contact intro |
| `LOG_TOPIC_ID` | — | Forum topic ID for the moderation log |
| `ADMIN_IDS` | — | Comma-separated owner trust list; always allowed, never moderated |
| `ADMIN_CACHE_SECONDS` | `900` | Admin-status cache lifetime |

**AI providers**

| Key | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required; OpenRouter models must end in `:free` or be listed in `PAID_MODELS` |
| `CHAT_MODEL` | `inclusionai/ling-3.0-flash-sante:free` | Primary chat model (all study tools/actions) |
| `CHAT_FALLBACK_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free,poolside/laguna-s-2.1:free` | Fallback chain |
| `VISION_MODEL` | `dots-studio/dots-3-note-preview:free` | Page/image analysis (can share `CHAT_MODEL`) |
| `VISION_FALLBACK_MODELS` | — | Optional vision fallbacks |
| `PAID_MODELS` | — | Comma list of paid OpenRouter ids you explicitly allow (e.g. `deepseek/deepseek-v4.1-flash`) |
| `AUDIO_MODELS` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Audio transcription fallback chain |
| `GROQ_API_KEY` | — | Optional free tier: Whisper + `GROQ_CHAT_MODEL` |
| `GROQ_CHAT_MODEL` | `openai/gpt-oss-120b` | Groq chat model |
| `GROQ_CHAT_FIRST` | `true` | `true` tries Groq first for text-only turns; `false` puts it last |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Groq transcription |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Override for proxies |
| `IMAGE_MODEL` | — | Optional paid image-generation fallback (illustrations use free Pollinations first) |
| `RATE_LIMIT_RPM` | `8` | Requests/minute pacing |
| `DAILY_CAP` | `200` | Daily model-call budget per non-admin user (admins unlimited) |

**Moderation**

| Key | Default | Meaning |
|---|---|---|
| `DRY_RUN` | `true` | Log-only until you flip it |
| `WARNING_DELETE_SECONDS` | `60` | Lifetime of the offender-only violation notice |
| `WELCOME_ENABLED` | `true` | Welcome new members |
| `WELCOME_DELETE_SECONDS` | `60` | Lifetime of the welcome message |
| `MUTE_WARNING_SECONDS` | `15` | Lifetime of the private mute notice |
| `STRIKE_DECAY_DAYS` | `30` | Violations older than this stop counting |

**Sources & limits**

| Key | Default | Meaning |
|---|---|---|
| `MAX_MEDIA_BYTES` | `18874368` (18 MiB) | Per-file download cap |
| `MAX_TEXT_CHARS` | `12000` | Text document cap |
| `SOURCE_IMAGE_LIMIT` | `30` | Page-image previews embedded in generated PDFs |
| `PUBLIC_SOURCE_PAGES` | `10` | Page cap for non-admin source jobs (0 disables; admins use `MAX_SOURCE_PAGES` = 200) |
| `SOURCE_WEB_IMAGE_LIMIT` | `4` | Wikimedia Commons illustrations fetched in simplified documents |
| `CONTEXT_TOKEN_BUDGET` | `24000` | Per-chat context budget |
| `DATA_DIR` | `data` | Media, artifacts, logs root |
| `AUDIT_RETENTION_DAYS` | `90` | Audit pruning window |

**Public DM window**

| Key | Default | Meaning |
|---|---|---|
| `REPO_URL` | — | Shown in the first-contact intro (e.g. your GitHub repo) |
| `DM_QUOTA_5H` | `0` | Optional 5-hour window (0 disables) |
| `DM_QUOTA_24H` | `0` | Optional 24-hour window (0 disables) |

---

## Commands

| Context | Command | What it does |
|---|---|---|
| DM (admins) | `/start` `/menu` `/help` | Window, main menu, guide |
| | `/summary` `/notes` `/explain` `/exercise` `/flash` | Study actions (reply to a message or send text/photo/voice) |
| | `/new` `/usage` | Reset context · daily budget |
| | `/visual …` `/image …` `/draw …` `/visual-dot …` | Generate a plot or diagram |
| | `/source_status [job]` | Queue/job progress (no argument = latest) |
| | `/revise TOKEN NOTES` | New revision of a processed document |
| | `/groups` | Pick a group you administer → mute / unmute, or per-topic mute inside forum communities |
| Any chat | `/rules` | Post the community rules |
| Group (any managed) | `/warns` (reply or `@user`) · `/stats` | Member case file · 30-day report |
| Community (admin) | `/block WORD` `/unblock WORD` `/reset USER` | Curate the filter · clear a member's violations |
| Owner | `/ping` | Liveness check |

---

## How it works

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

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q        # 137 passed
```

The suite is fully offline: no tokens, no network, no hidden state — every flow is exercised
against fakes, including moderation enforcement, the quote-free job queue, the provider
fallback chain, and the PDF page loop.

---

## Deploying

`deploy/install.sh` is idempotent on Oracle Linux / RHEL (`dnf`) and Debian/Ubuntu (`apt`):
system packages, Python 3.12 venv, Graphviz, Noto Naskh Arabic, Typst, optional static ffmpeg,
the `megatronics` system user, the systemd unit, and a 03:00 daily backup cron with 7-day
rotation.

```bash
sudo bash deploy/install.sh
sudo nano /opt/megatronics/.env
sudo systemctl enable --now megatronics-bot
```

The installer pins two conventions: `APP_DIR=/opt/megatronics` and a `megatronics` service
user. To change either, edit `deploy/install.sh`, `deploy/megatronics-bot.service`, and
`deploy/backup.sh` together.

Operational notes learned the hard way:

- The unit runs with `PrivateTmp=true` — files for the bot must live under its data dir, not
  `/tmp`.
- Keep heavy jobs serialised; the queue assumes a small (1-vCPU) box.
- Backups are SQLite-online-safe snapshots (DB + files + logs) — no downtime needed.

---

## Roadmap

- Quiz mode with timed tests and grading
- Per-group settings (welcome text, rules, log target, moderation toggle)
- Spaced repetition for `/flash` cards with Anki/CSV export
- Flood/anti-spam heuristics on top of the strike ladder
- Appeal flow for muted members

---

## Contributing & security

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For security issues,
follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

MIT — see [LICENSE](LICENSE). The default configuration runs on Groq and OpenRouter free tiers;
paid ids work only when you explicitly allowlist them in `PAID_MODELS`.
