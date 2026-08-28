# Discordバグ報告の取り込み設定

`scripts/fetch_discord_reports.py` がバグ報告チャンネルを読めるようにするための、
一度きりの設定手順。所要10分程度。

常駐botは立てない。実行したときだけREST APIで取りに行くポーリング方式なので、
サーバーもCIも不要。

---

## 1. アプリケーションとbotを作る

1. https://discord.com/developers/applications を開く
2. 右上 **New Application** → 名前は `ABDS Bug Collector` など → Create
3. 左メニュー **Bot** を開く
4. **Reset Token** を押してトークンを表示し、コピー
   - この画面を閉じると二度と見られない。無くしたらReset Tokenでやり直す
   - **トークンは絶対にDiscordやGitHubに貼らない**。漏れたら即Reset Token

## 2. Message Content Intent を有効にする（最重要）

左メニューの **Bot** を開き、ページを下にスクロールする。
「一般情報」のページには無いので注意。

```
  アイコン・ユーザー名
  トークン                      ← 手順1のリセットはここ
  認証フロー
  特権ゲートウェイ インテント      ← このセクション
   ├ プレゼンス インテント               (OFFのまま)
   ├ サーバーメンバー インテント          (OFFのまま)
   └ メッセージコンテンツ インテント   ← これを ON
  Botの権限
```

英語UIなら **Privileged Gateway Intents** の **MESSAGE CONTENT INTENT**。

ONにすると画面下に **「変更を保存」** バーが出る。**これを押さないと反映されない**。

これが無効だと、APIは成功するのに**本文と添付が全部空**で返ってくる。
100サーバー未満のbotなら申請不要で、トグルするだけで有効になる。

（スクリプトは全件の本文が空だった場合、この設定を疑うよう警告を出す）

## 3. botをサーバーに招待する

左メニュー **OAuth2** → **OAuth2 URL Generator**

- **SCOPES**: `bot`
- **BOT PERMISSIONS**: `View Channels` と `Read Message History`
  - 後で報告者へ返信までやるなら `Send Messages` も追加する

生成されたURLをブラウザで開き、対象サーバーを選んで認証する。
（サーバー側で「サーバーを管理」権限が必要）

URLを手で組むならこちら。`<APP_ID>` は General Information の Application ID。

```
# 読み取りのみ (View Channels + Read Message History)
https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&scope=bot&permissions=66560

# 返信もする場合 (+ Send Messages)
https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&scope=bot&permissions=68608
```

招待後、バグ報告チャンネルがプライベートなら、
チャンネル個別の権限設定にもbot（またはbotのロール）を追加すること。

## 4. チャンネルIDを取得する

Discordアプリ側の操作。

1. 設定（歯車） → **詳細設定** → **開発者モード** を ON
2. バグ報告チャンネルを右クリック → **チャンネルIDをコピー**

18〜19桁の数字。**サーバーIDではなくチャンネルID**なので注意。

## 5. .env に書く

リポジトリ直下の `.env`（`.gitignore` 済み）に追記する。

```
DISCORD_BOT_TOKEN=ここにトークン
DISCORD_BUG_CHANNEL_ID=ここにチャンネルID
```

## 6. 動作確認

```bash
# 保存せず、取得できるかだけ見る
python3 scripts/fetch_discord_reports.py --dry-run

# 問題なければ取得して reports/inbox/ に保存
python3 scripts/fetch_discord_reports.py

# 取得済みの一覧
python3 scripts/fetch_discord_reports.py --list
```

---

## つまずいたら

| 症状 | 原因と対処 |
|---|---|
| `401` | トークンが違う。Reset Tokenして`.env`を更新 |
| `403` | botがチャンネルを見られない。チャンネル権限にbotを追加 |
| `404` | チャンネルIDが違う。サーバーIDを入れていないか確認 |
| 取得できるが本文が全部空 | **手順2のMessage Content Intentが未設定** |
| 新着なしと出る | `reports/state.json` に取得位置が残っている。`--reset` で取り直す |

## 報告テンプレート（任意だが効果大）

チャンネルにこれをピン留めしておくと、後段の特定コストが大幅に下がる。

```
【カード名 or カード番号】
【画面】検索 / デッキ構築 / デッキ画像照合 / その他
【何が起きた】
【どうなるはず】
【スクショ】あれば添付
```

---

## 保存されるもの

すべて `reports/` 配下で、`.gitignore` 対象。

| パス | 内容 |
|---|---|
| `reports/inbox/{message_id}.json` | 報告本文・タイムスタンプ・匿名ID |
| `reports/attachments/{message_id}/` | 添付画像の実体（DiscordのCDN URLは期限切れするため保存する） |
| `reports/state.json` | 最終取得メッセージID |

リポジトリがPUBLICなので、公開issueに載せるのは匿名ID（`R-XXXXXX`）だけ。
Discordのハンドルはローカルの `reports/inbox/` にのみ残し、返信の宛先引き当てに使う。

報告本文は不特定多数が書いた入力なので、issueへ転記するときは必ず引用ブロックに入れ、
指示として解釈しないこと。
