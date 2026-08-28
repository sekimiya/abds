"""Arsenal Commander deck simulator Flask app.

参考: 親プロジェクトのアーセナルベース実装 (app.py) を簡素化し、
コマンダーカードの「色」によるバフマッチングに対応したもの。
"""

import json
import os
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CARD_INDEX_PATH = os.path.join(DATA_DIR, "card_index.json")

# 起動時にメモリへ読み込むカード索引
card_index = []
card_by_number = {}


def load_card_index():
    """JSON 索引を読み込む。"""
    global card_index, card_by_number
    if not os.path.exists(CARD_INDEX_PATH):
        card_index = []
        card_by_number = {}
        return
    with open(CARD_INDEX_PATH, "r", encoding="utf-8") as f:
        card_index = json.load(f)
    card_by_number = {c["number"]: c for c in card_index}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/card_index")
def api_card_index():
    return jsonify(card_index)


@app.route("/api/card/<number>")
def api_card(number):
    card = card_by_number.get(number)
    if not card:
        return jsonify({"error": "not found"}), 404
    return jsonify(card)


@app.route("/api/cards/batch", methods=["POST"])
def api_cards_batch():
    numbers = request.get_json(force=True) or []
    return jsonify([card_by_number.get(n) for n in numbers if n in card_by_number])


@app.route("/api/decks/validate", methods=["POST"])
def api_validate_deck():
    from logic.deck_validation import validate_deck

    payload = request.get_json(force=True) or {}
    deck = payload.get("deck", [])
    cmd = payload.get("cmd")
    result = validate_deck(deck, cmd, card_by_number)
    return jsonify(result)


@app.route("/api/decks/stats", methods=["POST"])
def api_deck_stats():
    from logic.stats import compute_deck_stats

    payload = request.get_json(force=True) or {}
    deck = payload.get("deck", [])
    cmd = payload.get("cmd")
    return jsonify(compute_deck_stats(deck, cmd, card_by_number))


@app.route("/api/decks/encode", methods=["POST"])
def api_encode_deck():
    from logic.deck_code import encode_deck

    payload = request.get_json(force=True) or {}
    return jsonify({"code": encode_deck(payload.get("deck", []), payload.get("cmd"), payload.get("name", ""))})


@app.route("/api/decks/decode", methods=["POST"])
def api_decode_deck():
    from logic.deck_code import decode_deck

    payload = request.get_json(force=True) or {}
    return jsonify(decode_deck(payload.get("code", "")))


def main():
    load_card_index()
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=True)


# gunicorn などでインポートされた場合のため
load_card_index()

if __name__ == "__main__":
    main()
