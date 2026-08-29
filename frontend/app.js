/* PineTester frontend */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let CFG = null, LAST = null, charts = {}, priceChart = null;

const cm = CodeMirror.fromTextArea($("#code"), {
  lineNumbers: true, theme: "material-darker", mode: "javascript",
  lineWrapping: false, tabSize: 4, indentUnit: 4,
});

/* ---------- persistence ---------- */
const FIELDS = ["symbol", "market", "timeframe", "mintick", "start", "end",
  "cap", "qtype", "qval", "comm", "slip"];
function saveState() {
  const s = { code: cm.getValue() };
  FIELDS.forEach(f => s[f] = $("#" + f).value);
  localStorage.setItem("pt_state", JSON.stringify(s));
}
function loadState() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem("pt_state") || "{}"); } catch (e) {}
  if (s.code) cm.setValue(s.code); else cm.setValue(window.PRESETS["EMA crossover"]);
  FIELDS.forEach(f => { if (s[f] != null && s[f] !== "") $("#" + f).value = s[f]; });
}
cm.on("change", saveState);
FIELDS.forEach(f => document.addEventListener("input", e => { if (e.target.id === f) { saveState(); estimate(); } }));

/* ---------- init ---------- */
function fill(sel, arr) { $(sel).innerHTML = arr.map(x => `<option>${x}</option>`).join(""); }
function isoAgo(years) { const d = new Date(); d.setFullYear(d.getFullYear() - years); return d.toISOString().slice(0, 10); }
function isoToday() { return new Date().toISOString().slice(0, 10); }

fetch("/api/config").then(r => r.json()).then(c => {
  CFG = c;
  fill("#symbol", c.symbols); fill("#timeframe", c.timeframes); fill("#market", c.markets);
  $("#preset").innerHTML = Object.keys(window.PRESETS).map(k => `<option>${k}</option>`).join("");
  $("#ometric").innerHTML = Object.entries(c.metrics).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#cmpsyms").innerHTML = c.symbols.map(s =>
    `<span class="chip" data-sym="${s}">${s}</span>`).join("");
  loadState();
  if (!$("#start").value) $("#start").value = isoAgo(2);
  if (!$("#end").value) $("#end").value = isoToday();
  $("#timeframe").value = $("#timeframe").value || "1h";
  $("#hint").textContent =
    `Supported: ta.* indicators, strategy.entry/exit/close, input.*, if/for/while/switch, user functions. ` +
    `Data 1m–1d, spot + USD-M futures. Max ~${(c.max_bars).toLocaleString()} bars/run.`;
  estimate();
});

/* ---------- date & cap chips ---------- */
$("#datechips").onclick = e => {
  const r = e.target.dataset.range; if (!r) return;
  $("#end").value = isoToday();
  $("#start").value = r === "ytd" ? new Date().getFullYear() + "-01-01" : isoAgo(+r);
  saveState(); estimate();
};
$$(".chip[data-cap]").forEach(c => c.onclick = () => { $("#cap").value = c.dataset.cap; saveState(); });

/* ---------- bar estimate ---------- */
let estT;
function estimate() {
  clearTimeout(estT);
  estT = setTimeout(async () => {
    const q = new URLSearchParams({ timeframe: $("#timeframe").value, start: $("#start").value, end: $("#end").value });
    try {
      const r = await fetch("/api/estimate?" + q); const j = await r.json();
      if (j.bars == null) { $("#est").textContent = ""; return; }
      const over = j.bars > j.max_bars;
      $("#est").className = "est" + (over ? " bad" : "");
      $("#est").textContent = `≈ ${j.bars.toLocaleString()} bars` +
        (over ? ` — over the ${j.max_bars.toLocaleString()} limit, use a higher timeframe or shorter range` : "");
    } catch (e) {}
  }, 250);
}

/* ---------- presets ---------- */
$("#loadPreset").onclick = () => {
  const k = $("#preset").value;
  if (window.PRESETS[k]) { cm.setValue(window.PRESETS[k]); saveState(); }
};

/* ---------- tabs ---------- */
$$(".tabs button").forEach(b => b.onclick = () => {
  $$(".tabs button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $$(".tab").forEach(t => t.classList.remove("show"));
  $("#tab-" + b.dataset.tab).classList.add("show");
  if (b.dataset.tab === "chart" && LAST) drawPriceChart(LAST);
});

/* ---------- formatting ---------- */
const money = x => (x == null || isNaN(x)) ? "–" :
  (x < 0 ? "-$" : "$") + Math.abs(x).toLocaleString(undefined, { maximumFractionDigits: 2 });
const pct = x => (x == null || isNaN(x)) ? "–" : x.toFixed(2) + "%";
const nm = (x, d = 2) => (x == null || isNaN(x)) ? "–" : (+x).toFixed(d);
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "neu";
const dts = t => new Date(t).toISOString().slice(0, 16).replace("T", " ");

/* ---------- run backtest ---------- */
function body(extra = {}) {
  return Object.assign({
    code: cm.getValue(),
    symbol: $("#symbol").value, timeframe: $("#timeframe").value, market: $("#market").value,
    start: $("#start").value, end: $("#end").value,
    mintick: parseFloat($("#mintick").value) || 0.01,
    initial_capital: parseFloat($("#cap").value) || null,
    commission_pct: $("#comm").value !== "" ? parseFloat($("#comm").value) : null,
    slippage: $("#slip").value !== "" ? parseFloat($("#slip").value) : null,
    qty_type: $("#qtype").value || null,
    qty_value: $("#qval").value !== "" ? parseFloat($("#qval").value) : null,
    overrides: collectOverrides(),
  }, extra);
}
function collectOverrides() {
  const o = {};
  $$("[data-param]").forEach(el => o[el.dataset.param] = el.type === "checkbox" ? el.checked : el.value);
  return o;
}
function overlay(on, text) { $("#overlay").classList.toggle("hide", !on); if (text) $("#ovtext").textContent = text; }

async function runBacktest() {
  const btn = $("#run"); btn.disabled = true; btn.textContent = "Running…";
  overlay(true, "Downloading data & running backtest…");
  $("#errbox").style.display = "none";
  try {
    const r = await fetch("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body()) });
    const d = await r.json();
    if (d.error) showErr(d); else { LAST = d; render(d); }
  } catch (e) { showErr({ error: String(e) }); }
  overlay(false); btn.disabled = false; btn.textContent = "Run Backtest";
}
$("#run").onclick = runBacktest;
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); runBacktest(); }
});

function showErr(d) {
  $("#empty").style.display = "none"; $("#results").style.display = "none";
  const b = $("#errbox"); b.style.display = "block";
  b.innerHTML = `<div class="err"><b>${d.error || "Error"}</b>\n\n${(d.logs || []).join("\n")}\n\n${d.trace || ""}</div>`;
}

/* ---------- render results ---------- */
function render(d) {
  $("#empty").style.display = "none"; $("#errbox").style.display = "none";
  $("#results").style.display = "block";
  const s = d.stats;

  const hero = [
    ["Net P/L", money(s.net_profit), cls(s.net_profit)],
    ["Return", pct(s.net_profit_pct), cls(s.net_profit_pct)],
    ["Win rate", pct(s.win_rate), "neu"],
    ["Profit factor", nm(s.profit_factor), cls(s.profit_factor - 1)],
    ["Max DD", pct(-s.max_drawdown_pct), "neg"],
    ["Trades", s.total_trades, "neu"],
  ];
  $("#hero").innerHTML = hero.map(([k, v, c]) => `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join("");

  const C = [
    ["Final equity", money(s.final_equity), "neu"],
    ["Buy & hold", pct(s.buy_hold_pct), cls(s.buy_hold_pct)],
    ["CAGR", pct(s.cagr_pct), cls(s.cagr_pct)],
    ["Sharpe", nm(s.sharpe), cls(s.sharpe)],
    ["Sortino", nm(s.sortino), cls(s.sortino)],
    ["Calmar", nm(s.calmar), cls(s.calmar)],
    ["Volatility (ann.)", pct(s.volatility_pct), "neu"],
    ["Max DD $", money(-s.max_drawdown), "neg"],
    ["Recovery factor", nm(s.recovery_factor), "neu"],
    ["Exposure", pct(s.exposure_pct), "neu"],
    ["Avg trade", money(s.avg_trade), cls(s.avg_trade)],
    ["Avg trade %", pct(s.avg_trade_pct), cls(s.avg_trade_pct)],
    ["Avg win", money(s.avg_win), "pos"],
    ["Avg loss", money(s.avg_loss), "neg"],
    ["Payoff ratio", nm(s.payoff_ratio), "neu"],
    ["Winning trades", s.winning_trades, "pos"],
    ["Losing trades", s.losing_trades, "neg"],
    ["Largest win", money(s.largest_win), "pos"],
    ["Largest loss", money(s.largest_loss), "neg"],
    ["Max consec. wins", s.max_consec_wins, "neu"],
    ["Max consec. losses", s.max_consec_losses, "neu"],
    ["Avg bars/trade", nm(s.avg_bars_in_trade, 1), "neu"],
    ["Kelly %", pct(s.kelly_pct), "neu"],
    ["Best month", pct(s.best_month_pct), "pos"],
    ["Worst month", pct(s.worst_month_pct), "neg"],
    ["Positive months", pct(s.positive_months_pct), "neu"],
    ["Commission paid", money(-s.commission_paid), "neg"],
    ["Bars tested", s.bars.toLocaleString(), "neu"],
  ];
  $("#cards").innerHTML = C.map(([k, v, c]) => `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join("");

  const w = d.warnings || [];
  $("#warnbox").innerHTML = w.length ? `<div class="warn"><b>${w.length} warning(s)</b>\n${w.join("\n")}</div>` : "";

  drawEquity(d);
  drawTrades(d);
  drawMonthly(d);
  renderParams(d.inputs || []);
  fillOptimizeInputs(d.inputs || []);
  $("#logbox").textContent = ((d.warnings || []).join("\n") + "\n\n" + (d.logs || []).join("\n")).trim();
  if ($("#tab-chart").classList.contains("show")) drawPriceChart(d);
}

/* ---------- price chart (lightweight-charts) ---------- */
function drawPriceChart(d) {
  const box = $("#chartbox");
  box.innerHTML = "";
  const chart = LightweightCharts.createChart(box, {
    layout: { background: { color: "#0d1117" }, textColor: "#8b949e" },
    grid: { vertLines: { color: "#1c2129" }, horzLines: { color: "#1c2129" } },
    rightPriceScale: { borderColor: "#2a323d" },
    timeScale: { borderColor: "#2a323d", timeVisible: true },
    crosshair: { mode: 0 },
    height: 420,
  });
  const candle = chart.addCandlestickSeries({
    upColor: "#3fb950", downColor: "#f85149", borderVisible: false,
    wickUpColor: "#3fb950", wickDownColor: "#f85149",
  });
  candle.setData(d.candles);
  candle.setMarkers(d.markers || []);
  const vol = chart.addHistogramSeries({ priceScaleId: "", color: "#2a323d", priceFormat: { type: "volume" } });
  vol.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
  vol.setData(d.volume || []);
  const palette = ["#2f81f7", "#d29922", "#a371f7", "#3fb950", "#f85149", "#39c5cf"];
  (d.plots || []).forEach((p, i) => {
    const ls = chart.addLineSeries({ color: palette[i % palette.length], lineWidth: 1.5, priceLineVisible: false });
    ls.setData(p.data);
  });
  chart.timeScale().fitContent();
  const ro = new ResizeObserver(() => chart.applyOptions({ width: box.clientWidth }));
  ro.observe(box);
  chart.applyOptions({ width: box.clientWidth });
  priceChart = chart;
  $("#chartctl").innerHTML = `<span class="muted">${(d.candles || []).length} candles · ${(d.markers || []).length} markers` +
    ((d.plots || []).length ? ` · plots: ${d.plots.map(p => p.title).join(", ")}` : "") + `</span>`;
}

/* ---------- equity / drawdown (Chart.js) ---------- */
function lineChart(id, datasets, opts = {}) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($("#" + id), {
    type: "line",
    data: { datasets },
    options: Object.assign({
      parsing: false, animation: false, normalized: true,
      interaction: { intersect: false, mode: "index" },
      scales: {
        x: { type: "linear", ticks: { color: "#8b949e", maxTicksLimit: 8, callback: v => new Date(v * 1000).toISOString().slice(0, 10) }, grid: { color: "#1c2129" } },
        y: { ticks: { color: "#8b949e" }, grid: { color: "#1c2129" } },
      },
      plugins: { legend: { labels: { color: "#8b949e" } } },
    }, opts),
  });
}
function drawEquity(d) {
  const eq = d.equity.map(p => ({ x: p.t, y: p.equity }));
  const bh = d.equity.map(p => ({ x: p.t, y: p.bh }));
  const dd = d.equity.map(p => ({ x: p.t, y: p.dd }));
  lineChart("eqchart", [
    { label: "Strategy equity", data: eq, borderColor: "#2f81f7", borderWidth: 1.6, pointRadius: 0, fill: false },
    { label: "Buy & hold", data: bh, borderColor: "#8b949e", borderWidth: 1, pointRadius: 0, borderDash: [4, 3], fill: false },
  ]);
  lineChart("ddchart", [
    { label: "Drawdown %", data: dd, borderColor: "#f85149", backgroundColor: "rgba(248,81,73,.15)", borderWidth: 1, pointRadius: 0, fill: true },
  ]);
}

/* ---------- trades ---------- */
let tradeSort = { k: "n", dir: 1 };
function drawTrades(d) {
  $("#tradenote").textContent = `${d.trades.length} of ${d.trade_count} trades shown`;
  const cols = [["n", "#"], ["side", "Side"], ["entry_time", "Entry"], ["exit_time", "Exit"],
    ["entry_price", "Entry $"], ["exit_price", "Exit $"], ["qty", "Qty"], ["bars", "Bars"],
    ["pnl", "PnL"], ["pnl_pct", "PnL %"], ["cum_pnl", "Cum PnL"], ["reason", "Exit"]];
  const rows = [...d.trades].sort((a, b) => {
    let x = a[tradeSort.k], y = b[tradeSort.k];
    if (typeof x === "string") return tradeSort.dir * x.localeCompare(y);
    return tradeSort.dir * (x - y);
  });
  $("#tradetbl").innerHTML =
    `<thead><tr>${cols.map(([k, l]) => `<th data-k="${k}">${l}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(t => `<tr>
      <td>${t.n}</td><td>${t.side}</td><td>${dts(t.entry_time)}</td><td>${dts(t.exit_time)}</td>
      <td>${nm(t.entry_price, 4)}</td><td>${nm(t.exit_price, 4)}</td><td>${nm(t.qty, 4)}</td><td>${t.bars}</td>
      <td class="${cls(t.pnl)}">${money(t.pnl)}</td><td class="${cls(t.pnl_pct)}">${pct(t.pnl_pct)}</td>
      <td class="${cls(t.cum_pnl)}">${money(t.cum_pnl)}</td><td>${t.reason}</td></tr>`).join("") + "</tbody>";
  $$("#tradetbl th").forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    tradeSort = { k, dir: tradeSort.k === k ? -tradeSort.dir : 1 };
    drawTrades(d);
  });
}
$("#csv").onclick = () => {
  if (!LAST) return;
  const cols = ["n", "side", "entry_time", "exit_time", "entry_price", "exit_price", "qty", "bars", "pnl", "pnl_pct", "cum_pnl", "reason"];
  const lines = [cols.join(",")].concat(LAST.trades.map(t =>
    cols.map(c => (c.endsWith("_time") ? new Date(t[c]).toISOString() : t[c])).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${$("#symbol").value}_${$("#timeframe").value}_trades.csv`;
  a.click();
};

/* ---------- monthly heatmap ---------- */
function drawMonthly(d) {
  const m = d.monthly || [];
  if (!m.length) { $("#heatbox").innerHTML = `<p class="muted">no monthly data</p>`; return; }
  const years = [...new Set(m.map(x => x.year))].sort();
  const map = {}; m.forEach(x => map[x.label] = x.return_pct);
  const yearTot = {};
  years.forEach(y => {
    const v = m.filter(x => x.year === y);
    let g = 1; v.forEach(x => g *= (1 + x.return_pct / 100));
    yearTot[y] = (g - 1) * 100;
  });
  const col = v => {
    if (v == null) return "background:#161b22;color:#8b949e";
    const a = Math.min(1, Math.abs(v) / 20);
    return `background:rgba(${v >= 0 ? "63,185,80" : "248,81,73"},${0.15 + a * 0.6});color:#e6edf3`;
  };
  const mn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let h = `<div class="tablewrap"><table class="heat"><thead><tr><th>Year</th>${mn.map(x => `<th>${x}</th>`).join("")}<th>Year</th></tr></thead><tbody>`;
  years.forEach(y => {
    h += `<tr><td>${y}</td>`;
    for (let i = 1; i <= 12; i++) {
      const v = map[`${y}-${String(i).padStart(2, "0")}`];
      h += `<td style="${col(v)}">${v == null ? "" : v.toFixed(1)}</td>`;
    }
    h += `<td style="${col(yearTot[y])}"><b>${yearTot[y].toFixed(1)}</b></td></tr>`;
  });
  $("#heatbox").innerHTML = h + "</tbody></table></div>";
}

/* ---------- detected inputs ---------- */
function renderParams(inputs) {
  if (!inputs.length) { $("#params").innerHTML = ""; return; }
  $("#params").innerHTML = `<h3 class="sec">Strategy inputs</h3><div class="inputs">` +
    inputs.map(i => {
      if (typeof i.default === "boolean")
        return `<div class="ir"><label style="margin:0">${i.title}</label><input type="checkbox" data-param="${i.name}" ${i.default ? "checked" : ""}></div>`;
      return `<div class="ir"><label style="margin:0">${i.title}</label><input data-param="${i.name}" value="${i.default}"></div>`;
    }).join("") + `</div>`;
}

/* ---------- optimize ---------- */
function fillOptimizeInputs(inputs) {
  const numeric = inputs.filter(i => typeof i.default === "number");
  const opts = `<option value="">—</option>` + numeric.map(i => `<option value="${i.name}">${i.title}</option>`).join("");
  $("#op1").innerHTML = opts; $("#op2").innerHTML = opts;
  if (numeric[0]) { $("#op1").value = numeric[0].name; seedRange("#op1", numeric[0]); }
  if (numeric[1]) { $("#op2").value = numeric[1].name; seedRange("#op2", numeric[1]); }
}
function seedRange(sel, inp) {
  const p = sel.replace("op", "op");
  const base = inp.default;
  $(sel + "a").value = Math.max(1, Math.round(base * 0.5));
  $(sel + "b").value = Math.round(base * 1.5);
  $(sel + "s").value = Math.max(1, Math.round(base * 0.1));
}
$("#op1").onchange = () => { const i = (LAST?.inputs || []).find(x => x.name === $("#op1").value); if (i) seedRange("#op1", i); };
$("#op2").onchange = () => { const i = (LAST?.inputs || []).find(x => x.name === $("#op2").value); if (i) seedRange("#op2", i); };

$("#runopt").onclick = async () => {
  const params = [];
  if ($("#op1").value) params.push({ name: $("#op1").value, start: $("#op1a").value, stop: $("#op1b").value, step: $("#op1s").value });
  if ($("#op2").value) params.push({ name: $("#op2").value, start: $("#op2a").value, stop: $("#op2b").value, step: $("#op2s").value });
  if (!params.length) { $("#optout").innerHTML = `<p class="err">Select at least one parameter.</p>`; return; }
  overlay(true, "Running optimization grid…");
  try {
    const r = await fetch("/api/optimize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body({ params, metric: $("#ometric").value })) });
    const d = await r.json();
    overlay(false);
    if (d.error) { $("#optout").innerHTML = `<div class="err">${d.error}</div>`; return; }
    renderOpt(d);
  } catch (e) { overlay(false); $("#optout").innerHTML = `<div class="err">${e}</div>`; }
};
function renderOpt(d) {
  const flat = d.grid.flat();
  const vals = flat.map(c => c.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const col = v => {
    const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
    return `background:rgba(63,185,80,${0.1 + t * 0.7})`;
  };
  let h = `<p class="muted">${d.combos} runs · best ${d.metric_label} = <b>${nm(d.best.value)}</b> at ` +
    `${d.params[0]}=${d.best.v1}${d.best.v2 != null ? `, ${d.params[1]}=${d.best.v2}` : ""} ` +
    `(net ${money(d.best.net)}, ${nm(d.best.win_rate, 1)}% win, ${d.best.trades} trades)</p>`;
  h += `<div class="tablewrap"><table class="heat"><thead><tr><th>${d.params[1] || ""} \\ ${d.params[0]}</th>` +
    d.axis1.map(a => `<th>${a}</th>`).join("") + `</tr></thead><tbody>`;
  d.grid.forEach((row, ri) => {
    h += `<tr><td>${d.axis2[ri] != null ? d.axis2[ri] : "—"}</td>`;
    row.forEach(c => {
      h += `<td style="${col(c.value)};cursor:pointer" title="net ${money(c.net)} · ${nm(c.win_rate, 1)}% win · ${c.trades} trades · DD ${nm(c.dd, 1)}%" data-v1="${c.v1}" data-v2="${c.v2}">${nm(c.value, 1)}</td>`;
    });
    h += `</tr>`;
  });
  h += `</tbody></table></div><p class="muted">Click a cell to apply those values to the inputs.</p>`;
  $("#optout").innerHTML = h;
  $$("#optout td[data-v1]").forEach(td => td.onclick = () => {
    setParam(d.params[0], td.dataset.v1);
    if (d.params[1] && td.dataset.v2 !== "null") setParam(d.params[1], td.dataset.v2);
    runBacktest();
  });
}
function setParam(name, val) {
  const el = $(`[data-param="${name}"]`);
  if (el) el.value = val;
}

/* ---------- compare ---------- */
$("#cmpsyms").onclick = e => { if (e.target.dataset.sym) e.target.classList.toggle("active"); };
$("#runcmp").onclick = async () => {
  const syms = $$("#cmpsyms .chip.active").map(c => c.dataset.sym);
  if (!syms.length) { $("#cmpout").innerHTML = `<p class="muted">Select one or more pairs above.</p>`; return; }
  overlay(true, `Backtesting ${syms.length} pairs…`);
  try {
    const r = await fetch("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body({ symbols: syms })) });
    const d = await r.json();
    overlay(false);
    if (d.error) { $("#cmpout").innerHTML = `<div class="err">${d.error}</div>`; return; }
    const rows = d.rows.slice().sort((a, b) => (b.net_profit_pct || -1e9) - (a.net_profit_pct || -1e9));
    $("#cmpout").innerHTML = `<div class="tablewrap"><table><thead><tr>
      <th>Pair</th><th>Return %</th><th>Net P/L</th><th>Win %</th><th>PF</th><th>Trades</th><th>Max DD %</th><th>Sharpe</th><th>Buy&hold %</th></tr></thead><tbody>` +
      rows.map(x => x.ok ? `<tr>
        <td>${x.symbol}</td><td class="${cls(x.net_profit_pct)}">${pct(x.net_profit_pct)}</td>
        <td class="${cls(x.net_profit)}">${money(x.net_profit)}</td><td>${nm(x.win_rate, 1)}</td>
        <td class="${cls(x.profit_factor - 1)}">${nm(x.profit_factor)}</td><td>${x.trades}</td>
        <td class="neg">${nm(x.max_dd_pct, 1)}</td><td>${nm(x.sharpe)}</td>
        <td class="${cls(x.buy_hold_pct)}">${pct(x.buy_hold_pct)}</td></tr>`
        : `<tr><td>${x.symbol}</td><td colspan="8" class="muted">${x.error}</td></tr>`).join("") +
      `</tbody></table></div>`;
  } catch (e) { overlay(false); $("#cmpout").innerHTML = `<div class="err">${e}</div>`; }
};
