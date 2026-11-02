async function computeMarketContext(mode){
  try{
    if (mode==='NYSE'){
      const ind = await fetchNyseTicker('SPY');
      const d = ind['1d'];
      if (!d) return null;
      return {ticker:'SPY', price:d.price, ema50:d.ema50, gateOn:d.price>d.ema50, atrPct:d.atrPct, rsi:d.rsi};
    } else {
      const ind = await fetchCryptoTicker('BTC');
      const d = ind['1d'];
      if (!d) return null;
      return {ticker:'BTC', price:d.price, ema50:d.ema50, gateOn:d.price>d.ema50, atrPct:d.atrPct, rsi:d.rsi, macdHist:d.macdHist};
    }
  }catch(e){ return null; }
}
