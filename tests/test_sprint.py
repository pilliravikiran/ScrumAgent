"""Sprint report tests — no network, no cost."""

from datetime import date
from types import SimpleNamespace

import pytest

from agent import AgentError, run_sprint_report
from config import Settings
from tools import ToolError, compute_sprint_stats, fetch_sprint_issues

TODAY = date(2026, 7, 17)


def settings(**kw):
    return Settings(anthropic_api_key="test", mock_mode=True,
                    api_max_retries=2, **kw)


def issue(**overrides):
    base = {"key": "P-1", "summary": "Do a thing", "status": "To Do",
            "category": "new", "assignee": "Daniel", "priority": "High",
            "due": None, "updated": "2026-07-16", "type": "Task"}
    base.update(overrides)
    return base


class TestComputeSprintStats:
    def test_empty(self):
        s = compute_sprint_stats([], today=TODAY)
        assert s["total"] == 0 and s["completion_pct"] == 0

    def test_counts_and_completion(self):
        s = compute_sprint_stats([
            issue(key="P-1", category="done"),
            issue(key="P-2", category="indeterminate"),
            issue(key="P-3", category="new"),
            issue(key="P-4", category="done"),
        ], today=TODAY)
        assert (s["done"], s["in_progress"], s["todo"]) == (2, 1, 1)
        assert s["completion_pct"] == 50

    def test_overdue_excludes_done(self):
        s = compute_sprint_stats([
            issue(key="P-1", due="2026-07-10"),
            issue(key="P-2", due="2026-07-10", category="done"),
            issue(key="P-3", due="2026-07-20"),
        ], today=TODAY)
        assert s["overdue"] == ["P-1"]

    def test_stale_only_in_progress(self):
        s = compute_sprint_stats([
            issue(key="P-1", category="indeterminate", updated="2026-07-10"),
            issue(key="P-2", category="new", updated="2026-07-10"),
            issue(key="P-3", category="indeterminate", updated="2026-07-16"),
        ], today=TODAY)
        assert s["stale"] == ["P-1"]

    def test_open_by_assignee_excludes_done_and_sorts(self):
        s = compute_sprint_stats([
            issue(key="P-1", assignee="Sara"),
            issue(key="P-2", assignee="Daniel"),
            issue(key="P-3", assignee="Daniel"),
            issue(key="P-4", assignee="Daniel", category="done"),
        ], today=TODAY)
        assert s["open_by_assignee"] == {"Daniel": 2, "Sara": 1}

    def test_bad_dates_ignored(self):
        s = compute_sprint_stats([issue(due="soon", updated="whenever",
                                        category="indeterminate")],
                                 today=TODAY)
        assert s["overdue"] == [] and s["stale"] == []


class TestFetchSprintIssues:
    def test_mock_mode_returns_demo_sprint(self):
        issues, warnings = fetch_sprint_issues(settings())
        assert len(issues) >= 5 and warnings == []
        assert all({"key", "summary", "category", "assignee"} <= set(i)
                   for i in issues)


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text_response(t):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=t)], stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50))


class TestRunSprintReport:
    def test_happy_path(self):
        fake = FakeClient([text_response("## Sprint health\nOn track.")])
        r = run_sprint_report(settings(), client=fake)
        assert "On track" in r.report_md
        assert r.stats["total"] == len(r.issues) > 0
        assert r.usage.input_tokens == 100
        # stats + issues actually sent to the model
        assert "Statistics" in fake.requests[0]["messages"][0]["content"]

    def test_no_issues_skips_model_call(self):
        fake = FakeClient([])
        r = run_sprint_report(settings(), client=fake, issues=[])
        assert r.report_md == "" and fake.requests == []
        assert any("No issues" in w for w in r.warnings)

    def test_jira_failure_becomes_agent_error(self, monkeypatch):
        import agent as agent_mod

        def boom(_):
            raise ToolError("Jira unreachable")
        monkeypatch.setattr(agent_mod, "fetch_sprint_issues", boom)
        with pytest.raises(AgentError, match="Jira"):
            run_sprint_report(settings(), client=FakeClient([]))

    def test_empty_model_reply_warns(self):
        fake = FakeClient([text_response("")])
        r = run_sprint_report(settings(), client=fake)
        assert any("empty report" in w for w in r.warnings)
