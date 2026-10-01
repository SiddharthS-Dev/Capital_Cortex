// k6 load test for Capital Cortex (R3, §14): 1M-node seed, SLO thresholds.
// Driven by scripts/load_test.py (`make load`), which seeds the load database, starts `api-load`, gets a real
// dev-analyst access token and writes the sampled ids to /data/ids.json.
//
// Env: BASE_URL, TOKEN, DURATION (default 5m), RATE_MULT (default 1 = the arrival rates below),
//      SCENARIOS (comma list; default all five), MODE (rate = open-model arrival rates, default;
//      serial = VUS closed-loop users, for per-request latency of slow endpoints), VUS (default 1),
//      TIMEOUT (client request timeout, default 120s; a timeout counts as a failed request).
import http from 'k6/http';
import { check } from 'k6';

const ids = JSON.parse(open('/data/ids.json'));
const BASE = __ENV.BASE_URL || 'http://api-load:8000';
const DURATION = __ENV.DURATION || '5m';
const MULT = parseFloat(__ENV.RATE_MULT || '1');
const MODE = __ENV.MODE || 'rate';
const VUS = parseInt(__ENV.VUS || '1', 10);
const TIMEOUT = __ENV.TIMEOUT || '120s';
const ONLY = (__ENV.SCENARIOS || '').split(',').map((x) => x.trim()).filter(Boolean);
const AUTH = { Authorization: `Bearer ${__ENV.TOKEN}` };

// Arrival rates at RATE_MULT=1 (requests per second, open model): ~10-15 analysts active at once, each acting
// about every 10 s (the Capital Cortex audience is one company's capital team). RATE_MULT=3 is the stress run.
function scenario(exec, perSecond) {
  if (MODE === 'serial') return { executor: 'constant-vus', exec, vus: VUS, duration: DURATION };
  return {
    executor: 'constant-arrival-rate',
    exec,
    rate: Math.max(1, Math.round(perSecond * MULT * 10)),
    timeUnit: '10s',
    duration: DURATION,
    preAllocatedVUs: 10,
    maxVUs: 100,
  };
}

// scenario -> [executor fn, req/s, endpoint tag, SLO p95 ms]
// SLOs (§11/§14): dashboards p95 < 3 s, graph p95 < 5 s, scoring p95 < 10 s.
// The opportunity list is the Radar screen's read; it is held to the dashboard SLO.
const PLAN = {
  dashboard: ['dashboard', 0.1, 'dashboard_executive', 3000],
  opportunities: ['opportunities', 0.5, 'opportunities_list', 3000],
  neighbourhood: ['neighbourhood', 0.3, 'graph_neighbourhood', 5000],
  paths: ['paths', 0.2, 'graph_paths', 5000],
  rescore: ['rescore', 0.3, 'rescore', 10000],
};
const selected = Object.keys(PLAN).filter((k) => !ONLY.length || ONLY.includes(k));
const scenarios = {};
const thresholds = { checks: ['rate>0.99'] };
for (const k of selected) {
  const [fn, rate, tag, slo] = PLAN[k];
  scenarios[k] = scenario(fn, rate);
  thresholds[`http_req_duration{endpoint:${tag}}`] = [`p(95)<${slo}`];
  thresholds[`http_req_failed{endpoint:${tag}}`] = ['rate<0.01'];
  if (k === 'paths') {
    for (const kind of ['connected', 'warm_intro', 'random']) {
      thresholds[`http_req_duration{endpoint:graph_paths,kind:${kind}}`] = [`p(95)<${slo}`];
    }
  }
}

export const options = {
  scenarios,
  thresholds,
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
  discardResponseBodies: true,
};

const pick = (a) => a[Math.floor(Math.random() * a.length)];

function get(url, endpoint) {
  const r = http.get(`${BASE}${url}`, { headers: AUTH, tags: { endpoint }, timeout: TIMEOUT });
  check(r, { [`${endpoint} 200`]: (x) => x.status === 200 }, { endpoint });
  return r;
}

export function dashboard() {
  get('/v1/dashboards/executive', 'dashboard_executive');
}

export function opportunities() {
  get('/v1/opportunities?limit=50', 'opportunities_list');
}

export function neighbourhood() {
  get(`/v1/graph/query?template=neighbourhood&id=${pick(ids.neighbourhood)}&depth=2`, 'graph_neighbourhood');
}

// ids.paths: [from, to, kind]; kind = connected (3-hop intro chain), warm_intro (self org → org, 2 hops),
// random (two random organisations: usually no path within 4 hops, the worst case)
export function paths() {
  const [from, to, kind] = pick(ids.paths);
  const r = http.get(`${BASE}/v1/graph/paths?from=${from}&to=${to}`, {
    headers: AUTH, tags: { endpoint: 'graph_paths', kind }, timeout: TIMEOUT,
  });
  check(r, { 'graph_paths 200': (x) => x.status === 200 }, { endpoint: 'graph_paths' });
}

export function rescore() {
  const r = http.post(`${BASE}/v1/opportunities/${pick(ids.opportunities)}/rescore`, null, {
    headers: AUTH, tags: { endpoint: 'rescore' }, timeout: TIMEOUT,
  });
  check(r, { 'rescore 200': (x) => x.status === 200 }, { endpoint: 'rescore' });
}

export function handleSummary(data) {
  return { '/out/summary.json': JSON.stringify(data, null, 2) };
}
