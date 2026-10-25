"""Score the rule baseline and the LLM against the labeled meetings. Usage: python evals/run_eval.py [repeats]

Without ANTHROPIC_API_KEY only the rules row is produced. The LLM row scores the tasks that survive
the guardrail, and reports how many the guardrail dropped.
"""
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from meeting_tasks import extract as ex
from meeting_tasks.scoring import match, rates, score

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text())


def errors(tasks, gold) -> list[str]:
    """Error analysis: every extra task, missed task and wrong owner/due date, as readable lines."""
    pairs = match(tasks, gold)
    hit_p, hit_g = {id(p) for p, _ in pairs}, {id(g) for _, g in pairs}
    out = [f"extra:  {t.title!r} ({t.owner or '?'}) from {t.quote!r}" for t in tasks if id(t) not in hit_p]
    out += [f"missed: {g['title']!r} ({g['owner']})" for g in gold if id(g) not in hit_g]
    for p, g in pairs:
        if p.owner.lower() != g["owner"].lower():
            out.append(f"owner:  {g['title']!r} got {p.owner!r}, expected {g['owner']!r}")
        if str(p.due or "") != (g["due"] or ""):
            out.append(f"due:    {g['title']!r} got {p.due}, expected {g['due']}")
    return out


def evaluate(run, repeats, which, show_errors=False):
    total, dropped = Counter(), 0
    for name, case in GOLD.items():
        if case.get("set", "standard") != which:
            continue
        text, day = (HERE / "meetings" / name).read_text(), date.fromisoformat(case["date"])
        for i in range(repeats):
            print(f"  {name} run {i + 1}/{repeats} …", file=sys.stderr, flush=True)  # LLM calls take seconds each
            tasks, n_dropped = run(text, day)
            total.update(score(tasks, case["tasks"]))
            dropped += n_dropped
            for line in errors(tasks, case["tasks"]) if show_errors else []:
                print(f"      {line}", file=sys.stderr)
    return total, dropped


def llm(text, day):
    result = ex.extract(text, day)
    if result.source != "llm":
        raise SystemExit(f"LLM call failed: {result.error}")
    return result.tasks, len(result.dropped)


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    rows = []
    for which in ["standard", "hard"]:
        rows.append((which, "rules baseline", *evaluate(lambda t, d: (ex.rule_extract(t, d), 0), 1, which)))
        if os.getenv("ANTHROPIC_API_KEY"):
            rows.append((which, f"LLM ({ex.MODEL}) + guardrail", *evaluate(llm, repeats, which, show_errors=True)))
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set: LLM rows skipped.\n")

    print("| set | extractor | tasks found | precision | recall | F1 | owner correct | due date correct | guardrail drops |")
    print("|---|---|---|---|---|---|---|---|---|")
    for which, name, c, dropped in rows:
        r = rates(c)
        print(f"| {which} | {name} | {c['pred']} | {r['precision']:.0%} | {r['recall']:.0%} | {r['f1']:.0%} | "
              f"{r['owner_acc']:.0%} | {r['due_acc']:.0%} | {dropped} |")
    if ex.usage["in"]:
        calls = len(GOLD) * repeats
        print(f"\nLLM tokens: {ex.usage['in']} in / {ex.usage['out']} out ({ex.usage['in'] // calls} / "
              f"{ex.usage['out'] // calls} per meeting)")


if __name__ == "__main__":
    main()
