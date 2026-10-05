/* Application shell: routing, state, toasts, modals and scan polling. */
(function () {
  "use strict";

  const viewRoot = document.getElementById("view");
  const pageTitle = document.getElementById("page-title");
  const pageSubtitle = document.getElementById("page-subtitle");
  const topbarActions = document.getElementById("topbar-actions");
  const nav = document.getElementById("nav");
  const scanStatusEl = document.getElementById("scan-status");
  const scanStatusText = document.getElementById("scan-status-text");
  const systemMeta = document.getElementById("system-meta");
  const toasts = document.getElementById("toasts");
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modal-title");
  const modalBody = document.getElementById("modal-body");

  const STORAGE_KEY = "git-dashboard-state-v1";

  const defaultState = {
    activityDays: 30,
    bucket: "day",
    detailDays: 90,
    detailTab: "overview",
    branchFilter: "all",
    branchSearch: "",
    repoFilters: { search: "", status: "all", staleness: "all", sort: "last_commit", order: "desc", page: 1 },
  };

  const persisted = readState();
  const state = Object.assign({}, defaultState, persisted, {
    repoFilters: Object.assign({}, defaultState.repoFilters, persisted.repoFilters || {}),
  });

  const ROUTES = [
    { pattern: /^\/$/, title: "Dashboard", subtitle: "Repository health and activity at a glance", view: "dashboard" },
    { pattern: /^\/repositories$/, title: "Repositories", subtitle: "Every registered repository on this machine", view: "repositories" },
    {
      pattern: /^\/repositories\/(\d+)$/,
      title: "Repository",
      subtitle: "Commits, branches, contributors and health",
      view: "repositoryDetail",
      params: (match) => [Number(match[1])],
    },
    { pattern: /^\/activity$/, title: "Activity", subtitle: "Commit activity over time", view: "activity" },
    { pattern: /^\/branches$/, title: "Branches", subtitle: "Branch hygiene across repositories", view: "branches" },
    { pattern: /^\/settings$/, title: "Settings", subtitle: "Configuration, discovery, thresholds and exports", view: "settings" },
  ];

  let currentPath = null;
  let pollTimer = null;
  let lastJobSignature = null;

  /* ------------------------------------------------------------- utilities */
  function readState() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function persistState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      /* storage disabled - state simply stays in memory */
    }
  }

  function toast(message, kind, timeout) {
    const element = document.createElement("div");
    element.className = `toast toast-${kind || "info"}`;
    element.textContent = message;
    toasts.appendChild(element);
    setTimeout(() => {
      element.style.opacity = "0";
      element.style.transition = "opacity 0.25s";
      setTimeout(() => element.remove(), 260);
    }, timeout || 4200);
  }

  function showModal(title, html) {
    modalTitle.textContent = title;
    modalBody.innerHTML = html;
    modal.classList.remove("hidden");
  }

  function hideModal() {
    modal.classList.add("hidden");
  }

  /* ----------------------------------------------------------------- router */
  const ctx = {
    state,
    persistState,
    toast,
    showModal,
    hideModal,
    navigate,
    reload: () => render(currentPath || "/", { force: true }),
    pollScan,
    startScanAll,
  };

  function navigate(path, { replace = false } = {}) {
    if (path === currentPath && !replace) return;
    if (replace) history.replaceState({ path }, "", path);
    else history.pushState({ path }, "", path);
    render(path);
  }

  function matchRoute(path) {
    for (const route of ROUTES) {
      const match = route.pattern.exec(path);
      if (match) return { route, match };
    }
    return null;
  }

  async function render(path, options) {
    const matched = matchRoute(path);
    if (!matched) {
      viewRoot.innerHTML = `<div class="empty"><h3>Page not found</h3><p class="muted">${Fmt.escapeHtml(path)}</p>
        <a class="btn btn-primary" href="/" data-link>Back to dashboard</a></div>`;
      return;
    }
    currentPath = path;
    document.querySelectorAll("#nav a").forEach((link) => {
      const routePath = link.dataset.route;
      const active = routePath === "/" ? path === "/" : path.startsWith(routePath);
      link.classList.toggle("active", active);
    });

    const { route, match } = matched;
    pageTitle.textContent = route.title;
    pageSubtitle.textContent = route.subtitle;
    topbarActions.innerHTML = "";
    viewRoot.innerHTML = `<div class="loading">Loading…</div>`;

    const params = route.params ? route.params(match) : [];
    try {
      await window.Views[route.view](viewRoot, ctx, ...params);
    } catch (error) {
      console.error(error);
      viewRoot.innerHTML = `<div class="empty"><h3>Could not load this view</h3>
        <p class="muted">${Fmt.escapeHtml(error.message)}</p>
        <button class="btn" id="retry-view">Retry</button></div>`;
      const retry = document.getElementById("retry-view");
      if (retry) retry.addEventListener("click", () => render(path, { force: true }));
      toast(error.message, "error", 6000);
    }
    if (options && options.scrollTop) window.scrollTo({ top: 0 });
  }

  /* ----------------------------------------------------------- scan polling */
  function setScanIndicator(kind, text) {
    const dot = scanStatusEl.querySelector(".dot");
    dot.className = `dot dot-${kind}`;
    scanStatusText.textContent = text;
  }

  async function updateScanStatus() {
    try {
      const status = await Api.scanStatus();
      const job = status.job;
      if (status.running && job) {
        const progress = job.progress && job.progress.total ? ` (${job.progress.done}/${job.progress.total})` : "";
        setScanIndicator("busy", `Scanning${progress}: ${job.current || job.kind}`);
      } else if (job && job.status === "failed") {
        setScanIndicator("bad", `Last scan failed`);
      } else if (job && job.status === "partial") {
        setScanIndicator("warn", "Last scan partially failed");
      } else if (job) {
        setScanIndicator("ok", `Scan ${job.status}`);
      } else {
        setScanIndicator("idle", "Idle — no scans yet");
      }
    } catch (error) {
      setScanIndicator("bad", "Server unreachable");
    }
  }

  function jobSignature(job) {
    return job ? `${job.id}:${job.status}:${job.progress ? job.progress.done : 0}` : "none";
  }

  async function pollScan() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      let status;
      try {
        status = await Api.scanStatus();
      } catch (error) {
        return;
      }
      const job = status.job;
      const signature = jobSignature(job);
      await updateScanStatus();

      if (job && job.status !== "running" && signature !== lastJobSignature) {
        const previous = lastJobSignature;
        lastJobSignature = signature;
        if (previous !== null && previous !== "none") {
          const report = job.report || {};
          if (job.status === "failed") {
            toast(`Scan failed: ${job.error || "unknown error"}`, "error", 8000);
          } else {
            const added = job.commits_added || report.commits_added || 0;
            const failed = report.failed || 0;
            toast(
              `Scan ${job.status}: ${job.progress ? job.progress.done : 0} repository(ies), ${added} new commit(s)${failed ? `, ${failed} failed` : ""}.`,
              failed ? "warn" : "ok",
              7000
            );
            const failures = (report.repositories || []).filter((item) => item.status === "failed");
            failures.slice(0, 3).forEach((item) => toast(`${item.name}: ${item.error}`, "error", 9000));
          }
          render(currentPath || "/", { force: true });
        }
      }
      if (!status.running && lastJobSignature !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 1500);
    // take an immediate snapshot so completion detection works even for fast scans
    try {
      const status = await Api.scanStatus();
      lastJobSignature = jobSignature(status.job);
    } catch (error) {
      lastJobSignature = null;
    }
  }

  async function startScanAll(options) {
    try {
      const result = await Api.scanAll(Object.assign({ incremental: true, discover: true, background: true }, options || {}));
      lastJobSignature = null;
      toast(result.message || "Scan started…", "info");
      await updateScanStatus();
      pollScan();
    } catch (error) {
      toast(error.message, "error", 7000);
    }
  }

  async function refreshSystemMeta() {
    try {
      const health = await Api.health();
      systemMeta.innerHTML = `
        <span>git-dashboard ${Fmt.escapeHtml(health.version)}</span>
        <span>git ${health.git_available ? Fmt.escapeHtml(health.git_version || "ok") : "MISSING"}</span>
        <span>${Fmt.number(health.database.imported_repositories)} repositories</span>
        <span>db ${Fmt.bytes(health.database.size_bytes)} · schema v${Fmt.number(health.database.schema_version)}</span>
      `;
    } catch (error) {
      systemMeta.innerHTML = `<span>Server unreachable</span>`;
    }
  }

  /* ------------------------------------------------------------- shell wiring */
  nav.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-route]");
    if (!link) return;
    event.preventDefault();
    navigate(link.dataset.route);
  });

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-link]");
    if (link && link.getAttribute("href") && link.getAttribute("href").startsWith("/")) {
      event.preventDefault();
      navigate(link.getAttribute("href"));
    }
  });

  window.addEventListener("popstate", () => render(location.pathname + location.search, { scrollTop: true }));

  document.getElementById("btn-scan-all").addEventListener("click", () => startScanAll({ discover: true, incremental: true }));
  document.getElementById("btn-refresh").addEventListener("click", () => {
    refreshSystemMeta();
    updateScanStatus();
    render(currentPath || "/", { force: true });
  });
  document.getElementById("modal-close").addEventListener("click", hideModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) hideModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideModal();
  });

  /* ------------------------------------------------------------------ start */
  async function boot() {
    await refreshSystemMeta();
    await updateScanStatus();
    await render(location.pathname + location.search);
    const status = await Api.scanStatus().catch(() => null);
    if (status && status.running) {
      lastJobSignature = null;
      pollScan();
    }
    setInterval(refreshSystemMeta, 30000);
  }

  boot();
})();
