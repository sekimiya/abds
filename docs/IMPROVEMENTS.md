# ABDS 改善作業ログ

**ブランチ**: `improve/security-and-maintainability`  
**実施日**: 2026-03-09

---

## 実施した改善

### 1. onclick 内の JavaScript 文字列エスケープ（セキュリティ・バグ修正）

**問題**: デッキ名に `'` や `\` が含まれると、`onclick="DeckManager._loadByName('${escapeHtml(d.name)}')"` で JS が壊れる。
- `escapeHtml` は HTML 用のエスケープであり、JS 文字列用ではない
- 例: デッキ名 `O'Brien` → 構文エラー

**対応**:
- `escapeJsForAttr(str)` 関数を追加（`\` → `\\`, `'` → `\'` 等）
- `DeckManager._loadByName` / `_deleteByName` の onclick で `escapeJsForAttr(d.name)` を使用
- 対象: index.html, mobile.html

---

### 2. Toast の innerHTML 使用による XSS 対策

**問題**: `Toast.show(msg)` で `msg.includes('<')` のとき `innerHTML` を使用。ユーザー入力が入ると XSS の危険。

**対応**:
- 常に `textContent` を使用するよう変更
- HTML 表示が必要な場合は別途検討（現状は安全優先）

**対象**: index.html, mobile.html

---

### 3. showCardModal / _toggleBm のカード番号エスケープ

**問題**: `showCardModal('${cardNumber}')` でカード番号をそのまま渡している箇所あり。
- カード番号は通常 `AB01-001` 形式で制御文字は想定しにくいが、一貫性のためエスケープを適用

**対応**:
- カード番号を渡す onclick でも `escapeJsForAttr` を適用（念のため）
- showCardModal, SearchPanel._toggleBm の全呼び出し箇所を修正
- 対象: index.html, mobile.html の該当箇所

---

## 未実施（今後の検討事項）

- index.html と mobile.html の共通化・モジュール分割
- link_ability / link_abilities のデータ統一
- fix_reocr.py の JSON フォーマット維持ロジック見直し
- Supabase キーの環境変数化
- ユニットテストの追加

---

## 変更ファイル一覧

- index.html
- mobile.html
- IMPROVEMENTS.md（本ファイル）
