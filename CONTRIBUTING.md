# Contributing

Thanks for helping improve Megatronics Bot. Contributions of all sizes are welcome — bug
reports, documentation fixes, and pull requests.

## Development setup

Python **3.12+** is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

To run the bot itself, copy `.env.example` to `.env`, fill in the required keys, and start it
with `python -m app.main`. The `.env` file is loaded automatically at startup and is
gitignored.

## Ground rules

- **Tests stay offline.** No network calls, no real tokens — Telegram and model providers are
  exercised through fakes. Add tests for new behavior next to the existing ones in `tests/`.
- **Never commit secrets.** Configuration lives in `.env` (gitignored); `.env.example`
  documents every key.
- **No AI credit.** Commits, code, and documentation carry no AI attribution — no co-author
  trailers, and no mentions of AI tools or agents in commit messages or repository metadata.
- Keep pull requests focused — one change per PR, with tests updated alongside the behavior.
- Match the existing code style (`from __future__ import annotations`, typed dataclasses,
  one router per flow).

## Architecture

The module map and the request paths (moderation, study, sources) are documented in
[README.md](README.md#how-it-works).

## Security

Do not open public issues for vulnerabilities — see [SECURITY.md](SECURITY.md).
