# Arsenal Commander Deck Simulator

アーセナルベースのデッキシミュレータ（親プロジェクト `abds`）を参考に、
アーセナルコマンダー向けに再構築したデッキシミュレータです。

## 主な違い（アーセナルベースとの比較）

| 項目 | アーセナルベース | アーセナルコマンダー |
|------|----------------|-------------------|
| デッキ構成 | MS 5 + PL 5 + 作戦 2 | MS 5 + PL 5 + **コマンダー 1** |
| 作戦カード | あり | **廃止** |
| コマンダーカード | なし（艦長スキルのみ） | **あり、色を持つ** |
| ユニットの色 | なし | **あり** |
| バフ条件 | リンク能力など | **コマンダー色とユニット色が一致** |
| バフ数値 | 明確 | **現状は有無のみ表示** |

## ディレクトリ構成

```
arsenal_commander/
├── app.py                  # Flask アプリ
├── data/
│   └── card_index.json     # カード索引（サンプルデータ）
├── logic/
│   ├── constants.py        # ルール定数
│   ├── deck_validation.py  # デッキ検証
│   ├── deck_code.py        # デッキコード
│   ├── color_buff.py       # 色マッチングによるバフ判定
│   └── stats.py            # ステータス集計
├── templates/
│   └── index.html          # シミュレータ UI
├── static/
│   └── style.css           # スタイル
├── tests/
│   └── test_deck.py        # ロジックテスト
└── README.md
```

## 起動方法

```bash
cd arsenal_commander
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

ブラウザで http://localhost:5002 を開きます。

## テスト

```bash
cd arsenal_commander
pytest tests/
```

## データ拡張

`data/card_index.json` にカードを追加してください。必須フィールドは以下の通りです。

```json
{
  "number": "AC01-001",
  "name": "ガンダム",
  "type": "MS",
  "color": ["赤", "青"],
  "cost": 4,
  "rarity": "M",
  "category": "近距離",
  "atk": 370,
  "hp": 380,
  "series": "AC01",
  "front_url": "...",
  "back_url": "",
  "search_text": "..."
}
```

- `type`: `"MS"`, `"PL"`, `"CMD"` のいずれか
- `color`: 配列。`"赤"`, `"青"`, `"緑"` の組み合わせ。**空配列または未指定は無色**として扱われ、バフはかかりません
- `pilot`: PL カードの場合は重複禁止のチェックに使用

### アーセナルベースカードの扱い

アーセナルコマンダーではアーセナルベースのカードも使用可能です。その場合:

- `color` を空配列 `[]` または省略してください（無色）
- アーセナルコマンダーに存在しないパラメータは省略するか `null` にしてください。UI では非表示になります
- `category` や `cost`/`atk`/`hp` がない場合、該当部分は表示されません

## デッキコード形式

```
<slot0>,<slot1>,...,<slot9>|cmd=<cmd_number>|name=<deck_name>
```

空スロットは空文字、カード番号は `,` で区切ります。
