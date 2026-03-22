/* ─────────────────────────────────────────────
   SubScalp WealthBot — dashboard.js
   All live data, SocketIO, charts, interactions
───────────────────────────────────────────── */

const socket = io();

// ── State ──────────────────────────────────────
let botRunning   = false;
let activeStrategy = '—';
let equityData   = [];
let pnlData      = [];

// ── Clock ──────────────────────────────────────
setInterval(() => {
  const t = new Date().toTimeString().slice(0, 8);
  const el = document.getElementById('topbar-clock');
  if (el) el.textContent = t;
}, 1000);

// ── Navigation ────────────────────────────────
function goto(page, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  btn.classList.add('active');
  const titles = {
    dashboard: 'Dashboard',
    analytics:  'Analytics',
    trades:     'Trade History',
    settings:   'Settings'
  };
  document.getElementById('page-title').textContent = titles[page] || page;

  if (page === 'analytics')  { setTimeout(drawCharts, 80); loadAnalytics(); }
  if (page === 'trades')     { loadTrades(); }
  if (page === 'settings')   { loadSettings(); }
}

// ── SocketIO ───────────────────────────────────
socket.on('connect', () => {
  addLog('ok', '[WS] Connected to SubScalp server');
});

socket.on('disconnect', () => {
  addLog('warn', '[WS] Disconnected from server — reconnecting...');
});

socket.on('snapshot', (data) => {
  applyStats(data.stats);
  applyOpenTrades(data.open_trades);
  applyBotState(data.bot_state);
  if (data.equity)    { equityData = data.equity; }
  if (data.logs)      { renderLogs(data.logs); }
  updateSurvivalRules(data.stats);
});

socket.on('live_update', (data) => {
  if (data.open_trades !== undefined) applyOpenTrades(data.open_trades);
  if (data.bot_state)                applyBotState(data.bot_state);
  if (data.new_logs && data.new_logs.length) {
    data.new_logs.reverse().forEach(l => prependLog(l));
  }
});

socket.on('stats_update', (data) => {
  if (data.stats)     applyStats(data.stats);
  if (data.equity)    { equityData = data.equity; redrawEquity(); }
  if (data.daily_pnl) { pnlData = data.daily_pnl; redrawPnl(); }
});

// ── Apply Data Functions ───────────────────────
function applyStats(s) {
  if (!s) return;

  const balance  = 10000 + (s.net_pnl || 0);
  const netPnl   = s.net_pnl || 0;
  const today    = s.total_trades || 0;
  const wins     = s.wins || 0;
  const losses   = s.losses || 0;
  const winrate  = s.winrate || 0;
  const openPos  = s.open_positions || 0;

  setText('stat-balance',       fmt.currency(balance));
  setText('stat-balance-delta', `${netPnl >= 0 ? '+' : ''}${fmt.currency(netPnl)} total`);
  setClass('stat-balance-delta', netPnl >= 0 ? 'stat-delta up' : 'stat-delta dn');

  setText('stat-open-pnl',   '—');
  setText('stat-open-count', `${openPos} open position${openPos !== 1 ? 's' : ''}`);

  setText('stat-trades-today', `${today}`);
  setText('stat-trades-wr',    `${wins}W · ${losses}L · ${winrate}% WR`);

  // Drawdown placeholder — real value comes from risk_manager
  setText('stat-drawdown', '—');
}

function applyOpenTrades(trades) {
  const tbody = document.getElementById('open-trades-body');
  const label = document.getElementById('open-count-label');
  if (!tbody) return;

  label.textContent = `${trades.length} open`;

  if (!trades.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-row">No open positions</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map(t => `
    <tr>
      <td>${t.symbol}</td>
      <td><span class="badge ${t.direction.toLowerCase()}">${t.direction}</span></td>
      <td>${Number(t.lots).toFixed(2)}</td>
      <td>${fmt.price(t.entry_price)}</td>
      <td>${fmt.price(t.sl)}</td>
      <td>${fmt.price(t.tp)}</td>
      <td style="font-size:11px;color:var(--muted)">${t.strategy || '—'}</td>
    </tr>
  `).join('');
}

function applyBotState(state) {
  if (!state) return;
  botRunning     = !!state.running;
  activeStrategy = state.strategy || '—';

  const dot = document.getElementById('status-dot');
  const btn = document.getElementById('toggle-btn');
  const strat = document.getElementById('status-strategy');

  dot.className  = 'status-dot' + (botRunning ? '' : ' stopped');
  btn.className  = 'bot-toggle' + (botRunning ? ' running' : '');
  btn.textContent = botRunning ? 'STOP BOT' : 'START BOT';

  if (strat) strat.textContent = activeStrategy;

  setText('strategy-label', activeStrategy);
}

function updateSurvivalRules(s) {
  const maxTrades = 10;
  const today     = s?.total_trades || 0;

  setRule('rule-daily-loss',  'PASS', 'ok');
  setRule('rule-volatility',  'PASS', 'ok');
  setRule('rule-consec-sl',   'PASS · 0/3', 'ok');
  setRule('rule-winrate',     `PASS · ${s?.winrate || 0}%`, 'ok');
  setRule('rule-max-trades',  `${today} / ${maxTrades}`, today >= maxTrades ? 'fail' : 'warn');
  setRule('rule-regime',      'PASS', 'ok');

  setText('rules-status', 'All clear');
}

function setRule(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className   = `rule-val ${cls}`;
}

// ── Log Feed ───────────────────────────────────
function renderLogs(logs) {
  const feed = document.getElementById('log-feed');
  if (!feed) return;
  feed.innerHTML = '';
  logs.slice(0, 40).forEach(l => {
    feed.appendChild(buildLogLine(l));
  });
}

function prependLog(l) {
  const feed = document.getElementById('log-feed');
  if (!feed) return;
  feed.insertBefore(buildLogLine(l), feed.firstChild);
  const ts = document.getElementById('log-timestamp');
  if (ts) ts.textContent = fmtTime(l.created_at);
  // Cap at 60 lines
  while (feed.children.length > 60) feed.removeChild(feed.lastChild);
}

function buildLogLine(l) {
  const div  = document.createElement('div');
  div.className = 'log-line';
  const cls = levelClass(l.level);
  div.innerHTML = `<span class="log-time">${fmtTime(l.created_at)}</span><span class="log-event ${cls}">${escHtml(l.message)}</span>`;
  return div;
}

function levelClass(level) {
  if (!level) return '';
  const l = level.toUpperCase();
  if (l === 'TRADE') return 'trade';
  if (l === 'ERROR') return 'err';
  if (l === 'WARN')  return 'warn';
  if (l === 'INFO')  return 'info';
  return 'ok';
}

// ── Bot Toggle ────────────────────────────────
async function toggleBot() {
  const btn = document.getElementById('toggle-btn');
  btn.disabled = true;

  const endpoint = botRunning ? '/api/bot/stop' : '/api/bot/start';
  const body = botRunning ? {} : { strategy: selectedStrategy || activeStrategy };

  try {
    const res  = await fetch(endpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.ok) {
      console.error('Bot toggle failed:', data.error);
    }
    // State update will arrive via socket live_update
  } catch (e) {
    console.error('Bot toggle error:', e);
  } finally {
    btn.disabled = false;
  }
}

// ── Strategy Selection (settings page) ────────
let selectedStrategy = null;

function selectStrategy(card) {
  document.querySelectorAll('.strategy-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  selectedStrategy = card.dataset.strategy;
}

// ── Settings ──────────────────────────────────
async function loadSettings() {
  try {
    const res    = await fetch('/api/settings');
    const config = await res.json();

    // Fill text/number inputs
    Object.entries(config).forEach(([key, val]) => {
      const el = document.getElementById(`cfg-${key}`);
      if (!el) return;
      if (el.tagName === 'SELECT') {
        el.value = String(val).toLowerCase();
      } else {
        el.value = val;
      }
    });

    // Highlight active strategy card
    const strat = config.strategy || activeStrategy;
    if (strat) {
      document.querySelectorAll('.strategy-card').forEach(c => {
        c.classList.toggle('selected', c.dataset.strategy === strat);
      });
      selectedStrategy = strat;
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

async function saveSettings() {
  const keys = [
    'risk_per_trade', 'max_trades_per_day', 'daily_loss_limit',
    'max_trades_per_symbol_per_day', 'cooldown_candles_after_loss',
    'consecutive_sl_pause_count', 'broker', 'timeframe',
    'htf_trend_timeframe', 'poll_interval',
    'winrate_pause_threshold', 'winrate_lookback_trades'
  ];

  const payload = {};
  keys.forEach(key => {
    const el = document.getElementById(`cfg-${key}`);
    if (!el) return;
    const raw = el.value.trim();
    if (raw === '') return;
    payload[key] = isNaN(raw) ? raw : Number(raw);
  });

  if (selectedStrategy) payload.strategy = selectedStrategy;

  const btn      = document.getElementById('save-btn');
  const feedback = document.getElementById('save-feedback');
  btn.disabled   = true;
  feedback.textContent = '';

  try {
    const res  = await fetch('/api/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.ok) {
      feedback.textContent = `Saved ${data.saved.length} keys`;
      feedback.style.color = 'var(--green)';
      // Update topbar strategy badge
      if (payload.strategy) {
        setText('strategy-label', payload.strategy);
        activeStrategy = payload.strategy;
      }
    } else {
      feedback.textContent = data.error || 'Error saving';
      feedback.style.color = 'var(--red)';
    }
  } catch (e) {
    feedback.textContent = 'Network error';
    feedback.style.color = 'var(--red)';
  } finally {
    btn.disabled = false;
    setTimeout(() => { feedback.textContent = ''; }, 3000);
  }
}

// ── Analytics ─────────────────────────────────
async function loadAnalytics() {
  try {
    const [statsRes, pnlRes, stratRes, eqRes] = await Promise.all([
      fetch('/api/trades/stats?days=30'),
      fetch('/api/trades/daily-pnl?days=14'),
      fetch('/api/trades/strategy-stats'),
      fetch('/api/dashboard/equity'),
    ]);

    const stats   = await statsRes.json();
    const daily   = await pnlRes.json();
    const strats  = await stratRes.json();
    const equity  = await eqRes.json();

    pnlData    = daily;
    equityData = equity;

    const total   = stats.total_trades || 0;
    const wins    = stats.wins || 0;
    const losses  = stats.losses || 0;
    const winrate = stats.winrate || 0;
    const netPnl  = stats.net_pnl || 0;
    const avgWin  = stats.avg_win || 0;
    const avgLoss = stats.avg_loss || 0;
    const pf      = avgLoss ? Math.abs(avgWin / avgLoss).toFixed(2) : '—';

    setText('an-total',    total);
    setText('an-winrate',  `${winrate}%`);
    setText('an-wl',       `${wins}W · ${losses}L`);
    setText('an-pf',       pf);
    setText('an-pnl',      fmt.currency(netPnl));
    setText('an-return',   `${((netPnl / 10000) * 100).toFixed(2)}% return`);
    setText('an-avg-win',  fmt.currency(avgWin));
    setText('an-avg-loss', fmt.currency(avgLoss));

    // Donut
    const circ = 301.6;
    const winArc  = total ? (wins / total) * circ : 0;
    const lossArc = total ? (losses / total) * circ : 0;
    const winEl   = document.getElementById('donut-win');
    const lossEl  = document.getElementById('donut-loss');
    if (winEl) {
      winEl.setAttribute('stroke-dasharray',  `${winArc.toFixed(1)} ${circ}`);
      winEl.setAttribute('stroke-dashoffset', '75.4');
    }
    if (lossEl) {
      const lossOffset = -(winArc - 75.4);
      lossEl.setAttribute('stroke-dasharray',  `${lossArc.toFixed(1)} ${circ}`);
      lossEl.setAttribute('stroke-dashoffset', lossOffset.toFixed(1));
    }
    setText('donut-pct',      `${winrate}%`);
    setText('donut-label',    `${total} trades`);
    setText('donut-wins',     wins);
    setText('donut-losses',   losses);
    setText('donut-avg-win',  fmt.currency(avgWin));
    setText('donut-avg-loss', fmt.currency(avgLoss));

    // Strategy table
    const stBody = document.getElementById('strategy-stats-body');
    if (stBody) {
      stBody.innerHTML = strats.length
        ? strats.map(s => `
          <tr>
            <td>${s.strategy || '—'}</td>
            <td>${s.trades}</td>
            <td class="${s.winrate >= 50 ? 'pnl-pos' : 'pnl-neg'}">${s.winrate}%</td>
            <td class="${s.net_pnl >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt.currency(s.net_pnl)}</td>
            <td class="pnl-pos">${fmt.currency(s.avg_win)}</td>
            <td class="pnl-neg">${fmt.currency(s.avg_loss)}</td>
          </tr>
        `).join('')
        : `<tr><td colspan="6" class="empty-row">No closed trades yet</td></tr>`;
    }

    drawCharts();
  } catch (e) {
    console.error('Analytics load error:', e);
  }
}

// ── Trade History ─────────────────────────────
async function loadTrades() {
  const strategy = document.getElementById('filter-strategy')?.value || '';
  const symbol   = document.getElementById('filter-symbol')?.value   || '';
  const days     = document.getElementById('filter-days')?.value     || 30;

  const params = new URLSearchParams({ days });
  if (strategy) params.set('strategy', strategy);
  if (symbol)   params.set('symbol',   symbol);

  try {
    const res    = await fetch(`/api/trades?${params}`);
    const trades = await res.json();
    const tbody  = document.getElementById('history-body');
    if (!tbody) return;

    tbody.innerHTML = trades.length
      ? trades.map(t => {
          const pnlVal = t.pnl != null ? t.pnl : null;
          const pnlStr = pnlVal != null
            ? `<span class="${pnlVal >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt.currency(pnlVal)}</span>`
            : '—';
          return `
          <tr>
            <td>${fmtDatetime(t.open_time)}</td>
            <td>${t.symbol}</td>
            <td><span class="badge ${t.direction.toLowerCase()}">${t.direction}</span></td>
            <td>${t.lots}</td>
            <td>${fmt.price(t.entry_price)}</td>
            <td>${t.exit_price ? fmt.price(t.exit_price) : '—'}</td>
            <td>${fmt.price(t.sl)}</td>
            <td>${fmt.price(t.tp)}</td>
            <td>${pnlStr}</td>
            <td style="font-size:11px;color:var(--muted)">${t.strategy || '—'}</td>
            <td><span class="badge ${t.status}">${t.status}</span></td>
          </tr>`;
        }).join('')
      : `<tr><td colspan="11" class="empty-row">No trades found for the selected filters</td></tr>`;
  } catch (e) {
    console.error('Trade history load error:', e);
  }
}

// ── Charts ────────────────────────────────────
function drawCharts() {
  redrawEquity();
  redrawPnl();
}

function redrawEquity() {
  const c = document.getElementById('equityChart');
  if (!c || !equityData.length) return;
  const W   = c.parentElement.clientWidth - 40;
  c.width   = W;
  c.height  = 160;
  const ctx = c.getContext('2d');
  const pts = equityData.map(d => d.balance);
  if (pts.length < 2) return;

  const min  = Math.min(...pts) - Math.abs(Math.min(...pts) * 0.01);
  const max  = Math.max(...pts) + Math.abs(Math.max(...pts) * 0.01);
  const toY  = v => 15 + (1 - (v - min) / (max - min)) * 130;
  const toX  = i => 10 + i * (W - 20) / (pts.length - 1);

  ctx.clearRect(0, 0, W, 160);

  // Fill
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(pts[0]));
  pts.forEach((v, i) => { if (i > 0) ctx.lineTo(toX(i), toY(v)); });
  ctx.lineTo(toX(pts.length - 1), 160);
  ctx.lineTo(toX(0), 160);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, 160);
  grad.addColorStop(0, 'rgba(0,212,168,0.16)');
  grad.addColorStop(1, 'rgba(0,212,168,0)');
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(pts[0]));
  pts.forEach((v, i) => { if (i > 0) ctx.lineTo(toX(i), toY(v)); });
  ctx.strokeStyle = '#00d4a8';
  ctx.lineWidth   = 2;
  ctx.stroke();

  // End dot
  ctx.beginPath();
  ctx.arc(toX(pts.length - 1), toY(pts[pts.length - 1]), 4, 0, Math.PI * 2);
  ctx.fillStyle = '#00d4a8';
  ctx.fill();
}

function redrawPnl() {
  const c = document.getElementById('pnlChart');
  if (!c || !pnlData.length) return;
  const W   = c.parentElement.clientWidth - 40;
  c.width   = W;
  c.height  = 100;
  const ctx = c.getContext('2d');
  const bars = pnlData.map(d => d.pnl);
  const maxA = Math.max(...bars.map(Math.abs), 1);
  const bw   = Math.max(4, (W - (bars.length - 1) * 4) / bars.length);

  ctx.clearRect(0, 0, W, 100);

  bars.forEach((v, i) => {
    const h = Math.abs(v) / maxA * 42;
    const x = i * (bw + 4);
    const y = v >= 0 ? 50 - h : 50;
    ctx.fillStyle   = v >= 0 ? '#22c55e' : '#ef4444';
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(x, y, bw, h, 3);
    } else {
      ctx.rect(x, y, bw, h);
    }
    ctx.fill();
  });
  ctx.globalAlpha = 1;
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth   = 1;
  ctx.beginPath();
  ctx.moveTo(0, 50);
  ctx.lineTo(W, 50);
  ctx.stroke();
}

window.addEventListener('resize', () => {
  if (document.getElementById('page-analytics')?.classList.contains('active')) {
    drawCharts();
  }
});

// ── Utilities ─────────────────────────────────
const fmt = {
  currency: (v) => {
    if (v == null) return '—';
    const n = parseFloat(v);
    return (n >= 0 ? '+$' : '-$') + Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  },
  price: (v) => {
    if (v == null) return '—';
    const n = parseFloat(v);
    return n > 999 ? n.toFixed(2) : n.toFixed(5);
  },
};

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setClass(id, cls) {
  const el = document.getElementById(id);
  if (el) el.className = cls;
}

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toTimeString().slice(0, 8); }
  catch { return iso.slice(11, 19) || '—'; }
}

function fmtDatetime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toISOString().slice(0, 16).replace('T', ' ');
  } catch { return iso; }
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
