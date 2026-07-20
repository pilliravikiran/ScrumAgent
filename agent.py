"""Meeting-to-Action agent: extraction loop + verification pass.

Production hardening:
- Transcript validated before any API spend.
- Every API call retried with exponential backoff on rate limits /
  connection errors / 5xx (bounded).
- Tool errors are returned to the model (is_error) so it can adapt;
  repeated identical failures don't loop forever thanks to caps.
- A second, independent verification pass checks every created ticket
  against the transcript and flags anything unsupported.
- Token usage tracked and reported.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date

import anthropic

from config import Settings
from tools import (RunContext, ToolError, ask_user, compute_sprint_stats,
                   create_ticket, draft_email, fetch_sprint_issues)

logger = logging.getLogger("m2a.agent")


class AgentError(Exception):
    """Unrecoverable agent failure with a user-friendly message."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, u):
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens


@dataclass
class AgentResult:
    summary: str
    ctx: RunContext
    events: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


SYSTEM_PROMPT = """You are a meeting operations agent. You receive a raw meeting
transcript or notes. Your job:

1. Identify every concrete ACTION ITEM: what must be done, who owns it (use the
   name mentioned; if no owner is stated, set owner to "UNASSIGNED"), and any
   deadline mentioned (ISO date if possible, else the phrase used, else null).
2. Identify DECISIONS made and OPEN QUESTIONS left unresolved.
3. Call create_ticket once for EACH action item. Clear imperative title
   (<= 70 chars); description with enough transcript context for the assignee.
4. After all tickets, call draft_email exactly once: short intro, Decisions,
   Action Items (owners + deadlines), Open Questions. Plain text.
5. Finally reply with a short plain-text summary (at most five sentences):
   ticket count, decisions, and open questions. Do not use Markdown tables,
   separators, or long blank-space blocks.

Rules:
- Never invent action items, owners, or deadlines not supported by the
  transcript. Open questions are NOT action items unless someone was asked
  to resolve them.
- When something important is AMBIGUOUS — an action item with no clear owner,
  a vague deadline ("soon", "next week" with no date), or an unclear scope —
  call ask_user with a specific question for the scrum master. Then proceed
  anyway with the best supported value (owner "UNASSIGNED", due null). Never
  wait for an answer. Ask at most 5 questions, only ones a scrum master would
  genuinely need to resolve.
- If the user message includes a "Clarifications from the scrum master"
  section, treat those answers as authoritative additions to the transcript
  and do NOT re-ask them.
- If a create_ticket call returns an error saying a duplicate was rejected,
  do NOT retry it — move on.
- If the text is not a meeting transcript at all (e.g. an article, code,
  random text), create no tickets and no email; reply explaining the input
  does not look like meeting notes.
- One ticket per action item. Do not bundle."""

TOOLS = [
    {
        "name": "create_ticket",
        "description": "Create a task ticket in the team's tracker. Call once per action item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Imperative, <= 70 chars"},
                "description": {"type": "string"},
                "owner": {"type": "string", "description": "Named person or 'UNASSIGNED'"},
                "due": {"type": ["string", "null"]},
                "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
            },
            "required": ["title", "description", "owner", "priority"],
        },
    },
    {
        "name": "draft_email",
        "description": "Save the follow-up email draft. Call exactly once, after all tickets.",
        "input_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string"},
                           "body": {"type": "string"}},
            "required": ["subject", "body"],
        },
    },
    {
        "name": "ask_user",
        "description": ("Record a clarifying question for the scrum master "
                        "when the transcript is ambiguous (unclear owner, "
                        "vague deadline, fuzzy scope). Non-blocking: after "
                        "calling, proceed with the best supported value."),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string",
                             "description": "Specific, answerable question"},
                "context": {"type": "string",
                            "description": "The transcript line(s) that are ambiguous"},
                "ticket_key": {"type": ["string", "null"],
                               "description": "Related ticket key, if any"},
            },
            "required": ["question"],
        },
    },
]

VERIFY_TOOL = [{
    "name": "report_verification",
    "description": "Report whether each ticket is supported by the transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "supported": {"type": "boolean"},
                        "note": {"type": "string",
                                 "description": "One sentence: why, citing the transcript"},
                    },
                    "required": ["key", "supported", "note"],
                },
            }
        },
        "required": ["results"],
    },
}]

RETRYABLE = (anthropic.RateLimitError, anthropic.APIConnectionError,
             anthropic.InternalServerError)


def _call_api(client, settings: Settings, usage: Usage, **kwargs):
    """Messages.create with bounded exponential backoff."""
    last: Exception | None = None
    for attempt in range(1, settings.api_max_retries + 1):
        try:
            resp = client.messages.create(**kwargs)
            usage.add(resp.usage)
            return resp
        except RETRYABLE as e:
            last = e
            if attempt < settings.api_max_retries:
                sleep = min(2 ** attempt, 20)
                logger.warning("API attempt %d failed (%s); retry in %ds",
                               attempt, type(e).__name__, sleep)
                time.sleep(sleep)
        except anthropic.AuthenticationError:
            raise AgentError("Invalid Anthropic API key.")
        except anthropic.BadRequestError as e:
            raise AgentError(f"API rejected the request: {e.message}")
    raise AgentError(f"Anthropic API unavailable after "
                     f"{settings.api_max_retries} attempts "
                     f"({type(last).__name__}). Try again in a minute.")


def validate_transcript(transcript: str, settings: Settings) -> str:
    if not isinstance(transcript, str):
        raise AgentError("Transcript must be text.")
    transcript = transcript.strip()
    if len(transcript) < settings.min_transcript_chars:
        raise AgentError("Transcript is too short to contain a meeting — "
                         "paste the full notes.")
    if len(transcript) > settings.max_transcript_chars:
        raise AgentError(
            f"Transcript is {len(transcript):,} characters; the limit is "
            f"{settings.max_transcript_chars:,}. Split it into parts and "
            f"run each part.")
    return transcript


def _today_line(today: date) -> str:
    """Grounds the model so 'Friday'/'next Wednesday' resolve to real dates."""
    return (f"Today's date is {today.isoformat()} ({today:%A}). Resolve every "
            f"relative deadline ('Friday', 'Wednesday the 22nd', 'next week') "
            f"to an absolute ISO date (YYYY-MM-DD) in the correct year, "
            f"relative to today. Never guess a past year.")


def run_agent(transcript: str, settings: Settings,
              event_log=None, client=None,
              clarifications: list | None = None,
              today: date | None = None) -> AgentResult:
    """Full pipeline: validate -> extract/act -> verify.

    `clarifications`: answered agent questions from a previous run, each
    {"question": ..., "answer": ...} — appended to the transcript as
    authoritative context so the agent doesn't re-ask.
    `today`: injectable current date for grounding relative deadlines.
    """
    today = today or date.today()
    transcript = validate_transcript(transcript, settings)
    if clarifications:
        qa = "\n".join(f"- Q: {c['question']}\n  A: {c['answer']}"
                       for c in clarifications
                       if c.get("answer", "").strip())
        if qa:
            transcript += ("\n\nClarifications from the scrum master "
                           "(authoritative):\n" + qa)
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                           timeout=settings.api_timeout_s,
                                           max_retries=0)  # we retry ourselves
    ctx = RunContext(settings=settings)
    usage = Usage()
    events: list = []

    def log(event):
        events.append(event)
        if event_log:
            try:
                event_log(event)
            except Exception:      # UI must never kill the run
                logger.exception("event_log callback failed")

    tool_fns = {"create_ticket": lambda **kw: create_ticket(ctx, **kw),
                "draft_email": lambda **kw: draft_email(ctx, **kw),
                "ask_user": lambda **kw: ask_user(ctx, **kw)}

    # ---------------- phase 1: extraction + actions ----------------
    messages = [{"role": "user",
                 "content": f"{_today_line(today)}\n\nMeeting transcript:"
                            f"\n\n{transcript}"}]
    summary = ""
    for _ in range(settings.max_agent_iterations):
        resp = _call_api(client, settings, usage, model=settings.model,
                         max_tokens=4000, system=SYSTEM_PROMPT,
                         tools=TOOLS, messages=messages)

        for block in resp.content:
            if block.type == "text" and block.text.strip():
                log({"type": "text", "text": block.text})

        if resp.stop_reason != "tool_use":
            summary = "".join(b.text for b in resp.content
                              if b.type == "text").strip()
            break

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            log({"type": "tool_call", "name": block.name, "input": block.input})
            try:
                out = tool_fns[block.name](**block.input)
                log({"type": "tool_result", "name": block.name, "result": out})
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(out)})
            except ToolError as e:
                log({"type": "tool_error", "name": block.name, "error": str(e)})
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(e), "is_error": True})
            except TypeError as e:   # model sent junk args despite schema
                msg = f"Invalid arguments: {e}"
                log({"type": "tool_error", "name": block.name, "error": msg})
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": msg, "is_error": True})
        messages.append({"role": "user", "content": results})
    else:
        ctx.warnings.append("Agent hit the iteration cap; results may be "
                            "incomplete.")
        summary = summary or "Stopped at iteration cap."

    # ---------------- phase 2: verification pass ----------------
    if ctx.tickets:
        log({"type": "text", "text": "Verifying tickets against transcript…"})
        tickets_json = json.dumps([
            {"key": t.key, "title": t.title, "owner": t.owner, "due": t.due}
            for t in ctx.tickets])
        vresp = _call_api(
            client, settings, usage, model=settings.model, max_tokens=2000,
            system=("You are an auditor. For each ticket, check the transcript: "
                    "is this action item, its owner, and its deadline actually "
                    "supported by what was said? Unstated owner must be "
                    "'UNASSIGNED' to count as supported. Report via the tool."),
            tools=VERIFY_TOOL,
            tool_choice={"type": "tool", "name": "report_verification"},
            messages=[{"role": "user", "content":
                       f"{_today_line(today)}\n\nTranscript:\n{transcript}"
                       f"\n\nTickets:\n{tickets_json}"}])
        try:
            vdata = next(b.input for b in vresp.content
                         if b.type == "tool_use")
            by_key = {t.key: t for t in ctx.tickets}
            for r in vdata.get("results", []):
                t = by_key.get(r.get("key"))
                if t is not None:
                    t.verified = bool(r.get("supported"))
                    t.verify_note = str(r.get("note", ""))[:500]
            flagged = [t for t in ctx.tickets if t.verified is False]
            for t in flagged:
                ctx.warnings.append(
                    f"⚠ {t.key} '{t.title}' may not be supported by the "
                    f"transcript: {t.verify_note}")
            log({"type": "text",
                 "text": (f"Verification: {len(ctx.tickets) - len(flagged)}/"
                          f"{len(ctx.tickets)} tickets confirmed."
                          + (f" {len(flagged)} flagged." if flagged else ""))})
        except (StopIteration, KeyError, TypeError):
            ctx.warnings.append("Verification pass returned malformed data; "
                                "tickets are unverified.")

    return AgentResult(summary=summary, ctx=ctx, events=events, usage=usage)


# ---------------------------------------------------------------- sprint
@dataclass
class SprintReport:
    report_md: str
    stats: dict
    issues: list
    warnings: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


SPRINT_SYSTEM_PROMPT = """You are a scrum master's assistant writing a sprint
health report for the team. You receive the current sprint's issues and
pre-computed statistics.

Write a concise markdown report with exactly these sections:

## Sprint health
One-paragraph verdict: on track / at risk / off track, and why.

## Blockers & risks
Overdue and stale items by key, who owns them, and what's at stake. If none,
say so in one line.

## Workload
Whether open work is balanced across people; call out anyone overloaded or
idle, and unassigned items.

## Recommended actions
3-5 concrete, specific next steps a scrum master should take (who to talk to,
what to re-scope, what to unblock). Reference issue keys.

Rules:
- Use ONLY the data provided. Never invent issues, people, or dates.
- Use the pre-computed stats for all numbers; do not recount.
- Refer to issues by key (e.g. PROJ-12).
- Plain, direct language. No filler."""


def run_sprint_report(settings: Settings, client=None,
                      issues=None, warnings=None, event_log=None) -> SprintReport:
    """Fetch current sprint from Jira (or mock) and write a health report.

    `issues`/`warnings` can be injected for testing; normally both come
    from fetch_sprint_issues().
    """
    def log(text: str) -> None:
        if event_log:
            try:
                event_log({"type": "text", "text": text})
            except Exception:
                logger.exception("event_log callback failed")

    log("Reading the current sprint…")
    if issues is None:
        try:
            issues, warnings = fetch_sprint_issues(settings)
        except ToolError as e:
            raise AgentError(f"Could not read the sprint from Jira: {e}")
    warnings = list(warnings or [])

    if not issues:
        return SprintReport(
            report_md="", stats=compute_sprint_stats([]), issues=[],
            warnings=warnings + ["No issues found in the current sprint — "
                                 "is there an active sprint on the board?"])

    stats = compute_sprint_stats(issues)
    log("Analyzing sprint progress and risks…")
    client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                           timeout=settings.api_timeout_s,
                                           max_retries=0)
    usage = Usage()
    resp = _call_api(
        client, settings, usage, model=settings.model, max_tokens=2000,
        system=SPRINT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   f"Statistics:\n{json.dumps(stats, indent=2)}\n\n"
                   f"Issues:\n{json.dumps(issues, indent=2)}"}])
    report = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not report:
        warnings.append("Model returned an empty report; showing raw "
                        "statistics only.")
    log("Sprint report complete.")
    return SprintReport(report_md=report, stats=stats, issues=issues,
                        warnings=warnings, usage=usage)
