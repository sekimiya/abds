# 修正候補リスト（データ整合性チェック結果）

チェック日: 2026-03-05
対象: card_index.json, card_details.json, link_index.json, tactics_cards.json

## 自動修正済み（11件）

| カードNO | カード名 | 修正内容 |
|----------|----------|----------|
| VE01-006 | ガンダムTR-1[ヘイズル改]高機動仕様（実戦配備カラー） | eb_level: null → 2 |
| VE01-008 | νガンダム | eb_level: null → 2 |
| VE01-008_p1 | νガンダム | eb_level: null → 2 |
| VE01-009 | サザビー | eb_level: null → 1 |
| VE01-009_p1 | サザビー | eb_level: null → 1 |
| VE01-013 | アリュゼウス | eb_level: null → 1 |
| VE01-013_p1 | アリュゼウス | eb_level: null → 1 |
| VE01-017 | ストライクフリーダムガンダム弐式 | eb_level: null → 1 |
| VE01-017_p1 | ストライクフリーダムガンダム弐式 | eb_level: null → 1 |
| VE01-019 | マイティーストライクフリーダムガンダム | eb_level: null → 1 |
| VE01-025 | ブラックナイトスコード カルラ | eb_level: null → 2 |

## 修正候補（要確認）

### 1. EB状態の矛盾（has_eb=False なのに eb_type=normal）

ゲーム上EBを持つが、OCR解析でEB SP情報が取得できなかったカードと推定。
has_ebをtrueにするか、eb_typeを空にするか要確認。

| カードNO | カード名 | 懸念理由 |
|----------|----------|----------|
| VE01-015 | フリーダムガンダム | has_eb=False, eb_type="normal", eb_level=null, eb_text="ECHOES BEAT"のみ。EB SPの詳細データなし |
| VE01-032 | ガンダムエクシアダークマター | has_eb=False, eb_type="normal", eb_level=null, eb_text="ECHOES BEAT"のみ。EB SPの詳細データなし |

### 2. VE01シリーズ PR版カード — EB情報欠落

VE01時代のカードだがPR版のため、echoes_beatオブジェクトが空。
VE01のMSカードは原則EBを持つため、データ追加が必要な可能性あり。

| カードNO | カード名 | 懸念理由 |
|----------|----------|----------|
| PR-427 | インフィニットジャスティスガンダム弐式 | VE01時代のMSカードだがechoes_beat={}（空）。EB情報が未入力 |
| PR-427_p1 | インフィニットジャスティスガンダム弐式 | 同上 |

### 3. VE01 MSカード — eb_trigger_level未設定（26枚）

eb_trigger_levelはPLカード専用フィールドのため、MSカードでnullは**正常**。
ただし、ゲーム仕様上MSカードにもEB発動条件レベルがある場合は追加が必要。

→ **現時点では問題なしと判断（PLカード専用フィールド）**

### 4. ARシリーズ — OCRデータなし（65枚）

AR01〜AR04の全MSカードにOCRデータが存在しない（新シリーズのため未処理）。

→ **既知の未処理。OCR実行時に解消予定**

## チェック結果サマリ（問題なし）

| チェック項目 | 結果 |
|-------------|------|
| link_index.json（142件） | required/effect/condition 全件あり。問題なし |
| tactics_cards.json（28件） | 全フィールド存在。問題なし |
| PLカードの terrain が空文字 | PLカードに地形適正はないため正常 |
| card_index.json の power フィールド | 全MSカードでnull（card_indexには含まれないフィールド。正常） |
| PR-001 スタッツ全0 | has_ocr=True だがスタッツが0。初期カードの仕様と推定 |
