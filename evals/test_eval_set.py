"""Sanity checks on the eval itself: the answer key scores perfectly, every labeled owner and quote
source exists, and the rule baseline runs on every meeting."""
import json
from datetime import date
from pathlib import Path

import pytest

from meeting_tasks.extract import rule_extract
from meeting_tasks.models import Task
from meeting_tasks.scoring import rates, score

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text())


@pytest.mark.parametrize("name", GOLD)
def test_answer_key_scores_perfectly_against_itself(name):
    gold = GOLD[name]["tasks"]
    as_tasks = [Task(title=g["title"], owner=g["owner"], due=g["due"], quote="x" * 3) for g in gold]
    assert rates(score(as_tasks, gold)) == {"precision": 1, "recall": 1, "f1": 1, "owner_acc": 1, "due_acc": 1}


@pytest.mark.parametrize("name", GOLD)
def test_labeled_owners_appear_in_the_meeting(name):
    text = (HERE / "meetings" / name).read_text()
    assert all(g["owner"] in text for g in GOLD[name]["tasks"])


def test_error_analysis_names_extras_misses_and_wrong_fields():
    import sys

    sys.path.insert(0, str(HERE))
    from run_eval import errors

    gold = GOLD["product-sync.txt"]["tasks"]
    pred = [Task(title="Send the revised quote to Acme", owner="Anna", due="2026-10-28", quote="x" * 3),
            Task(title="Be honest about onboarding", owner="Chris", quote="I'll be honest")]
    lines = errors(pred, gold)
    assert "owner:  'Send the revised quote to Acme' got 'Anna', expected 'Ben'" in lines
    assert any(line.startswith("extra:  'Be honest") for line in lines)
    assert sum(line.startswith("missed:") for line in lines) == 3


@pytest.mark.parametrize("name", GOLD)
def test_rule_baseline_runs(name):
    rule_extract((HERE / "meetings" / name).read_text(), date.fromisoformat(GOLD[name]["date"]))
