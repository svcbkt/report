/* ------------------------------------------------------------------
 * 台股晨報 前端邏輯
 * 資料來源：data.json（由 read_news.py 透過 GitHub Actions 每日產生）
 * 若 data.json 讀取失敗（例如離線開啟本機檔案），會退回示範資料，
 * 並在畫面上標示「示範資料」以避免誤判為當日真實資訊。
 * ------------------------------------------------------------------ */

const FALLBACK_DATA = {
  generated_at: null,
  market_tone: '中性偏多',
  market_summary: '尚未取得今日晨報資料。請確認 data.json 是否已由排程產生，或稍後點擊「產生最新報告」重新讀取。',
  signal_row: [
    { label: '全球市場', text: '－', arrow: '→', tone: 'neutral-text' },
    { label: '台股技術面', text: '－', arrow: '→', tone: 'neutral-text' },
    { label: '資金情緒', text: '－', arrow: '→', tone: 'neutral-text' }
  ],
  taiex: { value: '－', change: '－', change_pct: '', tone: 'neutral-text', chart_points: [50, 50, 50, 50, 50, 50, 50, 50] },
  markets: [],
  news: [],
  sectors: [],
  watchlist_holdings: []
};

const $ = (selector) => document.querySelector(selector);
let holdings = JSON.parse(localStorage.getItem('premarket-holdings') || 'null') || [];
let editingSymbol = null;
let reportData = FALLBACK_DATA;
let usingFallback = true;

/* ---------------- 資料讀取 ---------------- */

async function loadReport() {
  try {
    // 加上時間戳避免瀏覽器快取住舊的 data.json
    const res = await fetch(`data.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    reportData = { ...FALLBACK_DATA, ...json };
    usingFallback = false;
  } catch (err) {
    console.warn('讀取 data.json 失敗，使用示範資料：', err);
    reportData = FALLBACK_DATA;
    usingFallback = true;
  }
  renderAll();
}

/* ---------------- 渲染函式 ---------------- */

const TONE_TO_PILL_CLASS = { 'positive': 'bullish', 'negative': 'bearish', 'neutral-text': 'neutral' };

function renderBriefing() {
  const toneClass = reportData.market_tone_class || 'neutral-text';
  $('#marketTone').textContent = reportData.market_tone;
  $('#marketTone').className = `risk-pill ${TONE_TO_PILL_CLASS[toneClass] || 'neutral'}`;
  $('#marketSummary').textContent = reportData.market_summary;

  const rows = reportData.signal_row.length ? reportData.signal_row : FALLBACK_DATA.signal_row;
  $('.signal-row').innerHTML = rows.map((row) => `
    <div><span>${escapeHtml(row.label)}</span><strong class="${row.tone}">${escapeHtml(row.text)} <em>${row.arrow}</em></strong></div>
  `).join('');
}

function renderTaiex() {
  const t = reportData.taiex || FALLBACK_DATA.taiex;
  $('#taiexValue').textContent = t.value;
  const changeEl = document.querySelector('.quote-change');
  changeEl.className = `quote-change ${t.tone || 'neutral-text'}`;
  changeEl.innerHTML = `${escapeHtml(t.change)}<br><small>${escapeHtml(t.change_pct || '')}</small>`;

  const points = (t.chart_points && t.chart_points.length >= 2) ? t.chart_points : FALLBACK_DATA.taiex.chart_points;
  const { linePath, fillPath } = buildChartPaths(points);
  const lineEl = document.querySelector('.chart-line');
  const fillEl = document.querySelector('.chart-fill');
  lineEl.setAttribute('d', linePath);
  fillEl.setAttribute('d', fillPath);

  // 依當日漲跌上色：紅漲／綠跌／中性用琥珀色，對應台股慣例
  const TONE_COLORS = {
    'positive': { line: '#f1757f', fillTop: '#f1757f' },
    'negative': { line: '#3ac79b', fillTop: '#3ac79b' },
    'neutral-text': { line: '#e7b765', fillTop: '#e7b765' }
  };
  const colors = TONE_COLORS[t.tone] || TONE_COLORS['neutral-text'];
  lineEl.style.stroke = colors.line;
  const stops = document.querySelectorAll('#fill stop');
  if (stops.length >= 1) stops[0].setAttribute('stop-color', colors.fillTop);
}

function buildChartPaths(points) {
  const width = 360, height = 106, topPad = 10, bottomPad = 10;
  const min = Math.min(...points), max = Math.max(...points);
  const range = max - min || 1;
  const step = width / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = i * step;
    const y = topPad + (1 - (p - min) / range) * (height - topPad - bottomPad);
    return [x, y];
  });
  const linePath = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const fillPath = `${linePath} L${width} ${height} L0 ${height} Z`;
  return { linePath, fillPath };
}

function renderMarkets() {
  $('#globalMarkets').innerHTML = (reportData.markets || []).map(([name, value, change, trend]) => `
    <article class="market-card"><div class="market-name"><span>${escapeHtml(name)}</span><span class="${trend}">${trend === 'positive' ? '▲' : trend === 'negative' ? '▼' : '◆'}</span></div><strong>${escapeHtml(value)}</strong><span class="change ${trend}">${escapeHtml(change)}</span></article>`).join('')
    || '<p class="reason">尚無市場資料。</p>';
}

function renderNews() {
  $('#newsList').innerHTML = (reportData.news || []).map(([title, caption, impact, tone, tag]) => `
    <article class="news-item"><span class="news-tag ${tone}">${escapeHtml((tag || '').toUpperCase())}</span><div class="news-title">${escapeHtml(title)}</div><span class="impact ${tone}">${escapeHtml(impact)}</span><div class="news-caption">${escapeHtml(caption)}</div></article>`).join('')
    || '<p class="reason">今日尚無新聞摘要。</p>';
}

function renderSectors() {
  $('#sectorList').innerHTML = (reportData.sectors || []).map(([name, score, change, warn]) => `
    <div class="sector-row"><span>${escapeHtml(name)}</span><div class="bar"><b class="${warn}" style="width:${score}%"></b></div><em class="${warn ? 'neutral-text' : 'positive'}">${escapeHtml(change)}</em></div>`).join('')
    || '<p class="reason">今日尚無族群資料。</p>';
}

function mergedHoldings() {
  // 以本機（使用者手動新增）的持股清單為主，若代號有出現在 data.json 的
  // watchlist_holdings 中，就用排程產出的最新判讀覆蓋 signal / reason / tone，
  // 並附上股價、三大法人買賣超、融資融券等排程抓到的資料。
  const autoBySymbol = Object.fromEntries((reportData.watchlist_holdings || []).map((h) => [h.symbol, h]));
  return holdings.map((h) => {
    const auto = autoBySymbol[h.symbol];
    if (!auto) return h;
    return {
      ...h,
      signal: auto.signal, reason: auto.reason, tone: auto.tone,
      price: auto.price, price_change: auto.price_change, price_trend: auto.price_trend,
      institutional: auto.institutional, margin: auto.margin,
    };
  });
}

function formatLots(shares) {
  // 股數轉換為「張」（1張=1000股），並附上正負號
  const lots = Math.round(shares / 1000);
  return `${lots >= 0 ? '+' : ''}${lots.toLocaleString('zh-TW')}張`;
}

function formatInstitutionalLine(inst) {
  if (!inst) return '';
  const parts = [
    `外資${formatLots(inst.foreign_net)}`,
    `投信${formatLots(inst.trust_net)}`,
    `自營${formatLots(inst.dealer_net)}`,
  ];
  return `法人：${parts.join(' ')}`;
}

function formatMarginLine(margin) {
  if (!margin) return '';
  const balanceLots = Math.round(margin.margin_balance / 1000).toLocaleString('zh-TW');
  const changeLots = formatLots(margin.margin_change);
  return `融資餘額 ${balanceLots}張（${changeLots}）`;
}

function renderHoldings() {
  const list = mergedHoldings();
  $('#holdingCount').textContent = list.length;
  $('#portfolioMessage').textContent = list.length
    ? `正在追蹤 ${list.length} 檔持股；每次排程產生報告時會一併更新個股摘要。`
    : '加入你的持股後，這裡會自動彙整每檔股票的盤前資訊與風險提示。';
  $('#holdingsBody').innerHTML = list.length ? list.map((stock) => {
    const priceLine = stock.price
      ? `<div class="stock-price ${stock.price_trend || ''}">${escapeHtml(stock.price)} <small>${escapeHtml(stock.price_change || '')}</small></div>` : '';
    const instLine = formatInstitutionalLine(stock.institutional);
    const marginLine = formatMarginLine(stock.margin);
    const extraLines = [instLine, marginLine].filter(Boolean).map(t => `<div class="reason-extra">${escapeHtml(t)}</div>`).join('');
    return `<tr><td><div class="stock-name">${escapeHtml(stock.name)}</div><div class="stock-code">${escapeHtml(stock.symbol)}${stock.cost ? ` · 成本 ${escapeHtml(String(stock.cost))}` : ''}</div>${priceLine}</td><td><span class="stock-signal ${stock.tone}">${escapeHtml(stock.signal)}</span></td><td class="reason">${escapeHtml(stock.reason)}${extraLines}</td><td><button class="delete-button" data-edit="${escapeHtml(stock.symbol)}">編輯</button> <button class="delete-button" data-delete="${escapeHtml(stock.symbol)}">移除</button></td></tr>`;
  }).join('')
    : '<tr><td colspan="4" class="reason">尚未加入持股。點擊右上方「新增個股」開始建立你的專屬晨報。</td></tr>';
  localStorage.setItem('premarket-holdings', JSON.stringify(holdings));
}

function renderMeta() {
  const noteEl = document.querySelector('.source-note');
  if (noteEl) noteEl.textContent = usingFallback ? '示範資料' : '自動產出';
  const updatedEl = document.querySelector('.updated');
  const latestTimestamp = reportData.prices_updated_at || reportData.generated_at;
  if (updatedEl && latestTimestamp) {
    const d = new Date(latestTimestamp);
    updatedEl.innerHTML = `<i></i> 資料更新於 ${d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
  }
}

function renderAll() {
  $('#reportDate').textContent = reportData.report_date_text || todayText();
  renderBriefing();
  renderTaiex();
  renderMarkets();
  renderNews();
  renderSectors();
  renderHoldings();
  renderMeta();
}

/* ---------------- 工具函式 ---------------- */

function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;', "'":'&#39;','"':'&quot;' })[c]); }
function showToast(message) { const toast = $('#toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2700); }
function openHolding(stock) { editingSymbol = stock?.symbol || null; $('#dialogTitle').textContent = stock ? '編輯持股' : '新增持股'; $('#symbolInput').value = stock?.symbol || ''; $('#nameInput').value = stock?.name || ''; $('#costInput').value = stock?.cost || ''; $('#holdingDialog').showModal(); }
function todayText() { return new Intl.DateTimeFormat('zh-TW', { year:'numeric', month:'long', day:'numeric', weekday:'long' }).format(new Date()).replace('週', '星期'); }

/* ---------------- 事件綁定 ---------------- */

$('#addHolding').addEventListener('click', () => openHolding());
$('#holdingsBody').addEventListener('click', (event) => {
  const symbol = event.target.dataset.delete || event.target.dataset.edit;
  if (!symbol) return;
  if (event.target.dataset.delete) { holdings = holdings.filter(x => x.symbol !== symbol); renderHoldings(); showToast('已從持股清單移除'); }
  else openHolding(holdings.find(x => x.symbol === symbol));
});
$('#holdingForm').addEventListener('submit', (event) => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  const symbol = $('#symbolInput').value.trim(); const name = $('#nameInput').value.trim(); const cost = $('#costInput').value.trim();
  if (!symbol || !name) return;
  const newItem = { symbol, name, cost, signal: '待更新', reason: '加入後，下次排程晨報將根據市場與新聞訊號自動產出摘要。', tone: 'watch' };
  if (editingSymbol) holdings = holdings.map(x => x.symbol === editingSymbol ? { ...x, ...newItem } : x);
  else if (holdings.some(x => x.symbol === symbol)) { showToast('這檔股票已在持股清單中'); return; }
  else holdings.push(newItem);
  $('#holdingDialog').close(); renderHoldings(); showToast(editingSymbol ? '持股資料已更新' : '已加入持股清單');
});
$('#openSettings').addEventListener('click', () => $('#settingsDialog').showModal());
$('#saveSettings').addEventListener('click', () => { localStorage.setItem('premarket-settings', JSON.stringify({ time: $('#scheduleTime').value, notifications: $('#notificationToggle').checked })); showToast('晨報設定已儲存'); });
$('#refreshReport').addEventListener('click', () => {
  const button = $('#refreshReport');
  button.disabled = true; button.innerHTML = '更新中…';
  loadReport().finally(() => {
    button.disabled = false; button.innerHTML = '<span>↻</span> 產生最新報告';
    showToast(usingFallback ? '目前讀不到今日的自動報告，顯示為示範資料' : '晨報已更新為最新排程資料');
  });
});
$('#notifyButton').addEventListener('click', async () => { if (!('Notification' in window)) return showToast('此瀏覽器不支援通知'); const permission = await Notification.requestPermission(); showToast(permission === 'granted' ? '通知已啟用' : '尚未取得通知權限'); });
$('#viewAllNews').addEventListener('click', () => showToast('完整新聞列表功能開發中'));
$('#mobileMenu').addEventListener('click', () => $('.sidebar').classList.toggle('open'));
document.querySelectorAll('.nav-item').forEach(link => link.addEventListener('click', () => { document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active')); link.classList.add('active'); $('.sidebar').classList.remove('open'); }));

/* ---------------- 啟動 ---------------- */

loadReport();
