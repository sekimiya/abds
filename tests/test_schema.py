"""OCRスキーマ正規化テスト: 全ファイルが正規フィールド名を使用していることを検証"""

from schema import STAT_ALIASES, LINK_ALIASES, ACTIVATION_KEYWORDS


def test_no_shorthand_stat_names(ocr_files):
    bad = []
    for cn, data in ocr_files.items():
        stats = data.get("ocr_data", {}).get("stats", {})
        if not isinstance(stats, dict):
            continue
        for alias in STAT_ALIASES:
            if alias in stats:
                bad.append(f"{cn}: stats.{alias}")
    assert not bad, f"非正規stat名: {bad}"


def test_no_plural_link_abilities(ocr_files):
    bad = []
    for cn, data in ocr_files.items():
        ocr = data.get("ocr_data", {})
        if "link_abilities" in ocr:
            bad.append(cn)
    assert not bad, f"link_abilities使用: {bad}"


def test_canonical_activation_field(ocr_files):
    bad = []
    for cn, data in ocr_files.items():
        msa = data.get("ocr_data", {}).get("ms_ability")
        if not isinstance(msa, dict):
            continue
        if "timing" in msa:
            bad.append(f"{cn}: ms_ability.timing")
        if "type" in msa and "activation" not in msa and msa["type"] in ACTIVATION_KEYWORDS:
            bad.append(f"{cn}: ms_ability.type(発動系)")
    assert not bad, f"非正規activation: {bad}"


def test_required_fields_present(ocr_files):
    bad = []
    for cn, data in ocr_files.items():
        if not data.get("card_number"):
            bad.append(f"{cn}: card_number missing")
        ocr = data.get("ocr_data", {})
        if not ocr.get("type"):
            bad.append(f"{cn}: ocr_data.type missing")
    assert not bad, f"必須フィールド欠損: {bad}"
