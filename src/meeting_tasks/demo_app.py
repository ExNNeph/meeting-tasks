"""Local web demo (nothing is written to GitHub): started with `meeting-tasks demo`."""
import os
from datetime import date

import pandas as pd
import streamlit as st

from meeting_tasks.extract import MODEL, extract
from meeting_tasks.issues import issue_body
from meeting_tasks.models import Task

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
st.caption("Paste meeting notes, extract the action items and preview the GitHub issues. "
           "This page never writes to GitHub.")

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

if tasks:
    st.subheader(f"GitHub issue preview ({len(tasks)})")
    st.caption("This is what `meeting-tasks notes.txt --repo you/your-repo --create` would create.")
    for t in tasks:
        with st.expander(t.title):
            st.markdown(issue_body(t, "notes.txt"))
else:
    st.write("No tasks to send.")
