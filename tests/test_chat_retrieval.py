import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from routers import chat_router
from routers.chat_retrieval import strict_search

ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "data" / "eval" / "chat_eval.json"
KB_PATH = ROOT / "data" / "chat_kb.json"
EVAL_ITEMS = {
    item["id"]: item
    for item in json.loads(EVAL_PATH.read_text(encoding="utf-8"))
}
CARDS = json.loads(KB_PATH.read_text(encoding="utf-8"))


def _strict_hits(case_id):
    item = EVAL_ITEMS[case_id]
    return strict_search(
        item["question"],
        chat_router.search,
        CARDS,
        chat_router.TAU,
    )


def test_strict_is_default_when_environment_override_is_unset():
    environment = os.environ.copy()
    environment.pop("CHAT_RETRIEVAL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from routers.chat_router import CHAT_RETRIEVAL; print(CHAT_RETRIEVAL)",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "strict"


@pytest.mark.parametrize("case_id", ["A06", "A09", "A11", "A16", "A18"])
def test_answerable_eval_questions_return_expected_paper(case_id):
    item = EVAL_ITEMS[case_id]
    hits = _strict_hits(case_id)
    returned_ids = {hit["id"] for hit in hits}

    assert returned_ids & set(item["expected_cards"])
    assert returned_ids <= set(item["expected_cards"])


@pytest.mark.parametrize("case_id", ["B01", "B06", "B07", "B09", "B10"])
def test_out_of_scope_eval_questions_are_rejected(case_id):
    item = EVAL_ITEMS[case_id]
    assert item["expected_source"] in {"web", "none"}
    assert _strict_hits(case_id) == []


@pytest.mark.parametrize("case_id", ["C01", "C02", "C03", "C06", "C09"])
def test_confusing_eval_questions_do_not_adopt_unexpected_cards(case_id):
    item = EVAL_ITEMS[case_id]
    hits = _strict_hits(case_id)
    returned_ids = {hit["id"] for hit in hits}

    assert hits
    assert returned_ids <= set(item["expected_cards"])
