/* Application shell: routing, state, theme, command palette, toasts, modals,
   keyboard shortcuts and scan progress. */
(function () {
  "use strict";

  const viewRoot = document.getElementById("view");
  const pageTitle = document.getElementById("page-title");
  const pageBadge = document.getElementById("page-badge");
  const pageSubtitle = document.getElementById("page-subtitle");
  const topbarActions = document.getElementById("topbar-actions");
  const nav = document.getElementById("nav");
  const scanStatusEl = document.getElementById("scan-status");
  const scanStatusText = document.getElementById("scan-status-text");
  const scanProgress = document.getElementById("scan-progress");
  const scanAllButton = document.getElementById("btn-scan-all");
  const refreshButton = document.getElementById("btn-refresh");
  const systemMeta = document.getElementById("system-meta");
  const brandMark = document.getElementById("brand-mark");

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

  const NAV_ITEMS = [
    { route: "/", icon: "dashboard", label: "Dashboard" },
    { route: "/repositories", icon: "repositories", label: "Repositories", badge: "repositories" },
    { route: "/activity", icon: "activity", label: "Activity" },
    { route: "/branches", icon: "branches", label: "Branches" },
    { route: "/settings", icon: "settings", label: "Settings" },
  ];

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
  let counts = { repositories: null, dirty: null };
  let repoCache = null;
  let chord = null;

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

  const toast = (message, kind, timeout) => UI.toast(message, kind, timeout);

  function isTypingTarget(target) {
    if (!target) return false;
    const tag = String(target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
  }

  /* ----------------------------------------------------------------- router */
  const ctx = {
    state,
    persistState,
    toast,
    showModal: (title, html) => UI.modal.open({ title, html }),
    hideModal: () => UI.modal.close(),
    navigate,
    reload: () => render(currentPath || "/", { force: true }),
    pollScan,
    startScanAll,
    openPalette,
    counts: () => counts,
  };

  function navigate(path, options) {
    const opts = options || {};
    if (path === currentPath && !opts.force) return;
    if (opts.replace) history.replaceState({ path }, "", path);
    else history.pushState({ path }, "", path);
    render(path, { focus: true });
  }

  function matchRoute(path) {
    for (const route of ROUTES) {
      const match = route.pattern.exec(path);
      if (match) return { route, match };
    }
    return null;
  }

  function paintNav(path) {
    nav.querySelectorAll("a[data-route]").forEach((link) => {
      const routePath = link.dataset.route;
      const active = routePath === "/" ? path === "/" : path.startsWith(routePath);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function notFound(path) {
    viewRoot.innerHTML = `<div class="empty-state">${Icons.get("search")}
      <h3>Page not found</h3><p class="mono">${Fmt.escapeHtml(path)}</p>
      <a class="btn btn-primary mt-8" href="/" data-link>${Icons.get("chevronLeft")}Back to dashboard</a></div>`;
  }

  async function render(path, options) {
    const opts = options || {};
    const matched = matchRoute(path);
    if (!matched) {
      currentPath = path;
      paintNav(path);
      notFound(path);
      return;
    }
    currentPath = path;
    paintNav(path);

    const { route, match } = matched;
    pageTitle.textContent = route.title;
    pageSubtitle.textContent = route.subtitle;
    document.title = `${route.title} · Local Git Dashboard`;
    viewRoot.innerHTML = UI.loading();
    if (opts.focus) viewRoot.focus({ preventScroll: true });

    const params = route.params ? route.params(match) : [];
    try {
      await window.Views[route.view](viewRoot, ctx, ...params);
      /* restart the entry animation for the freshly rendered view */
      viewRoot.classList.remove("view");
      void viewRoot.offsetWidth;
      viewRoot.classList.add("view");
    } catch (error) {
      console.error(error);
      viewRoot.innerHTML = UI.errorBox(error.message, "retry-view");
      const retry = document.getElementById("retry-view");
      if (retry) retry.addEventListener("click", () => render(path, { force: true }));
      toast(error.message, "error", 6000);
    }
    if (opts.scrollTop) window.scrollTo({ top: 0 });
  }

  /* --------------------------------------------------------- sidebar/nav state */
  function paintCounts() {
    const badge = nav.querySelector('[data-badge="repositories"]');
    if (badge && counts.repositories !== null) {
      badge.textContent = Fmt.number(counts.repositories);
      badge.title = `${Fmt.number(counts.repositories)} registered repositories`;
    }
    if (pageBadge) {
      pageBadge.innerHTML =
        counts.repositories === null
          ? ""
          : `<span class="badge badge--neutral">${Fmt.number(counts.repositories)} repositories</span>
             ${
               counts.dirty
                 ? `<span class="badge badge--warn" title="${Fmt.number(counts.dirty)} repositories with uncommitted changes">${Fmt.number(
                     counts.dirty
                   )} dirty</span>`
                 : ""
             }`;
    }
  }

  async function refreshCounts() {
    try {
      const [all, dirty] = await Promise.all([
        Api.repositories(Fmt.queryString({ per_page: 1 })),
        Api.repositories(Fmt.queryString({ status: "dirty", per_page: 1 })),
      ]);
      counts = { repositories: all.pagination.total, dirty: dirty.pagination.total };
      paintCounts();
    } catch (error) {
      /* the sidebar simply keeps its last known counts */
    }
  }

  async function refreshSystemMeta() {
    try {
      const health = await Api.health();
      systemMeta.innerHTML = `
        <span class="meta-item"><span class="meta-label">Version</span><span class="meta-value mono">${Fmt.escapeHtml(health.version)}</span></span>
        <span class="meta-item"><span class="meta-label">Git</span><span class="meta-value">${
          health.git_available ? `v${Fmt.escapeHtml(health.git_version || "ok")}` : '<span class="badge badge--danger">missing</span>'
        }</span></span>
        <span class="meta-item"><span class="meta-label">Database</span><span class="meta-value mono">${Fmt.bytes(
          health.database.size_bytes
        )} · schema v${Fmt.number(health.database.schema_version)}</span></span>
      `;
      const dot = document.getElementById("local-dot");
      if (dot) {
        dot.className = `state-dot state-dot--${health.warnings && health.warnings.length ? "warn" : "ok"}`;
      }
    } catch (error) {
      systemMeta.innerHTML = `<span class="badge badge--danger">Server unreachable</span>`;
      const dot = document.getElementById("local-dot");
      if (dot) dot.className = "state-dot state-dot--danger";
    }
  }

  /* ----------------------------------------------------------- scan polling */
  function setScanIndicator(kind, text) {
    const dot = scanStatusEl.querySelector(".state-dot");
    if (dot) dot.className = `state-dot state-dot--${kind}`;
    scanStatusText.textContent = text;
  }

  function setProgress(percent, indeterminate) {
    if (!scanProgress) return;
    const fill = scanProgress.querySelector("span") || scanProgress;
    const running = percent !== null || indeterminate;
    scanProgress.hidden = !running;
    scanProgress.classList.toggle("progress--indeterminate", Boolean(indeterminate));
    if (indeterminate) fill.style.width = "100%";
    else if (percent !== null) fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    if (scanAllButton) scanAllButton.disabled = Boolean(running);
  }

  async function updateScanStatus() {
    try {
      const status = await Api.scanStatus();
      const job = status.job;
      if (status.running && job) {
        const progress = job.progress || {};
        const hasTotal = Number(progress.total) > 0;
        const label = job.current || job.kind || "scan";
        setScanIndicator("busy", `Scanning ${hasTotal ? `${progress.done}/${progress.total} — ` : ""}${label}`);
        if (hasTotal) setProgress((Number(progress.done) / Number(progress.total)) * 100, false);
        else setProgress(null, true);
      } else if (job && job.status === "failed") {
        setScanIndicator("danger", "Last scan failed");
        setProgress(100, false);
        setTimeout(() => scanProgress && (scanProgress.hidden = true), 1200);
        if (scanAllButton) scanAllButton.disabled = false;
      } else if (job && job.status === "partial") {
        setScanIndicator("warn", "Last scan partially failed");
        setProgress(100, false);
        setTimeout(() => scanProgress && (scanProgress.hidden = true), 1200);
        if (scanAllButton) scanAllButton.disabled = false;
      } else if (job) {
        setScanIndicator("ok", `Last scan ${job.status}`);
        if (scanProgress) scanProgress.hidden = true;
        if (scanAllButton) scanAllButton.disabled = false;
      } else {
        setScanIndicator("idle", "Idle — no scans yet");
        if (scanProgress) scanProgress.hidden = true;
        if (scanAllButton) scanAllButton.disabled = false;
      }
    } catch (error) {
      setScanIndicator("danger", "Server unreachable");
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
              `Scan ${job.status}: ${job.progress ? job.progress.done : 0} repository(ies), ${added} new commit(s)${
                failed ? `, ${failed} failed` : ""
              }.`,
              failed ? "warn" : "ok",
              7000
            );
            const failures = (report.repositories || []).filter((item) => item.status === "failed");
            failures.slice(0, 3).forEach((item) => toast(`${item.name}: ${item.error}`, "error", 9000));
          }
          await refreshCounts();
          render(currentPath || "/", { force: true });
        }
      }
      if (!status.running && lastJobSignature !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 1500);
    /* immediate snapshot so completion detection works even for fast scans */
    try {
      const status = await Api.scanStatus();
      lastJobSignature = jobSignature(status.job);
      await updateScanStatus();
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

  /* --------------------------------------------------------- command palette */
  function paletteItems(repositories) {
    const items = [
      { group: "Actions", label: "Scan all repositories", icon: "scan", keywords: "refresh discover", run: () => startScanAll({ discover: true, incremental: true }) },
      { group: "Actions", label: "Reload current view", icon: "refresh", hint: "R", run: () => ctx.reload() },
      { group: "Actions", label: "Refresh server info", icon: "database", run: () => refreshSystemMeta() },
      { group: "Actions", label: "Switch colour theme", icon: "moon", run: () => UI.theme.toggle() },
      { group: "Actions", label: "Export JSON snapshot", icon: "download", run: () => Fmt.download(`${Api.base}/export/json?download=true`) },
      { group: "Actions", label: "Backup SQLite database", icon: "database", run: async () => {
        try {
          const result = await Api.backup();
          toast(`Database backed up (${Fmt.bytes(result.size_bytes)}) to ${result.backup}`, "ok", 7000);
        } catch (error) {
          toast(error.message, "error");
        }
      } },
    ];
    NAV_ITEMS.forEach((item) => {
      items.push({ group: "Go to", label: item.label, icon: item.icon, run: () => navigate(item.route) });
    });
    (repositories || []).forEach((repository) => {
      items.push({
        group: "Repositories",
        label: repository.name,
        hint: repository.path,
        icon: "repositories",
        keywords: `${repository.path} ${repository.current_branch || ""} repository`,
        run: () => navigate(`/repositories/${repository.id}`),
      });
    });
    return items;
  }

  async function openPalette() {
    UI.palette.open(paletteItems(repoCache));
    if (!repoCache) {
      try {
        const data = await Api.repositories(Fmt.queryString({ per_page: 50, sort: "last_commit", order: "desc" }));
        repoCache = data.items || [];
        setTimeout(() => {
          if (UI.palette.isOpen()) UI.palette.setItems(paletteItems(repoCache));
        }, 0);
      } catch (error) {
        /* the palette still works without repository entries */
      }
    }
  }

  /* ------------------------------------------------------- keyboard shortcuts */
  function wirePaletteButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "switch";
    button.id = "palette-open";
    button.title = "Command palette (⌘K)";
    button.innerHTML = `${Icons.get("search")}<span>Commands</span><span class="kbd">⌘K</span>`;
    button.addEventListener("click", openPalette);
    topbarActions.insertBefore(button, topbarActions.firstChild);
  }

  function handleShortcut(event) {
    const meta = event.metaKey || event.ctrlKey;
    if (meta && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (UI.palette.isOpen()) UI.palette.close();
      else openPalette();
      return;
    }
    if (event.key === "Escape") {
      if (UI.palette.isOpen()) UI.palette.close();
      else if (UI.modal.isOpen()) UI.modal.close();
      return;
    }
    if (isTypingTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;

    /* two-key chords win over single-key shortcuts: g d, g r, g a, g b, g s */
    if (chord === "g") {
      const routes = { d: "/", r: "/repositories", a: "/activity", b: "/branches", s: "/settings" };
      const target = routes[event.key.toLowerCase()];
      chord = null;
      if (target) {
        event.preventDefault();
        navigate(target);
        return;
      }
    }

    if (event.key === "/") {
      event.preventDefault();
      openPalette();
      return;
    }
    if (event.key === "r" || event.key === "R") {
      event.preventDefault();
      refreshSystemMeta();
      updateScanStatus();
      ctx.reload();
      return;
    }
    if (event.key === "g") {
      chord = "g";
      setTimeout(() => {
        chord = null;
      }, 1400);
    }
  }

  /* ------------------------------------------------------------- shell wiring */
  NAV_ITEMS.forEach((item) => {
    const link = document.createElement("a");
    link.className = "nav-link";
    link.href = item.route;
    link.dataset.route = item.route;
    link.innerHTML = `${Icons.get(item.icon)}<span>${item.label}</span>${
      item.badge ? `<span class="nav-badge" data-badge="${item.badge}" title="Registered repositories">–</span>` : ""
    }`;
    nav.appendChild(link);
  });

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

  document.getElementById("theme-toggle").addEventListener("click", () => UI.theme.toggle());
  scanAllButton.addEventListener("click", () => startScanAll({ discover: true, incremental: true }));
  refreshButton.addEventListener("click", () => {
    refreshSystemMeta();
    refreshCounts();
    updateScanStatus();
    ctx.reload();
  });
  document.getElementById("modal-close").addEventListener("click", () => UI.modal.close());
  document.getElementById("modal").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) UI.modal.close();
  });
  document.addEventListener("keydown", handleShortcut);

  /* ------------------------------------------------------------------ start */
  async function boot() {
    brandMark.innerHTML = Icons.get("commit");
    const closeButton = document.getElementById("modal-close");
    if (closeButton) closeButton.innerHTML = Icons.get("close");
    const refreshIcon = refreshButton.querySelector(".btn-icon-slot");
    if (refreshIcon) refreshIcon.innerHTML = Icons.get("refresh");
    const scanIcon = scanAllButton.querySelector(".btn-icon-slot");
    if (scanIcon) scanIcon.innerHTML = Icons.get("scan");

    UI.theme.init();
    wirePaletteButton();
    UI.wireCopy(document);
    await Promise.all([refreshSystemMeta(), refreshCounts(), updateScanStatus()]);
    await render(location.pathname + location.search);
    const status = await Api.scanStatus().catch(() => null);
    if (status && status.running) {
      lastJobSignature = null;
      pollScan();
    }
    setInterval(() => {
      refreshSystemMeta();
      refreshCounts();
    }, 30000);
  }

  boot();
})();
