/**
 * fix_link_errors.js
 *
 * card_details.json と link_index.json のリンクアビリティOCRエラーを修正
 *
 * 修正内容:
 * 1. OCR誤読リンク名を正しい名前に修正 (card_details.json)
 * 2. 誤読リンク名のエントリを正しい名前に統合 (link_index.json)
 * 3. [SQ]X と X の重複を [SQ]X に統合 (対象カードに両方ある場合)
 * 4. 修正後に3リンク以上残るカードをレポート
 */

const fs = require('fs');

const details = JSON.parse(fs.readFileSync('data/card_details.json', 'utf8'));
const linkIndex = JSON.parse(fs.readFileSync('data/link_index.json', 'utf8'));

// === Step 1: OCR誤読マッピング ===
const errorMap = {
  '嚇爽たる援軍': '颯爽たる援軍',
  '的確な': '的確な一撃',
  '肉薄する影': '肉薄する戦い',
  '多彩な技術': '多彩な戦術',
  '多彩な戦略': '多彩な戦術',
  '状況を変える力': '戦況を変える力',
  '彼の居場所': '彼等の居場所',
  '徹底した防御': '徹底した防衛陣',
  '戦力を整える力': '戦況を変える力',
  '戦力を支える力': '戦況を変える力',
  '戦力を求めて': '戦況を変える力',
  '戦力を整える': '戦況を変える力',
};

// [SQ]X と X が同一カードにある場合、X を削除（[SQ]版に統合）
const sqPrefixes = ['[SQ]新シャッフル同盟', '[SQ]彼等の居場所', '[SQ]駆け抜ける嵐',
  '[SQ]運命に抗う意志', '[SQ]ダブルオーの声', '[SQ]戦士のかがやき',
  '[SQ]永遠への回帰', '[SQ]それぞれの秋', '[SQ]軌跡が紡いだ日々'];
const sqToNormal = {};
sqPrefixes.forEach(sq => { sqToNormal[sq] = sq.replace(/^\[SQ\]/, ''); });

let fixedCards = 0;
let fixedLinks = 0;
const stillBad = [];

// === Step 2: card_details.json を修正 ===
Object.keys(details).forEach(num => {
  const ocr = details[num]?.ocr_data || details[num];
  const links = ocr?.link_abilities;
  if (!Array.isArray(links) || links.length <= 2) return;

  let changed = false;

  // 2a. OCR誤読を修正
  links.forEach(link => {
    if (errorMap[link.name]) {
      link.name = errorMap[link.name];
      changed = true;
    }
  });

  // 2b. 完全重複を除去
  const seen = new Set();
  const deduped = [];
  links.forEach(link => {
    if (!seen.has(link.name)) {
      seen.add(link.name);
      deduped.push(link);
    }
  });

  // 2c. [SQ]X と X が両方ある場合、X を除去
  const linkNames = new Set(deduped.map(l => l.name));
  const toRemove = new Set();
  sqPrefixes.forEach(sq => {
    const normal = sqToNormal[sq];
    if (linkNames.has(sq) && linkNames.has(normal)) {
      toRemove.add(normal);
    }
  });
  const final = deduped.filter(l => !toRemove.has(l.name));

  if (final.length !== links.length) {
    changed = true;
  }

  if (changed) {
    if (details[num]?.ocr_data) {
      details[num].ocr_data.link_abilities = final;
    } else {
      details[num].link_abilities = final;
    }
    fixedCards++;
    fixedLinks += links.length - final.length;

    if (final.length > 2) {
      stillBad.push(num + ': ' + final.length + ' links -> ' + final.map(l => l.name).join(', '));
    }
  }
});

// === Step 3: link_index.json を修正 ===
// 誤読エントリのカードを正しいエントリに統合して削除
let mergedEntries = 0;
Object.entries(errorMap).forEach(([bad, good]) => {
  if (!linkIndex[bad] || !linkIndex[good]) return;
  const badInfo = linkIndex[bad];
  const goodInfo = linkIndex[good];

  // カードを統合（重複排除）
  const msSet = new Set([...(goodInfo.ms_cards || []), ...(badInfo.ms_cards || [])]);
  const plSet = new Set([...(goodInfo.pl_cards || []), ...(badInfo.pl_cards || [])]);
  goodInfo.ms_cards = [...msSet].sort();
  goodInfo.pl_cards = [...plSet].sort();

  delete linkIndex[bad];
  mergedEntries++;
});

// === Step 4: 結果出力 ===
console.log('=== Fix Results ===');
console.log('Fixed cards:', fixedCards);
console.log('Removed duplicate links:', fixedLinks);
console.log('Merged link_index entries:', mergedEntries);
console.log('Remaining link_index entries:', Object.keys(linkIndex).length);

if (stillBad.length > 0) {
  console.log('\nStill >2 links after fix:', stillBad.length);
  stillBad.forEach(s => console.log('  ' + s));
}

// === Step 5: 保存 ===
fs.writeFileSync('data/card_details.json', JSON.stringify(details, null, 2), 'utf8');
fs.writeFileSync('data/link_index.json', JSON.stringify(linkIndex, null, 2), 'utf8');
console.log('\nSaved card_details.json and link_index.json');
