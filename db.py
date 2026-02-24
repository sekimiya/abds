"""Supabase DB abstraction layer for decks and comments.

When SUPABASE_URL / SUPABASE_KEY env vars are set, uses Supabase PostgreSQL.
Otherwise falls back to local decks.json (for local development).
"""

import os
import json
import uuid
import time
import threading

# ---------------------------------------------------------------------------
# Supabase client (lazy singleton)
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

_client = None


def get_client():
    """Return supabase Client or None (JSON fallback mode)."""
    global _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def is_supabase():
    """True when Supabase is configured."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


# ---------------------------------------------------------------------------
# JSON fallback helpers (existing behaviour)
# ---------------------------------------------------------------------------

_DECKS_FILE = 'decks.json'
_decks_lock = threading.Lock()


def _read_json():
    if not os.path.exists(_DECKS_FILE):
        return []
    with open(_DECKS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []


def _write_json(decks):
    with open(_DECKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(decks, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Deck CRUD
# ---------------------------------------------------------------------------

def list_decks():
    """Return list of deck dicts (newest first)."""
    client = get_client()
    if client is None:
        with _decks_lock:
            return _read_json()
    resp = client.table('decks').select('*').order('created_at', desc=True).execute()
    return resp.data


def create_deck(data):
    """Create a new deck. Returns (deck_dict, error_string|None)."""
    deck_id = str(uuid.uuid4())[:8]
    client = get_client()
    if client is None:
        deck_entry = {
            'id': deck_id,
            'deck_name': data['deck_name'],
            'comment': data.get('comment', ''),
            'cards': data['cards'],
            'tactics_main': data.get('tactics_main'),
            'tactics_sub': data.get('tactics_sub'),
            'timestamp': data.get('timestamp') or time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        with _decks_lock:
            decks = _read_json()
            decks.append(deck_entry)
            _write_json(decks)
        return deck_entry, None

    row = {
        'id': deck_id,
        'deck_name': data['deck_name'],
        'comment': data.get('comment', ''),
        'cards': data['cards'],
        'tactics_main': data.get('tactics_main'),
        'tactics_sub': data.get('tactics_sub'),
    }
    resp = client.table('decks').insert(row).execute()
    return resp.data[0], None


def update_deck(deck_id, data):
    """Update an existing deck. Returns (success_bool, error_string|None)."""
    client = get_client()
    if client is None:
        with _decks_lock:
            decks = _read_json()
            found = False
            for deck in decks:
                if deck.get('id') == deck_id:
                    if 'deck_name' in data:
                        deck['deck_name'] = data['deck_name']
                    if 'cards' in data:
                        deck['cards'] = data['cards']
                    if 'comment' in data:
                        deck['comment'] = data['comment']
                    deck['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                    found = True
                    break
            if not found:
                return False, 'Deck not found'
            _write_json(decks)
        return True, None

    updates = {}
    if 'deck_name' in data:
        updates['deck_name'] = data['deck_name']
    if 'cards' in data:
        updates['cards'] = data['cards']
    if 'comment' in data:
        updates['comment'] = data['comment']
    if 'tactics_main' in data:
        updates['tactics_main'] = data['tactics_main']
    if 'tactics_sub' in data:
        updates['tactics_sub'] = data['tactics_sub']
    if not updates:
        return True, None
    resp = client.table('decks').update(updates).eq('id', deck_id).execute()
    if not resp.data:
        return False, 'Deck not found'
    return True, None


def delete_deck(deck_id):
    """Delete a deck. Returns (success_bool, error_string|None)."""
    client = get_client()
    if client is None:
        with _decks_lock:
            decks = _read_json()
            original_len = len(decks)
            decks = [d for d in decks if d.get('id') != deck_id]
            if len(decks) == original_len:
                return False, 'Deck not found'
            _write_json(decks)
        return True, None

    resp = client.table('decks').delete().eq('id', deck_id).execute()
    if not resp.data:
        return False, 'Deck not found'
    return True, None


def like_deck(deck_id):
    """Increment likes by 1. Returns (new_likes_count|None, error_string|None)."""
    client = get_client()
    if client is None:
        with _decks_lock:
            decks = _read_json()
            for deck in decks:
                if deck.get('id') == deck_id:
                    deck['likes'] = deck.get('likes', 0) + 1
                    _write_json(decks)
                    return deck['likes'], None
        return None, 'Deck not found'

    # Use RPC for atomic increment
    resp = client.rpc('increment_likes', {'deck_id_param': deck_id}).execute()
    if resp.data is not None and len(resp.data) > 0:
        return resp.data[0]['likes'], None
    # Fallback: read-modify-write
    row = client.table('decks').select('likes').eq('id', deck_id).execute()
    if not row.data:
        return None, 'Deck not found'
    new_likes = (row.data[0].get('likes') or 0) + 1
    client.table('decks').update({'likes': new_likes}).eq('id', deck_id).execute()
    return new_likes, None


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def get_comments(deck_id):
    """Return list of comments for a deck."""
    client = get_client()
    if client is None:
        with _decks_lock:
            decks = _read_json()
            for deck in decks:
                if deck.get('id') == deck_id:
                    return deck.get('comments', []), None
        return None, 'Deck not found'

    resp = (client.table('comments')
            .select('*')
            .eq('deck_id', deck_id)
            .order('created_at', desc=False)
            .execute())
    return resp.data, None


def post_comment(deck_id, name, text):
    """Post a comment. Returns (comment_dict, error_string|None)."""
    comment_id = str(uuid.uuid4())[:8]
    client = get_client()
    if client is None:
        with _decks_lock:
            decks = _read_json()
            for deck in decks:
                if deck.get('id') == deck_id:
                    if 'comments' not in deck:
                        deck['comments'] = []
                    entry = {
                        'id': comment_id,
                        'name': name[:20],
                        'text': text,
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    }
                    deck['comments'].append(entry)
                    _write_json(decks)
                    return entry, None
        return None, 'Deck not found'

    # Verify deck exists
    check = client.table('decks').select('id').eq('id', deck_id).execute()
    if not check.data:
        return None, 'Deck not found'
    row = {
        'id': comment_id,
        'deck_id': deck_id,
        'name': name[:20],
        'text': text,
    }
    resp = client.table('comments').insert(row).execute()
    return resp.data[0], None
