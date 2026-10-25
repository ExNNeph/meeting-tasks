"""Create GitHub Issues through the `gh` CLI, so the user's existing `gh auth login` is reused and
no token ever passes through this tool."""
import json
import subprocess

from .models import Task


def issue_body(task: Task, source: str) -> str:
    lines = [f"**Owner:** {task.owner or 'unassigned'}", f"**Due:** {task.due or 'no deadline'}", "",
             f"> {task.quote}", "", f"_Extracted by meeting-tasks from {source}_"]
    return "\n".join(lines)


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issue_titles(repo: str) -> set[str]:
    out = _gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "1000", "--json", "title")
    return {i["title"].strip().lower() for i in json.loads(out)}


def sync(tasks: list[Task], repo: str, source: str, create: bool) -> list[tuple[Task, str]]:
    """Return (task, status) per task. Without create=True nothing is written (preview).
    Tasks whose title already exists as an open issue are skipped, so re-running is safe."""
    existing = open_issue_titles(repo)
    results = []
    for task in tasks:
        if task.title.strip().lower() in existing:
            results.append((task, "skipped: open issue with this title exists"))
        elif not create:
            results.append((task, "would create"))
        else:
            url = _gh("issue", "create", "--repo", repo, "--title", task.title,
                      "--body", issue_body(task, source)).strip()
            existing.add(task.title.strip().lower())
            results.append((task, f"created {url}"))
    return results
