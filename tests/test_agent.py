"""Agent loop tests using a scripted fake client — no network, no cost."""

from types import SimpleNamespace

import anthropic
import httpx
import pytest


def api_error(cls, status):
    """Construct a real SDK exception (needs a real httpx.Response)."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status_code=status, request=req)
    return cls(message="err", response=resp, body=None)

from agent import AgentError, run_agent, validate_transcript
from config import Settings


def settings(**kw):
    return Settings(anthropic_api_key="test", mock_mode=True,
                    api_max_retries=2, **kw)


# ------------------------------------------------------------ fakes
def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_block(name, input, id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id)


def response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=100,
                                                 output_tokens=50))


class FakeClient:
    """Returns scripted responses in order; records requests."""
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


TRANSCRIPT = ("Priya: Daniel, please fix the staging deploys by Friday. "
              "Daniel: On it. Priya: Decided — we ship v2 next sprint.")

TICKET_INPUT = {"title": "Fix staging deploys", "description": "From meeting",
                "owner": "Daniel", "priority": "High", "due": "Friday"}


def verification(supported=True, key="MOCK-1"):
    return response([tool_block("report_verification",
                                {"results": [{"key": key,
                                              "supported": supported,
                                              "note": "checked"}]})],
                    "tool_use")


# ------------------------------------------------------------ tests
class TestValidation:
    def test_too_short(self):
        with pytest.raises(AgentError, match="too short"):
            validate_transcript("hi", settings())

    def test_too_long(self):
        with pytest.raises(AgentError, match="limit"):
            validate_transcript("x" * 100_000, settings())

    def test_strips(self):
        assert validate_transcript("  " + TRANSCRIPT + "  ",
                                   settings()) == TRANSCRIPT


class TestAgentLoop:
    def test_happy_path(self):
        fake = FakeClient([
            response([tool_block("create_ticket", TICKET_INPUT)], "tool_use"),
            response([tool_block("draft_email",
                                 {"subject": "Recap", "body": "Hi all"},
                                 id="tu_2")], "tool_use"),
            response([text_block("Created 1 ticket.")], "end_turn"),
            verification(supported=True),
        ])
        result = run_agent(TRANSCRIPT, settings(), client=fake)
        assert len(result.ctx.tickets) == 1
        assert result.ctx.tickets[0].verified is True
        assert result.ctx.email_draft["subject"] == "Recap"
        assert "Created 1 ticket." in result.summary
        assert result.usage.input_tokens == 400   # 4 calls x 100

    def test_tool_error_fed_back_to_model(self):
        bad = dict(TICKET_INPUT, priority="MEGA")
        fake = FakeClient([
            response([tool_block("create_ticket", bad)], "tool_use"),
            response([text_block("Could not create the ticket.")], "end_turn"),
        ])
        result = run_agent(TRANSCRIPT, settings(), client=fake)
        # error went back as is_error tool_result
        tool_results = fake.requests[1]["messages"][-1]["content"]
        assert tool_results[0]["is_error"] is True
        assert "priority" in tool_results[0]["content"]
        assert result.ctx.tickets == []

    def test_verification_flags_unsupported(self):
        fake = FakeClient([
            response([tool_block("create_ticket", TICKET_INPUT)], "tool_use"),
            response([text_block("Done.")], "end_turn"),
            verification(supported=False),
        ])
        result = run_agent(TRANSCRIPT, settings(), client=fake)
        assert result.ctx.tickets[0].verified is False
        assert any("may not be supported" in w for w in result.ctx.warnings)

    def test_iteration_cap(self):
        s = settings(max_agent_iterations=2)
        fake = FakeClient([
            response([tool_block("create_ticket", TICKET_INPUT)], "tool_use"),
            response([tool_block("create_ticket",
                                 dict(TICKET_INPUT, title="Another"),
                                 id="tu_2")], "tool_use"),
            verification(),
        ])
        result = run_agent(TRANSCRIPT, s, client=fake)
        assert any("iteration cap" in w for w in result.ctx.warnings)

    def test_no_tickets_skips_verification(self):
        fake = FakeClient([
            response([text_block("Not a meeting transcript.")], "end_turn"),
        ])
        result = run_agent("This is just a long random article about birds "
                           "and their many wonderful migration patterns.",
                           settings(), client=fake)
        assert result.ctx.tickets == []
        assert len(fake.requests) == 1        # no verification call


class TestAskUserFlow:
    def test_question_recorded_and_run_continues(self):
        fake = FakeClient([
            response([tool_block("ask_user",
                                 {"question": "Who owns the pricing page?",
                                  "context": "copy is still placeholder"}),
                      tool_block("create_ticket", TICKET_INPUT, id="tu_2")],
                     "tool_use"),
            response([text_block("Done.")], "end_turn"),
            verification(),
        ])
        result = run_agent(TRANSCRIPT, settings(), client=fake)
        assert len(result.ctx.questions) == 1
        assert len(result.ctx.tickets) == 1     # question didn't block work

    def test_today_date_grounded_in_prompt(self):
        from datetime import date
        fake = FakeClient([response([text_block("ok")], "end_turn")])
        run_agent(TRANSCRIPT, settings(), client=fake, today=date(2026, 7, 17))
        sent = fake.requests[0]["messages"][0]["content"]
        assert "2026-07-17" in sent and "Friday" in sent  # correct weekday
        assert "correct year" in sent

    def test_clarifications_appended_to_transcript(self):
        fake = FakeClient([response([text_block("ok")], "end_turn")])
        run_agent(TRANSCRIPT, settings(), client=fake,
                  clarifications=[{"question": "Who owns X?",
                                   "answer": "Sara"},
                                  {"question": "ignored", "answer": "  "}])
        sent = fake.requests[0]["messages"][0]["content"]
        assert "Clarifications from the scrum master" in sent
        assert "A: Sara" in sent
        assert "ignored" not in sent            # blank answers dropped


class TestRetries:
    def test_retries_rate_limit_then_succeeds(self):
        err = api_error(anthropic.RateLimitError, 429)
        fake = FakeClient([
            err,
            response([text_block("ok")], "end_turn"),
        ])
        result = run_agent(TRANSCRIPT, settings(), client=fake)
        assert "ok" in result.summary

    def test_gives_up_after_max_retries(self):
        err = api_error(anthropic.RateLimitError, 429)
        fake = FakeClient([err, err, err])
        with pytest.raises(AgentError, match="unavailable"):
            run_agent(TRANSCRIPT, settings(), client=fake)

    def test_auth_error_is_immediate_and_friendly(self):
        err = api_error(anthropic.AuthenticationError, 401)
        fake = FakeClient([err])
        with pytest.raises(AgentError, match="API key"):
            run_agent(TRANSCRIPT, settings(), client=fake)
