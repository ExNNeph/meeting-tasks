from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field


class Task(BaseModel):
    title: str = Field(min_length=3)  # short imperative, e.g. "Send the revised quote to Acme"
    owner: str = ""  # first name as spoken in the meeting; "" if nobody took it
    due: date | None = None
    quote: str = Field(min_length=3)  # sentence from the transcript that commits to the task


@dataclass
class Extraction:
    tasks: list[Task]
    source: str  # "llm", "rules" or "rules (API error)"
    dropped: list[tuple[Task, str]] = field(default_factory=list)  # (task, why the guardrail removed it)
    error: str = ""
