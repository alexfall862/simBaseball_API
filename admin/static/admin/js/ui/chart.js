// ui/chart.js — Chart.js lifecycle wrapper. Charts are destroyed when the
// view's AbortSignal fires, so no feature needs a global per chart.
//
//   const c = mountChart(canvasEl, { type: 'bar', data, options }, ctx.signal);
//   c.update(newData);   c.destroy();

const THEME = {
  grid: 'rgba(148, 163, 184, 0.12)',
  tick: '#9ca3af',
  legend: '#d1d5db',
  palette: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6'],
};

export const CHART_COLORS = THEME.palette;

export function color(i, alpha = 1) {
  const hex = THEME.palette[i % THEME.palette.length];
  if (alpha >= 1) return hex;
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function applyTheme(config) {
  const Chart = window.Chart;
  if (Chart && Chart.defaults) {
    Chart.defaults.color = THEME.tick;
    Chart.defaults.borderColor = THEME.grid;
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif";
  }
  const options = config.options || (config.options = {});
  options.responsive = options.responsive !== false;
  options.maintainAspectRatio = options.maintainAspectRatio ?? false;
  options.plugins = options.plugins || {};
  options.plugins.legend = options.plugins.legend || {};
  options.plugins.legend.labels = { color: THEME.legend, boxWidth: 12, ...(options.plugins.legend.labels || {}) };
  if (options.scales) {
    for (const s of Object.values(options.scales)) {
      s.grid = { color: THEME.grid, ...(s.grid || {}) };
      s.ticks = { color: THEME.tick, ...(s.ticks || {}) };
    }
  }
  // Auto-colour datasets that did not specify a colour.
  const ds = (config.data && config.data.datasets) || [];
  ds.forEach((d, i) => {
    if (!d.backgroundColor && !d.borderColor) {
      d.borderColor = color(i);
      d.backgroundColor = config.type === 'line' ? color(i, 0.15) : color(i, 0.75);
    }
    if (config.type === 'line' && d.tension == null) d.tension = 0.25;
  });
  return config;
}

export function mountChart(canvas, config, signal) {
  const Chart = window.Chart;
  if (!Chart) {
    console.warn('Chart.js not loaded');
    return { update() {}, destroy() {}, chart: null };
  }
  if (!(canvas instanceof HTMLCanvasElement)) {
    const c = document.createElement('canvas');
    canvas.innerHTML = '';
    canvas.appendChild(c);
    canvas = c;
  }
  const chart = new Chart(canvas.getContext('2d'), applyTheme(config));
  const handle = {
    chart,
    update(data, options) {
      if (data) chart.data = data;
      if (options) Object.assign(chart.options, options);
      applyTheme({ type: chart.config.type, data: chart.data, options: chart.options });
      chart.update();
    },
    destroy() { try { chart.destroy(); } catch (_) { /* already gone */ } },
  };
  if (signal) signal.addEventListener('abort', handle.destroy, { once: true });
  return handle;
}

/** Wrap a canvas in a sized container. Returns the canvas element. */
export function chartCanvas(parent, { height = 320 } = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  wrap.style.height = `${height}px`;
  const c = document.createElement('canvas');
  wrap.appendChild(c);
  parent.appendChild(wrap);
  return c;
}
