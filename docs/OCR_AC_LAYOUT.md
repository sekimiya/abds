# アーセナルコマンダー(AC)カードのOCR仕様

ARSENAL COMMANDER 版デッキシミュレータ(`commander/`)のカードデータを、カード画像から作るための仕様。
ソースは `commander/ocr/<カード番号>.json`、アプリ用データは `scripts/build_commander_data.py` で
`commander/data/` に生成する(アーセナルベース側の `data/` とは完全に別系統)。

## 対象カード

公式ニュース「オープンβテスト カード一覧」(https://www.gundam-ac.com/news/002.php) の全45種。

- オープンβテスト払い出しカード TEST-001〜033(TEST-001〜003 はコマンダー)
- パラレル TEST-001〜003 の PARA(OCR不要。ベースからコピー)
- プロモーションパック Ver.NEXT PR-504〜509 とパラレル 504/506/508(同上)

**AB のロケテスト弾 TEST-001〜036 とは番号が同じでも別のカード**。混ぜないこと。

画像は `commander/images/` にある(公式のファイル名のまま、`TEST_004R_dummy.webp` と `TEST_004b_dummy.webp` のような形)。

## 券面の読み方

### 裏面(データはほぼこちら)

- 左上: `MOBILE SUIT` / `PILOT` と、その横の色表記 `RED` / `GREEN` / `BLUE` / `COLORLESS`(複数あり)
- 大見出し: `UNIT`(MS/PL) または `COMMANDER`
- 左上の箱: タイプ(遠距離/近距離/殲滅/制圧/防衛) と `コスト N`(コマンダーにはコストなし)
- 型式+英名(MS) / 英名(PL)、カード名
- 白い帯: 特徴。`SEED DESTINY/ザフト/コーディネイター` のように `/` 区切り
- `ATK` / `HP`(UNITのみ)
- MS: `MS ABILITY`(名前/コスト/発動条件/対象/範囲図形 + 説明)、`SPECIAL ATTACK`(名前/SPコスト/対象/威力/範囲図形 + 説明)
- PL: `PL SKILL`(名前/発動条件 + 説明)
- COMMANDER: `COMMANDER SKILL`(説明のみ)、`MS ABILITY`、`COMMANDER SYSTEM`(黒帯の名前 + 説明。「バトル中に1度だけ〜」の定型文は除く)
- 下部: illust、カード番号、レアリティ

### PR-504〜509(NEXT: 2ゲーム併記)

裏面の**上半分がAC**、下半分はアーセナルベース。AC側だけを読む。

- 色は `COLORLESS`(→ `colors: []`)
- 特徴は白い帯の `アーセナルベース`
- ATK/HP は `ARSENAL COMMANDER` ロゴの右の値(下段の機動力等ではない)
- MS ABILITY / SPECIAL ATTACK / PL SKILL は上半分のもの

## JSON形式

```json
{
  "card_number": "TEST-004",
  "card_name": "ブレイズザクファントム(レイ・ザ・バレル専用機)",
  "front_image": "TEST_004R_dummy.webp",
  "back_image": "TEST_004b_dummy.webp",
  "ocr_engine": "claude_code_subagent",
  "ocr_timestamp": "2026-09-24T00:00:00",
  "ocr_data": {
    "type": "MS",
    "name": "ブレイズザクファントム(レイ・ザ・バレル専用機)",
    "english_name": "REY'S BLAZE ZAKU PHANTOM",
    "model": "ZGMF-1001/M",
    "rarity": "R",
    "colors": ["赤"],
    "category": "遠距離",
    "cost": 3,
    "traits": ["SEED DESTINY", "ザフト"],
    "stats": {"atk": 270, "hp": 300},
    "ms_ability": {
      "name": "援護[防御]", "cost": null, "activation": "出撃時発動",
      "target": "コマンダー(味方)", "shape": "コマンダー",
      "description": "一定時間、味方コマンダーの被ダメージを軽減する。"
    },
    "special_attack": {
      "name": "ファイヤビー誘導ミサイル爆撃", "sp_cost": 2, "target": "範囲(敵)",
      "power": 2800, "shape": "円間接",
      "description": "対象の敵を中心として範囲攻撃を行う。"
    },
    "pilot_skill": null,
    "commander_skill": null,
    "commander_system": null,
    "illustrator": "Chifuyu Yukishiro"
  }
}
```

### フィールド規約

| フィールド | 規約 |
|---|---|
| type | `MS` / `PL` / `CMD`(大見出しが COMMANDER なら CMD) |
| colors | RED→`赤` GREEN→`緑` BLUE→`青`。印字順。COLORLESS は `[]` |
| cost | 整数。CMD は `null` |
| stats | `{"atk","hp"}`。CMD は `null` |
| traits | 白帯を `/` で分割した配列 |
| ms_ability.cost | 「コスト -」「ー」は `null` |
| shape | 範囲図形の横の短いラベル(円自身中心/扇/直線/円間接/単体 等)。無ければ `""` |
| pilot_skill | PLのみ `{"name","trigger","description"}` |
| commander_skill | CMDのみ `{"description"}` |
| commander_system | CMDのみ `{"name","description"}` |
| rarity | 右下の印字(C/R/M/P/CMD/PR 等) |

- 全角スラッシュ `／` は半角 `/` にする。括弧はカード名の印字どおり(全角/半角を混ぜない場合は半角 `()`)。
- 推測で埋めない。読めなければ `""` / `null`。
