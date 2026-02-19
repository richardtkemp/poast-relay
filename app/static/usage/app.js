dayjs.extend(dayjs_plugin_relativeTime);

const API = '/usage/api';
const COLORS = {
  input:      '#58a6ff',
  output:     '#3fb950',
  cacheRead:  '#d29922',
  cacheWrite: '#bc8cff',
  cost:       '#f85149',
};

// State
let state = {
  agent: '',
  sessionId: '',
  sessionAgent: '',
  hours: 24,
  metric: 'tokens',   // 'tokens' | 'cost'
  sessions: [],
};

// Chart instances
let charts = {};

// --- DOM refs ---
const $agent = document.getElementById('filter-agent');
const $session = document.getElementById('filter-session');
const presetButtons = document.querySelectorAll('.time-presets button');
const $toggleTokens = document.getElementById('toggle-tokens');
const $toggleCost = document.getElementById('toggle-cost');

// --- Helpers ---
function sinceISO() {
  return new Date(Date.now() - state.hours * 3600_000).toISOString();
}

function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function fmtCost(n) {
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(3);
  return '$' + n.toFixed(4);
}

function pct(n) {
  return (n * 100).toFixed(1) + '%';
}

async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

// --- Chart defaults ---
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, sans-serif';
Chart.defaults.font.size = 11;

function createLineChart(canvasId, datasets, labels) {
  if (charts[canvasId]) charts[canvasId].destroy();
  const ctx = document.getElementById(canvasId).getContext('2d');
  charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true },
      },
    },
  });
}

function createBarChart(canvasId, labels, data, colors) {
  if (charts[canvasId]) charts[canvasId].destroy();
  const ctx = document.getElementById(canvasId).getContext('2d');
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors || COLORS.input,
        borderRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true },
        y: { grid: { display: false } },
      },
    },
  });
}

// --- Data loading ---
async function loadSessions() {
  state.sessions = await fetchJSON(`${API}/sessions`);

  // Populate agent dropdown
  const agents = [...new Set(state.sessions.map(s => s.agent))].sort();
  $agent.innerHTML = '<option value="">All</option>' +
    agents.map(a => `<option value="${a}">${a}</option>`).join('');

  populateSessionDropdown();
}

function populateSessionDropdown() {
  let filtered = state.sessions;
  if (state.agent) {
    filtered = filtered.filter(s => s.agent === state.agent);
  }
  $session.innerHTML = '<option value="">All (aggregate)</option>' +
    filtered.slice(0, 50).map(s => {
      const label = s.sessionKey || s.sessionId.slice(0, 8);
      const age = s.updatedAt ? dayjs(s.updatedAt).fromNow() : '';
      return `<option value="${s.agent}/${s.sessionId}">${s.agent}/${label} ${age}</option>`;
    }).join('');
}

async function loadAggregate() {
  const params = new URLSearchParams({ since: sinceISO() });
  if (state.agent) params.set('agent', state.agent);
  const gran = state.hours <= 24 ? 'hour' : 'day';
  params.set('granularity', gran);

  const data = await fetchJSON(`${API}/aggregate?${params}`);
  renderAggregateCharts(data);
}

async function loadSessionTurns() {
  const params = new URLSearchParams({ since: sinceISO() });
  const data = await fetchJSON(
    `${API}/sessions/${state.sessionAgent}/${state.sessionId}/turns?${params}`
  );
  renderTurnCharts(data);
}

// --- Rendering ---
function updateSummary(totals) {
  document.getElementById('stat-tokens').textContent = fmt(totals.totalTokens);
  document.getElementById('stat-cost').textContent = fmtCost(totals.totalCost);
  const totalCache = totals.cacheRead + totals.cacheWrite;
  const hitRate = totalCache > 0 ? totals.cacheRead / totalCache : 0;
  document.getElementById('stat-cache').textContent = pct(hitRate);
  document.getElementById('stat-turns').textContent = fmt(totals.turns);
}

function renderAggregateCharts(buckets) {
  if (!buckets.length) {
    updateSummary({ totalTokens: 0, totalCost: 0, cacheRead: 0, cacheWrite: 0, turns: 0 });
    ['chart-usage', 'chart-cost', 'chart-cache'].forEach(id => {
      if (charts[id]) charts[id].destroy();
    });
    return;
  }

  const labels = buckets.map(b => {
    const d = dayjs(b.bucket);
    return state.hours <= 24 ? d.format('HH:mm') : d.format('MMM D');
  });

  // Summary
  const totals = buckets.reduce((acc, b) => {
    acc.totalTokens += b.input + b.output + b.cacheRead + b.cacheWrite;
    acc.totalCost += b.totalCost;
    acc.cacheRead += b.cacheRead;
    acc.cacheWrite += b.cacheWrite;
    acc.turns += b.turns;
    return acc;
  }, { totalTokens: 0, totalCost: 0, cacheRead: 0, cacheWrite: 0, turns: 0 });
  updateSummary(totals);

  // Usage over time
  const mkDS = (key, color) => ({
    label: key,
    data: buckets.map(b => b[key]),
    borderColor: color,
    backgroundColor: color + '20',
    fill: true,
    tension: 0.3,
    pointRadius: 2,
  });
  createLineChart('chart-usage', [
    mkDS('input', COLORS.input),
    mkDS('output', COLORS.output),
    mkDS('cacheRead', COLORS.cacheRead),
    mkDS('cacheWrite', COLORS.cacheWrite),
  ], labels);

  // Cost over time
  createLineChart('chart-cost', [{
    label: 'Cost',
    data: buckets.map(b => b.totalCost),
    borderColor: COLORS.cost,
    backgroundColor: COLORS.cost + '20',
    fill: true,
    tension: 0.3,
    pointRadius: 2,
  }], labels);

  // Cache efficiency
  createLineChart('chart-cache', [{
    label: 'Cache Hit Rate',
    data: buckets.map(b => {
      const total = b.cacheRead + b.cacheWrite;
      return total > 0 ? b.cacheRead / total : 0;
    }),
    borderColor: COLORS.cacheRead,
    backgroundColor: COLORS.cacheRead + '20',
    fill: true,
    tension: 0.3,
    pointRadius: 2,
  }], labels);
}

function renderTurnCharts(turns) {
  if (!turns.length) {
    updateSummary({ totalTokens: 0, totalCost: 0, cacheRead: 0, cacheWrite: 0, turns: 0 });
    return;
  }

  // Bucket turns by hour or individual
  const bucketMap = {};
  const gran = state.hours <= 24 ? 'hour' : 'day';
  turns.forEach(t => {
    const d = dayjs(t.timestamp);
    const key = gran === 'hour' ? d.format('YYYY-MM-DDTHH:00:00Z') : d.format('YYYY-MM-DD');
    if (!bucketMap[key]) {
      bucketMap[key] = { bucket: key, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalCost: 0, turns: 0 };
    }
    const b = bucketMap[key];
    const u = t.usage;
    b.input += u.input || 0;
    b.output += u.output || 0;
    b.cacheRead += u.cacheRead || 0;
    b.cacheWrite += u.cacheWrite || 0;
    b.totalCost += (u.cost && u.cost.total) || 0;
    b.turns += 1;
  });

  const buckets = Object.values(bucketMap).sort((a, b) => a.bucket.localeCompare(b.bucket));
  renderAggregateCharts(buckets);
}

async function loadSessionComparison() {
  // Get all sessions and compute per-session costs from turns
  const filtered = state.agent
    ? state.sessions.filter(s => s.agent === state.agent)
    : state.sessions;

  // Fetch turns for top sessions (limited to avoid too many requests)
  const candidates = filtered.slice(0, 30);
  const results = await Promise.all(
    candidates.map(async (s) => {
      const params = new URLSearchParams({ since: sinceISO() });
      const turns = await fetchJSON(
        `${API}/sessions/${s.agent}/${s.sessionId}/turns?${params}`
      );
      const totalCost = turns.reduce((sum, t) => sum + ((t.usage.cost && t.usage.cost.total) || 0), 0);
      const label = (s.sessionKey || s.sessionId.slice(0, 8));
      return { label: `${s.agent}/${label}`, totalCost };
    })
  );

  // Sort by cost descending, take top 20
  results.sort((a, b) => b.totalCost - a.totalCost);
  const top = results.filter(r => r.totalCost > 0).slice(0, 20);

  if (top.length) {
    createBarChart(
      'chart-sessions',
      top.map(r => r.label),
      top.map(r => r.totalCost),
      top.map(() => COLORS.cost + 'cc'),
    );
  }
}

// --- Event handlers ---
$agent.addEventListener('change', () => {
  state.agent = $agent.value;
  state.sessionId = '';
  state.sessionAgent = '';
  $session.value = '';
  populateSessionDropdown();
  refresh();
});

$session.addEventListener('change', () => {
  const val = $session.value;
  if (val) {
    const [agent, ...rest] = val.split('/');
    state.sessionAgent = agent;
    state.sessionId = rest.join('/');
  } else {
    state.sessionAgent = '';
    state.sessionId = '';
  }
  refresh();
});

presetButtons.forEach(btn => {
  btn.addEventListener('click', () => {
    presetButtons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.hours = parseInt(btn.dataset.hours, 10);
    refresh();
  });
});

$toggleTokens.addEventListener('click', () => {
  state.metric = 'tokens';
  $toggleTokens.classList.add('active');
  $toggleCost.classList.remove('active');
  refresh();
});

$toggleCost.addEventListener('click', () => {
  state.metric = 'cost';
  $toggleCost.classList.add('active');
  $toggleTokens.classList.remove('active');
  refresh();
});

// --- Refresh ---
let refreshTimer = null;
function refresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    if (state.sessionId) {
      await loadSessionTurns();
    } else {
      await loadAggregate();
    }
    loadSessionComparison();
  }, 150);
}

// --- Init ---
(async () => {
  await loadSessions();
  refresh();
})();
