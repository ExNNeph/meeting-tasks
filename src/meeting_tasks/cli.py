import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

from .extract import extract
from .issues import sync

DEMO_APP = Path(__file__).with_name("demo_app.py")


def demo() -> None:
    """Start the local web demo on http://localhost:8501 and open the browser."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise SystemExit('The demo needs Streamlit: pip install -e ".[demo]"')
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(DEMO_APP), "--server.address", "localhost",
                    "--server.port", "8501", "--browser.gatherUsageStats", "false",
                    "--client.toolbarMode", "minimal",  # hides Streamlit's "Deploy" button
                    "--server.fileWatcherType", "none"])  # no code reloading needed, and no "install Watchdog" hint


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["demo"]:
        return demo()
    p = argparse.ArgumentParser(prog="meeting-tasks", description="Turn meeting notes into GitHub Issues. "
                                "Run `meeting-tasks demo` for the local web demo.")
    p.add_argument("notes", type=Path, help="transcript or notes file (lines like 'Anna: I'll send the deck')")
    p.add_argument("--date", type=date.fromisoformat, default=date.today(),
                   help="meeting date for relative deadlines like 'Friday' (default: today)")
    p.add_argument("--repo", help="owner/name of the GitHub repo for the issues")
    p.add_argument("--create", action="store_true", help="actually create the issues (default: preview only)")
    args = p.parse_args(argv)
    if args.create and not args.repo:
        p.error("--create needs --repo")

    result = extract(args.notes.read_text(encoding="utf-8"), args.date)
    print(f"{len(result.tasks)} task(s) found ({result.source})" + (f": {result.error}" if result.error else ""))
    for t in result.tasks:
        print(f"- {t.title}  [owner: {t.owner or '?'}, due: {t.due or '-'}]")
    for t, why in result.dropped:
        print(f"  dropped by guardrail: {t.title!r} ({why})")
    if args.repo:
        for t, status in sync(result.tasks, args.repo, args.notes.name, args.create):
            print(f"{status}: {t.title}")
        if not args.create:
            print("Preview only. Add --create to create these issues.")
