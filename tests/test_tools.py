import pytest

from config import Settings
from tools import (RunContext, ToolError, ask_user, create_ticket,
                   draft_email)


def ctx(**overrides):
    s = Settings(anthropic_api_key="test", mock_mode=True, **overrides)
    return RunContext(settings=s)


def valid(**overrides):
    kw = dict(title="Fix staging deploys", description="Deploys failing.",
              owner="Daniel", priority="High", due="2026-07-17")
    kw.update(overrides)
    return kw


class TestCreateTicket:
    def test_creates_mock_ticket(self):
        c = ctx()
        out = create_ticket(c, **valid())
        assert out["key"] == "MOCK-1"
        assert c.tickets[0].owner == "Daniel"

    def test_sequential_keys(self):
        c = ctx()
        create_ticket(c, **valid())
        create_ticket(c, **valid(title="Update pricing copy"))
        assert [t.key for t in c.tickets] == ["MOCK-1", "MOCK-2"]

    @pytest.mark.parametrize("field,value", [
        ("title", ""), ("title", "   "), ("title", None), ("title", 42),
        ("description", ""), ("owner", ""),
    ])
    def test_rejects_bad_strings(self, field, value):
        with pytest.raises(ToolError):
            create_ticket(ctx(), **valid(**{field: value}))

    def test_rejects_bad_priority(self):
        with pytest.raises(ToolError, match="priority"):
            create_ticket(ctx(), **valid(priority="URGENT!!"))

    def test_null_and_blank_due_allowed(self):
        c = ctx()
        create_ticket(c, **valid(due=None))
        create_ticket(c, **valid(title="Other", due="  "))
        assert c.tickets[0].due is None
        assert c.tickets[1].due is None

    def test_duplicate_title_rejected(self):
        c = ctx()
        create_ticket(c, **valid())
        with pytest.raises(ToolError, match="Duplicate"):
            create_ticket(c, **valid(title="fix STAGING deploys!"))
        assert len(c.tickets) == 1

    def test_ticket_cap(self):
        c = ctx(max_tickets_per_run=2)
        create_ticket(c, **valid(title="A"))
        create_ticket(c, **valid(title="B"))
        with pytest.raises(ToolError, match="cap"):
            create_ticket(c, **valid(title="C"))

    def test_title_truncated(self):
        c = ctx()
        create_ticket(c, **valid(title="x" * 500))
        assert len(c.tickets[0].title) <= 120

    def test_contexts_are_isolated(self):
        c1, c2 = ctx(), ctx()
        create_ticket(c1, **valid())
        assert c2.tickets == []          # the v1 global-state bug, fixed


class TestAskUser:
    def test_records_question(self):
        c = ctx()
        out = ask_user(c, question="Who owns the pricing task?",
                       context="Sara: someone should own pricing",
                       ticket_key="MOCK-2")
        assert "recorded" in out["status"]
        assert "Proceed now" in out["instruction"]   # non-blocking by design
        assert c.questions[0]["question"] == "Who owns the pricing task?"
        assert c.questions[0]["ticket_key"] == "MOCK-2"

    def test_rejects_empty_question(self):
        with pytest.raises(ToolError):
            ask_user(ctx(), question="   ")

    def test_question_cap(self):
        c = ctx()
        for i in range(5):
            ask_user(c, question=f"Question {i}?")
        with pytest.raises(ToolError, match="cap"):
            ask_user(c, question="One too many?")
        assert len(c.questions) == 5

    def test_bad_optional_args_tolerated(self):
        c = ctx()
        ask_user(c, question="Valid?", context=None, ticket_key=42)
        assert c.questions[0]["context"] == ""
        assert c.questions[0]["ticket_key"] is None


class TestDraftEmail:
    def test_saves_draft(self):
        c = ctx()
        draft_email(c, subject="Recap", body="Hello")
        assert c.email_draft["subject"] == "Recap"

    def test_second_call_warns_and_overwrites(self):
        c = ctx()
        draft_email(c, subject="v1", body="a")
        draft_email(c, subject="v2", body="b")
        assert c.email_draft["subject"] == "v2"
        assert any("more than once" in w for w in c.warnings)

    def test_rejects_empty(self):
        with pytest.raises(ToolError):
            draft_email(ctx(), subject="", body="x")
