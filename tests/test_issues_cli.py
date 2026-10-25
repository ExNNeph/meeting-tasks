import json
from datetime import date

import pytest

from meeting_tasks import cli, issues
from meeting_tasks.models import Task

TASKS = [Task(title="Send the quote", owner="Ben", due=date(2026, 10, 28), quote="I'll send it"),
         Task(title="Update pricing page", quote="I'll update the pricing page")]


@pytest.fixture
def gh(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps([{"title": "Update Pricing Page"}])  # already open, different case
        return f"https://github.com/o/r/issues/{len(calls)}\n"

    monkeypatch.setattr(issues, "_gh", fake)
    return calls


def test_preview_creates_nothing(gh):
    results = issues.sync(TASKS, "o/r", "notes.txt", create=False)
    assert [s for _, s in results] == ["would create", "skipped: open issue with this title exists"]
    assert not any(c[:2] == ("issue", "create") for c in gh)


def test_create_skips_existing_and_passes_body(gh):
    results = issues.sync(TASKS, "o/r", "notes.txt", create=True)
    created = [c for c in gh if c[:2] == ("issue", "create")]
    assert len(created) == 1 and "Send the quote" in created[0]
    body = created[0][created[0].index("--body") + 1]
    assert "**Owner:** Ben" in body and "**Due:** 2026-10-28" in body and "> I'll send it" in body
    assert results[0][1].startswith("created https://github.com/")


def test_cli_create_requires_repo(tmp_path):
    notes = tmp_path / "n.txt"
    notes.write_text("Anna: I'll send the deck.")
    with pytest.raises(SystemExit):
        cli.main([str(notes), "--create"])


def test_cli_prints_tasks_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    notes = tmp_path / "n.txt"
    notes.write_text("Anna: I'll send the deck by Friday.")
    cli.main([str(notes), "--date", "2026-10-26"])
    out = capsys.readouterr().out
    assert "1 task(s) found (rules)" in out and "owner: Anna, due: 2026-10-30" in out
