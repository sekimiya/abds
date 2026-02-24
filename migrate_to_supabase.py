"""One-shot migration: decks.json -> Supabase tables (decks + comments).

Usage:
    1. Set SUPABASE_URL and SUPABASE_KEY environment variables
    2. python migrate_to_supabase.py
"""

import json
import os
import sys

from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print('Error: SUPABASE_URL and SUPABASE_KEY must be set')
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_KEY)

with open('decks.json', 'r', encoding='utf-8') as f:
    decks = json.load(f)

print(f'Found {len(decks)} decks to migrate')

for deck in decks:
    deck_row = {
        'id': deck['id'],
        'deck_name': deck['deck_name'],
        'comment': deck.get('comment', ''),
        'cards': deck['cards'],
        'tactics_main': deck.get('tactics_main'),
        'tactics_sub': deck.get('tactics_sub'),
        'likes': deck.get('likes', 0),
        'created_at': deck.get('timestamp'),
    }
    print(f"  Inserting deck: {deck['id']} ({deck['deck_name']})")
    client.table('decks').upsert(deck_row).execute()

    # Migrate embedded comments to separate table
    for comment in deck.get('comments', []):
        comment_row = {
            'id': comment['id'],
            'deck_id': deck['id'],
            'name': comment.get('name', 'アースノイド'),
            'text': comment['text'],
            'created_at': comment.get('timestamp'),
        }
        print(f"    Inserting comment: {comment['id']}")
        client.table('comments').upsert(comment_row).execute()

print('Migration complete!')
