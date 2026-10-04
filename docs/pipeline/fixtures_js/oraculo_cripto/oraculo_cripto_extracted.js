// Extraído de /opt/axonik/scanner/index.html el 2026-10-04T17:13:20Z por verificar_cripto.sh
// NO EDITAR A MANO.

// --- MAX_RAW_SCORE ---
const MAX_RAW_SCORE = {
  'ST-01': 110, 'ST-04': 85, 'ST-05': 75, 'ST-06': 75, 'ST-09': 80,
  'ST-11': 70, 'ST-15': 65, 'ST-16': 75,
  'SC-01': 65, 'SC-02': 80, 'SC-PB': 80,
};

// --- STRATEGY_META ---
const STRATEGY_META = {
  'ST-01': {name:'Pullback a Tendencia', group:'swing', holding:'1-5 días', maxHoldDays:5},
  'ST-04': {name:'MACD Triple Confluencia', group:'medio', holding:'1-4 sem', maxHoldDays:28},
  'ST-05': {name:'Gap Continuidad', group:'intraday', holding:'30m-4h', maxHoldDays:0},
  'ST-06': {name:'Rebote EMA200', group:'swing', holding:'1-4 sem', maxHoldDays:28},
  'ST-09': {name:'Swing 2D Momentum', group:'swing', holding:'2-3 días', maxHoldDays:3},
  'ST-11': {name:'Proximidad 52W High', group:'medio', holding:'1-4 sem', maxHoldDays:28},
  'ST-15': {name:'ADX Breakout', group:'medio', holding:'1-4 sem', maxHoldDays:28},
  'ST-16': {name:'Compresión en Tendencia', group:'swing', holding:'1-3 días', maxHoldDays:3},
  'SC-01': {name:'BTC Explosivo', group:'crypto', holding:'1-5 días', maxHoldDays:5},
  'SC-02': {name:'Altcoin Rotation', group:'crypto', holding:'1-5 días', maxHoldDays:5},
  'SC-PB': {name:'Pullback + Gate BTC', group:'crypto', holding:'2-7 días', maxHoldDays:7},
};

// --- emaArr ---
function emaArr(prices, period, allowPartial){
  const n = prices.length;
  if (n < period){
    if (!allowPartial || n < 2) return prices.map(()=>NaN);
    const seed = prices.reduce((a,b)=>a+b,0)/n;
    const out = new Array(n-1).fill(NaN);
    out.push(seed);
    return out;
  }
  const k = 2/(period+1);
  const seed = prices.slice(0,period).reduce((a,b)=>a+b,0)/period;
  const out = new Array(period-1).fill(NaN);
  out.push(seed);
  for (let i=period;i<n;i++){
    out.push(prices[i]*k + out[out.length-1]*(1-k));
  }
  return out;
}

// --- calcRSI ---
function calcRSI(closes, period){
  period = period||14;
  if (closes.length < period+2) return NaN;
  const deltas = [];
  for (let i=1;i<closes.length;i++) deltas.push(closes[i]-closes[i-1]);
  let avgG = deltas.slice(0,period).reduce((a,d)=>a+(d>0?d:0),0)/period;
  let avgL = deltas.slice(0,period).reduce((a,d)=>a+(d<0?-d:0),0)/period;
  for (let i=period;i<deltas.length;i++){
    const g = deltas[i]>0?deltas[i]:0, l = deltas[i]<0?-deltas[i]:0;
    avgG = (avgG*(period-1)+g)/period;
    avgL = (avgL*(period-1)+l)/period;
  }
  if (avgL===0) return 100;
  return 100-100/(1+avgG/avgL);
}

// --- calcMACD ---
function calcMACD(closes, fast, slow, signal){
  fast=fast||12; slow=slow||26; signal=signal||9;
  const ef = emaArr(closes, fast), es = emaArr(closes, slow);
  const macdLine = ef.map((f,i)=> (isNaN(f)||isNaN(es[i])) ? NaN : f-es[i]);
  const valid = macdLine.filter(v=>!isNaN(v));
  if (valid.length < signal+1) return [NaN,NaN,NaN,NaN];
  const sigArr = emaArr(valid, signal);
  const histo = [];
  for (let i=signal-1;i<valid.length;i++){
    if (!isNaN(sigArr[i])) histo.push(valid[i]-sigArr[i]);
  }
  if (histo.length<2) return [valid[valid.length-1], sigArr[sigArr.length-1], NaN, NaN];
  return [valid[valid.length-1], sigArr[sigArr.length-1], histo[histo.length-1], histo[histo.length-2]];
}

// --- calcATR ---
function calcATR(highs, lows, closes, period){
  period = period||14;
  if (closes.length < period+2) return NaN;
  const tr = [];
  for (let i=1;i<closes.length;i++){
    tr.push(Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1])));
  }
  let atr = tr.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for (let i=period;i<tr.length;i++){
    atr = (atr*(period-1)+tr[i])/period;
  }
  return atr;
}

// --- calcADX ---
function calcADX(highs, lows, closes, period){
  period = period||14;
  const n = highs.length;
  if (n < period*2) return {adx:NaN, diPlus:NaN, diMinus:NaN};
  const tr=[], plusDM=[], minusDM=[];
  for (let i=1;i<n;i++){
    const upMove = highs[i]-highs[i-1];
    const downMove = lows[i-1]-lows[i];
    plusDM.push(upMove>downMove && upMove>0 ? upMove : 0);
    minusDM.push(downMove>upMove && downMove>0 ? downMove : 0);
    tr.push(Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1])));
  }
  function wilder(arr){
    const out = [];
    let sum = arr.slice(0,period).reduce((a,b)=>a+b,0);
    out[period-1] = sum;
    for (let i=period;i<arr.length;i++){
      sum = sum - sum/period + arr[i];
      out[i] = sum;
    }
    return out;
  }
  const trS = wilder(tr), pS = wilder(plusDM), mS = wilder(minusDM);
  const diP=[], diM=[], dx=[];
  for (let i=period-1;i<tr.length;i++){
    if (trS[i]===undefined || trS[i]===0) continue;
    const p = 100*pS[i]/trS[i], m = 100*mS[i]/trS[i];
    diP.push(p); diM.push(m);
    dx.push(100*Math.abs(p-m)/((p+m)||1));
  }
  if (dx.length < period) return {adx:NaN, diPlus: diP[diP.length-1], diMinus: diM[diM.length-1]};
  let adx = dx.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for (let i=period;i<dx.length;i++) adx = (adx*(period-1)+dx[i])/period;
  return {adx, diPlus: diP[diP.length-1], diMinus: diM[diM.length-1]};
}

// --- calcRVOL ---
function calcRVOL(volumes){
  if (volumes.length < 21) return NaN;
  const last = volumes[volumes.length-1];
  const prev20 = volumes.slice(-21,-1);
  const avg = prev20.reduce((a,b)=>a+b,0)/prev20.length;
  return avg>0 ? last/avg : NaN;
}

// --- calcVWAP ---
function calcVWAP(candles){
  if (!candles.length) return NaN;
  const lastDate = new Date(candles[candles.length-1].t*1000).toISOString().slice(0,10);
  const session = candles.filter(c => new Date(c.t*1000).toISOString().slice(0,10) === lastDate);
  let pv=0, vol=0;
  for (const c of session){ const typ=(c.h+c.l+c.c)/3; pv+=typ*c.v; vol+=c.v; }
  return vol>0 ? pv/vol : NaN;
}

// --- calcCompression ---
function calcCompression(candles, n){
  n = n||6;
  if (candles.length < n) return NaN;
  const slice = candles.slice(-n);
  const high = Math.max(...slice.map(c=>c.h));
  const low = Math.min(...slice.map(c=>c.l));
  const mid = (high+low)/2;
  return mid>0 ? (high-low)/mid*100 : NaN;
}

// --- calcGapPct ---
function calcGapPct(candles){
  if (candles.length < 2) return NaN;
  const today = candles[candles.length-1], prev = candles[candles.length-2];
  return prev.c>0 ? (today.o-prev.c)/prev.c*100 : NaN;
}

// --- computeIndicators ---
function computeIndicators(candles, tf){
  if (!candles || candles.length < 5) return null;
  const closes = candles.map(c=>c.c), highs = candles.map(c=>c.h),
        lows = candles.map(c=>c.l), volumes = candles.map(c=>c.v);
  const price = closes[closes.length-1];
  const ema20 = emaArr(closes,20)[closes.length-1];
  const ema50 = emaArr(closes,50)[closes.length-1];
  const ema200 = emaArr(closes,200,true)[closes.length-1];
  const rsi = calcRSI(closes,14);
  const [macd, macdSignal, macdHist, macdHistPrev] = calcMACD(closes);
  const atr = calcATR(highs,lows,closes,14);
  const atrPct = (atr && price) ? atr/price*100 : NaN;
  const rvol = calcRVOL(volumes);
  const adxR = calcADX(highs,lows,closes,14);
  const compression = calcCompression(candles,6);
  const gapPct = tf==='1d' ? calcGapPct(candles) : NaN;
  const vwap = tf==='15m' ? calcVWAP(candles) : NaN;
  return {
    price, ema20, ema50, ema200, rsi, macd, macdSignal, macdHist, macdHistPrev,
    atr, atrPct, rvol, adx:adxR.adx, diPlus:adxR.diPlus, diMinus:adxR.diMinus,
    compression, gapPct, vwap, candles,
  };
}

// --- f ---
function f(text, tf, points){ return {text, tf, points}; }

// --- finalizeVerdict ---
function finalizeVerdict(score, hardNo, rvol1d, rvolMin){
  let verdict;
  if (hardNo || score < 55) verdict = 'NO';
  else if (score >= 70) verdict = 'OPERAR';
  else verdict = 'VIGILAR';
  if (verdict==='OPERAR' && !isNaN(rvol1d) && rvol1d < rvolMin) verdict = 'VIGILAR';
  return verdict;
}

// --- mkResult ---
function mkResult(id, score, factors, applicable, hardNo, rvol1d, rvolMin){
  if (!applicable) return {id, score:0, baseScore:0, factors, applicable, verdict:'N/A'};
  const maxRaw = MAX_RAW_SCORE[id];
  let normalized = maxRaw>0 ? Math.round(score/maxRaw*100) : 0;
  normalized = Math.max(0, Math.min(100, normalized));
  const verdict = finalizeVerdict(normalized, hardNo, rvol1d, rvolMin);
  return {id, score: normalized, baseScore: normalized, rawScore: score, maxRawScore: maxRaw,
          factors, applicable, verdict};
}

// --- mkNA ---
function mkNA(id, reason){
  return {id, score:0, baseScore:0, factors:[], applicable:false, verdict:'N/A', naReason: reason||'No aplica en este momento'};
}

// --- tickerHardNo ---
function tickerHardNo(mode, price, d, settings){
  if (mode==='NYSE' && price < settings.priceMin) return true;
  if (!isNaN(d.atrPct) && d.atrPct > settings.atrMax) return true;
  return false;
}

// --- evalST01 ---
function evalST01(ctx){
  const {ind,funda,hardNo,settings} = ctx;
  const d=ind['1d'], h=ind['1h'], m=ind['15m'];
  if (!d||!h||!m) return mkNA('ST-01');
  let score=0; const factors=[];
  if (d.ema20>d.ema50 && d.ema50>d.ema200){ score+=25; factors.push(f('EMA20>50>200 alineación alcista','1D',25)); }
  const pullback = (d.ema20) ? (d.price-d.ema20)/d.ema20*100 : NaN;
  if (!isNaN(pullback) && pullback>=-2 && pullback<=3){ score+=20; factors.push(f(`Pullback EMA20 ${pullback.toFixed(1)}%`,'1D',20)); }
  if (d.rsi>=40 && d.rsi<=55){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)} zona pullback`,'1D',15)); }
  if (d.macdHist>0 && d.macdHist>d.macdHistPrev){ score+=15; factors.push(f('MACD hist positivo creciente','1D',15)); }
  if (h.rsi>=40 && h.rsi<=60){ score+=5; factors.push(f(`RSI ${h.rsi.toFixed(0)} zona`,'1H',5)); }
  if (h.macdHist>0 && h.macdHist>h.macdHistPrev){ score+=5; factors.push(f('MACD girando alcista','1H',5)); }
  if (!isNaN(m.vwap) && m.price>m.vwap){ score+=5; factors.push(f('Precio > VWAP','15M',5)); }
  if (!isNaN(m.ema20) && m.price>m.ema20){ score+=5; factors.push(f('Precio > EMA20','15M',5)); }
  if (m.rvol>=1.5){ score+=10; factors.push(f(`RVOL ${m.rvol.toFixed(1)}x`,'15M',10)); }
  if (funda){
    if (funda.profit_margin!=null && funda.profit_margin>0.15){ score+=3; factors.push(f('Margen neto >15%','FUND',3)); }
    if (funda.revenue_growth!=null && funda.revenue_growth>0.10){ score+=2; factors.push(f('Rev growth >10%','FUND',2)); }
  }
  return mkResult('ST-01', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST05 ---
function evalST05(ctx){
  const {ind,hardNo,settings} = ctx;
  const d=ind['1d'], m=ind['15m'];
  if (!d||!m||isNaN(d.gapPct) || Math.abs(d.gapPct)<0.3) return mkNA('ST-05','Sin gap real hoy');
  let score=0; const factors=[];
  if (d.gapPct>=1.5){ score+=20; factors.push(f(`Gap alcista +${d.gapPct.toFixed(1)}%`,'1D',20)); }
  if (d.rvol>=2){ score+=15; factors.push(f(`RVOL 1D ${d.rvol.toFixed(1)}x`,'1D',15)); }
  if (!isNaN(m.vwap) && m.price>m.vwap){ score+=20; factors.push(f('Precio > VWAP post-gap','15M',20)); }
  if (m.rvol>=2.5){ score+=20; factors.push(f(`RVOL 15M ${m.rvol.toFixed(1)}x`,'15M',20)); }
  return mkResult('ST-05', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST06 ---
function evalST06(ctx){
  const {ind,hardNo,settings} = ctx;
  const d=ind['1d'], h=ind['1h'];
  if (!d||!h||isNaN(d.ema200)) return mkNA('ST-06');
  const dist = (d.price-d.ema200)/d.ema200*100;
  if (Math.abs(dist) > 2) return mkNA('ST-06','Precio lejos de EMA200');
  let score=25; const factors=[f(`Precio en zona EMA200 (${dist.toFixed(1)}%)`,'1D',25)];
  if (d.rsi>=35 && d.rsi<=50){ score+=20; factors.push(f(`RSI ${d.rsi.toFixed(0)} zona rebote`,'1D',20)); }
  if (d.price>d.ema200){ score+=15; factors.push(f('Precio > EMA200','1D',15)); }
  if (h.rvol>=1.5){ score+=15; factors.push(f(`RVOL 1H ${h.rvol.toFixed(1)}x`,'1H',15)); }
  return mkResult('ST-06', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST09 ---
function evalST09(ctx){
  const {ind,hardNo,settings} = ctx;
  const d=ind['1d'], h=ind['1h'], m=ind['15m'];
  if (!d||!h||!m||d.candles.length<22) return mkNA('ST-09');
  const vols = d.candles.map(c=>c.v);
  const prevVol = vols[vols.length-2];
  const prevAvg20 = vols.slice(-22,-2).reduce((a,b)=>a+b,0)/20;
  const rvolPrev = prevAvg20>0 ? prevVol/prevAvg20 : NaN;
  const prevC = d.candles[d.candles.length-2];
  const rangeClose = (prevC.h-prevC.l)>0 ? (prevC.c-prevC.l)/(prevC.h-prevC.l) : NaN;
  if (isNaN(rvolPrev) || rvolPrev < 1.3) return mkNA('ST-09','Sesión anterior sin RVOL alto');
  let score=0; const factors=[];
  if (rvolPrev>=1.8){ score+=20; factors.push(f(`RVOL sesión anterior ${rvolPrev.toFixed(1)}x`,'1D',20)); }
  if (!isNaN(rangeClose) && rangeClose>=0.8){ score+=15; factors.push(f(`Cierre en ${(rangeClose*100).toFixed(0)}% del rango`,'1D',15)); }
  if (d.rsi>=55 && d.rsi<=70){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)} momentum`,'1D',15)); }
  if (h.macdHist>0){ score+=15; factors.push(f('MACD 1H positivo','1H',15)); }
  if (!isNaN(m.vwap) && m.price>m.vwap){ score+=15; factors.push(f('Precio > VWAP sesión','15M',15)); }
  return mkResult('ST-09', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST11 ---
function evalST11(ctx){
  const {ind,funda,hardNo,settings} = ctx;
  const d=ind['1d'];
  if (!d||!funda||funda.fifty_two_week_high==null) return mkNA('ST-11','Sin fundamentales/52W high');
  const high = funda.fifty_two_week_high;
  const pct = (d.price-high)/high*100;
  if (pct < -15) return mkNA('ST-11','Lejos del 52W high');
  let score=0; const factors=[];
  if (pct >= -5){ score+=25; factors.push(f(`${pct.toFixed(1)}% del 52W high (<5%)`,'1D',25)); }
  else if (pct >= -10){ score+=15; factors.push(f(`${pct.toFixed(1)}% del 52W high (<10%)`,'1D',15)); }
  if (d.rsi < 75){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)} < 75`,'1D',15)); }
  if (funda.revenue_growth!=null && funda.revenue_growth>0.10){ score+=15; factors.push(f('Rev growth >10%','FUND',15)); }
  if (d.rvol>=1.5){ score+=15; factors.push(f(`RVOL ${d.rvol.toFixed(1)}x`,'1D',15)); }
  return mkResult('ST-11', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST15 ---
function evalST15(ctx){
  const {ind,hardNo,settings} = ctx;
  const d=ind['1d'];
  if (!d||isNaN(d.adx) || d.adx<15 || d.adx>40) return mkNA('ST-15','ADX fuera de rango de inicio de tendencia');
  let score=0; const factors=[];
  if (d.adx>=20 && d.adx<=35 && d.diPlus>d.diMinus){ score+=25; factors.push(f(`ADX ${d.adx.toFixed(0)} DI+>DI-`,'1D',25)); }
  if (d.rvol>=1.8){ score+=15; factors.push(f(`RVOL ${d.rvol.toFixed(1)}x`,'1D',15)); }
  if (d.price>d.ema20){ score+=15; factors.push(f('Precio > EMA20','1D',15)); }
  if (d.rsi>=55 && d.rsi<=70){ score+=10; factors.push(f(`RSI ${d.rsi.toFixed(0)}`,'1D',10)); }
  return mkResult('ST-15', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalST16 ---
function evalST16(ctx){
  const {ind,hardNo,settings} = ctx;
  const d=ind['1d'], h=ind['1h'], m=ind['15m'];
  if (!d||!h||!m||isNaN(h.compression) || h.compression>3) return mkNA('ST-16','Sin compresión real');
  let score=0; const factors=[];
  if (d.ema20>d.ema50){ score+=20; factors.push(f('Tendencia EMA20>50','1D',20)); }
  if (h.compression<=2){ score+=20; factors.push(f(`Compresión ${h.compression.toFixed(1)}% (6 velas)`,'1H',20)); }
  if (m.rvol>=2){ score+=20; factors.push(f(`RVOL ruptura ${m.rvol.toFixed(1)}x`,'15M',20)); }
  if (!isNaN(m.ema200) && m.price>m.ema200){ score+=15; factors.push(f('Precio > EMA200','15M',15)); }
  return mkResult('ST-16', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalSC01 ---
function evalSC01(ctx){
  const {ind,hardNo,settings,ticker} = ctx;
  if (ticker!=='BTC' && ticker!=='ETH') return mkNA('SC-01','Solo BTC/ETH');
  const d=ind['1d'], m=ind['15m'];
  if (!d) return mkNA('SC-01');
  let score=0; const factors=[];
  const squeezeResolved = !isNaN(d.compression) && d.compression<=6 && d.rvol>=2.5;
  if (squeezeResolved){ score+=20; factors.push(f(`Squeeze resuelto, RVOL ${d.rvol.toFixed(1)}x`,'1D',20)); }
  if (d.rsi>=55 && d.rsi<=70){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)}`,'1D',15)); }
  if (d.macdHist>0){ score+=15; factors.push(f('MACD positivo','1D',15)); }
  if (m && !isNaN(m.vwap) && m.price>m.vwap){ score+=15; factors.push(f('Precio > VWAP','15M',15)); }
  return mkResult('SC-01', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalSC02 ---
function evalSC02(ctx){
  const {ind,hardNo,settings,ticker,btcGateOn} = ctx;
  if (ticker==='BTC' || ticker==='ETH') return mkNA('SC-02','Solo altcoins');
  if (!btcGateOn) return mkNA('SC-02','Gate BTC OFF');
  const d=ind['1d'], h=ind['1h'];
  if (!d||!h) return mkNA('SC-02');
  let score=0; const factors=[];
  if (d.price>d.ema50){ score+=20; factors.push(f('Precio > EMA50','1D',20)); }
  if (d.ema20>d.ema50){ score+=15; factors.push(f('EMA20 > EMA50','1D',15)); }
  if (d.rsi<60){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)} < 60`,'1D',15)); }
  if (d.rvol>=1.5){ score+=15; factors.push(f(`RVOL ${d.rvol.toFixed(1)}x`,'1D',15)); }
  if (h.macdHist>0){ score+=15; factors.push(f('MACD 1H positivo','1H',15)); }
  return mkResult('SC-02', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- evalSCPB ---
function evalSCPB(ctx){
  const {ind,hardNo,settings,btcGateOn} = ctx;
  if (!btcGateOn) return mkNA('SC-PB','Gate BTC OFF');
  const d=ind['1d'], h=ind['1h'], m=ind['15m'];
  if (!d||!h||!m) return mkNA('SC-PB');
  let score=0; const factors=[];
  if (d.ema20>d.ema50 && d.ema50>d.ema200){ score+=25; factors.push(f('EMA 20>50>200','1D',25)); }
  const pullback = d.ema20 ? (d.price-d.ema20)/d.ema20*100 : NaN;
  if (!isNaN(pullback) && pullback>=-3 && pullback<=2){ score+=20; factors.push(f(`Pullback EMA20 ${pullback.toFixed(1)}%`,'1D',20)); }
  if (d.rsi>=40 && d.rsi<=55){ score+=15; factors.push(f(`RSI ${d.rsi.toFixed(0)}`,'1D',15)); }
  if (h.macdHist>0 && h.macdHist>h.macdHistPrev){ score+=10; factors.push(f('MACD 1H girando alcista','1H',10)); }
  if (m.rvol>=1.5){ score+=10; factors.push(f(`RVOL 15M ${m.rvol.toFixed(1)}x`,'15M',10)); }
  return mkResult('SC-PB', score, factors, true, hardNo, d.rvol, settings.rvolMin);
}

// --- NYSE_STRATEGIES ---
const NYSE_STRATEGIES = [evalST01,evalST05,evalST06,evalST09,evalST11,evalST15,evalST16];

// --- CRYPTO_STRATEGIES ---
const CRYPTO_STRATEGIES = [evalSC01,evalSC02,evalSCPB];

// --- applyEventAdjustments ---
function applyEventAdjustments(strategies, mode, funda, insiderSummary, hardNo, rvol1d, rvolMin){
  let earningsDays = null;
  if (mode==='NYSE' && funda && funda.next_earnings){
    const ed = new Date(funda.next_earnings+'T00:00:00Z');
    earningsDays = (ed - Date.now()) / 86400000;
  }
  const insiderScore = (mode==='NYSE' && insiderSummary)
    ? Math.max(-8, Math.min(8, insiderSummary.insider_score||0)) : 0;

  return strategies.map(s=>{
    if (!s.applicable) return s;
    // s.score ya está normalizado a base 100 (mkResult) — los modificadores
    // de evento se aplican DESPUÉS de normalizar, nunca dentro del raw.
    let score = s.score;
    const factors = s.factors.slice();
    let earningsAdj = 0, insiderAdj = 0;

    if (earningsDays!=null && earningsDays>=0 && (s.group==='swing' || s.group==='medio')){
      const maxHold = STRATEGY_META[s.id].maxHoldDays;
      if (earningsDays <= maxHold){
        earningsAdj = -10;
        score += earningsAdj;
        factors.push(f(`Earnings en ${Math.ceil(earningsDays)}d dentro del holding — cierra antes`, 'EVENTO', -10));
      }
    }
    if (insiderScore !== 0){
      insiderAdj = insiderScore;
      score += insiderAdj;
      factors.push(f(`Insider score ${insiderScore>=0?'+':''}${insiderScore}`, 'INSIDER', insiderScore));
    }
    if (score === s.score) return s;

    score = Math.max(0, Math.min(100, score));
    const verdict = finalizeVerdict(score, hardNo, rvol1d, rvolMin);
    // s.baseScore se conserva tal cual (score normalizado antes de modificadores)
    // para poder mostrar el desglose "78 (base 82 · insider +4 · earnings -8)".
    return Object.assign({}, s, {score, earningsAdj, insiderAdj, factors, verdict});
  });
}

// --- evaluateTicker ---
function evaluateTicker(ticker, ind, funda, mode, settings, btcGateOn, insiderSummary){
  const d = ind['1d'];
  if (!d) return null;
  const hardNo = tickerHardNo(mode, d.price, d, settings);
  const ctx = {ind, funda, hardNo, settings, mode, ticker, btcGateOn};
  const fns = mode==='NYSE' ? NYSE_STRATEGIES : CRYPTO_STRATEGIES;
  let strategies = fns.map(fn=>{
    const r = fn(ctx);
    return Object.assign({}, r, STRATEGY_META[r.id]);
  });
  strategies = applyEventAdjustments(strategies, mode, funda, insiderSummary, hardNo, d.rvol, settings.rvolMin);

  const applicableStrats = strategies.filter(s=>s.applicable);
  let best = null;
  if (applicableStrats.length) best = applicableStrats.reduce((a,b)=> b.score>a.score ? b : a);

  let earningsDays = null;
  if (mode==='NYSE' && funda && funda.next_earnings){
    earningsDays = (new Date(funda.next_earnings+'T00:00:00Z') - Date.now()) / 86400000;
  }

  return {
    ticker, price:d.price, ind, funda, strategies, best,
    globalVerdict: best ? best.verdict : 'N/A',
    globalScore: best ? best.score : 0,
    hardNo,
    insiderSummary: insiderSummary || null,
    earningsDays: (earningsDays!=null && earningsDays>=0 && earningsDays<=35) ? Math.ceil(earningsDays) : null,
  };
}

// --- detectAutoTrigger ---
function detectAutoTrigger(r){
  if (!r || r.error || r.hardNo) return null;
  if (r.globalVerdict==='NO' || r.globalVerdict==='N/A') return null;
  const applicable = r.strategies.filter(s=>s.applicable);

  const byGroup = {};
  for (const s of applicable){
    if (s.score>=80) (byGroup[s.group] = byGroup[s.group]||[]).push(s);
  }
  for (const group in byGroup){
    if (byGroup[group].length>=2) return {type:'AUTO_MULTI', strategies: byGroup[group]};
  }

  const highSingle = applicable.filter(s=>s.score>=90);
  if (highSingle.length){
    const top = highSingle.reduce((a,b)=> b.score>a.score ? b : a, highSingle[0]);
    return {type:'AUTO_HIGH', strategies:[top]};
  }
  return null;
}

