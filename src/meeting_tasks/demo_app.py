"""Local web demo, started with `meeting-tasks demo`. Writes to GitHub only after explicit confirmation."""
import os
import re
import subprocess
from datetime import date

import pandas as pd
import streamlit as st

from meeting_tasks.extract import MODEL, extract
from meeting_tasks.issues import issue_body, parse_team, sync
from meeting_tasks.models import Task

REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")

SAMPLE = """Anna: Okay, let's start. The Acme demo went well last week.
Ben: Agreed. They want a revised quote before they sign.
Anna: Ben, can you send the revised quote to Acme by Wednesday?
Ben: Sure, I'll send it by Wednesday.
Chris: I'll be honest, the onboarding flow still confuses people.
Anna: We could maybe redesign the whole onboarding at some point.
Chris: Let's not commit to that now. But I will write up the three biggest onboarding issues by Friday.
Ben: I was going to update the pricing page, but I won't have time this week.
Anna: Then I'll update the pricing page myself.
Chris: Also, the bug in the export is already fixed, I deployed it this morning.
Anna: Great. Action item: Chris to book the room for the customer workshop.
Chris: Fine, I can do that tomorrow.
Anna: That's all, thanks everyone."""

st.set_page_config(page_title="Meeting Tasks demo", page_icon="✅", layout="wide")
st.title("✅ Meeting Notes → Tasks")
st.caption("Paste meeting notes, extract the action items, review them and send them to GitHub as issues. "
           "Nothing is written to GitHub until you confirm.")

with st.sidebar:
    meeting_date = st.date_input("Meeting date", date(2026, 10, 26),
                                 help="Relative deadlines like 'Friday' are resolved from this date.")
    api_key = st.text_input("Anthropic API key (optional)", type="password",
                            help="Used only for your requests in this local session, never stored.")
    if api_key or os.getenv("ANTHROPIC_API_KEY"):
        where = "sidebar" if api_key else "ANTHROPIC_API_KEY environment variable"
        st.success(f"🔑 Key set ({where}): tasks are extracted by Claude ({MODEL}).")
    else:
        st.info("No key: a simple keyword baseline is used. Paste a key and press Enter to compare with Claude.")
    st.markdown("**Guardrail:** every task must quote the transcript. Tasks whose quote or owner is not "
                "in the notes are dropped and listed with the reason.")

notes = st.text_area("Meeting notes", SAMPLE, height=300)


@st.cache_data(show_spinner="Reading the meeting…")
def cached_extract(text: str, day: date, key: str):
    # cached so reruns (clicking, scrolling) never call or pay for the API twice
    return extract(text, day, key or None)


if st.button("Extract tasks", type="primary"):
    st.session_state.result = cached_extract(notes, meeting_date, api_key)
    st.session_state.result_for = (notes, meeting_date, api_key)
    st.session_state.run_id = st.session_state.get("run_id", 0) + 1  # fresh editor for each extraction

result = st.session_state.get("result")
if result is None:
    st.info("👆 Click **Extract tasks** to find the action items in these notes.")
    st.stop()
if st.session_state.get("result_for") != (notes, meeting_date, api_key):
    st.warning("The notes, date or key changed since this result. Click **Extract tasks** again to update it.")

if result.source == "llm":
    st.success(f"Extracted by Claude ({MODEL}). Every task below is backed by a quote from the notes.")
elif result.source == "rules (API error)":
    st.error(f"The Claude call failed, so the keyword baseline was used instead.\n\n`{result.error}`")
else:
    st.info("Extracted by the keyword baseline. It also picks up phrases like \"I'll be honest\" and duplicates; "
            "add an API key to see how Claude handles them.")

if result.dropped:
    with st.expander(f"Dropped by the guardrail ({len(result.dropped)})"):
        for task, why in result.dropped:
            st.warning(f"**{task.title}**: {why}")

st.subheader("Review the tasks")
st.caption("Edit text, owner or due date, delete rows (select, then 🗑) or add one at the bottom. "
           "The quote is the evidence from the notes and stays locked. Only this table is sent to GitHub.")
edited = st.data_editor(
    # dates stay date objects (or None) so Arrow keeps one column type
    pd.DataFrame([{"task": t.title, "owner": t.owner, "due": t.due, "quote": t.quote} for t in result.tasks],
                 columns=["task", "owner", "due", "quote"]),
    num_rows="dynamic", hide_index=True, width="stretch", key=f"tasks{st.session_state.get('run_id', 0)}",
    column_config={"task": st.column_config.TextColumn(required=True), "due": st.column_config.DateColumn(),
                   "quote": st.column_config.TextColumn(disabled=True)},
)


def text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


tasks = []
for row in edited.to_dict("records"):
    if len(text(row["task"])) < 3:
        continue  # empty row just added, or a title too short to be a task
    tasks.append(Task(title=text(row["task"]), owner=text(row["owner"]), quote=text(row["quote"]),
                      due=None if pd.isna(row["due"]) else pd.to_datetime(row["due"]).date()))
st.session_state.tasks = tasks

if not tasks:
    st.write("No tasks to send.")
    st.stop()

source = f"meeting notes from {meeting_date:%d.%m.%Y}"
st.subheader(f"GitHub issue preview ({len(tasks)})")
for t in tasks:
    with st.expander(t.title):
        st.markdown(issue_body(t, source))

st.subheader("Send to GitHub")
st.caption("Uses your `gh auth login`. Nothing is written until you tick the confirmation and click Create.")
left, right = st.columns(2)
repo = left.text_input("Repository", placeholder="you/your-repo", key="repo").strip()
team_text = right.text_area("Team (optional): one 'Name = GitHub username' per line",
                            placeholder="Ben = ben-dev\nAnna = anna42", height=110, key="team")
try:
    team = parse_team(team_text)
except ValueError as e:
    st.error(f"Team: {e}")
    st.stop()
if not repo:
    st.stop()
if not REPO.fullmatch(repo):
    st.error("Repository must look like `owner/name`.")
    st.stop()


def run_sync(create: bool):
    """sync() with readable errors instead of tracebacks; returns the results or None."""
    try:
        return sync(tasks, repo, source, create, team)
    except FileNotFoundError:
        st.error("The GitHub CLI `gh` is not installed. Install it and run `gh auth login`.")
    except subprocess.CalledProcessError as e:
        st.error(f"GitHub CLI error (not logged in, or no access to `{repo}`?):\n\n`{(e.stderr or str(e)).strip()}`")


def show(results):
    for t, status in results:
        if status.startswith("created"):
            st.success(f"**{t.title}**: {status}")
        elif status.startswith("failed"):
            st.error(f"**{t.title}**: {status}")
        else:
            st.info(f"**{t.title}**: {status}")


if st.button("Check repo (preview, writes nothing)", key="check"):
    st.session_state.checked = (repo, run_sync(create=False))
if st.session_state.get("checked", (None,))[0] == repo and st.session_state.checked[1]:
    show(st.session_state.checked[1])

confirm = st.checkbox(f"Yes, create these {len(tasks)} issues in {repo}", key="confirm")
if st.button(f"Create issues in {repo}", type="primary", disabled=not confirm, key="create"):
    st.session_state.created = run_sync(create=True)
if st.session_state.get("created"):
    st.subheader("Result")
    show(st.session_state.created)
