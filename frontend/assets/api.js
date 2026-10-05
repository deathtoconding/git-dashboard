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
    settings: () => api.get("/settings"),
    saveSettings: (body) => api.put("/settings", body),
    exportJson: (repositoryId) => api.get(`/export/json${repositoryId ? `?repository_id=${repositoryId}` : ""}`),
    exportCsvUrl: (table, repositoryId) =>
      `${API_BASE}/export/csv/${table}${repositoryId ? `?repository_id=${repositoryId}` : ""}`,
    backup: () => api.post("/export/backup"),
    snapshot: () => api.post("/export/snapshot"),
  };

  /* ------------------------------------------------------------- formatting */
  const numberFormat = new Intl.NumberFormat();

  function fmtNumber(value) {
    if (value === null || value === undefined || value === "") return "0";
    return numberFormat.format(Math.round(Number(value)));
  }

  function fmtDuration(days) {
    if (days === null || days === undefined) return "never";
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return `${days} days ago`;
    if (days < 365) return `${Math.round(days / 30)} mo ago`;
    return `${(days / 365).toFixed(1)} yr ago`;
  }

  function fmtDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function fmtDay(value) {
    if (!value) return "—";
    const date = new Date(value.length <= 10 ? `${value}T00:00:00Z` : value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
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

  function stateBadge(repository) {
    const map = {
      clean: ["badge-ok", "clean"],
      dirty: ["badge-warn", "uncommitted"],
      detached: ["badge-warn", "detached HEAD"],
      bare: ["badge-neutral", "bare"],
      empty: ["badge-neutral", "no commits"],
      error: ["badge-bad", "error"],
      unknown: ["badge-neutral", "not scanned"],
    };
    const [cls, label] = map[repository.state] || map.unknown;
    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  }

  function stalenessBadge(staleness, label) {
    const map = {
      active: "badge-ok",
      inactive: "badge-info",
      stale: "badge-warn",
      abandoned: "badge-bad",
      empty: "badge-neutral",
      unknown: "badge-neutral",
    };
    return `<span class="badge ${map[staleness] || "badge-neutral"}">${escapeHtml(label || staleness || "unknown")}</span>`;
  }

  function healthColor(score) {
    if (score >= 85) return "#3fb950";
    if (score >= 70) return "#7bd88f";
    if (score >= 55) return "#d29922";
    if (score >= 40) return "#e3873f";
    return "#f85149";
  }

  function healthBadge(health) {
    if (!health) return '<span class="badge badge-neutral">—</span>';
    const score = Math.round(health.score || 0);
    return `<span class="badge" style="background:${healthColor(score)}22;color:${healthColor(score)};border-color:${healthColor(score)}55">${health.grade || ""} ${score}</span>`;
  }

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

  global.Api = api;
  global.Fmt = {
    number: fmtNumber,
    duration: fmtDuration,
    date: fmtDate,
    day: fmtDay,
    bytes: fmtBytes,
    shortSha,
    escapeHtml,
    stateBadge,
    stalenessBadge,
    healthBadge,
    healthColor,
    queryString,
    debounce,
    download,
  };
})(window);
