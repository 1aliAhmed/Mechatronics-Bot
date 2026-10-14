# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **Report a vulnerability** button
(repository → **Security** → **Advisories**) instead of opening a public issue.

Never include live bot tokens, API keys, or other secrets in a report.

## Supported versions

Only the latest `main` is supported.

## Handling secrets

Configuration is read from `.env`, which is gitignored. Rotate any token you believe has been
exposed in code, logs, or git history.
