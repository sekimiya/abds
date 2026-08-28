#!/usr/bin/env python3
"""
指定チャンネルへメッセージを投稿する(お知らせ用)。

外向きの送信なので既定は下書き表示のみ。--send を明示したときだけ送る。
ファイルは "---" だけの行で区切ると複数メッセージに分割して順に投稿する
(Discordの1メッセージ2000文字制限に対応)。

使い方:
  python scripts/post_discord.py --channel <ID> --file notes.md
  python scripts/post_discord.py --channel <ID> --file notes.md --send
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, '.env')
API = 'https://discord.com/api/v10'
USER_AGENT = 'ABDSBugCollector (https://github.com/sekimiya/abds, 1.0)'
LIMIT = 2000


def load_token():
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token and os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding='utf-8'):
            if line.startswith('DISCORD_BOT_TOKEN='):
                token = line.split('=', 1)[1].strip().strip('"\'')
                break
    if not token:
        print('エラー: DISCORD_BOT_TOKEN が未設定です。', file=sys.stderr)
        sys.exit(1)
    return token


def split_messages(text):
    parts = [p.strip('\n') for p in text.split('\n---\n')]
    return [p for p in parts if p.strip()]


def post(token, channel_id, content):
    payload = json.dumps({
        'content': content,
        # お知らせで不用意に全員へ通知しない
        'allowed_mentions': {'parse': []},
    }).encode('utf-8')
    req = urllib.request.Request(
        f'{API}/channels/{channel_id}/messages', data=payload, method='POST',
        headers={'Authorization': f'Bot {token}',
                 'Content-Type': 'application/json',
                 'User-Agent': USER_AGENT})
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code == 429:
                try:
                    wait = float(json.loads(body).get('retry_after', 1))
                except (json.JSONDecodeError, ValueError, TypeError):
                    wait = 1.0
                time.sleep(wait + 0.5)
                continue
            hint = {403: 'botがそのチャンネルに投稿できません。'
                         'チャンネルの権限設定にbotを追加してください。',
                    404: 'チャンネルIDが見つかりません。'}.get(e.code, '')
            print(f'エラー: Discord API {e.code} {hint}\n  {body[:200]}',
                  file=sys.stderr)
            return None
    return None


def main():
    ap = argparse.ArgumentParser(description='Discordチャンネルへ投稿する')
    ap.add_argument('--channel', required=True, help='投稿先チャンネルID')
    ap.add_argument('--file', required=True, help='本文ファイル("---"行で分割)')
    ap.add_argument('--send', action='store_true',
                    help='実際に送信する(指定しない限り下書き表示のみ)')
    args = ap.parse_args()

    text = open(args.file, encoding='utf-8').read()
    messages = split_messages(text)

    over = [i for i, m in enumerate(messages, 1) if len(m) > LIMIT]
    for i, m in enumerate(messages, 1):
        print(f'--- メッセージ {i}/{len(messages)} ({len(m)}文字) ---')
        print(m)
        print()
    if over:
        print(f'エラー: {LIMIT}文字を超えるメッセージがあります: {over}',
              file=sys.stderr)
        sys.exit(1)

    if not args.send:
        print('下書きのみ表示しました。送信するには --send を付けてください。')
        return

    token = load_token()
    for i, m in enumerate(messages, 1):
        res = post(token, args.channel, m)
        if not res:
            print(f'  メッセージ {i} の送信に失敗しました。中断します。',
                  file=sys.stderr)
            sys.exit(1)
        print(f'  送信しました {i}/{len(messages)} (id {res.get("id")})')
        time.sleep(0.5)


if __name__ == '__main__':
    main()
