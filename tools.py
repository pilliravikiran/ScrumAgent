"""Tools the agent can call, plus per-run state.

Production notes:
- No module-level mutable state: every run gets its own RunContext, so
  concurrent users (e.g. two Streamlit sessions) can never mix results.
- All external calls have timeouts and bounded retries.
- All tool inputs are validated *again* in Python — never trust that the
  model respected the schema.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests

from config import Settings

logger = logging.getLogger("m2a.tools")

VALID_PRIORITIES = {"High", "Medium", "Low"}
MAX_TITLE_LEN = 120
MAX_DESC_LEN = 5_000


class ToolError(Exception):
    """Recoverable tool failure — reported back to the model as is_error."""


@dataclass
class Ticket:
    key: str
    title: str
    description: str
    owner: str
    priority: str
    due: str | None
    url: str | None = None
    verified: bool | None = None      # set by the verification pass
    verify_note: str = ""


@dataclass
class RunContext:
    """All mutable state for a single agent run."""
    settings: Settings
    tickets: list[Ticket] = field(default_factory=list)
    email_draft: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    ticket_failures: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)   # agent → user

    def _normalized_titles(self) -> set[str]:
        return {re.sub(r"\W+", " ", t.title).strip().lower() for t in self.tickets}


# ------------------------------------------------------------------ Jira
class JiraClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session = requests.Session()
        self.session.auth = (settings.jira_email, settings.jira_api_token)
        self.session.headers["Content-Type"] = "application/json"

    def create_issue(self, title: str, description: str, owner: str,
                     due: str | None) -> dict:
        payload = {
            "fields": {
                "project": {"key": self.s.jira_project_key},
                "issuetype": {"name": "Task"},
                "summary": title[:255],
                "description": {
                    "type": "doc", "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text":
                            f"{description}\n\nOwner: {owner}\n"
                            f"Due: {due or 'not specified'}\n"
                            f"Created by Meeting-to-Action agent."}],
                    }],
                },
            }
        }
        url = f"{self.s.jira_base_url}/rest/api/3/issue"
        last_err: Exception | None = None
        for attempt in range(1, self.s.jira_max_retries + 1):
            try:
                resp = self.session.post(url, json=payload,
                                         timeout=self.s.jira_timeout_s)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ToolError(f"Jira HTTP {resp.status_code}")
                if resp.status_code == 401:
                    raise ToolError("Jira auth failed (401) — check email/token.")
                if resp.status_code == 403:
                    raise ToolError("Jira permission denied (403) — check project access.")
                if resp.status_code == 404:
                    raise ToolError(f"Jira project '{self.s.jira_project_key}' not found (404).")
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError, ToolError) as e:
                last_err = e
                # Auth/permission errors won't fix themselves — don't retry.
                if isinstance(e, ToolError) and any(
                        c in str(e) for c in ("401", "403", "404")):
                    raise
                if attempt < self.s.jira_max_retries:
                    sleep = 1.5 ** attempt
                    logger.warning("Jira attempt %d failed (%s); retrying in %.1fs",
                                   attempt, e, sleep)
                    time.sleep(sleep)
        raise ToolError(f"Jira unreachable after {self.s.jira_max_retries} "
                        f"attempts: {last_err}")

    def search_sprint_issues(self) -> tuple[list[dict], list[str]]:
        """Issues in the project's open sprint(s), normalized.

        Returns (issues, warnings). One page (up to max_sprint_issues);
        if Jira reports more, a warning says results are truncated.
        """
        url = f"{self.s.jira_base_url}/rest/api/3/search/jql"
        payload = {
            "jql": (f"project = {self.s.jira_project_key} "
                    f"AND sprint in openSprints() ORDER BY status"),
            "maxResults": self.s.max_sprint_issues,
            "fields": ["summary", "status", "assignee", "priority",
                       "duedate", "updated", "issuetype"],
        }
        last_err: Exception | None = None
        for attempt in range(1, self.s.jira_max_retries + 1):
            try:
                resp = self.session.post(url, json=payload,
                                         timeout=self.s.jira_timeout_s)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ToolError(f"Jira HTTP {resp.status_code}")
                if resp.status_code == 401:
                    raise ToolError("Jira auth failed (401) — check email/token.")
                if resp.status_code == 403:
                    raise ToolError("Jira permission denied (403) — check project access.")
                if resp.status_code == 400:
                    raise ToolError(
                        "Jira rejected the sprint query (400) — the project "
                        f"'{self.s.jira_project_key}' may not exist or may "
                        "not use sprints (company-managed boards need a "
                        "Scrum board).")
                resp.raise_for_status()
                data = resp.json()
                issues = [_normalize_issue(i) for i in data.get("issues", [])]
                warnings = []
                if data.get("nextPageToken"):
                    warnings.append(
                        f"Sprint has more than {self.s.max_sprint_issues} "
                        f"issues; report covers the first "
                        f"{self.s.max_sprint_issues}.")
                return issues, warnings
            except (requests.Timeout, requests.ConnectionError, ToolError) as e:
                last_err = e
                if isinstance(e, ToolError) and any(
                        c in str(e) for c in ("400", "401", "403")):
                    raise
                if attempt < self.s.jira_max_retries:
                    sleep = 1.5 ** attempt
                    logger.warning("Jira search attempt %d failed (%s); "
                                   "retrying in %.1fs", attempt, e, sleep)
                    time.sleep(sleep)
        raise ToolError(f"Jira unreachable after {self.s.jira_max_retries} "
                        f"attempts: {last_err}")


def _normalize_issue(raw: dict) -> dict:
    f = raw.get("fields", {}) or {}
    assignee = (f.get("assignee") or {}).get("displayName") or "Unassigned"
    status = (f.get("status") or {}).get("name") or "Unknown"
    category = ((f.get("status") or {}).get("statusCategory") or {}
                ).get("key") or "new"        # new | indeterminate | done
    return {
        "key": raw.get("key", "?"),
        "summary": f.get("summary") or "",
        "status": status,
        "category": category,
        "assignee": assignee,
        "priority": (f.get("priority") or {}).get("name") or "None",
        "due": (f.get("duedate") or None),
        "updated": (f.get("updated") or "")[:10] or None,
        "type": (f.get("issuetype") or {}).get("name") or "Task",
    }


# ------------------------------------------------------------------ tools
def _validate_str(value, name: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{name}' must be a non-empty string.")
    return value.strip()[:max_len]


def create_ticket(ctx: RunContext, title: str, description: str, owner: str,
                  priority: str, due=None) -> dict:
    # ---- validate everything, trust nothing
    title = _validate_str(title, "title", MAX_TITLE_LEN)
    description = _validate_str(description, "description", MAX_DESC_LEN)
    owner = _validate_str(owner, "owner", 100)
    if priority not in VALID_PRIORITIES:
        raise ToolError(f"priority must be one of {sorted(VALID_PRIORITIES)}, "
                        f"got '{priority}'.")
    if due is not None and (not isinstance(due, str) or not due.strip()):
        due = None

    # ---- guards
    if len(ctx.tickets) >= ctx.settings.max_tickets_per_run:
        raise ToolError(f"Ticket cap ({ctx.settings.max_tickets_per_run}) "
                        f"reached — no more tickets will be created.")
    normalized = re.sub(r"\W+", " ", title).strip().lower()
    if normalized in ctx._normalized_titles():
        raise ToolError(f"Duplicate ticket rejected: '{title}' already exists "
                        f"this run. Do not re-create it.")

    # ---- create
    if ctx.settings.mock_mode:
        ticket = Ticket(key=f"MOCK-{len(ctx.tickets) + 1}", title=title,
                        description=description, owner=owner,
                        priority=priority, due=due)
        ctx.tickets.append(ticket)
        logger.info("Mock ticket %s: %s", ticket.key, title)
        return {"status": "created (mock)", "key": ticket.key}

    try:
        data = JiraClient(ctx.settings).create_issue(title, description,
                                                     owner, due)
    except ToolError as e:
        ctx.ticket_failures.append(f"{title}: {e}")
        raise
    key = data["key"]
    url = f"{ctx.settings.jira_base_url}/browse/{key}"
    ctx.tickets.append(Ticket(key=key, title=title, description=description,
                              owner=owner, priority=priority, due=due, url=url))
    logger.info("Jira ticket %s: %s", key, title)
    return {"status": "created", "key": key, "url": url}


# ------------------------------------------------------------------ sprint
def _mock_sprint_issues(today: date) -> list[dict]:
    """Realistic demo sprint so the report works without Jira."""
    d = lambda n: (today + timedelta(days=n)).isoformat()
    mk = lambda key, summary, status, category, assignee, priority, due, upd: {
        "key": key, "summary": summary, "status": status,
        "category": category, "assignee": assignee, "priority": priority,
        "due": due, "updated": upd, "type": "Task"}
    return [
        mk("MOCK-101", "Move permissions request to post-onboarding",
           "In Progress", "indeterminate", "Daniel", "High", d(3), d(-1)),
        mk("MOCK-102", "Finalize pricing page copy", "In Progress",
           "indeterminate", "Sara", "Medium", d(-2), d(-4)),
        mk("MOCK-103", "Investigate flaky staging deploys", "Done", "done",
           "Daniel", "High", d(-1), d(-1)),
        mk("MOCK-104", "Beta metrics summary for investor update",
           "To Do", "new", "Daniel", "Medium", d(5), d(-6)),
        mk("MOCK-105", "Android tablet support decision", "To Do", "new",
           "Unassigned", "Low", None, d(-8)),
        mk("MOCK-106", "Update onboarding funnel dashboards", "Done", "done",
           "Sara", "Low", d(-3), d(-2)),
        mk("MOCK-107", "QA pass on onboarding v2", "To Do", "new",
           "Priya", "High", d(2), d(-5)),
        mk("MOCK-108", "Fix crash on empty workspace", "In Review",
           "indeterminate", "Priya", "High", d(-1), d(0)),
    ]


def fetch_sprint_issues(settings: Settings) -> tuple[list[dict], list[str]]:
    """Current-sprint issues: mock data in mock mode, else real Jira."""
    if settings.mock_mode:
        return _mock_sprint_issues(date.today()), []
    return JiraClient(settings).search_sprint_issues()


def compute_sprint_stats(issues: list[dict],
                         today: date | None = None) -> dict:
    """Deterministic sprint numbers — computed in Python, not by the model."""
    today = today or date.today()

    def parse(s):
        try:
            return date.fromisoformat(s) if s else None
        except ValueError:
            return None

    done = [i for i in issues if i["category"] == "done"]
    in_progress = [i for i in issues if i["category"] == "indeterminate"]
    todo = [i for i in issues if i["category"] not in ("done", "indeterminate")]
    overdue = [i for i in issues
               if i["category"] != "done"
               and (dd := parse(i["due"])) is not None and dd < today]
    stale = [i for i in in_progress
             if (u := parse(i["updated"])) is not None
             and (today - u).days > 3]

    by_assignee: dict[str, int] = {}
    for i in issues:
        if i["category"] != "done":
            by_assignee[i["assignee"]] = by_assignee.get(i["assignee"], 0) + 1

    total = len(issues)
    return {
        "total": total,
        "done": len(done),
        "in_progress": len(in_progress),
        "todo": len(todo),
        "completion_pct": round(100 * len(done) / total) if total else 0,
        "overdue": [i["key"] for i in overdue],
        "stale": [i["key"] for i in stale],
        "open_by_assignee": dict(sorted(by_assignee.items(),
                                        key=lambda kv: -kv[1])),
    }


MAX_QUESTIONS_PER_RUN = 5


def ask_user(ctx: RunContext, question: str, context: str = "",
             ticket_key=None) -> dict:
    """Record a clarifying question for the scrum master. Never blocks the
    run — the agent is told to proceed with its best supported value."""
    question = _validate_str(question, "question", 300)
    if not isinstance(context, str):
        context = ""
    if len(ctx.questions) >= MAX_QUESTIONS_PER_RUN:
        raise ToolError(f"Question cap ({MAX_QUESTIONS_PER_RUN}) reached — "
                        f"stop asking and proceed with best supported values.")
    ctx.questions.append({"question": question, "context": context.strip()[:500],
                          "ticket_key": ticket_key if isinstance(ticket_key, str)
                          else None})
    return {"status": "question recorded for the scrum master",
            "instruction": "Proceed now with the best value the transcript "
                           "supports (e.g. owner UNASSIGNED, due null). "
                           "Do not wait for an answer."}


def draft_email(ctx: RunContext, subject: str, body: str) -> dict:
    subject = _validate_str(subject, "subject", 200)
    body = _validate_str(body, "body", 20_000)
    if ctx.email_draft:
        ctx.warnings.append("Agent called draft_email more than once; "
                            "kept the latest draft.")
    ctx.email_draft = {"subject": subject, "body": body}
    return {"status": "draft saved"}
