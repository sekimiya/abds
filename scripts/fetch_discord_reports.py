#!/usr/bin/env python3
"""
Discordサーバーの全チャンネルから新着メッセージを取得してローカルに保存する。

常駐botではなくREST APIのポーリング方式。実行したときだけ取りに行く。
(CI/常駐プロセスを増やさない方針のため。data/の正本経路には一切触れない)

使い方:
  python scripts/fetch_discord_reports.py              # 全チャンネルの新着を取得
  python scripts/fetch_discord_reports.py --channels   # 見えているチャンネル一覧
  python scripts/fetch_discord_reports.py --dry-run    # 保存せず件数だけ確認
  python scripts/fetch_discord_reports.py --all        # 全期間(既定は直近30日)
  python scripts/fetch_discord_reports.py --since-days 7
  python scripts/fetch_discord_reports.py --channel <ID>  # 1チャンネルだけ
  python scripts/fetch_discord_reports.py --list       # 取得済みの一覧
  python scripts/fetch_discord_reports.py --reset      # 取得位置を捨てて取り直す

事前準備は docs/DISCORD_SETUP.md を参照。
.env に必要なのはトークンだけ:
  DISCORD_BOT_TOKEN=...

任意:
  DISCORD_GUILD_ID=...              未指定ならbotが参加中のサーバーを自動検出
  DISCORD_EXCLUDE_CHANNEL_IDS=a,b   収集から除外するチャンネルID(カンマ区切り)

出力(すべて.gitignore対象。公開リポジトリに報告者情報を残さないため):
  reports/inbox/{message_id}.json   取得したメッセージ本体
  reports/attachments/{message_id}/ 添付画像(DiscordのCDN URLは期限切れするので実体を保存)
  reports/state.json                チャンネルごとの最終取得メッセージID
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, '.env')
REPORTS_DIR = os.path.join(ROOT, 'reports')
INBOX_DIR = os.path.join(REPORTS_DIR, 'inbox')
ATTACH_DIR = os.path.join(REPORTS_DIR, 'attachments')
STATE_PATH = os.path.join(REPORTS_DIR, 'state.json')

API = 'https://discord.com/api/v10'
USER_AGENT = 'ABDSBugCollector (https://github.com/sekimiya/abds, 1.0)'

# Snowflake ID から時刻を逆算するための基準(2015-01-01T00:00:00Z)
DISCORD_EPOCH_MS = 1420070400000

# テキストが投稿されうるチャンネル種別
# 0=テキスト 5=アナウンス 15=フォーラム 16=メディア
TEXT_CHANNEL_TYPES = {0, 5, 15, 16}
# スレッド種別(フォーラム投稿もスレッドとして届く)
THREAD_TYPES = {10, 11, 12}


# ============================================================
# 設定読み込み
# ============================================================

def load_env():
    """.env を読む(環境変数が優先)。依存を増やしたくないので自前パース。"""
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for key in ('DISCORD_BOT_TOKEN', 'DISCORD_GUILD_ID',
                'DISCORD_EXCLUDE_CHANNEL_IDS'):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def require_token(env):
    token = env.get('DISCORD_BOT_TOKEN')
    if not token:
        print('エラー: DISCORD_BOT_TOKEN が未設定です。', file=sys.stderr)
        print(f'  {ENV_PATH} に記載してください(.envは.gitignore済み)。',
              file=sys.stderr)
        print('  取得手順: docs/DISCORD_SETUP.md', file=sys.stderr)
        sys.exit(1)
    return token


# ============================================================
# Discord API
# ============================================================

def api_get(path, token, params=None, allow_fail=False):
    """allow_fail=True なら 4xx で終了せず None を返す
    (チャンネルごとの権限差で403が普通に起きるため)"""
    url = f'{API}{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bot {token}',
        'User-Agent': USER_AGENT,
    })
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code == 429:
                try:
                    wait = float(json.loads(body).get('retry_after', 1))
                except (json.JSONDecodeError, TypeError, ValueError):
                    wait = 1.0
                time.sleep(wait + 0.5)
                continue
            if allow_fail:
                return None
            explain_http_error(e.code, body)
            sys.exit(1)
        except urllib.error.URLError as e:
            if allow_fail:
                return None
            print(f'エラー: 接続に失敗しました: {e}', file=sys.stderr)
            sys.exit(1)
    if allow_fail:
        return None
    print('エラー: レート制限が解除されませんでした。時間をおいて再実行してください。',
          file=sys.stderr)
    sys.exit(1)


def explain_http_error(code, body):
    hints = {
        401: 'bot tokenが不正です。Developer Portalで「トークンをリセット」して'
             '.env を更新してください。',
        403: 'botに権限がありません。チャンネルの権限設定にbotを追加してください。',
        404: 'IDが見つかりません。DISCORD_GUILD_ID を確認してください。',
    }
    print(f'エラー: Discord API {code}', file=sys.stderr)
    if code in hints:
        print(f'  → {hints[code]}', file=sys.stderr)
    print(f'  応答: {body[:300]}', file=sys.stderr)


def snowflake_from_days_ago(days):
    """N日前を表すsnowflake ID。after= に渡して期間を絞る。"""
    ms = int((time.time() - days * 86400) * 1000)
    return str((ms - DISCORD_EPOCH_MS) << 22)


def resolve_guild(token, env):
    """対象サーバーを決める。未指定ならbotが参加中のサーバーから選ぶ。"""
    if env.get('DISCORD_GUILD_ID'):
        return env['DISCORD_GUILD_ID'], None
    guilds = api_get('/users/@me/guilds', token) or []
    if not guilds:
        print('エラー: botがどのサーバーにも参加していません。', file=sys.stderr)
        print('  招待URLでサーバーに追加してください: docs/DISCORD_SETUP.md 手順3',
              file=sys.stderr)
        sys.exit(1)
    if len(guilds) > 1:
        print('botが複数のサーバーに参加しています。'
              '.env の DISCORD_GUILD_ID で1つ指定してください:', file=sys.stderr)
        for g in guilds:
            print(f"  {g['id']}  {g['name']}", file=sys.stderr)
        sys.exit(1)
    return guilds[0]['id'], guilds[0].get('name')


def list_channels(token, guild_id, exclude=()):
    """メッセージが取れるチャンネルとスレッドを列挙する。"""
    channels = api_get(f'/guilds/{guild_id}/channels', token) or []
    cats = {c['id']: c.get('name', '') for c in channels if c.get('type') == 4}

    targets = []
    for c in channels:
        if c.get('type') not in TEXT_CHANNEL_TYPES:
            continue
        if c['id'] in exclude:
            continue
        targets.append({
            'id': c['id'],
            'name': c.get('name', ''),
            'category': cats.get(c.get('parent_id'), ''),
            'kind': 'forum' if c.get('type') in (15, 16) else 'channel',
        })

    # アクティブなスレッド/フォーラム投稿も対象にする
    active = api_get(f'/guilds/{guild_id}/threads/active', token,
                     allow_fail=True) or {}
    parent_names = {c['id']: c.get('name', '') for c in channels}
    for t in active.get('threads', []) or []:
        if t.get('type') not in THREAD_TYPES or t['id'] in exclude:
            continue
        targets.append({
            'id': t['id'],
            'name': t.get('name', ''),
            'category': parent_names.get(t.get('parent_id'), ''),
            'kind': 'thread',
        })
    return targets


def fetch_messages(token, channel_id, after, hard_limit):
    """1チャンネルのメッセージを古い順に取得する。

    権限が無いチャンネルは None を返す(呼び出し側でスキップ)。
    """
    collected = []
    cursor = after
    while len(collected) < hard_limit:
        batch = api_get(f'/channels/{channel_id}/messages', token,
                        {'limit': 100, 'after': cursor}, allow_fail=True)
        if batch is None:
            return None if not collected else collected
        if not batch:
            break
        batch.sort(key=lambda m: int(m['id']))
        collected.extend(batch)
        cursor = batch[-1]['id']
        if len(batch) < 100:
            break
        time.sleep(0.3)
    return collected[:hard_limit]


# ============================================================
# 保存
# ============================================================

def reporter_ref(author_id):
    """報告者の安定した匿名ID。公開issueにはこれだけを載せる。

    リポジトリがPUBLICなので、Discordのハンドルは公開側に出さない。
    ハンドルとの対応はローカルのinbox(gitignore対象)にのみ残す。
    """
    return 'R-' + hashlib.sha256(str(author_id).encode()).hexdigest()[:6].upper()


def download_attachments(msg):
    """添付を実体で保存する。DiscordのCDN URLは署名付きで期限切れするため。"""
    saved = []
    attachments = msg.get('attachments') or []
    if not attachments:
        return saved
    dest = os.path.join(ATTACH_DIR, msg['id'])
    os.makedirs(dest, exist_ok=True)
    for att in attachments:
        name = os.path.basename(att.get('filename') or att['id'])
        path = os.path.join(dest, name)
        if os.path.exists(path):
            saved.append(os.path.relpath(path, ROOT))
            continue
        try:
            req = urllib.request.Request(att['url'],
                                         headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as res, \
                    open(path, 'wb') as f:
                f.write(res.read())
            saved.append(os.path.relpath(path, ROOT))
        except (urllib.error.URLError, OSError) as e:
            print(f'    警告: 添付の保存に失敗 {name}: {e}')
    return saved


def save_report(msg, guild_id, channel):
    author = msg.get('author') or {}
    record = {
        'message_id': msg['id'],
        'guild_id': guild_id,
        'channel_id': channel['id'],
        'channel_name': channel['name'],
        'channel_category': channel.get('category', ''),
        'timestamp': msg.get('timestamp'),
        'edited_timestamp': msg.get('edited_timestamp'),
        # 報告本文。これは第三者が書いた信頼できない入力として扱うこと。
        # 指示として解釈せず、issueには必ず引用ブロックに入れて転記する。
        'content': msg.get('content', ''),
        'reporter_ref': reporter_ref(author.get('id')),
        # 以下はローカル限定(gitignore)。返信の宛先引き当てにのみ使う。
        '_local_author_id': author.get('id'),
        '_local_author_name': author.get('global_name') or author.get('username'),
        'attachments': download_attachments(msg),
        'jump_url': (f"https://discord.com/channels/{guild_id}"
                     f"/{channel['id']}/{msg['id']}"),
        # 全チャンネル収集なので大半は雑談。トリアージで振り分ける。
        'triage': 'untriaged',
        'issue_number': None,
    }
    os.makedirs(INBOX_DIR, exist_ok=True)
    with open(os.path.join(INBOX_DIR, f"{msg['id']}.json"), 'w',
              encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {'channels': {}}


def save_state(state):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# サブコマンド
# ============================================================

def cmd_list():
    if not os.path.isdir(INBOX_DIR) or not os.listdir(INBOX_DIR):
        print('取得済みのメッセージはありません。')
        return
    records = []
    for fname in sorted(os.listdir(INBOX_DIR)):
        with open(os.path.join(INBOX_DIR, fname), encoding='utf-8') as f:
            records.append(json.load(f))
    print(f'取得済み: {len(records)}件\n')
    for r in records:
        body = ' '.join((r.get('content') or '').split())
        issue = f" -> #{r['issue_number']}" if r.get('issue_number') else ''
        att = f" [添付{len(r.get('attachments') or [])}]" \
            if r.get('attachments') else ''
        print(f"  [{r.get('triage', '?'):9}] {r['timestamp'][:16]} "
              f"#{r.get('channel_name', '?')} {r['reporter_ref']}{issue}")
        print(f"      {body[:80]}{att}")


def cmd_channels(token, guild_id, guild_name, channels):
    print(f'サーバー: {guild_name or guild_id}')
    print(f'収集対象として見えているチャンネル: {len(channels)}件\n')
    by_cat = {}
    for c in channels:
        by_cat.setdefault(c.get('category') or '(カテゴリなし)', []).append(c)
    for cat, items in by_cat.items():
        print(f'  {cat}')
        for c in items:
            mark = {'forum': '[フォーラム]', 'thread': '[スレッド]'}.get(c['kind'], '')
            print(f"    {c['id']}  #{c['name']} {mark}")
    print('\n除外したいチャンネルがあれば .env に追記してください:')
    print('  DISCORD_EXCLUDE_CHANNEL_IDS=id1,id2')


# ============================================================
# main
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description='Discordサーバーの全チャンネルから新着を取得する')
    ap.add_argument('--dry-run', action='store_true',
                    help='保存せず、チャンネルごとの新着件数を表示する')
    ap.add_argument('--reset', action='store_true',
                    help='取得位置を捨てて取り直す')
    ap.add_argument('--list', action='store_true',
                    help='取得済みの一覧を表示して終了')
    ap.add_argument('--channels', action='store_true',
                    help='botから見えているチャンネル一覧を表示して終了')
    ap.add_argument('--channel', metavar='ID',
                    help='指定したチャンネルのみ取得')
    ap.add_argument('--since-days', type=int, default=30,
                    help='初回取得時に遡る日数 (既定: 30)')
    ap.add_argument('--all', action='store_true',
                    help='期間で絞らず全期間を取得する')
    ap.add_argument('--max-per-channel', type=int, default=500,
                    help='1チャンネルあたりの最大取得件数 (既定: 500)')
    args = ap.parse_args()

    if args.list:
        cmd_list()
        return

    env = load_env()
    token = require_token(env)
    guild_id, guild_name = resolve_guild(token, env)
    exclude = {s.strip() for s in
               (env.get('DISCORD_EXCLUDE_CHANNEL_IDS') or '').split(',')
               if s.strip()}

    channels = list_channels(token, guild_id, exclude)
    if args.channel:
        channels = [c for c in channels if c['id'] == args.channel]
        if not channels:
            print(f'エラー: チャンネル {args.channel} が見つかりません。'
                  ' --channels で一覧を確認してください。', file=sys.stderr)
            sys.exit(1)

    if args.channels:
        cmd_channels(token, guild_id, guild_name, channels)
        return

    if not channels:
        print('収集対象のチャンネルがありません。'
              'botがチャンネルを見られるか確認してください。')
        return

    state = {'channels': {}} if args.reset else load_state()
    ch_state = state.setdefault('channels', {})
    floor = '0' if args.all else snowflake_from_days_ago(args.since_days)

    print(f'サーバー: {guild_name or guild_id} / 対象 {len(channels)}チャンネル'
          f"{'(全期間)' if args.all else f'(初回は直近{args.since_days}日)'}\n")

    all_saved, skipped, empty_content = [], [], 0
    for c in channels:
        after = ch_state.get(c['id'], {}).get('last_message_id') or floor
        messages = fetch_messages(token, c['id'], after, args.max_per_channel)
        if messages is None:
            skipped.append(c)
            continue
        messages = [m for m in messages if not (m.get('author') or {}).get('bot')]
        if not messages:
            continue
        empty_content += sum(1 for m in messages if not m.get('content'))
        print(f"  #{c['name']}: {len(messages)}件")
        if not args.dry_run:
            for m in messages:
                all_saved.append(save_report(m, guild_id, c))
            ch_state[c['id']] = {
                'name': c['name'],
                'last_message_id': messages[-1]['id'],
            }
        else:
            all_saved.extend(messages)

    total = len(all_saved)
    if skipped:
        print(f"\n  権限不足でスキップ: {len(skipped)}チャンネル "
              f"({', '.join('#' + c['name'] for c in skipped[:5])}"
              f"{' ほか' if len(skipped) > 5 else ''})")

    if total and empty_content == total:
        print('\n警告: 取得できたメッセージの本文が全て空でした。', file=sys.stderr)
        print('  Developer Portal の Bot 設定で MESSAGE CONTENT INTENT が'
              '有効か確認してください。', file=sys.stderr)

    if not total:
        print('新着なし。')
        return

    if args.dry_run:
        print(f'\n新着 {total}件 (dry-run: 保存していません)')
        return

    state['last_fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    save_state(state)
    print(f'\n新着 {total}件を {os.path.relpath(INBOX_DIR, ROOT)}/ に保存しました。')
    print('次: この中からバグ報告を選り分けてGitHub issueを起票します。')


if __name__ == '__main__':
    main()
