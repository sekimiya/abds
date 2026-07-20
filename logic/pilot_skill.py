"""
GAB デッキシミュレーター PLスキル条件解析・効果分類

パイロットスキルのトリガー条件と効果を構造化する。
Wiki (gundamab.swiki.jp) のゲームメカニクス情報に基づく。
"""

import re
from typing import Optional

from .types import PLSkillInfo


def classify_skill_trigger(pl_ocr: Optional[dict]) -> Optional[str]:
    """PLスキルのトリガー条件を分類する。

    Args:
        pl_ocr: PLカードのOCRデータ

    Returns:
        トリガータイプ文字列。スキルが無い場合はNone。
    """
    skill_text = _get_skill_text(pl_ocr)
    if not skill_text:
        return None

    if re.search(r'(撃破|撃墜)', skill_text):
        return 'on_kill'
    if re.search(r'出撃時', skill_text):
        return 'on_deploy'
    if re.search(r'(HP|体力).*(以下|一定)', skill_text):
        return 'hp_threshold'
    if re.search(r'(戦闘開始|バトル開始)', skill_text):
        return 'on_battle_start'
    if re.search(r'(一定時間|秒)', skill_text):
        return 'timed'
    if re.search(r'(攻撃時|攻撃した)', skill_text):
        return 'on_attack'
    if re.search(r'被弾|被ダメ', skill_text):
        return 'on_hit'

    return 'passive'


def classify_skill_effect(pl_ocr: Optional[dict]) -> Optional[str]:
    """PLスキルの効果を分類する。

    Args:
        pl_ocr: PLカードのOCRデータ

    Returns:
        効果タイプ文字列。スキルが無い場合はNone。
    """
    skill_text = _get_skill_text(pl_ocr)
    if not skill_text:
        return None

    if re.search(r'コスト.*ダウン|コスト.*減少|コスト.*軽減', skill_text):
        return 'cost_down'
    if re.search(r'(攻撃力|ダメージ).*アップ', skill_text):
        return 'stat_up'
    if re.search(r'(機動力|移動速度).*アップ', skill_text):
        return 'mobility_up'
    if re.search(r'HP.*回復|体力.*回復', skill_text):
        return 'hp_recovery'
    if re.search(r'(防御|ダメージ軽減|ダメージカット)', skill_text):
        return 'defense_up'
    if re.search(r'(SP|ゲージ).*(チャージ|増加|回復)', skill_text):
        return 'sp_charge'
    if re.search(r'(クリティカル|会心)', skill_text):
        return 'critical'
    if re.search(r'(範囲|全体)', skill_text):
        return 'area_effect'

    return 'other'


def get_skill_info(pl_ocr: Optional[dict]) -> Optional[PLSkillInfo]:
    """PLスキルの構造化情報を取得する。

    Args:
        pl_ocr: PLカードのOCRデータ

    Returns:
        構造化されたスキル情報。スキルが無い場合はNone。
    """
    skill_text = _get_skill_text(pl_ocr)
    if not skill_text:
        return None

    trigger_type = classify_skill_trigger(pl_ocr)
    effect_type = classify_skill_effect(pl_ocr)

    info: PLSkillInfo = {
        'trigger_type': trigger_type or 'unknown',
        'effect_type': effect_type or 'unknown',
        'raw': skill_text,
    }

    # トリガーとエフェクトの詳細テキストを分離
    trigger, effect = _split_trigger_effect(skill_text)
    if trigger:
        info['trigger'] = trigger
    if effect:
        info['effect'] = effect

    return info


def _get_skill_text(pl_ocr: Optional[dict]) -> Optional[str]:
    """PLカードからスキルテキストを取得する。"""
    if not pl_ocr:
        return None

    skill = pl_ocr.get('pl_skill') or pl_ocr.get('pilot_skill')

    if isinstance(skill, str):
        return skill if skill.strip() else None

    if isinstance(skill, dict):
        # trigger/effect 形式
        parts = []
        if skill.get('trigger'):
            parts.append(skill['trigger'])
        if skill.get('effect'):
            parts.append(skill['effect'])
        if parts:
            return '。'.join(parts)
        # description / raw 形式
        text = skill.get('description') or skill.get('raw') or skill.get('name')
        return text if text and text.strip() else None

    if isinstance(skill, list) and skill:
        texts = []
        for s in skill:
            if isinstance(s, str):
                texts.append(s)
            elif isinstance(s, dict):
                t = s.get('description') or s.get('effect') or s.get('name', '')
                if t:
                    texts.append(t)
        return '。'.join(texts) if texts else None

    return None


def _split_trigger_effect(text: str) -> tuple:
    """スキルテキストをトリガーとエフェクトに分離する。"""
    # "〜時、〜" or "〜時に〜" パターン
    match = re.match(r'(.+?[時際])[\s、,に]+(.+)', text)
    if match:
        return match.group(1), match.group(2)

    # "〜と〜" パターン
    match = re.match(r'(.+?(?:すると|したら|した時))[\s、,]*(.+)', text)
    if match:
        return match.group(1), match.group(2)

    return None, text
