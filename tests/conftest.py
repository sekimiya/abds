import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
OCR_DIR = ROOT / "ocr_results_debug"


@pytest.fixture(scope="session")
def card_index():
    with open(DATA_DIR / "card_index.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def card_details():
    with open(DATA_DIR / "card_details.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def link_index():
    with open(DATA_DIR / "link_index.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def ocr_files():
    """全OCR _basic.json を {card_number: data} で返す。"""
    results = {}
    for fname in sorted(os.listdir(OCR_DIR)):
        if not fname.endswith("_basic.json"):
            continue
        with open(OCR_DIR / fname, encoding="utf-8") as f:
            data = json.load(f)
        cn = data.get("card_number", "")
        if cn:
            results[cn] = data
    return results
