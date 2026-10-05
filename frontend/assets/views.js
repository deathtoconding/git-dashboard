/* View renderers for the dashboard. Each view returns an optional dispose() hook. */
(function (global) {
  "use strict";

  const { escapeHtml: esc, number: num, date, day, duration, queryString, stateBadge, stalenessBadge, healthBadge, healthColor, shortSha, bytes } = Fmt;
  const RANGES = [
    { days: 7, label: "7 days" },
    { days: 30, label: "30 days" },
    { days: 90, label: "90 days" },
    { days: 365, label: "1 year" },
  ];

  function rangeButtons(activeDays, attribute) {
    return `<div class="toolbar" style="gap:4px">
      <label style="margin:0">Range</label>
      ${RANGES.map(
        (range) =>
          `<button class="btn btn-sm ${range.days === activeDays ? "btn-primary" : ""}" data-${attribute}="${range.days}">${range.label}</button>`
      ).join("")}
    </div>`;
  }

  function emptyPanel(title, hint, action) {
    return `<div class="empty"><h3>${esc(title)}</h3><p class="muted">${esc(hint)}</p>${action || ""}</div>`;
  }

  function insightsHtml(items) {
    if (!items || !items.length) {
      return `<p class="muted">No issues detected across your repositories. 🎉</p>`;
    }
    const icons = { error: "⛔", warning: "⚠️", info: "💡" };
    return items
      .map(
        (item) => `<div class="insight insight-${esc(item.severity)}">
          <span class="insight-icon">${icons[item.severity] || "•"}</span>
          <div>
            <div><strong>${esc(item.repository_name || "Dashboard")}</strong> — ${esc(item.message)}</div>
            ${item.action ? `<div class="action">→ ${esc(item.action)}</div>` : ""}
          </div>
        </div>`
      )
      .join("");
  }

  function repoLink(repository) {
    return `<a href="/repositories/${repository.id}" data-link>${esc(repository.name)}</a>`;
  }

  function repoTable(rows, options) {
    const opts = options || {};
    if (!rows || !rows.length) {
      return emptyPanel(
        "No repositories yet",
        "Add a path or configure repository roots in Settings, then scan.",
        `<a class="btn btn-primary" href="/settings" data-link style="margin-top:10px">Open settings</a>`
      );
    }
    return `<div class="table-wrap"><table>
      <thead><tr>
        <th>Repository</th><th>Branch</th><th>Last commit</th><th class="right">Commits</th>
        <th class="right">Changes</th><th>Health</th><th>Status</th>${opts.actions === false ? "" : "<th></th>"}
      </tr></thead>
      <tbody>
        ${rows
          .map(
            (repository) => `<tr class="clickable" data-repository="${repository.id}">
            <td>
              <div>${repoLink(repository)}</div>
              <div class="muted mono truncate" title="${esc(repository.path)}">${esc(repository.path)}</div>
            </td>
            <td class="mono">${esc(repository.current_branch || "—")}${repository.detached_head ? ' <span class="badge badge-warn">detached</span>' : ""}</td>
            <td class="nowrap">${repository.last_commit_at ? `${day(repository.last_commit_at)}<div class="muted">${duration(repository.days_since_last_commit)}</div>` : '<span class="muted">never</span>'}</td>
            <td class="right mono">${num(repository.total_commits)}</td>
            <td class="right">${
              repository.uncommitted_files
                ? `<span class="badge badge-warn">${num(repository.uncommitted_files)}</span>`
                : '<span class="muted">clean</span>'
            }</td>
            <td>${healthBadge(repository.health)}</td>
            <td>${stateBadge(repository)} ${stalenessBadge(repository.staleness, repository.staleness_label)}</td>
            ${opts.actions === false ? "" : `<td class="right nowrap">
              <button class="btn btn-sm" data-scan="${repository.id}" title="Scan this repository now">⟳</button>
              <a class="btn btn-sm" href="/repositories/${repository.id}" data-link title="Open details">Open</a>
            </td>`}
          </tr>`
          )
          .join("")}
      </tbody>
    </table></div>`;
  }

  /* ------------------------------------------------------------------ shared */
  function wireRepoTable(root, ctx) {
    root.querySelectorAll("tr[data-repository]").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest("button, a")) return;
        ctx.navigate(`/repositories/${row.dataset.repository}`);
      });
    });
    root.querySelectorAll("[data-scan]").forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.stopPropagation();
        try {
          await Api.scanRepository(button.dataset.scan, { incremental: true, background: true });
          ctx.toast("Scan started…", "info");
          ctx.pollScan();
        } catch (error) {
          ctx.toast(error.message, "error");
        }
      });
    });
  }

  /* --------------------------------------------------------------- dashboard */
  async function dashboard(root, ctx) {
    const days = ctx.state.activityDays || 30;
    const data = await Api.dashboard(days, "day");
    const cards = data.cards;

    root.innerHTML = `
      <section class="cards">
        <div class="card"><span class="label">Repositories</span><span class="value">${num(cards.repositories)}</span>
          <span class="hint">${num(cards.dirty_repositories)} with uncommitted changes</span></div>
        <div class="card ${cards.uncommitted_changes ? "alert" : ""}"><span class="label">Uncommitted changes</span><span class="value">${num(cards.uncommitted_changes)}</span>
          <span class="hint">files across all repositories</span></div>
        <div class="card"><span class="label">Branches</span><span class="value">${num(cards.branches)}</span>
          <span class="hint">${num(cards.stale_branches)} stale</span></div>
        <div class="card"><span class="label">Commits</span><span class="value">${num(cards.commits)}</span>
          <span class="hint">${num(cards.commits_last_30d)} in the last 30 days</span></div>
        <div class="card"><span class="label">Contributors</span><span class="value">${num(cards.contributors)}</span>
          <span class="hint">unique author emails</span></div>
        <div class="card ${cards.stale_repositories ? "alert" : ""}"><span class="label">Stale repositories</span><span class="value">${num(cards.stale_repositories)}</span>
          <span class="hint">avg health ${num(cards.average_health)}</span></div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <div><h2>Commit activity</h2><span class="panel-sub">Commits per day across every repository</span></div>
          ${rangeButtons(days, "range")}
        </div>
        <div id="activity-chart"></div>
        <div class="chart-legend">
          <span>Total in range: <strong>${num(data.activity.summary.total)}</strong></span>
          <span>Peak day: <strong>${num(data.activity.summary.peak)}</strong></span>
          <span>Average/day: <strong>${data.activity.summary.average}</strong></span>
        </div>
      </section>

      <section class="grid-2">
        <div class="panel">
          <div class="panel-header"><h2>Repositories</h2><a href="/repositories" data-link class="btn btn-sm">View all</a></div>
          ${repoTable(data.repositories.slice(0, 8), { actions: false })}
        </div>
        <div class="panel">
          <div class="panel-header">
            <h2>Recommendations</h2>
            <span class="panel-sub">${data.insights.length} finding(s)</span>
          </div>
          <div id="insights">${insightsHtml(data.insights.slice(0, 8))}</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header"><h2>Recently active</h2><span class="panel-sub">Last updated ${date(data.last_updated)}</span></div>
        ${repoTable(data.recent_repositories, { actions: false })}
      </section>
    `;

    Charts.lineChart(root.querySelector("#activity-chart"), data.activity.series);
    wireRepoTable(root, ctx);
    root.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.activityDays = Number(button.dataset.range);
        ctx.persistState();
        ctx.reload();
      });
    });
  }

  /* ------------------------------------------------------------ repositories */
  async function repositories(root, ctx) {
    const filters = ctx.state.repoFilters;
    const perPage = 25;
    const query = queryString({
      search: filters.search,
      status: filters.status,
      staleness: filters.staleness,
      sort: filters.sort,
      order: filters.order,
      per_page: perPage,
      page: filters.page,
    });
    const data = await Api.repositories(query);
    const pagination = data.pagination;

    root.innerHTML = `
      <section class="panel">
        <div class="toolbar" style="justify-content:space-between">
          <div class="toolbar">
            <div class="field"><label>Search</label><input id="filter-search" placeholder="name, path or branch" value="${esc(filters.search || "")}" /></div>
            <div class="field"><label>Status</label>
              <select id="filter-status">
                ${["all", "clean", "dirty", "detached", "bare", "empty", "error", "unknown"]
                  .map((value) => `<option value="${value}" ${filters.status === value ? "selected" : ""}>${value}</option>`)
                  .join("")}
              </select></div>
            <div class="field"><label>Staleness</label>
              <select id="filter-staleness">
                ${["all", "active", "inactive", "stale", "abandoned"]
                  .map((value) => `<option value="${value}" ${filters.staleness === value ? "selected" : ""}>${value}</option>`)
                  .join("")}
              </select></div>
            <div class="field"><label>Sort</label>
              <select id="filter-sort">
                ${["last_commit", "name", "commits", "branches", "changes", "health", "scanned"]
                  .map((value) => `<option value="${value}" ${filters.sort === value ? "selected" : ""}>${value.replace("_", " ")}</option>`)
                  .join("")}
              </select></div>
            <div class="field"><label>Order</label>
              <select id="filter-order">
                <option value="desc" ${filters.order === "desc" ? "selected" : ""}>desc</option>
                <option value="asc" ${filters.order === "asc" ? "selected" : ""}>asc</option>
              </select></div>
          </div>
          <div class="toolbar">
            <button class="btn" id="btn-discover">🔍 Discover</button>
            <button class="btn btn-primary" id="btn-add-repo">＋ Add repository</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h2>${num(pagination.total)} registered repository(ies)</h2>
          <span class="panel-sub">page ${pagination.page} of ${pagination.pages}</span>
        </div>
        ${repoTable(data.items)}
        ${pagination.pages > 1
          ? `<div class="pager">
              <button class="btn btn-sm" id="page-prev" ${pagination.page <= 1 ? "disabled" : ""}>← Previous</button>
              <span>${pagination.page} / ${pagination.pages}</span>
              <button class="btn btn-sm" id="page-next" ${pagination.page >= pagination.pages ? "disabled" : ""}>Next →</button>
            </div>`
          : ""}
      </section>
    `;

    wireRepoTable(root, ctx);
    const reload = () => ctx.reload();
    const applyFilters = () => {
      ctx.state.repoFilters.page = 1;
      ctx.persistState();
      reload();
    };

    root.querySelector("#filter-search").addEventListener("input", Fmt.debounce((event) => {
      ctx.state.repoFilters.search = event.target.value;
      applyFilters();
    }, 320));
    ["status", "staleness", "sort", "order"].forEach((key) => {
      root.querySelector(`#filter-${key}`).addEventListener("change", (event) => {
        ctx.state.repoFilters[key] = event.target.value;
        applyFilters();
      });
    });
    const prev = root.querySelector("#page-prev");
    const next = root.querySelector("#page-next");
    if (prev) prev.addEventListener("click", () => { ctx.state.repoFilters.page = pagination.page - 1; ctx.persistState(); reload(); });
    if (next) next.addEventListener("click", () => { ctx.state.repoFilters.page = pagination.page + 1; ctx.persistState(); reload(); });

    root.querySelector("#btn-add-repo").addEventListener("click", async () => {
      const value = window.prompt("Path of a local Git repository (e.g. /home/me/projects/api):");
      if (!value) return;
      try {
        const result = await Api.createRepository({ path: value.trim() });
        ctx.toast(`Registered '${result.repository.name}'.`, "ok");
        ctx.pollScan();
        Api.scanRepository(result.repository.id, { incremental: true, background: true }).catch(() => {});
        ctx.reload();
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });

    root.querySelector("#btn-discover").addEventListener("click", async () => {
      try {
        const result = await Api.discover({ register: true });
        const registered = result.registered_count || 0;
        ctx.toast(`Discovered ${result.count} repositories, registered ${registered} new.`, "ok");
        if (result.errors && result.errors.length) ctx.toast(`${result.errors.length} directory(ies) could not be read (see server log).`, "warn", 6000);
        ctx.reload();
      } catch (error) {
        ctx.toast(error.message, "error", 7000);
      }
    });
  }

  /* --------------------------------------------------------- repository page */
  async function repositoryDetail(root, ctx, repositoryId) {
    const detail = await Api.repository(repositoryId);
    const repository = detail.repository;
    const health = detail.health;
    const tab = ctx.state.detailTab || "overview";

    root.innerHTML = `
      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>${esc(repository.name)}</h2>
            <div class="muted mono">${esc(repository.path)}</div>
          </div>
          <div class="toolbar">
            <button class="btn btn-primary" id="btn-scan">⟳ Refresh repository</button>
            <button class="btn" id="btn-scan-full" title="Re-walk the complete history">Full rescan</button>
            <button class="btn btn-danger" id="btn-remove">Remove</button>
          </div>
        </div>
        <div class="grid-3">
          <div><label>Current branch</label><div class="mono">${esc(repository.current_branch || "—")}${repository.detached_head ? ' <span class="badge badge-warn">detached</span>' : ""}</div></div>
          <div><label>HEAD commit</label><div class="mono truncate" title="${esc(repository.head_commit || "")}">${shortSha(repository.head_commit)} ${esc(repository.head_subject || "")}</div></div>
          <div><label>Last scan</label><div>${repository.last_scanned_at ? date(repository.last_scanned_at) : '<span class="muted">never scanned</span>'}</div></div>
          <div><label>Remote</label><div class="mono truncate" title="${esc(repository.remote_url || "")}">${esc(repository.remote_url || "none")}</div></div>
          <div><label>State</label><div>${stateBadge(repository)} ${stalenessBadge(repository.staleness, repository.staleness_label)}</div></div>
          <div><label>Scan history</label><div>${num(detail.scans.length)} recent run(s)</div></div>
        </div>
        ${repository.last_error ? `<div class="insight insight-error" style="margin-top:12px"><span class="insight-icon">⛔</span><div>${esc(repository.last_error)}</div></div>` : ""}
      </section>

      <section class="grid-2">
        <div class="panel">
          <div class="panel-header"><h2>Health score</h2><span class="panel-sub">transparent, weighted signals</span></div>
          <div class="health-header">
            ${Charts.healthRing(health.score)}
            <div>
              <div style="font-size:20px;font-weight:650">${esc(health.level)} <span class="badge badge-neutral">grade ${esc(health.grade)}</span></div>
              <div class="muted">${esc(health.staleness.message)}</div>
              <div class="muted">${num(health.counts.commits_30d)} commit(s) in 30 days · ${num(health.counts.local_branches)} local branch(es)</div>
            </div>
          </div>
          <div style="margin-top:16px">
            ${health.signals
              .map(
                (signal) => `<div class="signal">
                  <span class="signal-label" title="weight ${(signal.weight * 100).toFixed(0)}%">${esc(signal.label)} <span class="muted">${(signal.weight * 100).toFixed(0)}%</span></span>
                  <span class="signal-track"><span class="signal-fill" style="width:${Math.max(2, signal.score)}%;background:${healthColor(signal.score)}"></span></span>
                  <span class="signal-score">${signal.score}</span>
                </div>
                <div class="signal-detail">${esc(signal.detail)}</div>`
              )
              .join("")}
          </div>
        </div>
        <div class="panel">
          <div class="panel-header"><h2>Actionable findings</h2><span class="panel-sub">${health.recommendations.length} recommendation(s)</span></div>
          ${insightsHtml(health.recommendations.map((item) => ({ ...item, repository_name: repository.name })))}
          <h3 style="margin-top:14px">Working tree</h3>
          ${
            health.working_tree_warnings.length
              ? health.working_tree_warnings.map((warning) => `<div class="insight insight-${esc(warning.severity)}"><span class="insight-icon">•</span><div>${esc(warning.message)}</div></div>`).join("")
              : '<p class="muted">Working tree is clean.</p>'
          }
        </div>
      </section>

      <section class="panel">
        <div class="tabs">
          ${["overview", "commits", "branches", "contributors", "activity", "insights"]
            .map((name) => `<button data-tab="${name}" class="${tab === name ? "active" : ""}">${name[0].toUpperCase() + name.slice(1)}</button>`)
            .join("")}
        </div>
        <div id="tab-content"><div class="loading">Loading…</div></div>
      </section>
    `;

    root.querySelector("#btn-scan").addEventListener("click", async () => {
      try {
        await Api.scanRepository(repositoryId, { incremental: true, background: true });
        ctx.toast("Scanning repository…", "info");
        ctx.pollScan();
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });
    root.querySelector("#btn-scan-full").addEventListener("click", async () => {
      try {
        await Api.scanRepository(repositoryId, { incremental: false, full_history: true, background: true });
        ctx.toast("Full rescan started…", "info");
        ctx.pollScan();
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });
    root.querySelector("#btn-remove").addEventListener("click", async () => {
      if (!window.confirm(`Remove '${repository.name}' from the dashboard? Collected data is deleted (the Git repository itself is untouched).`)) return;
      try {
        await Api.deleteRepository(repositoryId);
        ctx.toast("Repository removed.", "ok");
        ctx.navigate("/repositories");
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });

    const tabContainer = root.querySelector("#tab-content");
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.detailTab = button.dataset.tab;
        ctx.persistState();
        root.querySelectorAll("[data-tab]").forEach((other) => other.classList.toggle("active", other === button));
        renderTab(button.dataset.tab);
      });
    });

    async function renderTab(name) {
      tabContainer.innerHTML = `<div class="loading">Loading…</div>`;
      try {
        if (name === "overview") await overviewTab(tabContainer, repositoryId, ctx);
        else if (name === "commits") await commitsTab(tabContainer, repositoryId, ctx);
        else if (name === "branches") await branchesTab(tabContainer, repositoryId, ctx);
        else if (name === "contributors") await contributorsTab(tabContainer, repositoryId, ctx);
        else if (name === "activity") await activityTab(tabContainer, repositoryId, ctx, repository);
        else await insightsTab(tabContainer, repositoryId, ctx, health, detail);
      } catch (error) {
        tabContainer.innerHTML = emptyPanel("Could not load this tab", error.message);
      }
    }

    await renderTab(tab);
  }

  async function overviewTab(root, repositoryId, ctx) {
    const [metricsPayload, churn, heatmap] = await Promise.all([
      Api.metrics(repositoryId),
      Api.fileChurn(repositoryId).catch(() => ({ items: [] })),
      Api.heatmap(repositoryId, 365).catch(() => null),
    ]);
    const metrics = metricsPayload.metrics;
    const changes = metricsPayload.changes;
    root.innerHTML = `
      <div class="cards">
        <div class="card"><span class="label">Total commits</span><span class="value">${num(metrics.total_commits)}</span>
          <span class="hint">${num(metrics.stored_commits)} stored locally</span></div>
        <div class="card"><span class="label">Contributors</span><span class="value">${num(metrics.contributors)}</span></div>
        <div class="card"><span class="label">Branches</span><span class="value">${num(metrics.branches)}</span>
          <span class="hint">${num(metrics.remote_branches)} remote</span></div>
        <div class="card"><span class="label">Tracked files</span><span class="value">${num(metrics.tracked_files)}</span></div>
        <div class="card"><span class="label">Repository age</span><span class="value">${num(metrics.age_days)}</span>
          <span class="hint">days between first and last commit</span></div>
        <div class="card"><span class="label">Last commit</span><span class="value" style="font-size:16px">${metrics.latest_commit.date ? day(metrics.latest_commit.date) : "—"}</span>
          <span class="hint">${esc(metrics.latest_commit.author || "")}</span></div>
      </div>

      <div class="grid-2" style="margin-top:16px">
        <div>
          <h3>Code changes</h3>
          <div class="grid-3">
            <div class="card"><span class="label">Lines added</span><span class="value" style="color:#56d364">+${num(changes.lines_added)}</span></div>
            <div class="card"><span class="label">Lines deleted</span><span class="value" style="color:#ff9490">-${num(changes.lines_deleted)}</span></div>
            <div class="card"><span class="label">Net</span><span class="value">${changes.net_lines >= 0 ? "+" : ""}${num(changes.net_lines)}</span></div>
            <div class="card"><span class="label">Files touched</span><span class="value">${num(changes.files_touched)}</span></div>
            <div class="card"><span class="label">Avg / commit</span><span class="value">${num(changes.average_changes_per_commit)}</span>
              <span class="hint">lines changed</span></div>
            <div class="card"><span class="label">Last 30 days</span><span class="value">${num(changes.last_30_days.lines_added + changes.last_30_days.lines_deleted)}</span>
              <span class="hint">lines changed</span></div>
          </div>
          <h3 style="margin-top:16px">First commit</h3>
          <p class="muted">${metrics.first_commit.date ? `${esc(metrics.first_commit.subject || "")} — ${esc(metrics.first_commit.author || "")} on ${day(metrics.first_commit.date)}` : "No commits stored yet."}</p>
        </div>
        <div>
          <h3>Most changed files (churn)</h3>
          <div id="churn-chart"></div>
        </div>
      </div>

      <h3 style="margin-top:18px">Commit heatmap (weekday × hour, last year)</h3>
      <div id="heatmap"></div>
    `;
    Charts.barChart(
      root.querySelector("#churn-chart"),
      (churn.items || []).slice(0, 10).map((item) => ({ label: item.path, value: item.churn })),
      { emptyMessage: "No file changes collected yet." }
    );
    if (heatmap) Charts.heatmap(root.querySelector("#heatmap"), heatmap);
  }

  const commitState = { page: 1, per_page: 25, search: "", author: "", since: "", until: "" };

  async function commitsTab(root, repositoryId, ctx) {
    const query = queryString(commitState);
    const data = await Api.commits(repositoryId, query);
    const pagination = data.pagination;
    root.innerHTML = `
      <div class="toolbar" style="justify-content:space-between">
        <div class="toolbar">
          <div class="field"><label>Search subject or SHA</label><input id="commit-search" value="${esc(commitState.search)}" placeholder="fix, 3f2a1b…" /></div>
          <div class="field"><label>Author</label><input id="commit-author" value="${esc(commitState.author)}" placeholder="name or email" /></div>
          <div class="field"><label>Since</label><input id="commit-since" type="date" value="${esc(commitState.since)}" /></div>
          <div class="field"><label>Until</label><input id="commit-until" type="date" value="${esc(commitState.until)}" /></div>
          <button class="btn" id="commit-clear">Clear</button>
        </div>
        <span class="panel-sub">${num(pagination.total)} commit(s) stored, page ${pagination.page}/${pagination.pages}</span>
      </div>
      <div class="table-wrap" style="margin-top:12px"><table>
        <thead><tr><th>SHA</th><th>Author</th><th>Date</th><th>Message</th><th class="right">Changes</th><th class="right">Files</th></tr></thead>
        <tbody>
          ${data.items
            .map(
              (commit) => `<tr class="clickable" data-sha="${esc(commit.sha)}">
              <td class="mono">${shortSha(commit.sha)}${commit.is_merge ? ' <span class="badge badge-neutral">merge</span>' : ""}</td>
              <td>${esc(commit.author_name)}<div class="muted">${esc(commit.author_email)}</div></td>
              <td class="nowrap">${day(commit.authored_at)}</td>
              <td>${esc(commit.subject)}${commit.refs ? `<div class="muted mono">${esc(commit.refs)}</div>` : ""}</td>
              <td class="right nowrap"><span class="diff-add">+${num(commit.additions)}</span> <span class="diff-del">-${num(commit.deletions)}</span></td>
              <td class="right mono">${num(commit.files_changed)}</td>
            </tr>`
            )
            .join("") || `<tr><td colspan="6" class="muted">No commits match these filters.</td></tr>`}
        </tbody>
      </table></div>
      ${pagination.pages > 1
        ? `<div class="pager">
            <button class="btn btn-sm" id="c-prev" ${pagination.page <= 1 ? "disabled" : ""}>← Previous</button>
            <span>${pagination.page} / ${pagination.pages}</span>
            <button class="btn btn-sm" id="c-next" ${pagination.page >= pagination.pages ? "disabled" : ""}>Next →</button>
          </div>`
        : ""}
    `;

    ["search", "author", "since", "until"].forEach((key) => {
      const element = root.querySelector(`#commit-${key}`);
      const handler = Fmt.debounce((event) => {
        commitState[key] = event.target.value;
        commitState.page = 1;
        commitsTab(root, repositoryId, ctx);
      }, 350);
      element.addEventListener("input", handler);
      element.addEventListener("change", handler);
    });
    root.querySelector("#commit-clear").addEventListener("click", () => {
      Object.assign(commitState, { page: 1, search: "", author: "", since: "", until: "" });
      commitsTab(root, repositoryId, ctx);
    });
    const prev = root.querySelector("#c-prev");
    const next = root.querySelector("#c-next");
    if (prev) prev.addEventListener("click", () => { commitState.page = pagination.page - 1; commitsTab(root, repositoryId, ctx); });
    if (next) next.addEventListener("click", () => { commitState.page = pagination.page + 1; commitsTab(root, repositoryId, ctx); });

    root.querySelectorAll("tr[data-sha]").forEach((row) => {
      row.addEventListener("click", async () => {
        try {
          const payload = await Api.commit(repositoryId, row.dataset.sha);
          ctx.showModal(`Commit ${shortSha(payload.commit.sha)}`, `
            <div class="grid-3">
              <div><label>Author</label><div>${esc(payload.commit.author_name)} <span class="muted">${esc(payload.commit.author_email)}</span></div></div>
              <div><label>Authored</label><div>${date(payload.commit.authored_at)}</div></div>
              <div><label>Committed</label><div>${date(payload.commit.committed_at)}</div></div>
              <div><label>Parents</label><div class="mono">${payload.commit.parents ? payload.commit.parents.split(" ").map(shortSha).join(", ") : "root commit"}</div></div>
              <div><label>Refs</label><div class="mono">${esc(payload.commit.refs || "—")}</div></div>
              <div><label>Changes</label><div><span class="diff-add">+${num(payload.additions)}</span> <span class="diff-del">-${num(payload.deletions)}</span> in ${num(payload.file_count)} file(s)</div></div>
            </div>
            <h3 style="margin-top:16px">${esc(payload.commit.subject)}</h3>
            <div class="table-wrap"><table>
              <thead><tr><th>File</th><th>Change</th><th class="right">Added</th><th class="right">Deleted</th></tr></thead>
              <tbody>
                ${payload.files
                  .map(
                    (file) => `<tr><td class="mono">${esc(file.path)}</td><td><span class="badge badge-neutral">${esc(file.change_type)}</span></td>
                      <td class="right diff-add">+${num(file.additions)}</td><td class="right diff-del">-${num(file.deletions)}</td></tr>`
                  )
                  .join("") || `<tr><td colspan="4" class="muted">No file statistics stored for this commit (for example a merge commit).</td></tr>`}
              </tbody>
            </table></div>
          `);
        } catch (error) {
          ctx.toast(error.message, "error");
        }
      });
    });
  }

  async function branchesTab(root, repositoryId, ctx, filter) {
    const activeFilter = filter || "all";
    const data = await Api.branches(repositoryId, queryString({ filter: activeFilter }));
    const summary = data.summary || {};
    root.innerHTML = `
      <div class="toolbar" style="justify-content:space-between">
        <div class="toolbar">
          <label style="margin:0">Filter</label>
          ${["all", "current", "active", "inactive", "stale", "merged"]
            .map((value) => `<button class="btn btn-sm ${activeFilter === value ? "btn-primary" : ""}" data-branch-filter="${value}">${value}</button>`)
            .join("")}
        </div>
        <span class="panel-sub">${num(summary.local_branches || 0)} local · ${num(summary.remote_branches || 0)} remote · ${num(summary.stale_branches || 0)} stale (≥ ${summary.thresholds ? summary.thresholds.stale_days : 90} days)</span>
      </div>
      <div class="table-wrap" style="margin-top:12px"><table>
        <thead><tr><th>Branch</th><th>Last commit</th><th>Subject</th><th class="right">Age</th><th>Track</th><th>Status</th></tr></thead>
        <tbody>
          ${data.items
            .map(
              (branch) => `<tr ${branch.is_stale ? 'style="background:rgba(210,153,34,0.06)"' : ""}>
              <td class="mono">${esc(branch.name)}${branch.is_current ? ' <span class="badge badge-ok">current</span>' : ""}</td>
              <td class="nowrap">${branch.last_commit_at ? day(branch.last_commit_at) : "—"}</td>
              <td><span class="truncate" title="${esc(branch.subject || "")}">${esc(branch.subject || "")}</span></td>
              <td class="right">${num(branch.age_days)} d</td>
              <td class="mono muted">${branch.upstream ? `${esc(branch.upstream)} ${branch.ahead ? `↑${branch.ahead}` : ""}${branch.behind ? ` ↓${branch.behind}` : ""}` : "—"}</td>
              <td>${
                branch.is_stale
                  ? '<span class="badge badge-warn">stale</span>'
                  : branch.is_inactive
                  ? '<span class="badge badge-info">inactive</span>'
                  : branch.is_merged
                  ? '<span class="badge badge-purple">merged</span>'
                  : branch.is_current
                  ? '<span class="badge badge-ok">current</span>'
                  : '<span class="badge badge-neutral">active</span>'
              }</td>
            </tr>`
            )
            .join("") || `<tr><td colspan="6" class="muted">No branches match this filter.</td></tr>`}
        </tbody>
      </table></div>
    `;
    root.querySelectorAll("[data-branch-filter]").forEach((button) => {
      button.addEventListener("click", () => branchesTab(root, repositoryId, ctx, button.dataset.branchFilter));
    });
  }

  async function contributorsTab(root, repositoryId) {
    const data = await Api.contributors(repositoryId);
    root.innerHTML = `
      <div class="grid-2">
        <div>
          <div class="table-wrap"><table>
            <thead><tr><th>Contributor</th><th class="right">Commits</th><th class="right">Added</th><th class="right">Deleted</th><th class="right">Net</th><th>Last activity</th><th class="right">Share</th></tr></thead>
            <tbody>
              ${data.items
                .map(
                  (item) => `<tr>
                  <td>${esc(item.name)}<div class="muted">${esc(item.email || "no email")}</div></td>
                  <td class="right mono">${num(item.commit_count)}</td>
                  <td class="right diff-add">+${num(item.additions)}</td>
                  <td class="right diff-del">-${num(item.deletions)}</td>
                  <td class="right mono">${item.net_lines >= 0 ? "+" : ""}${num(item.net_lines)}</td>
                  <td class="nowrap">${item.last_commit_at ? day(item.last_commit_at) : "—"}</td>
                  <td class="right mono">${item.share}%</td>
                </tr>`
                )
                .join("") || `<tr><td colspan="7" class="muted">No contributors collected yet.</td></tr>`}
            </tbody>
          </table></div>
        </div>
        <div>
          <h3>Commits per contributor</h3>
          <div id="contributor-chart"></div>
        </div>
      </div>
    `;
    Charts.barChart(
      root.querySelector("#contributor-chart"),
      data.items.slice(0, 12).map((item) => ({ label: item.name, value: item.commit_count })),
      { emptyMessage: "No contributors collected yet." }
    );
  }

  async function activityTab(root, repositoryId, ctx, repository) {
    const days = ctx.state.detailDays || 90;
    const data = await Api.repoActivity(repositoryId, days, "day");
    const metrics = data.metrics;
    root.innerHTML = `
      <div class="toolbar" style="justify-content:space-between">
        ${rangeButtons(days, "detail-range")}
        <span class="panel-sub">Trend: <strong>${esc(metrics.trend)}</strong> (this week ${num(metrics.week_over_week.current)} vs ${num(metrics.week_over_week.previous)} last week)</span>
      </div>
      <div id="detail-chart" style="margin-top:12px"></div>
      <div class="chart-legend">
        <span>Total: <strong>${num(data.summary.total)}</strong></span>
        <span>Peak: <strong>${num(data.summary.peak)}</strong></span>
        <span>Average/day: <strong>${data.summary.average}</strong></span>
      </div>
      <div class="cards" style="margin-top:16px">
        <div class="card"><span class="label">Today</span><span class="value">${num(metrics.commits.today)}</span></div>
        <div class="card"><span class="label">This week</span><span class="value">${num(metrics.commits.week)}</span></div>
        <div class="card"><span class="label">This month</span><span class="value">${num(metrics.commits.month)}</span></div>
        <div class="card"><span class="label">Commits / day (lifetime)</span><span class="value">${metrics.commits_per_day}</span></div>
        <div class="card"><span class="label">Commits / week (90d)</span><span class="value">${metrics.commits_per_week}</span></div>
        <div class="card"><span class="label">Active contributors (30d)</span><span class="value">${num(metrics.active_contributors_30d)}</span>
          <span class="hint">${num(metrics.inactive_contributors_30d)} inactive before that</span></div>
      </div>
      <p class="tooltip-note" style="margin-top:10px">Days since last commit: ${num(metrics.days_since_last_commit)} · repository age: ${num(metrics.lifetime_days)} days · first commit ${metrics.first_commit_at ? day(metrics.first_commit_at) : "—"}</p>
    `;
    Charts.lineChart(root.querySelector("#detail-chart"), data.series);
    root.querySelectorAll("[data-detail-range]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.detailDays = Number(button.dataset.detailRange);
        ctx.persistState();
        activityTab(root, repositoryId, ctx, repository);
      });
    });
  }

  async function insightsTab(root, repositoryId, ctx, health, detail) {
    root.innerHTML = `
      <div class="grid-2">
        <div>
          <h3>Recommendations</h3>
          ${insightsHtml(health.recommendations)}
          <h3 style="margin-top:14px">Staleness</h3>
          <p>${stalenessBadge(health.staleness.bucket, health.staleness.label)} ${esc(health.staleness.message)}</p>
          <h3 style="margin-top:14px">Branch hygiene</h3>
          <ul class="muted">
            <li>${num(health.branch_health.total_branches)} branch(es) total, ${num(health.branch_health.local_branches)} local</li>
            <li>${num(health.branch_health.stale_branches)} stale, ${num(health.branch_health.inactive_branches)} inactive, ${num(health.branch_health.merged_branches)} merged</li>
            ${health.branch_health.stale_branch_names.length ? `<li>Stale: <span class="mono">${esc(health.branch_health.stale_branch_names.slice(0, 8).join(", "))}</span></li>` : ""}
          </ul>
        </div>
        <div>
          <h3>Recent scans</h3>
          <div class="table-wrap"><table>
            <thead><tr><th>Started</th><th>Kind</th><th>Status</th><th class="right">Records</th><th class="right">Duration</th></tr></thead>
            <tbody>
              ${detail.scans
                .map(
                  (scan) => `<tr>
                  <td class="nowrap">${date(scan.started_at)}</td>
                  <td>${esc(scan.kind)}</td>
                  <td><span class="badge ${scan.status === "completed" ? "badge-ok" : scan.status === "failed" ? "badge-bad" : "badge-warn"}">${esc(scan.status)}</span></td>
                  <td class="right mono">${num(scan.records_processed)}</td>
                  <td class="right mono">${scan.duration_ms ? `${num(scan.duration_ms)} ms` : "—"}</td>
                </tr>`
                )
                .join("") || `<tr><td colspan="5" class="muted">No scans recorded yet.</td></tr>`}
            </tbody>
          </table></div>
          ${detail.scans.some((scan) => scan.error) ? `<p class="tooltip-note">Last error: ${esc((detail.scans.find((scan) => scan.error) || {}).error || "")}</p>` : ""}
        </div>
      </div>
    `;
  }

  /* ---------------------------------------------------------------- activity */
  async function activity(root, ctx) {
    const days = ctx.state.activityDays || 30;
    const bucket = ctx.state.bucket || "day";
    const [data, byRepo] = await Promise.all([Api.activity(days, bucket), Api.get(`/activity/repositories?days=${days}`)]);
    root.innerHTML = `
      <section class="panel">
        <div class="panel-header">
          <div><h2>Commit activity</h2><span class="panel-sub">across every registered repository</span></div>
          <div class="toolbar">
            ${rangeButtons(days, "range")}
            <div class="field"><label>Bucket</label>
              <select id="bucket">
                ${["day", "week", "month"].map((value) => `<option value="${value}" ${bucket === value ? "selected" : ""}>${value}</option>`).join("")}
              </select></div>
          </div>
        </div>
        <div id="activity-chart"></div>
        <div class="chart-legend">
          <span>Total: <strong>${num(data.summary.total)}</strong></span>
          <span>Peak: <strong>${num(data.summary.peak)}</strong></span>
          <span>Average: <strong>${data.summary.average}</strong></span>
          <span>Buckets: <strong>${num(data.summary.buckets)}</strong></span>
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Per repository</h2><span class="panel-sub">commits in the last ${days} days</span></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Repository</th><th class="right">Commits in range</th><th class="right">All time</th><th>Last commit</th><th>Health</th><th>Status</th></tr></thead>
          <tbody>
            ${(byRepo.items || [])
              .map(
                (row) => `<tr class="clickable" data-repository="${row.id}">
                <td>${esc(row.name)}<div class="muted mono truncate">${esc(row.path)}</div></td>
                <td class="right mono">${num(row.commits)}</td>
                <td class="right mono">${num(row.total_commits)}</td>
                <td class="nowrap">${row.last_commit_at ? day(row.last_commit_at) : '<span class="muted">never</span>'}</td>
                <td>${healthBadge({ score: row.health_score, grade: row.health_grade })}</td>
                <td>${stalenessBadge(row.staleness, row.staleness)}</td>
              </tr>`
              )
              .join("") || `<tr><td colspan="6" class="muted">No repositories registered yet.</td></tr>`}
          </tbody>
        </table></div>
      </section>
    `;
    Charts.lineChart(root.querySelector("#activity-chart"), data.series);
    root.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.activityDays = Number(button.dataset.range);
        ctx.persistState();
        ctx.reload();
      });
    });
    root.querySelector("#bucket").addEventListener("change", (event) => {
      ctx.state.bucket = event.target.value;
      ctx.persistState();
      ctx.reload();
    });
    root.querySelectorAll("tr[data-repository]").forEach((row) => {
      row.addEventListener("click", () => ctx.navigate(`/repositories/${row.dataset.repository}`));
    });
  }

  /* ---------------------------------------------------------------- branches */
  async function branches(root, ctx) {
    const filter = ctx.state.branchFilter || "all";
    const search = ctx.state.branchSearch || "";
    const data = await Api.allBranches(queryString({ filter, search }));
    root.innerHTML = `
      <section class="panel">
        <div class="panel-header">
          <div><h2>Branches</h2><span class="panel-sub">${num(data.count)} branch(es) · stale threshold ${num(data.thresholds.stale_days)} days</span></div>
          <div class="toolbar">
            <div class="field"><label>Search</label><input id="branch-search" value="${esc(search)}" placeholder="branch or repository" /></div>
            <label style="margin:0">Filter</label>
            ${["all", "current", "active", "stale", "merged"]
              .map((value) => `<button class="btn btn-sm ${filter === value ? "btn-primary" : ""}" data-branch-filter="${value}">${value}</button>`)
              .join("")}
          </div>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th>Repository</th><th>Branch</th><th>Last commit</th><th class="right">Age</th><th>Track</th><th>Status</th></tr></thead>
          <tbody>
            ${data.items
              .map(
                (branch) => `<tr class="clickable" data-repository="${branch.repository_id}" ${branch.is_stale ? 'style="background:rgba(210,153,34,0.06)"' : ""}>
                <td>${esc(branch.repository_name)}</td>
                <td class="mono">${esc(branch.name)}${branch.is_current ? ' <span class="badge badge-ok">current</span>' : ""}</td>
                <td class="nowrap">${branch.last_commit_at ? day(branch.last_commit_at) : "—"}</td>
                <td class="right">${num(branch.age_days)} d</td>
                <td class="mono muted">${branch.upstream ? esc(branch.upstream) : "—"}</td>
                <td>${
                  branch.is_stale
                    ? '<span class="badge badge-warn">stale</span>'
                    : branch.is_merged
                    ? '<span class="badge badge-purple">merged</span>'
                    : branch.is_remote
                    ? '<span class="badge badge-neutral">remote</span>'
                    : branch.is_current
                    ? '<span class="badge badge-ok">current</span>'
                    : '<span class="badge badge-neutral">active</span>'
                }</td>
              </tr>`
              )
              .join("") || `<tr><td colspan="6" class="muted">No branches match these filters. Scan a repository to collect branches.</td></tr>`}
          </tbody>
        </table></div>
      </section>
    `;
    root.querySelectorAll("tr[data-repository]").forEach((row) => {
      row.addEventListener("click", () => ctx.navigate(`/repositories/${row.dataset.repository}`));
    });
    root.querySelectorAll("[data-branch-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.branchFilter = button.dataset.branchFilter;
        ctx.persistState();
        ctx.reload();
      });
    });
    root.querySelector("#branch-search").addEventListener("input", Fmt.debounce((event) => {
      ctx.state.branchSearch = event.target.value;
      ctx.persistState();
      ctx.reload();
    }, 320));
  }

  /* ---------------------------------------------------------------- settings */
  async function settings(root, ctx) {
    const [payload, health] = await Promise.all([Api.settings(), Api.health()]);
    const settings = payload.settings;
    root.innerHTML = `
      <section class="grid-2">
        <div class="panel">
          <div class="panel-header"><h2>Repository roots</h2><span class="panel-sub">folders scanned for Git repositories</span></div>
          <div class="field">
            <label>One absolute path per line</label>
            <textarea id="roots" rows="5" placeholder="/home/me/projects">${esc((settings.repository_roots || []).join("\n"))}</textarea>
          </div>
          <div class="toolbar" style="margin-top:10px">
            <button class="btn btn-primary" id="save-roots">Save roots</button>
            <button class="btn" id="discover">Discover now</button>
            <button class="btn" id="register-new" title="Register every newly discovered repository">Register new &amp; scan</button>
          </div>
          <div id="roots-status" style="margin-top:10px"></div>
        </div>

        <div class="panel">
          <div class="panel-header"><h2>System</h2><span class="panel-sub">git-dashboard ${esc(health.version)}</span></div>
          <div class="grid-3">
            <div><label>Git</label><div>${health.git_available ? `<span class="badge badge-ok">v${esc(health.git_version || "?")}</span>` : '<span class="badge badge-bad">not found</span>'}</div></div>
            <div><label>Binary</label><div class="mono">${esc(health.git_binary)}</div></div>
            <div><label>Schema</label><div class="mono">v${num(health.database.schema_version)}</div></div>
            <div><label>Repositories</label><div class="mono">${num(health.database.imported_repositories)}</div></div>
            <div><label>Database size</label><div class="mono">${bytes(health.database.size_bytes)}</div></div>
            <div><label>Status</label><div>${health.warnings.length ? '<span class="badge badge-warn">degraded</span>' : '<span class="badge badge-ok">ok</span>'}</div></div>
          </div>
          <div style="margin-top:10px">
            <label>Database file</label><div class="settings-readonly">${esc(health.database.path)}</div>
            <label style="margin-top:8px">Config file</label><div class="settings-readonly">${esc(payload.paths.config_file || "(defaults in use)")}</div>
          </div>
          ${health.warnings.map((warning) => `<div class="insight insight-warning" style="margin-top:10px"><span class="insight-icon">⚠️</span><div>${esc(warning)}</div></div>`).join("")}
        </div>
      </section>

      <section class="panel">
        <div class="panel-header"><h2>Scanning &amp; analysis thresholds</h2><span class="panel-sub">stored in config.json</span></div>
        <div class="form-grid">
          <div class="field"><label>history_depth — commits stored per scan</label><input id="s-history_depth" type="number" min="1" value="${settings.history_depth}" /></div>
          <div class="field"><label>max_scan_depth — discovery recursion depth</label><input id="s-max_scan_depth" type="number" min="1" max="64" value="${settings.max_scan_depth}" /></div>
          <div class="field"><label>git_binary</label><input id="s-git_binary" value="${esc(settings.git_binary)}" /></div>
          <div class="field"><label>git_timeout_seconds</label><input id="s-git_timeout_seconds" type="number" min="1" value="${settings.git_timeout_seconds}" /></div>
          <div class="field"><label>inactive_branch_days</label><input id="s-inactive_branch_days" type="number" min="0" value="${settings.inactive_branch_days}" /></div>
          <div class="field"><label>stale_branch_days</label><input id="s-stale_branch_days" type="number" min="1" value="${settings.stale_branch_days}" /></div>
          <div class="field"><label>repo_inactive_days</label><input id="s-repo_inactive_days" type="number" min="0" value="${settings.repo_inactive_days}" /></div>
          <div class="field"><label>repo_stale_days</label><input id="s-repo_stale_days" type="number" min="1" value="${settings.repo_stale_days}" /></div>
          <div class="field"><label>repo_abandoned_days</label><input id="s-repo_abandoned_days" type="number" min="1" value="${settings.repo_abandoned_days}" /></div>
          <div class="field"><label>refresh_interval_minutes (0 = off)</label><input id="s-refresh_interval_minutes" type="number" min="0" value="${settings.refresh_interval_minutes}" /></div>
          <div class="field"><label>log_level</label>
            <select id="s-log_level">${["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((level) => `<option ${settings.log_level === level ? "selected" : ""}>${level}</option>`).join("")}</select></div>
          <div class="field"><label>host</label><input id="s-host" value="${esc(settings.host)}" /></div>
          <div class="field"><label>port</label><input id="s-port" type="number" min="1" max="65535" value="${settings.port}" /></div>
        </div>
        <div class="toolbar" style="margin-top:12px">
          <button class="btn btn-primary" id="save-settings">Save settings</button>
          <span class="muted">Thresholds must satisfy inactive &lt; stale &lt; abandoned.</span>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header"><h2>Data &amp; exports</h2><span class="panel-sub">everything stays on this machine</span></div>
        <div class="toolbar">
          <button class="btn" id="export-json">⬇ JSON snapshot</button>
          <button class="btn" id="write-snapshot">Write snapshot to data/exports</button>
          <button class="btn" id="backup">Backup SQLite database</button>
          <button class="btn" id="download-repos">CSV: repositories</button>
          <button class="btn" id="download-commits">CSV: commits</button>
          <button class="btn" id="download-branches">CSV: branches</button>
          <button class="btn" id="download-contributors">CSV: contributors</button>
          <button class="btn" id="download-scans">CSV: scan runs</button>
        </div>
        <p class="tooltip-note" style="margin-top:8px">CSV exports include every repository; use the repository page for per-repository data.</p>
      </section>
    `;

    const inputs = [
      "history_depth", "max_scan_depth", "git_binary", "git_timeout_seconds", "inactive_branch_days",
      "stale_branch_days", "repo_inactive_days", "repo_stale_days", "repo_abandoned_days",
      "refresh_interval_minutes", "log_level", "host", "port",
    ];
    root.querySelector("#save-roots").addEventListener("click", () => saveSettingsPatch({ repository_roots: parseRoots(root) }));
    root.querySelector("#save-settings").addEventListener("click", () => {
      const patch = {};
      inputs.forEach((key) => {
        const element = root.querySelector(`#s-${key}`);
        if (!element) return;
        patch[key] = element.type === "number" ? Number(element.value) : element.value;
      });
      saveSettingsPatch(patch);
    });
    root.querySelector("#discover").addEventListener("click", () => runDiscovery(root, ctx, false));
    root.querySelector("#register-new").addEventListener("click", () => runDiscovery(root, ctx, true));

    root.querySelector("#export-json").addEventListener("click", () => Fmt.download(`${Api.base}/export/json?download=true`));
    root.querySelector("#write-snapshot").addEventListener("click", async () => {
      try {
        const result = await Api.snapshot();
        ctx.toast(`Snapshot written to ${result.snapshot}`, "ok", 6000);
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });
    root.querySelector("#backup").addEventListener("click", async () => {
      try {
        const result = await Api.backup();
        ctx.toast(`Database backed up (${bytes(result.size_bytes)}) to ${result.backup}`, "ok", 7000);
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });
    [["download-repos", "repositories"], ["download-commits", "commits"], ["download-branches", "branches"],
     ["download-contributors", "contributors"], ["download-scans", "scan_runs"]].forEach(([id, table]) => {
      root.querySelector(`#${id}`).addEventListener("click", () => Fmt.download(Api.exportCsvUrl(table)));
    });

    await refreshRootStatus(root);

    async function saveSettingsPatch(patch) {
      try {
        const result = await Api.saveSettings(patch);
        ctx.toast(`Saved: ${result.changed.join(", ")}`, "ok");
        if (result.restart_required_for && result.restart_required_for.length) {
          ctx.toast(`Restart the server for: ${result.restart_required_for.join(", ")}`, "warn", 8000);
        }
        await refreshRootStatus(root);
      } catch (error) {
        ctx.toast(error.message, "error", 8000);
      }
    }
  }

  function parseRoots(root) {
    return root
      .querySelector("#roots")
      .value.split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  }

  async function refreshRootStatus(root) {
    const container = root.querySelector("#roots-status");
    if (!container) return;
    try {
      const data = await Api.get("/settings/roots");
      container.innerHTML = data.roots.length
        ? data.roots
            .map(
              (entry) =>
                `<div class="insight ${entry.exists ? "insight-info" : "insight-warning"}"><span class="insight-icon">${entry.exists ? "📁" : "⚠️"}</span>
                  <div class="mono">${esc(entry.path)}${entry.exists ? "" : " — does not exist"}</div></div>`
            )
            .join("")
        : `<p class="muted">No roots configured yet. Add one so the dashboard can discover repositories automatically.</p>`;
    } catch (error) {
      container.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
    }
  }

  async function runDiscovery(root, ctx, register) {
    const container = root.querySelector("#roots-status");
    container.innerHTML = `<div class="loading">Scanning configured roots…</div>`;
    try {
      const result = await Api.discover({ register });
      const repositories = (result.roots || []).flatMap((entry) => entry.repositories || []);
      container.innerHTML = `
        <p class="muted">${num(result.count)} repository(ies) found${register ? `, ${num(result.registered_count || 0)} registered` : ""}.</p>
        <div class="table-wrap" style="max-height:280px;overflow:auto"><table>
          <thead><tr><th>Path</th><th>Status</th></tr></thead>
          <tbody>${repositories
            .map(
              (repository) =>
                `<tr><td class="mono">${esc(repository.path)}</td><td>${
                  repository.already_registered ? '<span class="badge badge-neutral">registered</span>' : '<span class="badge badge-info">new</span>'
                }</td></tr>`
            )
            .join("") || `<tr><td colspan="2" class="muted">Nothing found. Check the root paths.</td></tr>`}</tbody>
        </table></div>
        ${result.errors && result.errors.length ? `<p class="tooltip-note">${result.errors.length} directory(ies) could not be read.</p>` : ""}
      `;
      if (register && (result.registered_count || 0) > 0) {
        ctx.toast(`Registered ${result.registered_count} repository(ies) — starting a scan.`, "ok");
        ctx.startScanAll({ discover: false });
      }
    } catch (error) {
      container.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
      ctx.toast(error.message, "error", 7000);
    }
  }

  global.Views = { dashboard, repositories, repositoryDetail, activity, branches, settings, repoTable, wireRepoTable, insightsHtml };
})(window);
