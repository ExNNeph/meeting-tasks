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
    table = at.dataframe[0].value
    assert "send the revised quote to Acme" in list(table["task"])
    assert len(at.expander) == len(table)  # one issue preview per task


def test_demo_without_streamlit_gives_install_hint(monkeypatch):
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "streamlit" else real(n, *a, **k))
    with pytest.raises(SystemExit, match="pip install"):
        cli.demo()
