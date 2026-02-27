"""軽量アクセスメトリクスモジュール（SQLiteベース）"""

import sqlite3
import os
import threading
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metrics.db')

_local = threading.local()


def _get_conn():
    """スレッドローカルな接続を返す（書き込みは都度commitで完結）"""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def init_db():
    """テーブル作成（IF NOT EXISTS）"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            response_time_ms REAL NOT NULL,
            remote_addr TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_requests_timestamp
        ON requests (timestamp)
    """)
    conn.commit()


def record_request(method, path, status_code, response_time_ms, remote_addr):
    """1行INSERT"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO requests (timestamp, method, path, status_code, response_time_ms, remote_addr) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            method,
            path,
            status_code,
            round(response_time_ms, 2),
            remote_addr or '',
        ),
    )
    conn.commit()


def get_summary(hours=24):
    """指定時間内の集計を返す"""
    conn = _get_conn()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # 総リクエスト数 / ユニークIP / 平均レスポンスタイム
    row = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT remote_addr) as unique_ips, "
        "AVG(response_time_ms) as avg_ms "
        "FROM requests WHERE timestamp >= ?",
        (since,),
    ).fetchone()

    total = row['total']
    unique_ips = row['unique_ips']
    avg_ms = round(row['avg_ms'], 1) if row['avg_ms'] else 0

    # エラー数（4xx/5xx）
    error_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM requests "
        "WHERE timestamp >= ? AND status_code >= 400",
        (since,),
    ).fetchone()
    error_count = error_row['cnt']

    # パス別アクセス数 TOP20
    path_rows = conn.execute(
        "SELECT path, COUNT(*) as cnt, AVG(response_time_ms) as avg_ms "
        "FROM requests WHERE timestamp >= ? "
        "GROUP BY path ORDER BY cnt DESC LIMIT 20",
        (since,),
    ).fetchall()
    top_paths = [
        {'path': r['path'], 'count': r['cnt'], 'avg_ms': round(r['avg_ms'], 1)}
        for r in path_rows
    ]

    # 時間帯別アクセス数
    hourly_rows = conn.execute(
        "SELECT substr(timestamp, 1, 13) as hour_key, COUNT(*) as cnt "
        "FROM requests WHERE timestamp >= ? "
        "GROUP BY hour_key ORDER BY hour_key",
        (since,),
    ).fetchall()
    hourly = [{'hour': r['hour_key'], 'count': r['cnt']} for r in hourly_rows]

    # ステータスコード別
    status_rows = conn.execute(
        "SELECT status_code, COUNT(*) as cnt "
        "FROM requests WHERE timestamp >= ? "
        "GROUP BY status_code ORDER BY status_code",
        (since,),
    ).fetchall()
    status_codes = {str(r['status_code']): r['cnt'] for r in status_rows}

    return {
        'total_requests': total,
        'unique_ips': unique_ips,
        'avg_response_ms': avg_ms,
        'error_count': error_count,
        'top_paths': top_paths,
        'hourly': hourly,
        'status_codes': status_codes,
        'hours': hours,
    }


def get_recent(limit=100):
    """直近リクエスト一覧"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT timestamp, method, path, status_code, response_time_ms, remote_addr "
        "FROM requests ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            'timestamp': r['timestamp'],
            'method': r['method'],
            'path': r['path'],
            'status_code': r['status_code'],
            'response_time_ms': r['response_time_ms'],
            'remote_addr': r['remote_addr'],
        }
        for r in rows
    ]


def cleanup(days=30):
    """古いデータ削除"""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM requests WHERE timestamp < ?", (cutoff,))
    conn.commit()
    return cur.rowcount
