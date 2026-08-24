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

  // ===== カード帯の位置特定 =====
  // ページ全体のスクリーンショット(ヘッダー・バナー・ブラウザUI込み)から、
  // 10枚のカードが並んだ矩形だけを先に切り出す。
  //
  // 総当たりで窓を滑らせるのではなく、構造で絞る:
  //   縦方向 … 「忙しい帯 / 平坦 / 忙しい帯」(= MS段・段間の隙間・PL段) を探す
  //             段間の隙間が潰れている画像では、1本の帯を半分に割る
  //   横方向 … その帯の中だけで列の profile を取り、幅の揃った5列を数える
  // 最後に候補を高解像度で採点して1つ選ぶ。
  const LOC_W = 600;

  function profileEnergy(img, W) {
    const H = Math.max(1, Math.round(img.height*W/img.width));
    const d = drawTo(img, W, H).data;
    const g = new Float32Array(W*H);
    for (let i=0,p=0;i<g.length;i++,p+=4) g[i] = 0.299*d[p]+0.587*d[p+1]+0.114*d[p+2];
    const bl = boxBlur(boxBlur(g, W, H, 2), W, H, 2);
    const e = new Float32Array(W*H);
    for (let i=0;i<e.length;i++) e[i] = Math.abs(g[i]-bl[i]);
    return { e, W, H };
  }
  // 指定した縦範囲だけで列プロファイルを取る(バナー等の影響を受けないようにするため)
  function colProfile(en, y0, y1) {
    const { e, W } = en;
    const out = new Float32Array(W);
    const a = Math.max(0, Math.round(y0)), b = Math.min(en.H, Math.round(y1));
    for (let y=a;y<b;y++) for (let x=0;x<W;x++) out[x] += e[y*W+x];
    const n = Math.max(1, b-a);
    let mx = 0;
    for (let x=0;x<W;x++){ out[x] /= n; if (out[x]>mx) mx = out[x]; }
    if (mx>0) for (let x=0;x<W;x++) out[x] /= mx;
    return out;
  }
  function rowProfile(en) {
    const { e, W, H } = en;
    const out = new Float32Array(H);
    for (let y=0;y<H;y++){ let s=0; for (let x=0;x<W;x++) s += e[y*W+x]; out[y] = s/W; }
    let mx = 0;
    for (const v of out) if (v>mx) mx = v;
    if (mx>0) for (let y=0;y<H;y++) out[y] /= mx;
    return out;
  }
  function bandsOf(prof, t, minLen) {
    const out = []; let s = null;
    for (let i=0;i<prof.length;i++){
      if (prof[i] > t && s === null) s = i;
      else if (prof[i] <= t && s !== null){ if (i-s >= minLen) out.push([s,i]); s = null; }
    }
    if (s !== null && prof.length-s >= minLen) out.push([s, prof.length]);
    return out;
  }
  // 幅がほぼ揃った n 本の帯になっているか
  function evenBands(bands, n, tol) {
    if (bands.length !== n) return false;
    const w = bands.map(b => b[1]-b[0]);
    const mn = Math.min(...w), mx = Math.max(...w);
    return mx > 0 && (mx-mn)/mx <= tol;
  }

  function locateBlock(img) {
    const en = profileEnergy(img, Math.min(LOC_W, img.width));
    const { W, H } = en;
    if (W < 60 || H < 30) return null;
    const rp = rowProfile(en);
    const cands = [];

    // カード間の隙間は縮小すると潰れて測れないので、内部の仕切りは当てにしない。
    // 帯の外端(パネル地との境目)だけを取り、5等分してカードの縦横比で検証する。
    const pushCand = (y0, y1) => {
      if (y1-y0 < 16) return;
      const cp = colProfile(en, y0, y1);
      const ch = (y1-y0)/2;
      const minLen = Math.max(3, Math.round(W/60));
      const seen = [];
      for (let ti=3; ti<45; ti+=2) {
        const cb = bandsOf(cp, ti/100, minLen);
        if (!cb.length) continue;
        // 幅の揃った5本が取れるならそれを使う。無理なら一番長い塊の外端を使う。
        let xL, xR;
        if (evenBands(cb, 5, 0.30)) { xL = cb[0][0]; xR = cb[4][1]; }
        else {
          let big = cb[0];
          for (const b of cb) if (b[1]-b[0] > big[1]-big[0]) big = b;
          xL = big[0]; xR = big[1];
        }
        // デッキ表示は画面幅の1/4は占める。小さな塊を拾わない
        if (xR-xL < W*0.25) continue;
        const ar = ((xR-xL)/5)/ch;
        if (Math.abs(ar - CARD_AR)/CARD_AR > 0.15) continue;
        if (seen.some(v => Math.abs(v[0]-xL)<3 && Math.abs(v[1]-xR)<3)) continue;
        seen.push([xL, xR]);
        cands.push({ xL, xR, y0, y1 });
      }
    };

    for (let ti=3; ti<50; ti+=2) {
      const rb = bandsOf(rp, ti/100, Math.max(3, Math.round(H/80)));
      if (!rb.length || rb.length > 40) continue;
      // 「高さの揃った2本の帯が細い隙間で隣り合う」= MS段とPL段
      for (let i=0;i+1<rb.length;i++){
        const a = rb[i], b = rb[i+1];
        const ha = a[1]-a[0], hb = b[1]-b[0], gap = b[0]-a[1];
        if (ha<8 || hb<8) continue;
        if (Math.abs(ha-hb)/Math.max(ha,hb) > 0.20) continue;
        if (gap > Math.max(ha,hb)*0.35) continue;
        pushCand(a[0], b[1]);
      }
      // 段間の隙間が潰れている場合は1本の帯を半分に割る
      for (const b of rb) pushCand(b[0], b[1]);
    }
    if (!cands.length) return null;

    // 同じ矩形を何度も拾うので間引く
    const uniq = [];
    for (const c of cands) {
      if (!uniq.some(u => Math.abs(u.xL-c.xL)<4 && Math.abs(u.xR-c.xR)<4 &&
                          Math.abs(u.y0-c.y0)<4 && Math.abs(u.y1-c.y1)<4)) uniq.push(c);
    }

    // 高解像度で採点して1つ選ぶ
    const sx = img.width/W, sy = img.height/H;
    let best = null;
    for (const c of uniq.slice(0, 40)) {
      const bx = c.xL*sx, by = c.y0*sy, bw = (c.xR-c.xL)*sx, bh = (c.y1-c.y0)*sy;
      // 大きく取れている候補を優先する(部分的に切り取った窓に落ち着かせない)
      const s = fineScore(img, bx, by, bw, bh) + 0.4*(bw/img.width);
      if (!best || s > best.s) best = { s, bx, by, bw, bh };
    }
    if (!best) return null;
    const padX = best.bw*0.04, padY = best.bh*0.04;
    const x = Math.max(0, Math.round(best.bx - padX));
    const y = Math.max(0, Math.round(best.by - padY));
    return {
      x, y,
      w: Math.min(img.width,  Math.round(best.bx + best.bw + padX)) - x,
      h: Math.min(img.height, Math.round(best.by + best.bh + padY)) - y
    };
  }

  // 候補を高解像度で採点する。カード間の隙間は元画像で十数pxしかなく、
  // 粗い解像度では潰れて測れないため、候補ごとに切り出し直して測る。
  const FINE_W = 300;
  function fineScore(img, bx, by, bw, bh) {
    const W = FINE_W, H = Math.max(8, Math.round(bh*W/bw));
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high';
    cx.drawImage(img, bx, by, bw, bh, 0, 0, W, H);
    const d = cx.getImageData(0, 0, W, H).data;
    const g = new Float32Array(W*H);
    for (let i=0,p=0;i<g.length;i++,p+=4) g[i] = 0.299*d[p]+0.587*d[p+1]+0.114*d[p+2];
    const bl = boxBlur(boxBlur(g, W, H, 2), W, H, 2);
    const e = new Float32Array(W*H);
    let mx = 0;
    for (let i=0;i<e.length;i++){ const v = Math.abs(g[i]-bl[i]); e[i]=v; if (v>mx) mx=v; }
    if (mx <= 0) return -Infinity;
    for (let i=0;i<e.length;i++) e[i] /= mx;
    const cw = W/5, ch = H/2;
    const colBand = (x0,x1) => {
      let s=0,n=0; const a=Math.max(0,Math.round(x0)), b=Math.min(W,Math.round(x1));
      for (let y=0;y<H;y++) for (let x=a;x<b;x++){ s+=e[y*W+x]; n++; }
      return n ? s/n : 0;
    };
    const rowBand = (y0,y1) => {
      let s=0,n=0; const a=Math.max(0,Math.round(y0)), b=Math.min(H,Math.round(y1));
      for (let y=a;y<b;y++) for (let x=0;x<W;x++){ s+=e[y*W+x]; n++; }
      return n ? s/n : 0;
    };
    let cell = 0;
    for (let c=0;c<5;c++) cell += colBand(c*cw+cw*0.2, (c+1)*cw-cw*0.2);
    cell /= 5;
    let gapV = 0;
    for (let k=1;k<5;k++) gapV += colBand(k*cw-2, k*cw+2);
    gapV /= 4;
    const gapH = rowBand(ch-2, ch+2);
    const E = 1e-6;
    // MS段とPL段の間には必ず隙間が入るので、これが最も効く手がかりになる
    return (cell-gapH)/(cell+gapH+E) + 0.5*(cell-gapV)/(cell+gapV+E) + 0.3*cell;
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

  // 切り出した領域の中で 5x2 の格子を精密に当てはめる
  function fitGridIn(img, box, ncol, nrow) {
    let ox = 0, oy = 0, src = img;
    if (box && (box.w*box.h) < img.width*img.height*0.8 && box.w > 8 && box.h > 8) {
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

  // 2つの経路で格子候補を作る。
  //   A: 従来どおり画像全体(粗い外接矩形)から当てはめる  … きれいなデッキ画像向き
  //   B: カード帯を特定してから当てはめる                … ページ全体のスクショ向き
  // どちらが正しいかは画像だけでは決めきれないので、両方返して
  // 実際の照合の確信度で選ぶ(scanDeck 側)。
  function detectGridCandidates(img, ncol=5, nrow=2) {
    const out = [];
    const a = fitGridIn(img, coarseBox(img), ncol, nrow);
    if (a) out.push(a);
    const lb = locateBlock(img);
    if (lb) {
      const b = fitGridIn(img, lb, ncol, nrow);
      // ほぼ同じ格子なら片方でよい
      if (b && !(a && Math.abs(a.cols[0][0]-b.cols[0][0]) < 3 &&
                      Math.abs(a.y0-b.y0) < 3 && Math.abs(a.y1-b.y1) < 3)) out.push(b);
    }
    return out;
  }
  function detectGrid(img, ncol=5, nrow=2) {
    const c = detectGridCandidates(img, ncol, nrow);
    return c.length ? c[0] : null;
  }

  // 索引側と照会側で必ず同じ値になるように、縮小はブラウザ任せにしない。
  // canvas の drawImage による縮小はブラウザごとにアルゴリズムが違い、
  // Chrome で作った索引が Safari では一致しなくなる(実測 dHash が最大25bitズレる)。
  // そこで等倍で切り出してから、自前のボックスフィルタで縮小する。
  const MID_W = 120, MID_H = 175;

  // 決定的な縮小(整数ブロック平均)。
  // 入力画素を1回だけ走査して出力ビンに足し込む。
  // ブラウザの drawImage による縮小と違い、どの環境でも同じ値になる。
  function boxDownsample(src, sw, sh, dw, dh, stride) {
    const st = stride || 4;
    const n = dw * dh;
    const acc = new Float64Array(n * 3), cnt = new Float64Array(n);
    for (let y = 0; y < sh; y++) {
      const dy = (y * dh / sh) | 0;
      const rowOff = dy * dw;
      for (let x = 0; x < sw; x++) {
        const o = (rowOff + ((x * dw / sw) | 0)) * 3;
        const p = (y * sw + x) * st;
        acc[o] += src[p]; acc[o + 1] += src[p + 1]; acc[o + 2] += src[p + 2];
        cnt[(rowOff + ((x * dw / sw) | 0))]++;
      }
    }
    const out = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const c = cnt[i] || 1, o = i * 3;
      out[o] = acc[o] / c; out[o + 1] = acc[o + 1] / c; out[o + 2] = acc[o + 2] / c;
    }
    return out;
  }

  function cellSignature(img, sx, sy, sw, sh) {
    // 外周6%はカード共通の枠なので除外
    let ix = Math.round(sx + sw*0.06), iy = Math.round(sy + sh*0.06);
    let iw = Math.round(sw*0.88), ih = Math.round(sh*0.88);
    const maxW = img.width || img.naturalWidth, maxH = img.height || img.naturalHeight;
    ix = Math.max(0, Math.min(ix, maxW-1)); iy = Math.max(0, Math.min(iy, maxH-1));
    iw = Math.max(1, Math.min(iw, maxW-ix)); ih = Math.max(1, Math.min(ih, maxH-iy));

    // 等倍で切り出す(拡大縮小しないのでブラウザ差が出ない)
    const cv = document.createElement('canvas');
    cv.width = iw; cv.height = ih;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, ix, iy, iw, ih, 0, 0, iw, ih);
    const raw = ctx.getImageData(0, 0, iw, ih).data;

    // ここから先は自前の縮小のみ(全ブラウザで同じ値になる)
    const mid = boxDownsample(raw, iw, ih, MID_W, MID_H, 4);
    const small = boxDownsample(mid, MID_W, MID_H, HG+1, HG, 3);
    const bits = [];
    for (let y=0; y<HG; y++) for (let x=0; x<HG; x++) {
      const a = (y*(HG+1)+x)*3, b = (y*(HG+1)+x+1)*3;
      const ga = 0.299*small[a]+0.587*small[a+1]+0.114*small[a+2];
      const gb = 0.299*small[b]+0.587*small[b+1]+0.114*small[b+2];
      bits.push(ga < gb ? 1 : 0);
    }
    const col4 = boxDownsample(mid, MID_W, MID_H, CG, CG, 3);
    const col = [];
    for (let i=0;i<CG*CG;i++) col.push(col4[i*3], col4[i*3+1], col4[i*3+2]);
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
  // accept を渡すと、それを満たすカードだけを候補にする。
  // (スロットの位置で MS / PL が決まっているので、属性で絞れる)
  function matchOne(sig, idx, k=3, accept) {
    let qh=0, ql=0;
    for (let i=0;i<32;i++) qh = (qh<<1)|sig.bits[i];
    for (let i=32;i<64;i++) ql = (ql<<1)|sig.bits[i];
    qh|=0; ql|=0;
    const res=[];
    for (let i=0;i<idx.nums.length;i++){
      const num = idx.nums[i];
      if (accept && !accept(num)) continue;
      const d = popcount(qh^idx.hi[i]) + popcount(ql^idx.lo[i]);
      const c = idx.cols[i];
      let s=0;
      for (let j=0;j<48;j++){ const t=sig.col[j]-c[j]; s+=t*t; }
      res.push([d*22 + Math.sqrt(s)*0.11, num]);
    }
    res.sort((a,b)=>a[0]-b[0]);
    return res.slice(0,k);
  }
  function readGrid(img, g, idx, accepts) {
    const ch = (g.y1-g.y0)/2, out = [];
    let conf = 0;
    let n = 0;
    for (let r=0;r<2;r++) for (let c=0;c<5;c++, n++){
      const [x0,x1] = g.cols[c];
      const s = cellSignature(img, x0, g.y0+r*ch, x1-x0, ch);
      const free = matchOne(s, idx, 3);            // 属性を絞らない場合の最良
      const acc = accepts && accepts[n];
      let m = free, constrained = false;
      if (acc && free.length && !acc(free[0][1])) {
        // 属性が合わない = 取り違え。その属性のカードに限って選び直す
        const alt = matchOne(s, idx, 3, acc);
        if (alt.length) { m = alt; constrained = true; }
      }
      if (!m.length) { out.push({ number: null, score: Infinity, margin: 0, alts: [] }); continue; }
      const margin = m.length > 1 ? m[1][0]-m[0][0] : 999;
      out.push({ number: m[0][1], score: m[0][0], margin,
                 alts: m.map(a=>a[1]),
                 constrained,                        // 属性で選び直したか
                 freeTop: free.length ? free[0][1] : null });
      conf += Math.min(margin, 200);   // 1枚の突出で全体が決まらないよう頭打ちにする
    }
    return { grid: g, cards: out, conf };
  }

  // opts.accepts … 10マスぶんの絞り込み関数の配列(省略可)
  function scanDeck(img, idx, opts) {
    const cands = detectGridCandidates(img);
    if (!cands.length) return null;
    const accepts = opts && opts.accepts;
    let best = null;
    for (const g of cands) {
      const r = readGrid(img, g, idx, accepts);
      if (!best || r.conf > best.conf) best = r;
    }
    return best;
  }

global.DeckScan = {
  prepareIndex: prepareIndex,
  cellSignature: cellSignature,
  detectGrid: detectGrid,
  locateBlock: locateBlock,
  matchOne: matchOne,
  scanDeck: scanDeck,
  // 索引生成用: カード画像1枚から署名の16進表現を作る
  signatureHex: function (img) {
    const s = cellSignature(img, 0, 0, img.width, img.height);
    let hi = 0, lo = 0;
    for (let j = 0; j < 32; j++) hi = (hi << 1) | s.bits[j];
    for (let j = 32; j < 64; j++) lo = (lo << 1) | s.bits[j];
    // 色は整数に丸める(小数のままだと索引が4倍に膨らむ。
    // ブラウザ間の誤差が0.3程度なので丸めても影響はない)
    return [((hi >>> 0).toString(16).padStart(8, '0')) +
            ((lo >>> 0).toString(16).padStart(8, '0')),
            s.col.map(v => Math.round(v))];
  }
};
})(window);
