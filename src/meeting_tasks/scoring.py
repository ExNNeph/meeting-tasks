"""Compare extracted tasks with a hand-labeled answer key (precision, recall, owner and due accuracy)."""
import re
from datetime import date

from .models import Task

STOP = {"the", "a", "an", "to", "for", "of", "and", "on", "by", "in", "with", "from", "our", "it", "them",
        "that", "this", "be", "up", "new", "i", "my", "me", "will", "can", "you"}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def similarity(a: str, b: str) -> float:
    """Share of the shorter title's content words that also appear in the other title."""
    wa, wb = words(a), words(b)
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


def match(pred: list[Task], gold: list[dict], threshold: float = 0.5) -> list[tuple[Task, dict]]:
    """Greedy one-to-one matching by title similarity, best pairs first."""
    pairs = sorted(((similarity(p.title, g["title"]), i, j) for i, p in enumerate(pred) for j, g in enumerate(gold)),
                   reverse=True)
    used_p, used_g, out = set(), set(), []
    for sim, i, j in pairs:
        if sim >= threshold and i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append((pred[i], gold[j]))
    return out


def score(pred: list[Task], gold: list[dict]) -> dict[str, int]:
    """Raw counts, so several meetings can be summed before computing rates."""
    matched = match(pred, gold)
    return {
        "pred": len(pred), "gold": len(gold), "tp": len(matched),
        "owner_ok": sum(p.owner.lower() == g["owner"].lower() for p, g in matched),
        "due_ok": sum(p.due == (date.fromisoformat(g["due"]) if g["due"] else None) for p, g in matched),
    }


def rates(c: dict[str, int]) -> dict[str, float]:
    p = c["tp"] / c["pred"] if c["pred"] else 0.0
    r = c["tp"] / c["gold"] if c["gold"] else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "owner_acc": c["owner_ok"] / c["tp"] if c["tp"] else 0.0,
            "due_acc": c["due_ok"] / c["tp"] if c["tp"] else 0.0}
