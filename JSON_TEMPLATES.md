# ABDS カードデータ スキーマ仕様 (canonical形式)

このドキュメントは、本リポジトリ(gh-pagesブランチ)で扱う全JSONの**現行スキーマ**を定義する。
正規化・バリデーションの実装は `schema.py`、ビルドは `rebuild_index.py` が正。
本ドキュメントと実装が食い違う場合は `schema.py` を正とし、本ドキュメントを直すこと。

## データフロー

```
all_cards_list/*.json      カードカタログ (番号・名前・画像URL)
ocr_results_debug/*_basic.json   OCR結果 (カード裏面の全情報)
        │
        ▼  python3 rebuild_index.py  (schema.py で正規化・canonical化)
data/card_index.json       一覧用の軽量インデックス
data/card_details.json     全カード詳細 (フロントエンドが参照)
data/link_index.json       リンクアビリティ索引
data/version.json          ビルドメタデータ
```

- パラレルカード(`_p1`等)は `all_cards_list/` のエントリから生成され、OCRデータはベースカードのコピー。OCRは不要。
- `ocr_results_debug/` 内で同じ `card_number` を持つ `_basic.json` が複数あってはならない(ソート順で最初の1件しか読まれない)。

## 1. all_cards_list エントリ

ファイル名: `{番号}_{シリーズ}_{カード名}.json`

```json
{
  "number": "VEB02-001",
  "name": "高機動試作型ザク",
  "series": "VEブースター2弾",
  "front": { "image_url": "https://www.gundam-ab.com/images/cardlist/card/VEB02-001.jpg?v250630" },
  "back":  { "image_url": "https://www.gundam-ab.com/images/cardlist/card/VEB02-001_b.jpg?v250630" }
}
```

## 2. OCR結果 (_basic.json)

```json
{
  "card_number": "VEB02-001",
  "card_name": "高機動試作型ザク",
  "series": "VEブースター2弾",
  "ocr_data": { /* 下記canonical形式 */ },
  "ocr_engine": "claude_code_subagent",
  "ocr_timestamp": "2026-05-15T00:00:00"
}
```

## 3. ocr_data canonical形式

### 共通フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| type | "MS" / "PL" | カード種別 |
| name | string | 表示名 (型式名ms_nameではなくカード名) |
| cost | int | コスト |
| rarity | string | C, U, R, M, P, PR, A(AR弾), LX(LXR弾), VE/SN(VEパラレル), LE 等の印字記号。**「SECRET」「PARALLEL」バナーはレアリティではない**。パラレル固有レアリティはall_cards_listエントリの`rarity`で上書き可 |
| category | string | MS: 近距離/遠距離/機動、PL: 殲滅/制圧/防衛 |
| affiliation | string | 所属 |
| illustrator | string | イラストレーター (不明は "") |
| stats | object | `{ "mobility", "ranged_attack", "melee_attack", "hp" }` すべてint |
| link_ability | array | 下記。**単数形 link_ability** (link_abilitiesは非canonical) |

### link_ability 要素

```json
{
  "name": "第08MS小隊",
  "condition": "デッキに3枚以上",
  "effect": "[遠距離攻撃力][近距離攻撃力]小アップ",
  "is_eb_link": false,
  "is_sq_link": false,
  "is_ab_link": false
}
```

- name に `[EB]` `[SQ]` `[AB]` プレフィックスは付けない (フラグで表現)
- name は `data/link_index.json` のマスターに存在する名前であること

### MSカード固有

```json
{
  "pilot": "アイナ・サハリン",
  "model": "MS-06RD-4 ZAKU HIGH MOBILITY TEST TYPE",
  "terrain_compatibility": { "ground": "A", "space": "S", "desert": "C", "water": "C" },
  "weapon": {
    "main": { "name": "ザク・マシンガン", "range": 3, "type": "遠距離" },
    "sub":  { "name": "ヒート・ホーク", "range": 1, "type": "近距離" }
  },
  "ms_ability": {
    "name": "転化[妨害]",
    "activation": "任意発動",
    "target": "範囲(敵)",
    "range": 0,
    "cost": 4,
    "description": "一定時間、自身を中心とした範囲内の敵ユニットを弱体化する。…"
  },
  "special_attack": { /* 下記 */ }
}
```

- terrain_compatibility の値は S/A/B/C。**カードに項目が無い場合(初期弾の水中等)は ""** (空文字列)
- ms_ability の発動条件キーは **activation** (timing/typeは非canonical)

### special_attack (canonical)

```json
{
  "name": "胸部メガ粒子砲撃射",
  "target": "貫通(敵)",
  "range": 4,
  "sp_cost": 2,
  "power": 3000,
  "description": "射線上の敵に貫通射撃でダメージを与える。",
  "sp_type": "",
  "echoes_beat": null,
  "united_sp": null,
  "squad_sp": null
}
```

- sp_type: "" (通常) / "ECHOES BEAT" / "ECHOES BEAT SP" / "SQUAD SP" / "UNITED SP"
- 威力・説明が「通常 / EB」併記の場合、special_attack側は通常分のみ、EB分はechoes_beat側へ分離

**echoes_beat** (EBがある場合。フラットなeb_level等をspecial_attack直下に置かない):

```json
{
  "name": "胸部メガ粒子砲撃射 Lv.2",
  "level": 2,
  "power": 3600,
  "range": 4,
  "target": "貫通(敵)",
  "description": "EBLv.を2下げる。射線上の敵に…"
}
```

**united_sp**: `{ "name", "partners": [..], "target", "range", "power", "description" }`
**squad_sp**: `{ "name", "target", "range", "power", "description", "note" }`

### PLカード固有

```json
{
  "english_name": "NILS NIELSEN",
  "physical": { "height": "ー", "age": "13歳" },
  "units": ["戦国アストレイ頑駄無"],
  "pilot_skill": {
    "name": "折り重なる斬撃",
    "trigger": "出撃後一定時間経過毎",
    "effect": "40秒経過毎に自身の[近距離攻撃力]を小アップする。最大3回まで発動。",
    "has_sq_skill": false,
    "sq_skill_details": null,
    "is_eb_skill": false,
    "eb_trigger_level": null,
    "sq_rush_effect": ""
  }
}
```

- キーは **pilot_skill** (pl_skillは非canonical)
- sq_skill_details (has_sq_skill=true時): `{ "name", "trigger", "effect", "sq_gauge_effect", "sq_max_effect", "sq_rush_effect" }`
- is_eb_skill: 「EB PL SKILL」表記 or triggerに「EBLv.」を含む場合 true。eb_trigger_level にLv数値

## 4. data/card_details.json

`{ カード番号: エントリ }` の辞書。エントリは `number, name, url, category, series, front, back, ocr_data` を持ち、
**name/category/series はocr_data内と同値であること** (二重保持のため乖離させない)。

## 5. data/card_index.json

エントリの配列。主要フィールド: `number, name, type, category, cost, series, rarity,
front_url, back_url, mobility, ranged, melee, hp, has_ocr, terrain, search_text,
pilot, model, illustrator` + SQ/EB/ABの派生フラグ群 (`has_eb, has_sq_skill, eb_level,
sp_effect_tags` 等)。`rebuild_index.py` が ocr_data から自動導出する。手で編集しない。

## 6. 検証

```bash
python3 normalize_ocr.py --check   # OCRソースの正規形チェック
python3 -m pytest tests/           # スキーマ・整合性テスト
python3 rebuild_index.py --dry-run # ビルド差分確認
```

CI: gh-pagesへのpush時に `.github/workflows/test.yml` が上記を実行する。

## 7. 値の正規語彙 (value canonical vocabulary)

フィールド名だけでなく**値**も以下の語彙に固定する。定義の正は `schema.py` の
`RARITY_ENUM` / `CATEGORY_ENUM` / `WEAPON_TYPE_ENUM` / `TARGET_ENUM` /
`ACTIVATION_ENUM` / `SP_TYPE_ENUM` / `TERRAIN_ENUM`。
エイリアス(下表の旧表記)は `normalize_ocr.py` が自動変換する。
どちらにも該当しない値は `normalize_ocr.py --check` / pytest / pre_deploy_check が
エラーにするため、**新規OCRデータの表記揺れはpush時にブロックされる**。

| フィールド | 正規値 | 自動変換されるエイリアス |
|---|---|---|
| rarity | C / U / R / M / P / PR / A / LX / LE | なし(SN/SECRET/PARALLEL/VE等は**エラー**。パラレル種別はall_cards_list側) |
| category (MS) | 近距離 / 遠距離 / 機動 | なし |
| category (PL) | 殲滅 / 制圧 / 防衛 | なし |
| weapon.*.type | 近距離 / 遠距離 / 防御 / ""(欄がー) | 射撃→遠距離, 格闘→近距離, 遠距離攻撃→遠距離, 近距離攻撃→近距離, 中距離射撃→遠距離, 近接格闘→近距離, 速距離→遠距離, ー/-/—→"" |
| target (ms_ability / special_attack / echoes_beat / united_sp / squad_sp) | 単体(敵) / 範囲(敵) / 貫通(敵) / 特殊(敵) / 全体(敵) / 単体(味方) / 範囲(味方) / 特殊(味方) / 自分 / 特殊(自分) / 特殊 / ""。複合は `/` 区切り(空白なし) | 全角（）→半角(), ／→/, 敵単体→単体(敵), 単体→単体(敵), 自身→自分, ー/—→"" |
| ms_ability.activation | 任意発動 / 出撃時発動 / 常時発動 / 自動発動 / "" | なし |
| sp_type | "" / ECHOES BEAT / ECHOES BEAT SP / SQUAD SP / UNITED SP | なし |
| terrain_compatibility.* | S / A / B / C / ""(項目なし) | なし |
| link_ability.condition | `デッキにN枚以上` / `デッキに<カテゴリ>がN枚以上` (旧レイアウトの長文も許容) | 機動力N枚→機動がN枚 等 |

- 武器スロット自体が存在しない(名前がー印字)場合は `null`(name:""やダッシュではなく)
- カードにMSアビリティがない(ー印字)場合は `ms_ability: null`

## 非canonicalな旧フィールド (使用禁止)

| 旧 | 正 |
|---|---|
| link_abilities | link_ability |
| ranged / melee (stats内) | ranged_attack / melee_attack |
| long_range_attack / short_range_attack | ranged_attack / melee_attack |
| terrain | terrain_compatibility |
| terrain.underwater | terrain_compatibility.water |
| ms_ability.timing / type | ms_ability.activation |
| pl_skill | pilot_skill |
| eb_level等のspecial_attack直下フラット配置 | special_attack.echoes_beat (ネスト) |
| echoes_beat_lv, power_eb | echoes_beat.level / .power |
| illust | illustrator |
| 属性/attribute/power(カード全体) | (存在しない。旧テンプレートの誤り) |
