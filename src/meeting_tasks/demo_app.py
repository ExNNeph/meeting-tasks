"""Local web demo (nothing is written to GitHub): started with `meeting-tasks demo`."""
import os
from datetime import date

import pandas as pd
import streamlit as st

from meeting_tasks.extract import MODEL, extract
from meeting_tasks.issues import issue_body

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

st.subheader(f"Tasks ({len(result.tasks)})")
if result.tasks:
    st.dataframe(pd.DataFrame([{"task": t.title, "owner": t.owner or "—", "due": t.due or "—", "quote": t.quote}
                               for t in result.tasks]), hide_index=True, width="stretch")
else:
    st.write("No action items found.")

if result.dropped:
    st.subheader(f"Dropped by the guardrail ({len(result.dropped)})")
    for task, why in result.dropped:
        st.warning(f"**{task.title}**: {why}")

if result.tasks:
    st.subheader("GitHub issue preview")
    st.caption("This is what `meeting-tasks notes.txt --repo you/your-repo --create` would create.")
    for t in result.tasks:
        with st.expander(t.title):
            st.markdown(issue_body(t, "notes.txt"))
