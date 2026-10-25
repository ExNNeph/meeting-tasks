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


def test_create_adds_label_once_and_assigns_mapped_owner(gh):
    tasks = [TASKS[0], Task(title="Book the room", owner="Chris", quote="I'll book it"),
             Task(title="Send the quote", owner="Ben", quote="duplicate in the same meeting")]
    results = issues.sync(tasks, "o/r", "notes.txt", create=True, team={"ben": "ben-dev"})
    assert sum(c[:2] == ("label", "create") for c in gh) == 1
    created = [c for c in gh if c[:2] == ("issue", "create")]
    assert len(created) == 2  # the duplicate title is skipped
    assert all(("--label", "meeting-task") == c[c.index("--label"):c.index("--label") + 2] for c in created)
    assert "--assignee" in created[0] and created[0][-1] == "ben-dev"
    assert "--assignee" not in created[1]  # Chris is not in the team file: stays unassigned
    assert results[0][1].endswith("(assign @ben-dev)") and results[2][1].startswith("skipped")


def test_one_failing_issue_does_not_stop_the_rest(monkeypatch):
    def fake(*args):
        if args[:2] == ("issue", "list"):
            return "[]"
        if "Send the quote" in args:
            raise issues.subprocess.CalledProcessError(1, "gh", stderr="could not assign user: nobody")
        return "https://github.com/o/r/issues/9\n"

    monkeypatch.setattr(issues, "_gh", fake)
    results = issues.sync(TASKS, "o/r", "notes.txt", create=True)
    assert [s.split(":")[0] for _, s in results] == ["failed", "created https"]


def test_parse_team():
    text = "# team\nBen = ben-dev\nAnna: @anna42   # trailing comment\n\n"
    assert issues.parse_team(text) == {"ben": "ben-dev", "anna": "anna42"}
    for bad in ["Ben ben-dev", "Ben = not a user", "Ben = -dash-start"]:
        with pytest.raises(ValueError, match="line 1"):
            issues.parse_team(bad)


def test_body_of_task_added_by_hand():
    body = issues.issue_body(Task(title="Order pizza for the workshop"), "notes.txt")
    assert "**Owner:** unassigned" in body and "Added by hand" in body and ">" not in body


def test_cli_rejects_bad_team_file(tmp_path):
    notes, team = tmp_path / "n.txt", tmp_path / "team.txt"
    notes.write_text("Anna: I'll send the deck.")
    team.write_text("Anna anna42")
    with pytest.raises(SystemExit):
        cli.main([str(notes), "--team", str(team)])


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
