# ScrumAgent — an AI assistant for Scrum Masters

A four-screen Streamlit app with a clean dark UI — top nav bar, priority-pill
ticket table, side-by-side summary and email view:

1. **Meeting agent** — paste a meeting transcript → an AI agent extracts
   every action item, **creates a ticket for each one** (Jira, or mock mode),
   **verifies its own output against the transcript**, and **drafts the
   follow-up email**. When the transcript is ambiguous (unclear owner, vague
   deadline), the agent **asks inline right after the run** — answer the
   question(s) and **re-run**; your answers are treated as authoritative.
2. **Sprint status** — reads the current sprint from your Jira board (or a
   demo sprint in mock mode) and writes a **sprint health report**: progress,
   overdue/stale items, workload balance, and recommended actions.
3. **Reports** — download the meeting and sprint reports from your latest runs
   as Markdown.
4. **Settings** — connect your Claude API key, pick a model, and toggle
   **Mock mode ↔ Real Jira** (which reveals the Jira connection fields).

## Architecture

```
Transcript ─▶ validate ─▶ Claude tool-use loop ─▶ verification pass ─▶ UI
                             ├─ create_ticket() ─▶ Jira REST (retries, timeouts)
                             └─ draft_email()

Jira board ─▶ fetch_sprint_issues() ─▶ compute_sprint_stats() ─▶ Claude ─▶ report
              (JQL: openSprints)        (deterministic Python)
```

| File | Role |
|---|---|
| `config.py` | Env loading + validation. Fails fast with clear messages. |
| `agent.py` | Tool-use loop (create_ticket / draft_email / ask_user), API retries w/ backoff, verification pass, sprint report, clarifications re-run, token tracking. |
| `tools.py` | Per-run `RunContext` (no globals), validated tools, Jira client (create + sprint search), sprint stats. |
| `app.py` | Streamlit UI: Apple dark theme, top nav, four screens (meeting / sprint / reports / settings), inline Q&A, keys via Settings. |
| `tests/` | 45 tests, no network needed: `python -m pytest tests/ -q` |

## Production hardening — what's covered

**Input:** empty/too-short/too-long transcripts rejected before any API spend;
non-meeting text (articles, code) produces zero tickets by prompt rule, tested.

**API resilience:** rate limits, connection errors, and 5xx retried with
exponential backoff (bounded); auth and bad-request errors surface immediately
with friendly messages; client timeout set; SDK auto-retry disabled so retry
policy lives in one place.

**Agent safety rails:** iteration cap (no infinite loops), ticket cap per run
(no runaway creation), duplicate-title rejection (idempotent within a run),
tool errors fed back to the model with `is_error` so it adapts instead of dying,
`TypeError` guard for schema-violating arguments.

**Hallucination control:** grounding rules in the system prompt (unstated owner
→ `UNASSIGNED`), plus an independent **verification pass** — a second model call
audits every ticket against the transcript and flags unsupported ones in the UI
(`✅ verified` / `⚠ unverified` with the auditor's note).

**Jira:** timeouts on every call; 429/5xx retried, 401/403/404 fail immediately
with actionable messages; partial failures reported per-ticket, never silently
swallowed.

**Concurrency:** all run state lives in a per-run `RunContext` — two users (or
two Streamlit sessions) can never mix tickets. (Tested.)

**Observability:** structured logging throughout; token usage per run shown in
the UI; full event trail of every tool call and result.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY
python -m pytest tests/ -q    # should print: 45 passed
streamlit run app.py
```

## Real Jira mode

Set `MOCK_MODE=false` and `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`,
`JIRA_PROJECT_KEY` in `.env`. Token: https://id.atlassian.com/manage-profile/security/api-tokens

Sprint status additionally requires the project to have a Scrum board with an
active sprint (`sprint in openSprints()` is used to find it).

## Known limitations (what "production" would still need at scale)

- No auth/multi-tenancy — anyone with the URL can use your API key. Put it
  behind a login before hosting publicly.
- No persistence — results live for the session. Add a DB to keep run history.
- Cross-run dedupe — duplicates are blocked within a run, not against tickets
  already in Jira from previous runs (would need a Jira search before create).
- No audio ingestion — text transcripts only.
