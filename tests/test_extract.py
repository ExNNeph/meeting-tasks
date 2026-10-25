from datetime import date

import pytest

from meeting_tasks import extract as ex
from meeting_tasks.models import Task

MONDAY = date(2026, 10, 26)
NOTES = "Anna: Ben, can you send the quote to Acme by Wednesday?\nBen: Sure, I'll send it by Wednesday."


@pytest.mark.parametrize("text,expected", [
    ("by Wednesday", date(2026, 10, 28)),
    ("by Monday", date(2026, 11, 2)),  # same weekday as the meeting means next week
    ("tomorrow", date(2026, 10, 27)),
    ("today", MONDAY),
    ("by the end of the week", date(2026, 10, 30)),
    ("next week", date(2026, 11, 2)),
    ("on 2026-12-01", date(2026, 12, 1)),
    ("at some point", None),
])
def test_parse_due(text, expected):
    assert ex.parse_due(text, MONDAY) == expected


def test_guardrail_accepts_quote_with_different_punctuation_and_case():
    task = Task(title="Send quote", owner="Ben", quote="sure i'll send it by wednesday")
    assert ex.grounded(task, NOTES) is None


def test_guardrail_rejects_task_without_quote():
    assert ex.grounded(Task(title="Send quote", owner="Ben"), NOTES) == "no supporting quote"


def test_guardrail_rejects_invented_quote_and_unknown_owner():
    assert "quote" in ex.grounded(Task(title="Call Acme", owner="Ben", quote="I'll call Acme"), NOTES)
    assert "owner" in ex.grounded(Task(title="Send quote", owner="Zoe", quote="I'll send it by Wednesday"), NOTES)


def fake_llm(monkeypatch, items):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ex, "_llm_extract", lambda *a: items)


def test_llm_tasks_pass_through_guardrail(monkeypatch):
    fake_llm(monkeypatch, [
        {"title": "Send the quote to Acme", "owner": "Ben", "due": "2026-10-28", "quote": "I'll send it by Wednesday."},
        {"title": "Call Acme", "owner": "Ben", "due": "", "quote": "I will call Acme tomorrow."},  # invented
        {"title": "Send deck", "owner": "Ben", "due": "next Friday", "quote": "I'll send it by Wednesday."},  # bad date
    ])
    result = ex.extract(NOTES, MONDAY)
    assert result.source == "llm"
    assert [(t.title, t.due) for t in result.tasks] == [("Send the quote to Acme", date(2026, 10, 28))]
    assert [why for _, why in result.dropped] == ["quote not found in the transcript",
                                                   "invalid fields (e.g. a malformed date)"]


def test_api_error_falls_back_to_rules_with_reason(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def boom(*a):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ex, "_llm_extract", boom)
    result = ex.extract(NOTES, MONDAY)
    assert (result.source, result.error) == ("rules (API error)", "RuntimeError: rate limited")
    assert result.tasks  # the rule baseline still found something


def test_without_key_uses_rules(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = ex.extract(NOTES, MONDAY)
    assert result.source == "rules"
    assert ("Ben", date(2026, 10, 28)) in {(t.owner, t.due) for t in result.tasks}
