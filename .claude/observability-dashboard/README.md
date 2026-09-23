# Observability Dashboard

Local HTTP dashboard for `governance-log.jsonl`. Single-file Python server, no dependencies beyond stdlib.

## Start

```bash
python .claude/observability-dashboard/server.py
# open http://127.0.0.1:7654/
```

Custom port or log path:

```bash
python .claude/observability-dashboard/server.py --port 8080 \
  --log-path /path/to/governance-log.jsonl
```

## Features

- **Event table** — all 17 governance event types, colour-coded by severity.
- **Stats strip** — total / today / failures / warnings / distinct sessions.
- **Filters** — session prefix, hook name, environment, date range, event-type checkboxes.
- **Noisy types hidden by default** — `classification_emitted`, `session_start`, `session_end`, `pass`, `agent_dispatched` are unchecked on first load.
- **Row detail modal** — click any row for full JSON.
- **Haiku analyze** — click a row, then "Analyze with Haiku" to run `_haiku_summarize.py` for that session. Requires `claude` CLI on PATH with valid OAuth.
- **Merge refresh** — "Refresh" merges new events without resetting filter state.

## Severity mapping

| Colour | Event types |
|--------|------------|
| Red    | `block`, `deny`, `qa_fail_reported`, `classifier_field_missing` |
| Yellow | `warn`, `warning`, `dark-zone` |
| Green  | `pass`, `allow_process_skill_exemption`, `h11_sidecar_fallback_activated` |
| Blue   | `session_start/end`, `agent_dispatched`, `classification_emitted`, `dashboard_alert` |
| Purple | `token_breakdown`, `error_summary` |

## Files

| File | Role |
|------|------|
| `server.py` | HTTP server — static files + `/api/events` + `/api/analyze` |
| `index.html` | Shell markup |
| `app.js` | All rendering, filtering, pagination, fetch logic |
| `styles.css` | Dark-theme styles |

## Security notes

- Static serving uses an explicit whitelist (`/`, `/index.html`, `/app.js`, `/styles.css`) — no directory traversal.
- `/api/analyze` parameters are validated by strict regex before subprocess invocation.
- `Content-Security-Policy: default-src 'self'` on HTML responses.
- All event field values rendered via `textContent` — not `innerHTML`.

## Data source

`../.claude/hooks/governance-log.jsonl` (relative to this directory). Override with `--log-path`.
