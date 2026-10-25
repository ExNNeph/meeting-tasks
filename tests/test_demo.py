import builtins

import pytest
from streamlit.testing.v1 import AppTest

from meeting_tasks import cli


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return AppTest.from_file(str(cli.DEMO_APP), default_timeout=20)  # the file `meeting-tasks demo` starts


def test_demo_waits_for_click(app):
    at = app.run()
    assert not at.exception
    assert any("Click **Extract tasks**" in i.value for i in at.info)
    assert not at.dataframe


def test_demo_extracts_with_rules_and_previews_issues(app):
    at = app.run()
    at.button[0].click().run()
    assert not at.exception
    table = at.dataframe[0].value  # the editable review table
    assert "send the revised quote to Acme" in list(table["task"])
    tasks = at.session_state["tasks"]  # what would be sent to GitHub
    assert [t.title for t in tasks] == list(table["task"])
    assert len(at.expander) == len(tasks)  # one issue preview per task (rules drop nothing)
    # regression: tasks with and without a deadline in one column made Arrow log a traceback
    assert {t.due is None for t in tasks} == {True, False}


@pytest.fixture
def gh(monkeypatch):
    from meeting_tasks import issues

    calls = []

    def fake(*args):
        calls.append(args)
        return "[]" if args[:2] == ("issue", "list") else f"https://github.com/o/r/issues/{len(calls)}\n"

    monkeypatch.setattr(issues, "_gh", fake)
    return calls


def extracted(app):
    at = app.run()
    at.button[0].click().run()
    return at


def test_create_needs_confirmation_and_then_creates(app, gh):
    at = extracted(app)
    at.text_input(key="repo").input("o/r").run()
    at.text_area(key="team").input("Ben = ben-dev").run()
    assert at.button(key="create").disabled  # nothing can be written without the tick
    at.button(key="check").click().run()
    assert not any(c[:2] == ("issue", "create") for c in gh)  # preview wrote nothing
    assert any("would create (assign @ben-dev)" in i.value for i in at.info)
    at.checkbox(key="confirm").check().run()
    at.button(key="create").click().run()
    assert not at.exception
    created = [c for c in gh if c[:2] == ("issue", "create")]
    assert len(created) == len(at.session_state["tasks"]) and len(at.success) >= len(created)


def test_bad_repo_and_team_are_rejected_before_any_gh_call(app, gh):
    at = extracted(app)
    at.text_input(key="repo").input("not a repo").run()
    assert any("owner/name" in e.value for e in at.error)
    at.text_input(key="repo").input("o/r").run()
    at.text_area(key="team").input("Ben ben-dev").run()
    assert any("Team: line 1" in e.value for e in at.error)
    assert gh == []


def test_missing_gh_shows_readable_error(app, monkeypatch):
    from meeting_tasks import issues

    def missing(*args):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(issues, "_gh", missing)
    at = extracted(app)
    at.text_input(key="repo").input("o/r").run()
    at.button(key="check").click().run()
    assert not at.exception and any("not installed" in e.value for e in at.error)


def test_demo_without_streamlit_gives_install_hint(monkeypatch):
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "streamlit" else real(n, *a, **k))
    with pytest.raises(SystemExit, match="pip install"):
        cli.demo()
