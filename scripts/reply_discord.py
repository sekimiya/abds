#!/usr/bin/env python3
"""
マージ済みPRに対応するDiscordの元報告へ、対応完了の返信を出す。

送信は外向きの操作なので、既定は下書き表示のみ。実際に送るには --send が要る。

使い方:
  python scripts/reply_discord.py --pending           # 返信待ちの一覧
  python scripts/reply_discord.py --pr 5              # 下書きを表示(送らない)
  python scripts/reply_discord.py --pr 5 --send       # 実際に送信する

仕組み:
  PR本文の "Fixes #N" から issue番号を取り、reports/inbox/ の中で
  issue_number が一致する報告を探して、その元メッセージへの返信として投稿する。
  送信済みは reports/inbox/*.json の replied_at に記録して二重送信を防ぐ。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, '.env')
INBOX_DIR = os.path.join(ROOT, 'reports', 'inbox')

API = 'https://discord.com/api/v10'
USER_AGENT = 'ABDSBugCollector (https://github.com/sekimiya/abds, 1.0)'
REPO = 'sekimiya/abds'


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


def gh_json(args):
    r = subprocess.run(['gh'] + args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'エラー: gh {" ".join(args)}\n{r.stderr}', file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


def load_reports():
    out = []
    if not os.path.isdir(INBOX_DIR):
        return out
    for f in sorted(os.listdir(INBOX_DIR)):
        p = os.path.join(INBOX_DIR, f)
        r = json.load(open(p, encoding='utf-8'))
        r['_path'] = p
        out.append(r)
    return out


def linked_issues(pr):
    """PR本文の Fixes/Closes/Refs #N から issue番号を拾う"""
    body = pr.get('body') or ''
    return sorted({int(n) for n in
                   re.findall(r'(?:Fixes|Closes|Resolves|Refs)\s+#(\d+)', body, re.I)})


def build_message(pr, issue_nums):
    """報告者向けの返信文。開発者向けの言い回しは避ける。"""
    lines = [
        'ご報告ありがとうございました。修正して反映しました。',
        '',
        f'  {pr["title"]}',
        f'  {pr["url"]}',
    ]
    if issue_nums:
        lines.append('  経緯: ' + ' '.join(
            f'https://github.com/{REPO}/issues/{n}' for n in issue_nums))
    lines += [
        '',
        'アプリを再読み込みすると反映されます。',
        'もし直っていないようでしたら、お手数ですがこのスレッドで教えてください。',
    ]
    return '\n'.join(lines)


def post_reply(token, channel_id, message_id, content):
    payload = json.dumps({
        'content': content,
        'message_reference': {
            'message_id': message_id,
            'channel_id': channel_id,
            'fail_if_not_exists': False,
        },
        # 返信先の人に通知が飛ぶ。報告への直接の回答なので既定でオン。
        'allowed_mentions': {'replied_user': True, 'parse': []},
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
            hint = {403: 'botに「メッセージを送る」権限がありません。',
                    404: 'チャンネルまたはメッセージが見つかりません。'}.get(e.code, '')
            print(f'エラー: Discord API {e.code} {hint}\n  {body[:200]}',
                  file=sys.stderr)
            return None
    return None


def cmd_pending():
    reports = load_reports()
    prs = gh_json(['pr', 'list', '--state', 'merged', '--limit', '50',
                   '--json', 'number,title,url,body'])
    rows = []
    for pr in prs:
        for issue in linked_issues(pr):
            for r in reports:
                if r.get('issue_number') == issue and not r.get('replied_at'):
                    rows.append((pr['number'], issue, r))
    if not rows:
        print('返信待ちはありません。')
        return
    print(f'返信待ち {len(rows)}件\n')
    for prn, issue, r in rows:
        body = ' '.join((r.get('content') or '').split())
        print(f"  PR #{prn} / issue #{issue} -> {r['reporter_ref']} "
              f"#{r['channel_name']} ({r['timestamp'][:10]})")
        print(f"      {body[:70]}")
    print('\n下書きを見る: python3 scripts/reply_discord.py --pr <番号>')


def main():
    ap = argparse.ArgumentParser(description='マージ済みPRの報告者へDiscordで返信する')
    ap.add_argument('--pr', type=int, help='対象のPR番号')
    ap.add_argument('--pending', action='store_true', help='返信待ちの一覧を表示')
    ap.add_argument('--send', action='store_true',
                    help='実際に送信する(指定しない限り下書き表示のみ)')
    args = ap.parse_args()

    if args.pending or not args.pr:
        cmd_pending()
        return

    pr = gh_json(['pr', 'view', str(args.pr), '--json',
                  'number,title,url,body,state'])
    if pr['state'] != 'MERGED':
        print(f"PR #{pr['number']} はまだマージされていません (state={pr['state']})。"
              ' 返信は保留します。', file=sys.stderr)
        sys.exit(1)

    issues = linked_issues(pr)
    reports = load_reports()
    targets = [r for r in reports
               if r.get('issue_number') in issues and not r.get('replied_at')]

    if not targets:
        print(f"PR #{pr['number']} に紐づく未返信の報告はありません。"
              f" (linked issues: {issues or 'なし'})")
        return

    content = build_message(pr, issues)
    print('=' * 60)
    print(content)
    print('=' * 60)
    print(f'\n送信先 {len(targets)}件:')
    for r in targets:
        print(f"  #{r['channel_name']}  {r['reporter_ref']}  "
              f"{r['timestamp'][:10]}  (msg {r['message_id']})")

    if not args.send:
        print('\n下書きのみ表示しました。送信するには --send を付けてください。')
        return

    token = load_token()
    for r in targets:
        res = post_reply(token, r['channel_id'], r['message_id'], content)
        if not res:
            print(f"  送信失敗: {r['message_id']}")
            continue
        r.pop('_path', None)
        path = os.path.join(INBOX_DIR, f"{r['message_id']}.json")
        rec = json.load(open(path, encoding='utf-8'))
        rec['replied_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        rec['reply_message_id'] = res.get('id')
        json.dump(rec, open(path, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f"  送信しました: {r['reporter_ref']} #{r['channel_name']}")


if __name__ == '__main__':
    main()
