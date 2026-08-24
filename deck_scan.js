// ================================================================
// DeckScan - デッキ画像照合の解析コア
//
// デッキ画像(MS5枚 + PL5枚の 5x2 配置)から10枚を切り出し、
// 画像指紋で data/card_signatures.json と照合してカード番号を得る。
// OCRは使わない(カード名が意匠化されていて読めないため)。
//
// !! このファイルは索引生成(scripts/build_card_signatures.py)からも
//    読み込まれる。索引側と端末側で縮小のしかたが少しでも違うと
//    誤認識が増えるので、signature の計算は必ずここ一箇所に置くこと。
// ================================================================
(function (global) {
'use strict';

  // ===== デッキ画像スキャン (ブラウザ実装) =====
  const WORK_W = 900, CARD_AR = 600/875, HG = 8, CG = 4;

  function drawTo(img, w, h) {
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, 0, w, h);
    return ctx.getImageData(0, 0, w, h);
  }
  // 分離型ボックスぼかし2回 ≒ ガウス。ctx.filter に依存しない(古いiOS対策)
  function boxBlur(src, w, h, r) {
    const tmp = new Float32Array(w*h), out = new Float32Array(w*h);
    for (let y=0;y<h;y++){ let s=0;
      for (let x=-r;x<=r;x++) s += src[y*w + Math.min(w-1,Math.max(0,x))];
      for (let x=0;x<w;x++){ tmp[y*w+x] = s/(2*r+1);
        s += src[y*w+Math.min(w-1,x+r+1)] - src[y*w+Math.max(0,x-r)]; } }
    for (let x=0;x<w;x++){ let s=0;
      for (let y=-r;y<=r;y++) s += tmp[Math.min(h-1,Math.max(0,y))*w+x];
      for (let y=0;y<h;y++){ out[y*w+x] = s/(2*r+1);
        s += tmp[Math.min(h-1,y+r+1)*w+x] - tmp[Math.max(0,y-r)*w+x]; } }
    return out;
  }
  function runsOf(flags, minlen) {
    const out=[]; let s=null;
    for (let i=0;i<flags.length;i++){
      if (flags[i] && s===null) s=i;
      else if (!flags[i] && s!==null){ if (i-s>=minlen) out.push([s,i]); s=null; } }
    if (s!==null && flags.length-s>=minlen) out.push([s,flags.length]);
    return out;
  }
  function longestRun(flags){
    let best=[0,0,0], s=null;
    for (let i=0;i<flags.length;i++){
      if (flags[i] && s===null) s=i;
      else if (!flags[i] && s!==null){ if (i-s>best[0]) best=[i-s,s,i]; s=null; } }
    if (s!==null && flags.length-s>best[0]) best=[flags.length-s,s,flags.length];
    return [best[1],best[2]];
  }
  // プロファイルの区間平均を O(1) で引くための累積和
  function prefix(a){ const p=new Float64Array(a.length+1);
    for(let i=0;i<a.length;i++) p[i+1]=p[i]+a[i]; return p; }
  function mean(p, a, b){ a=Math.max(0,Math.round(a)); b=Math.min(p.length-1,Math.round(b));
    return b<=a ? 0 : (p[b]-p[a])/(b-a); }

  // 1軸ぶんの当てはめ: n等分した内部の仕切り線が低エネルギー、
  // ブロック内部が高エネルギー、外側が低エネルギーになる (start, span) を探す
  function fitAxis(pf, L, n, minCell) {
    // 候補は上位 K 件だけ保持する(全件を配列に積むとスマホで重い)
    const K = 24, top = [];
    const push = (sc, s, span) => {
      if (top.length === K && sc <= top[K-1][0]) return;
      let i = top.length;
      top.push([sc, s, span]);
      while (i > 0 && top[i-1][0] < sc) { top[i] = top[i-1]; i--; }
      top[i] = [sc, s, span];
      if (top.length > K) top.length = K;
    };
    // 900px 幅での 2px 刻みで十分(元画像に戻すと数px以下の誤差)
    const STEP = 2;
    for (let span = minCell*n; span <= L; span += STEP) {
      const cell = span/n, m = Math.max(2, Math.round(cell*0.18));
      for (let s = 0; s + span <= L; s += STEP) {
        const inside = mean(pf, s, s+span);
        let nOut = 0, o = 0;
        if (s > 0) { o += mean(pf, s-m, s); nOut++; }
        if (s+span < L) { o += mean(pf, s+span, s+span+m); nOut++; }
        const outside = nOut ? o/nOut : 0;
        let gaps = 0;
        for (let k=1;k<n;k++){ const gx = s + k*cell; gaps += mean(pf, gx-1, gx+2); }
        gaps = n>1 ? gaps/(n-1) : 0;
        push((inside - outside) - 0.8*gaps, s, span);
      }
    }
    return top;
  }

  // 余白が極端に大きいと当てはめが不安定になるので、まず内容の外接矩形へ粗く寄せる
  function coarseBox(img) {
    const w = 300, h = Math.max(1, Math.round(img.height*w/img.width));
    const d = drawTo(img, w, h).data;
    const g = new Float32Array(w*h);
    for (let i=0,p=0;i<g.length;i++,p+=4) g[i] = 0.299*d[p]+0.587*d[p+1]+0.114*d[p+2];
    const bl = boxBlur(boxBlur(g, w, h, 1), w, h, 1);
    const cf = new Float32Array(w), rf = new Float32Array(h);
    for (let y=0;y<h;y++) for (let x=0;x<w;x++){
      const e = Math.abs(g[y*w+x]-bl[y*w+x]); cf[x]+=e; rf[y]+=e; }
    let mc=0,mr=0;
    for(const v of cf) if(v>mc)mc=v;
    for(const v of rf) if(v>mr)mr=v;
    const [x0,x1] = longestRun(Array.from(cf, v=>v>mc*0.08));
    const [y0,y1] = longestRun(Array.from(rf, v=>v>mr*0.08));
    if (x1-x0 < 20 || y1-y0 < 20) return null;
    const sx = img.width/w, sy = img.height/h;
    const padX = (x1-x0)*0.06*sx, padY = (y1-y0)*0.06*sy;
    const bx = Math.max(0, Math.round(x0*sx-padX)), by = Math.max(0, Math.round(y0*sy-padY));
    return { x: bx, y: by,
             w: Math.min(img.width,  Math.round(x1*sx+padX)) - bx,
             h: Math.min(img.height, Math.round(y1*sy+padY)) - by };
  }

  function detectGrid(img, ncol=5, nrow=2) {
    // 粗い外接矩形が画像の8割未満なら、そこだけを見る
    const box = coarseBox(img);
    let ox = 0, oy = 0, src = img;
    if (box && (box.w*box.h) < img.width*img.height*0.8) {
      const cv = document.createElement('canvas');
      cv.width = box.w; cv.height = box.h;
      cv.getContext('2d').drawImage(img, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
      src = cv; ox = box.x; oy = box.y;
    }
    const scale = WORK_W / src.width;
    const W = WORK_W, H = Math.max(1, Math.round(src.height*scale));
    const id = drawTo(src, W, H), d = id.data;
    const g = new Float32Array(W*H);
    for (let i=0,p=0;i<g.length;i++,p+=4) g[i] = 0.299*d[p]+0.587*d[p+1]+0.114*d[p+2];
    const bl = boxBlur(boxBlur(g, W, H, 2), W, H, 2);
    const colf = new Float32Array(W), rowf = new Float32Array(H);
    for (let y=0;y<H;y++) for (let x=0;x<W;x++){
      const e = Math.abs(g[y*W+x]-bl[y*W+x]);
      if ((y & 1) === 0) colf[x] += e;
      if ((x & 1) === 0) rowf[y] += e;
    }
    let mc=0, mr=0;
    for (const v of colf) if (v>mc) mc=v;
    for (const v of rowf) if (v>mr) mr=v;
    if (mc<=0 || mr<=0) return null;
    const pc = prefix(Float64Array.from(colf, v=>v/mc));
    const pr = prefix(Float64Array.from(rowf, v=>v/mr));

    const cc = fitAxis(pc, W, ncol, 24);
    const rc = fitAxis(pr, H, nrow, 34);
    if (!cc.length || !rc.length) return null;

    // 縦横の候補を突き合わせ、カードのセル比(0.686前後)に近い組を選ぶ
    let best = null;
    for (const [cs, xL, cspan] of cc) {
      for (const [rs, yT, rspan] of rc) {
        const ar = (cspan/ncol)/(rspan/nrow);
        const err = Math.abs(ar - CARD_AR)/CARD_AR;
        if (err > 0.12) continue;                  // カード比から外れる組み合わせは捨てる
        const score = cs + rs - err*2;
        if (!best || score > best.score) best = { score, xL, cspan, yT, rspan, ar };
      }
    }
    if (!best) return null;
    const inv = 1/scale, cw = best.cspan/ncol, cols = [];
    for (let c=0;c<ncol;c++)
      cols.push([ox + Math.round((best.xL+c*cw)*inv), ox + Math.round((best.xL+(c+1)*cw)*inv)]);
    return { score: best.score, aspect: best.ar, cols,
             y0: oy + Math.round(best.yT*inv), y1: oy + Math.round((best.yT+best.rspan)*inv) };
  }
  // 索引側(600x875のカード画像)と照会側(任意サイズの切り出し)で
  // 縮小の元解像度が違うとエイリアスの出方が変わるため、必ず同じ中間解像度を経由する
  const MID_W = 120, MID_H = 175;
  function cellSignature(img, sx, sy, sw, sh) {
    // 外周6%はカード共通の枠なので除外
    const ix = sx + sw*0.06, iy = sy + sh*0.06, iw = sw*0.88, ih = sh*0.88;
    const mid = document.createElement('canvas');
    mid.width = MID_W; mid.height = MID_H;
    let ctx = mid.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, ix, iy, iw, ih, 0, 0, MID_W, MID_H);

    const cv = document.createElement('canvas');
    cv.width = HG+1; cv.height = HG;
    ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(mid, 0, 0, MID_W, MID_H, 0, 0, HG+1, HG);
    const gd = ctx.getImageData(0,0,HG+1,HG).data;
    const gray = [];
    for (let i=0,p=0;i<(HG+1)*HG;i++,p+=4) gray.push(0.299*gd[p]+0.587*gd[p+1]+0.114*gd[p+2]);
    const bits=[];
    for (let y=0;y<HG;y++) for (let x=0;x<HG;x++)
      bits.push(gray[y*(HG+1)+x] < gray[y*(HG+1)+x+1] ? 1 : 0);

    const cv2 = document.createElement('canvas');
    cv2.width = CG; cv2.height = CG;
    ctx = cv2.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(mid, 0, 0, MID_W, MID_H, 0, 0, CG, CG);
    const cd = ctx.getImageData(0,0,CG,CG).data;
    const col=[];
    for (let i=0,p=0;i<CG*CG;i++,p+=4){ col.push(cd[p],cd[p+1],cd[p+2]); }
    return { bits, col };
  }

  function prepareIndex(raw) {
    const nums=[], hi=new Int32Array(Object.keys(raw).length), lo=new Int32Array(Object.keys(raw).length);
    const cols=[];
    let i=0;
    for (const k in raw) {
      nums.push(k);
      const h = raw[k][0];
      hi[i] = parseInt(h.slice(0,8),16)|0; lo[i] = parseInt(h.slice(8),16)|0;
      cols.push(raw[k][1]); i++;
    }
    return { nums, hi, lo, cols };
  }
  function popcount(v){ v=v-((v>>1)&0x55555555); v=(v&0x33333333)+((v>>2)&0x33333333);
    return (((v+(v>>4))&0x0f0f0f0f)*0x01010101)>>24; }
  function matchOne(sig, idx, k=3) {
    let qh=0, ql=0;
    for (let i=0;i<32;i++) qh = (qh<<1)|sig.bits[i];
    for (let i=32;i<64;i++) ql = (ql<<1)|sig.bits[i];
    qh|=0; ql|=0;
    const res=[];
    for (let i=0;i<idx.nums.length;i++){
      const d = popcount(qh^idx.hi[i]) + popcount(ql^idx.lo[i]);
      const c = idx.cols[i];
      let s=0;
      for (let j=0;j<48;j++){ const t=sig.col[j]-c[j]; s+=t*t; }
      res.push([d*22 + Math.sqrt(s)*0.11, idx.nums[i]]);
    }
    res.sort((a,b)=>a[0]-b[0]);
    return res.slice(0,k);
  }
  function scanDeck(img, idx) {
    const g = detectGrid(img);
    if (!g) return null;
    const ch = (g.y1-g.y0)/2, out=[];
    for (let r=0;r<2;r++) for (let c=0;c<5;c++){
      const [x0,x1] = g.cols[c];
      const s = cellSignature(img, x0, g.y0+r*ch, x1-x0, ch);
      const m = matchOne(s, idx);
      out.push({ number: m[0][1], score: m[0][0], margin: m[1][0]-m[0][0], alts: m.map(a=>a[1]) });
    }
    return { grid: g, cards: out };
  }

global.DeckScan = {
  prepareIndex: prepareIndex,
  cellSignature: cellSignature,
  detectGrid: detectGrid,
  matchOne: matchOne,
  scanDeck: scanDeck,
  // 索引生成用: カード画像1枚から署名の16進表現を作る
  signatureHex: function (img) {
    const s = cellSignature(img, 0, 0, img.width, img.height);
    let hi = 0, lo = 0;
    for (let j = 0; j < 32; j++) hi = (hi << 1) | s.bits[j];
    for (let j = 32; j < 64; j++) lo = (lo << 1) | s.bits[j];
    return [((hi >>> 0).toString(16).padStart(8, '0')) +
            ((lo >>> 0).toString(16).padStart(8, '0')), s.col];
  }
};
})(window);
