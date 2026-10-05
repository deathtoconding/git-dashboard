/* Tiny API client + shared helpers. No dependencies, no build step. */
(function (global) {
  "use strict";

  const API_BASE = "/api";

  async function request(path, options) {
    const response = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
      body: options && options.body ? JSON.stringify(options.body) : undefined,
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        payload = { detail: text };
      }
    }
    if (!response.ok) {
      const detail = payload && payload.detail ? payload.detail : response.statusText;
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
        : String(detail);
      const failure = new Error(message);
      failure.status = response.status;
      failure.payload = payload;
      throw failure;
    }
    return payload;
  }

  const api = {
    base: API_BASE,
    get: (path) => request(path),
    post: (path, body) => request(path, { method: "POST", body: body || {} }),
    put: (path, body) => request(path, { method: "PUT", body: body || {} }),
    del: (path) => request(path, { method: "DELETE" }),

    health: () => api.get("/health"),
    dashboard: (days, bucket) => api.get(`/dashboard?days=${days}&bucket=${bucket || "day"}`),
    repositories: (query) => api.get(`/repositories?${query}`),
    repository: (id) => api.get(`/repositories/${id}`),
    createRepository: (body) => api.post("/repositories", body),
    deleteRepository: (id) => api.del(`/repositories/${id}`),
    discover: (body) => api.post("/repositories/discover", body),
    suggestions: (limit) => api.get(`/repositories/suggestions?limit=${limit || 50}`),
    scanRepository: (id, body) => api.post(`/repositories/${id}/scan`, body || {}),
    scanAll: (body) => api.post("/scan/full", body || { incremental: true, discover: true, background: true }),
    scanStatus: () => api.get("/scan/status"),
    scanHistory: (limit) => api.get(`/scan/history?limit=${limit || 10}`),
    commits: (id, query) => api.get(`/repositories/${id}/commits?${query}`),
    commit: (id, sha) => api.get(`/repositories/${id}/commits/${sha}`),
    branches: (id, query) => api.get(`/repositories/${id}/branches?${query}`),
    allBranches: (query) => api.get(`/branches?${query}`),
    metrics: (id) => api.get(`/repositories/${id}/metrics`),
    repoActivity: (id, days, bucket) => api.get(`/repositories/${id}/activity?days=${days}&bucket=${bucket || "day"}`),
    contributors: (id) => api.get(`/repositories/${id}/contributors`),
    heatmap: (id, days) => api.get(`/repositories/${id}/heatmap?days=${days || 365}`),
    fileChurn: (id) => api.get(`/repositories/${id}/file-churn?limit=15`),
    health_: (id) => api.get(`/repositories/${id}/health`),
    status: (id) => api.get(`/repositories/${id}/status`),
    insights: (limit) => api.get(`/insights?limit=${limit || 25}`),
    activity: (days, bucket, repositoryId) =>
      api.get(`/activity?days=${days}&bucket=${bucket || "day"}${repositoryId ? `&repository_id=${repositoryId}` : ""}`),
    activityByRepository: (days, bucket) => api.get(`/activity/repositories?days=${days}&bucket=${bucket || "day"}`),
    settings: () => api.get("/settings"),
    saveSettings: (body) => api.put("/settings", body),
    exportJson: (repositoryId) => api.get(`/export/json${repositoryId ? `?repository_id=${repositoryId}` : ""}`),
    exportCsvUrl: (table, repositoryId) =>
      `${API_BASE}/export/csv/${table}${repositoryId ? `?repository_id=${repositoryId}` : ""}`,
    backup: () => api.post("/export/backup"),
    snapshot: () => api.post("/export/snapshot"),
  };

  /* ------------------------------------------------------------- numbers --- */
  const numberFormat = new Intl.NumberFormat();
  const compactFormat = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

  function fmtNumber(value) {
    if (value === null || value === undefined || value === "") return "0";
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return numberFormat.format(Math.abs(number) < 1 && number !== 0 ? number : Math.round(number));
  }

  function fmtCompact(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "0";
    return Math.abs(number) >= 10000 ? compactFormat.format(number) : fmtNumber(number);
  }

  function fmtDecimal(value, digits) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "0";
    return number.toFixed(digits === undefined ? 1 : digits);
  }

  function fmtPercent(value, digits) {
    return `${fmtDecimal(value, digits === undefined ? 0 : digits)}%`;
  }

  function fmtSigned(value) {
    const number = Number(value) || 0;
    return `${number > 0 ? "+" : ""}${fmtNumber(number)}`;
  }

  function fmtDuration(days) {
    if (days === null || days === undefined) return "never";
    const value = Number(days);
    if (value <= 0) return "today";
    if (value === 1) return "yesterday";
    if (value < 30) return `${value} days ago`;
    if (value < 365) return `${Math.round(value / 30)} mo ago`;
    return `${(value / 365).toFixed(1)} yr ago`;
  }

  function fmtDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function fmtDay(value) {
    if (!value) return "—";
    const date = new Date(String(value).length <= 10 ? `${value}T00:00:00Z` : value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
  }

  function fmtShortDay(value) {
    if (!value) return "—";
    const date = new Date(String(value).length <= 10 ? `${value}T00:00:00Z` : value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
  }

  function fmtBytes(bytes) {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
    return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  function shortSha(sha) {
    return sha ? String(sha).slice(0, 8) : "—";
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* --------------------------------------------------------------- people --- */
  function initials(name) {
    const parts = String(name || "?").trim().split(/[\s._-]+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function hueFor(text) {
    let hash = 0;
    for (let index = 0; index < String(text).length; index += 1) {
      hash = (hash * 31 + String(text).charCodeAt(index)) % 360;
    }
    return hash;
  }

  function avatar(name, extraClass) {
    const hue = hueFor(name || "?");
    const cls = extraClass ? ` ${extraClass}` : "";
    return `<span class="avatar${cls}" style="background:hsl(${hue} 46% 38%);color:#fff" title="${escapeHtml(name || "")}" aria-hidden="true">${escapeHtml(initials(name))}</span>`;
  }

  /* --------------------------------------------------------------- tones --- */
  const HEALTH_TONES = [
    { min: 85, tone: "ok", variable: "--ok" },
    { min: 70, tone: "ok", variable: "--ok" },
    { min: 55, tone: "warn", variable: "--warn" },
    { min: 40, tone: "warn", variable: "--danger" },
    { min: 0, tone: "danger", variable: "--danger" },
  ];

  function healthTone(score) {
    const value = Number(score) || 0;
    const entry = HEALTH_TONES.find((candidate) => value >= candidate.min) || HEALTH_TONES[HEALTH_TONES.length - 1];
    return entry.tone;
  }

  /** CSS colour for a score, usable in inline styles and SVG. */
  function healthColor(score) {
    const value = Number(score) || 0;
    const entry = HEALTH_TONES.find((candidate) => value >= candidate.min) || HEALTH_TONES[HEALTH_TONES.length - 1];
    return `var(${entry.variable})`;
  }

  function stateBadge(repository) {
    const map = {
      clean: ["ok", "clean"],
      dirty: ["warn", "uncommitted"],
      detached: ["warn", "detached HEAD"],
      bare: ["neutral", "bare"],
      empty: ["neutral", "no commits"],
      error: ["danger", "error"],
      unknown: ["neutral", "not scanned"],
    };
    const [tone, label] = map[repository.state] || map.unknown;
    return `<span class="badge badge--${tone}">${escapeHtml(label)}</span>`;
  }

  function stalenessBadge(staleness, label) {
    const map = { active: "ok", inactive: "info", stale: "warn", abandoned: "danger", empty: "neutral", unknown: "neutral" };
    return `<span class="badge badge--${map[staleness] || "neutral"}">${escapeHtml(label || staleness || "unknown")}</span>`;
  }

  function healthBadge(health) {
    if (!health) return '<span class="badge badge--neutral">—</span>';
    const score = Math.round(health.score || 0);
    const tone = healthTone(score);
    return `<span class="badge badge--${tone}">${escapeHtml(health.grade || "")} ${score}</span>`;
  }

  /* --------------------------------------------------------------- markup --- */
  function meter(value, options) {
    const opts = options || {};
    const max = Number(opts.max || 100) || 100;
    const percentage = Math.max(0, Math.min(100, (Number(value) || 0) / max * 100));
    const label = opts.label === undefined ? fmtNumber(value) : opts.label;
    const color = opts.color || "var(--accent)";
    return `<span class="meter${opts.size === "lg" ? " meter-lg" : ""}" role="img" aria-label="${escapeHtml(String(label))}">
      <span class="meter-track"><span class="meter-fill" style="width:${percentage.toFixed(1)}%;background:${color}"></span></span>
      ${opts.showValue === false ? "" : `<span class="meter-value">${escapeHtml(String(label))}</span>`}
    </span>`;
  }

  function skeleton(lines) {
    const count = lines || 3;
    const widths = ["w-80", "w-60", "w-30"];
    return `<div class="skeleton-group">${Array.from({ length: count })
      .map((_, index) => `<div class="skeleton skeleton-line ${widths[index % widths.length]}"></div>`)
      .join("")}</div>`;
  }

  function emptyIcon(name) {
    return Icons.get(name || "info");
  }

  /* ---------------------------------------------------------------- utils --- */
  function queryString(params) {
    const search = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "" && value !== "all") search.set(key, value);
    });
    return search.toString();
  }

  function debounce(fn, delay) {
    let timer = null;
    return function debounced(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  function download(url) {
    const link = document.createElement("a");
    link.href = url;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function copy(text) {
    try {
      if (navigator.clipboard && window.isSecureContext !== false) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (error) {
      /* fall through to the legacy path */
    }
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    } catch (error) {
      return false;
    }
  }

  global.Api = api;
  global.Fmt = {
    number: fmtNumber,
    compact: fmtCompact,
    decimal: fmtDecimal,
    percent: fmtPercent,
    signed: fmtSigned,
    duration: fmtDuration,
    date: fmtDate,
    day: fmtDay,
    shortDay: fmtShortDay,
    bytes: fmtBytes,
    shortSha,
    escapeHtml,
    initials,
    avatar,
    meter,
    skeleton,
    emptyIcon,
    healthTone,
    healthColor,
    stateBadge,
    stalenessBadge,
    healthBadge,
    queryString,
    debounce,
    download,
    copy,
  };
})(window);
