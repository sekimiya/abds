# NEXTレイアウト(2ゲーム併記裏面)のOCR仕様

BP09 (BOOSTER PACK [4.5th Anniversary NEXT Selection]) から、カード裏面が
**ARSENAL COMMANDER(新ルール) + ARSENAL BASE(既存ゲーム)の併記レイアウト**に変わった。
従来レイアウト(BP08以前)と読み取り位置が違うため、この弾以降は本書に従って抽出する。

出力スキーマ自体は従来どおり `docs/JSON_TEMPLATES.md` の canonical 形式。

## 裏面の構造

```
┌─────────────────────────────────────────┐
│ MOBILE SUIT / PILOT  UNIT   ◇◇◇ COLORLESS │ ← 属性は新ルール専用
│ [カテゴリ] [コスト N]                       │ ← ARSENAL BASE と共通の値
│ 型式名 / カード名                            │
│ 「アーセナルベース」帯                        │ ← 新ルールのトレイト。所属ではない
│ ARSENAL COMMANDER   ATK ___  HP ___        │ ← 新ルール専用の数値
│ MS ABILITY  名前│コスト│発動条件│対象│範囲図形  │ ← 図形以外は ARSENAL BASE と共通
│   説明文                                    │
│ SPECIAL ATTACK 名前│SPコスト│対象│威力│範囲図形│ ← 図形以外は ARSENAL BASE と共通
│   説明文                                    │
│ (PLカードは MS ABILITY/SPECIAL ATTACK の代わりに PL SKILL 名前│発動条件│説明)│
├─────────────────────────────────────────┤
│ ARSENAL BASE   地上 _ 宇宙 _ 砂漠 _ 水中 _   │ ← ここから下が既存ゲーム
│ WEAPON MAIN/SUB 名前│射程│種別   LINK ABILITY │
│ 機動力/遠距離攻撃/近距離攻撃/HP                │
│ MS ABILITY     射程 _                       │ ← 射程だけが再掲される
│ SPECIAL ATTACK 射程 _                       │
│ illust ___  / カード番号 / レアリティ           │
└─────────────────────────────────────────┘
```

## フィールド対応表

| canonicalフィールド | 取得位置 |
|---|---|
| type | 最上段 `MOBILE SUIT UNIT`→MS / `PILOT UNIT`→PL |
| name | 上段のカード名(日本語) |
| model (MS) | カード名の上の型式名(英字)。`RX-78NT-1 GUNDAM NT-1` のように全体を採る |
| english_name (PL) | カード名の上の英字名 |
| cost | 上段左の `コスト N`。**ARSENAL BASE のコストと同じ値**(公式検索で確認済み) |
| category | 上段左のカテゴリ(MS: 近距離/遠距離/機動、PL: 殲滅/制圧/防衛) |
| rarity | 右下の1〜2文字(C/U/R/M/P など)。`NEXT` `NEXT SECRET` 等のバナーはレアリティではない |
| illustrator | 左下 `illust ___`。表記が無ければ `""` |
| stats | 下段 ARSENAL BASE ブロックの 機動力/遠距離攻撃/近距離攻撃/HP。**上段の ATK/HP ではない** |
| terrain_compatibility | 下段 ARSENAL BASE ブロックの 地上/宇宙/砂漠/水中 |
| weapon.main/sub | 下段 WEAPON 欄(名前・射程・種別) |
| link_ability | 下段 LINK ABILITY 欄 |
| ms_ability.name / .cost / .activation / .target / .description | **上段** MS ABILITY 欄 |
| ms_ability.range | **下段** MS ABILITY 欄の `射程`(ダッシュ印字なら null) |
| special_attack.name / .sp_cost / .target / .power / .description | **上段** SPECIAL ATTACK 欄 |
| special_attack.range | **下段** SPECIAL ATTACK 欄の `射程` |
| pilot_skill.name / .trigger / .effect | 上段 PL SKILL 欄(名前 / 発動条件 / 説明文) |

## 印字が無くなった項目 → 必ず空値

新レイアウトでは以下が**カードに印字されない**。推測で埋めず、次の値を入れる。

| フィールド | 入れる値 |
|---|---|
| affiliation (所属) | `""` |
| pilot (MS の搭乗者) | `""` |
| physical.height / physical.age (PL) | `""` |
| units (PL の搭乗機) | `[]` |

頭頂高・本体重量・IMPACT AREA 図も廃止されたが、これらは元々 canonical スキーマに無い。

## 取ってはいけない新ルール専用パラメータ

既存ゲーム(ARSENAL BASE)には存在しないので、`ocr_data` に入れない。

- 属性 `COLORLESS` などの上部中央の表記
- `ARSENAL COMMANDER` 行の **ATK / HP**(下段の遠距離攻撃/HPと数値が一致することが多いが別物)
- MS ABILITY / SPECIAL ATTACK の右端の**範囲図形**(`円自身中心` `扇` `直線` `単体遠距離` `自身` など)と、その右の図形アイコン
- カード名の下の「アーセナルベース」帯(トレイト表記であって所属ではない)
- `NEXT` ロゴ、`NEXT SECRET` / `NEXT ALT SECRET` / `NEXT PARALLEL` バナー

## LINK ABILITY 欄の黄色い作戦タグ

`LINK ABILITY` の見出し左に黄色い「作戦」タグが付くリンク(BP09なら `僕たちのGAB`)は、
既存の `[AB]俺たちのトライエイジ` 等と同じABリンク。タグ画像は完全に同一。
ただし公式検索のリンク名一覧では `[AB]` プレフィックスが付かないので、公式表記からは判別できない。

- OCR側: タグ文字を `name` にも `effect` にも入れない。`is_ab_link` は既存データの慣例どおり `false` のまま。
- 派生フラグ: `rebuild_index.py` の `AB_LINK_NAMES` にリンク名を追加して `has_ab_link` を立てる。
- 効果が2行に分かれている場合(`専用作戦カードが使用可能` + `[HP]中アップ`)は
  半角スペースでつないで1つの `effect` にする(BP06-020 と同じ表記)。

## 判断に迷ったとき

- ダッシュ(`ー`)印字はすべて「値なし」。武器スロットごと無い場合は `weapon.sub: null`、
  MSアビリティが無い場合は `ms_ability: null`、射程のダッシュは `range: null`。
- 上段と下段で同じ項目(例: HP)の数値が食い違う場合、**既存ゲームのデータは必ず下段**を採る。
- 上段の MS ABILITY 説明文に「ロックオン」「追撃ゲージ」など新ルール用語が出てくることがあるが、
  説明文はカード印字のまま丸ごと入れる(要約・書き換えをしない)。

## 抽出後の機械照合

`scripts/fetch_official_facets.py` で公式検索のファセットを収集し、
`scripts/verify_against_official.py` でOCR結果と突き合わせる。
cost / rarity / category / 地形4軸 / 武器種別 / MSアビリティ名・コスト・発動条件・対象 /
戦術技コスト・対象 / リンク名・効果 / 4ステータス / 戦術技威力 が公式値で検証できる。

```bash
python3 scripts/fetch_official_facets.py --series 529309 --prefix BP09 -o series_data/facets_BP09.json
python3 scripts/verify_against_official.py series_data/facets_BP09.json
```
