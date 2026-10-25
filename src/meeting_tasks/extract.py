import json
import logging
import os
import re
from datetime import date, timedelta

from pydantic import ValidationError

from .models import Extraction, Task

log = logging.getLogger(__name__)
usage = {"in": 0, "out": 0}  # running token totals, read by evals/run_eval.py
MODEL = os.getenv("MEETING_TASKS_MODEL", "claude-opus-5-5")

SYSTEM = """You extract action items from meeting transcripts.
An action item is a concrete task that a person agreed to do, or was asked to do and accepted.
Do NOT include: ideas or options that were only discussed, tasks someone declined, tasks that are
already done, or tasks later handed to someone else (use the final owner instead).
For each action item return:
- title: a short imperative phrase (max 10 words), e.g. "Send the revised quote to Acme"
- owner: the first name of the person responsible, as written in the transcript; "" if unclear
- due: the deadline as YYYY-MM-DD, resolving relative dates ("Friday", "next week") against the
  meeting date; "" if no deadline was said
- quote: the exact sentence from the transcript where the task was committed, copied verbatim"""

SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in ["title", "owner", "due", "quote"]},
        "required": ["title", "owner", "due", "quote"],
        "additionalProperties": False,
    }}},
    "required": ["tasks"],
    "additionalProperties": False,
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def grounded(task: Task, transcript: str) -> str | None:
    """Guardrail: return why the task is not backed by the transcript, or None if it is."""
    if _norm(task.quote) not in _norm(transcript):
        return "quote not found in the transcript"
    if task.owner and _norm(task.owner) not in _norm(transcript):
        return f"owner '{task.owner}' never appears in the transcript"
    return None


def extract(transcript: str, meeting_date: date, api_key: str | None = None) -> Extraction:
    """LLM extraction if a key is available, otherwise the rule baseline. LLM tasks whose quote or
    owner is not in the transcript are dropped by the guardrail."""
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return Extraction(rule_extract(transcript, meeting_date), "rules")
    try:
        raw = _llm_extract(transcript, meeting_date, key)
    except Exception as e:  # API down, bad key, refusal: still give the user something
        log.warning("LLM call failed (%s), using rules", type(e).__name__)
        return Extraction(rule_extract(transcript, meeting_date), "rules (API error)",
                          error=f"{type(e).__name__}: {e}"[:300])
    kept, dropped = [], []
    for item in raw:
        try:
            task = Task(**{**item, "due": item.get("due") or None})
        except ValidationError:
            dropped.append((Task.model_construct(**item), "invalid fields (e.g. a malformed date)"))
            continue
        if reason := grounded(task, transcript):
            dropped.append((task, reason))
        else:
            kept.append(task)
    return Extraction(kept, "llm", dropped)


def _llm_extract(transcript: str, meeting_date: date, api_key: str | None = None) -> list[dict]:
    import anthropic

    resp = anthropic.Anthropic(api_key=api_key).beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if a safety classifier declines, the API retries on a fallback model
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"Meeting date: {meeting_date.isoformat()} "
                   f"({meeting_date:%A})\n\nTranscript:\n{transcript}"}],
    )
    usage["in"] += resp.usage.input_tokens
    usage["out"] += resp.usage.output_tokens
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined the request")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["tasks"]


# --- rule baseline: what a simple non-AI tool would do -------------------------------------------

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LINE = re.compile(r"^\s*([A-Z][a-z]+)\s*:\s*(.+)$")
COMMIT = re.compile(r"\b(?:I'll|I will|I can|I'm going to)\s+(.+)", re.IGNORECASE)
ASSIGN = re.compile(r"\b([A-Z][a-z]+),?\s+(?:will|can you|could you|please)\s+(.+)")
MARKER = re.compile(r"\b(?:action item|todo|to-do)\s*:\s*(.+)", re.IGNORECASE)


def parse_due(text: str, meeting_date: date) -> date | None:
    low = text.lower()
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low):
        return date.fromisoformat(m.group(1))
    if "tomorrow" in low:
        return meeting_date + timedelta(1)
    if re.search(r"\btoday\b", low):
        return meeting_date
    if "end of the week" in low or "end of week" in low or "eow" in low:
        return meeting_date + timedelta((4 - meeting_date.weekday()) % 7)
    if "next week" in low:
        return meeting_date + timedelta(7 - meeting_date.weekday())  # next Monday
    for i, day in enumerate(WEEKDAYS):
        if re.search(rf"\b{day}\b", low):
            return meeting_date + timedelta((i - meeting_date.weekday()) % 7 or 7)
    return None


def _title(text: str) -> str:
    text = re.split(r"\b(?:by|before|until|on)\s+(?:monday|tuesday|wednesday|thursday|friday|tomorrow|"
                    r"next week|the end|end of|\d{4}-)", text, flags=re.IGNORECASE)[0]
    return text.strip(" .,!?").rstrip(" ,")[:80] or text[:80]


def rule_extract(transcript: str, meeting_date: date) -> list[Task]:
    """Keyword baseline: "I'll ...", "<Name>, can you ...", "Action item: ...". No understanding of
    declines, hand-overs or finished work, which is exactly what the eval measures."""
    speakers = {m.group(1) for line in transcript.splitlines() if (m := LINE.match(line))}
    tasks = []
    for line in transcript.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        speaker, said = m.groups()
        for sentence in re.split(r"(?<=[.!?])\s+", said):
            owner, what = "", None
            if mm := MARKER.search(sentence):
                what = mm.group(1)
                owner = next((s for s in speakers if re.search(rf"\b{s}\b", what)), "")
            elif (mm := ASSIGN.search(sentence)) and mm.group(1) in speakers:
                owner, what = mm.groups()
            elif mm := COMMIT.search(sentence):
                owner, what = speaker, mm.group(1)
            if what and len(_title(what)) >= 3:
                tasks.append(Task(title=_title(what), owner=owner, due=parse_due(sentence, meeting_date),
                                  quote=sentence.strip()))
    return tasks
