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
from meeting_tasks.scoring import rates, score

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text())
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def evaluate(run, repeats):
    total, dropped = Counter(), 0
    for name, case in GOLD.items():
        text, day = (HERE / "meetings" / name).read_text(), date.fromisoformat(case["date"])
        for i in range(repeats):
            print(f"  {name} run {i + 1}/{repeats} …", file=sys.stderr, flush=True)  # LLM calls take seconds each
            tasks, n_dropped = run(text, day)
            total.update(score(tasks, case["tasks"]))
            dropped += n_dropped
    return total, dropped


def llm(text, day):
    result = ex.extract(text, day)
    if result.source != "llm":
        raise SystemExit(f"LLM call failed: {result.error}")
    return result.tasks, len(result.dropped)


rows = [("rules baseline", *evaluate(lambda t, d: (ex.rule_extract(t, d), 0), 1))]
if os.getenv("ANTHROPIC_API_KEY"):
    rows.append((f"LLM ({ex.MODEL}) + guardrail", *evaluate(llm, REPEATS)))
else:
    print("No ANTHROPIC_API_KEY set: LLM row skipped.\n")

print("| extractor | tasks found | precision | recall | F1 | owner correct | due date correct | guardrail drops |")
print("|---|---|---|---|---|---|---|---|")
for name, c, dropped in rows:
    r = rates(c)
    print(f"| {name} | {c['pred']} | {r['precision']:.0%} | {r['recall']:.0%} | {r['f1']:.0%} | "
          f"{r['owner_acc']:.0%} | {r['due_acc']:.0%} | {dropped} |")
if ex.usage["in"]:
    calls = len(GOLD) * REPEATS
    print(f"\nLLM tokens: {ex.usage['in']} in / {ex.usage['out']} out ({ex.usage['in'] // calls} / "
          f"{ex.usage['out'] // calls} per meeting)")
