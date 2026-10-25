"""Create GitHub Issues through the `gh` CLI, so the user's existing `gh auth login` is reused and
no token ever passes through this tool."""
import json
import re
import subprocess

from .models import Task

LABEL = "meeting-task"
USERNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")  # GitHub's username rules


def parse_team(text: str) -> dict[str, str]:
    """'Ben = ben-dev' lines (or 'Ben: @ben-dev') -> {'ben': 'ben-dev'}. Blank lines and # comments are
    ignored; anything else that is not a valid mapping raises ValueError naming the line."""
    team = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([^=:]+?)\s*[=:]\s*@?(\S+)", line)
        if not m or not USERNAME.fullmatch(m.group(2)):
            raise ValueError(f"line {n}: expected 'Name = github-username', got {line!r}")
        team[m.group(1).lower()] = m.group(2)
    return team


def issue_body(task: Task, source: str) -> str:
    quote = f"> {task.quote}" if task.quote else "_Added by hand during review_"
    lines = [f"**Owner:** {task.owner or 'unassigned'}", f"**Due:** {task.due or 'no deadline'}", "",
             quote, "", f"_Extracted by meeting-tasks from {source}_"]
    return "\n".join(lines)


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issue_titles(repo: str) -> set[str]:
    out = _gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "1000", "--json", "title")
    return {i["title"].strip().lower() for i in json.loads(out)}


def ensure_label(repo: str) -> None:
    # --force makes this idempotent: creates the label or updates it if it already exists
    _gh("label", "create", LABEL, "--repo", repo, "--color", "1D76DB", "--force",
        "--description", "Action item extracted from meeting notes")


def sync(tasks: list[Task], repo: str, source: str, create: bool,
         team: dict[str, str] | None = None) -> list[tuple[Task, str]]:
    """Return (task, status) per task. Without create=True nothing is written (preview).
    Tasks whose title already exists as an open issue are skipped, so re-running is safe. Owners
    found in `team` are assigned; one failing issue does not stop the others."""
    team = team or {}
    existing = open_issue_titles(repo)
    label_ready, results = False, []
    for task in tasks:
        key = task.title.strip().lower()
        assignee = team.get(task.owner.lower())
        to = f" (assign @{assignee})" if assignee else ""
        if key in existing:
            results.append((task, "skipped: open issue with this title exists"))
        elif not create:
            existing.add(key)  # a second task with the same title in this run would be skipped too
            results.append((task, "would create" + to))
        else:
            if not label_ready:
                ensure_label(repo)
                label_ready = True
            args = ["issue", "create", "--repo", repo, "--title", task.title,
                    "--body", issue_body(task, source), "--label", LABEL]
            try:
                url = _gh(*args, *(["--assignee", assignee] if assignee else [])).strip()
            except subprocess.CalledProcessError as e:
                results.append((task, f"failed: {(e.stderr or str(e)).strip()[:200]}"))
                continue
            existing.add(key)
            results.append((task, f"created {url}" + to))
    return results
