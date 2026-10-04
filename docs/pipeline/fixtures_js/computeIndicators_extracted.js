// Extraído de /opt/axonik/scanner/index.html el 2026-10-04T11:08:27Z por generar_fixtures_js.sh
// NO EDITAR A MANO -- regenerar con el script si el navegador cambia.

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

// --- calcRVOL ---
function calcRVOL(volumes){
  if (volumes.length < 21) return NaN;
  const last = volumes[volumes.length-1];
  const prev20 = volumes.slice(-21,-1);
  const avg = prev20.reduce((a,b)=>a+b,0)/prev20.length;
  return avg>0 ? last/avg : NaN;
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

// --- calcVWAP ---
function calcVWAP(candles){
  if (!candles.length) return NaN;
  const lastDate = new Date(candles[candles.length-1].t*1000).toISOString().slice(0,10);
  const session = candles.filter(c => new Date(c.t*1000).toISOString().slice(0,10) === lastDate);
  let pv=0, vol=0;
  for (const c of session){ const typ=(c.h+c.l+c.c)/3; pv+=typ*c.v; vol+=c.v; }
  return vol>0 ? pv/vol : NaN;
}

