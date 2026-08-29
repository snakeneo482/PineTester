window.PRESETS = {
  "EMA crossover": `//@version=5
strategy("EMA crossover", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

fastLen = input.int(20, "Fast EMA")
slowLen = input.int(50, "Slow EMA")

fast = ta.ema(close, fastLen)
slow = ta.ema(close, slowLen)
plot(fast, "Fast EMA")
plot(slow, "Slow EMA")

if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("L")
`,

  "RSI mean reversion": `//@version=5
strategy("RSI mean reversion", overlay=false, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=50,
     commission_type=strategy.commission.percent, commission_value=0.04)

len   = input.int(14, "RSI length")
lower = input.int(30, "Oversold")
upper = input.int(70, "Overbought")

r = ta.rsi(close, len)
plot(r, "RSI")

if ta.crossover(r, lower)
    strategy.entry("L", strategy.long)
if ta.crossunder(r, upper)
    strategy.close("L")
`,

  "MACD trend": `//@version=5
strategy("MACD trend", overlay=false, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

fast = input.int(12, "Fast")
slow = input.int(26, "Slow")
sig  = input.int(9,  "Signal")

[m, s, h] = ta.macd(close, fast, slow, sig)
plot(m, "MACD")
plot(s, "Signal")

if ta.crossover(m, s)
    strategy.entry("L", strategy.long)
if ta.crossunder(m, s)
    strategy.close("L")
`,

  "Bollinger breakout": `//@version=5
strategy("Bollinger breakout", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

len  = input.int(20, "Length")
mult = input.float(2.0, "StdDev mult")

[basis, upper, lower] = ta.bb(close, len, mult)
plot(upper, "Upper")
plot(lower, "Lower")

if ta.crossover(close, upper)
    strategy.entry("L", strategy.long)
if ta.crossunder(close, basis)
    strategy.close("L")
`,

  "Supertrend": `//@version=5
strategy("Supertrend", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

factor = input.float(3.0, "Factor")
atrLen = input.int(10, "ATR length")

[st, dir] = ta.supertrend(factor, atrLen)
plot(st, "Supertrend")

if dir < 0 and dir[1] > 0
    strategy.entry("L", strategy.long)
if dir > 0 and dir[1] < 0
    strategy.close("L")
`,

  "Donchian channel breakout": `//@version=5
strategy("Donchian breakout", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

len = input.int(20, "Channel length")
hi = ta.highest(high, len)[1]
lo = ta.lowest(low, len)[1]
plot(hi, "Upper")
plot(lo, "Lower")

if close > hi
    strategy.entry("L", strategy.long)
if close < lo
    strategy.close("L")
`,

  "ATR trailing stop trend": `//@version=5
strategy("ATR trend + stop", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100,
     commission_type=strategy.commission.percent, commission_value=0.04)

emaLen = input.int(100, "Trend EMA")
atrLen = input.int(14, "ATR length")
atrMult = input.float(3.0, "ATR stop mult")

trend = ta.ema(close, emaLen)
atr = ta.atr(atrLen)
plot(trend, "Trend")

if ta.crossover(close, trend)
    strategy.entry("L", strategy.long)

strategy.exit("x", "L", stop = close - atrMult * atr)

if ta.crossunder(close, trend)
    strategy.close("L")
`,

  "Buy & hold": `//@version=5
strategy("Buy & hold", overlay=true, initial_capital=10000,
     default_qty_type=strategy.percent_of_equity, default_qty_value=100)

if bar_index == 0
    strategy.entry("L", strategy.long)
`,
};
