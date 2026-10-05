/* View renderers for the dashboard. Each view returns an optional dispose() hook. */
(function (global) {
  "use strict";

  const { escapeHtml: esc, number: num, date, day, duration, queryString, stateBadge, stalenessBadge, healthBadge, healthColor, shortSha, bytes, avatar } = Fmt;

  const RANGES = [
    { days: 7, label: "7d" },
    { days: 30, label: "30d" },
    { days: 90, label: "90d" },
    { days: 365, label: "1y" },
  ];

  const SEVERITY = {
    error: { icon: "error", tone: "danger", label: "error" },
    warning: { icon: "alert", tone: "warn", label: "warning" },
    info: { icon: "bulb", tone: "info", label: "info" },
    ok: { icon: "check", tone: "ok", label: "ok" },
  };

  /* ---------------------------------------------------------------- pieces --- */

  /** Segmented button group; `attribute` becomes `data-<attribute>` on each button. */
  function segmented(items, active, attribute, ariaLabel) {
    return `<div class="segmented" role="group"${ariaLabel ? ` aria-label="${esc(ariaLabel)}"` : ""}>
      ${items
        .map(
          (item) =>
            `<button type="button" data-${attribute}="${esc(item.value)}" aria-pressed="${String(item.value) === String(active)}">${esc(item.label)}</button>`
        )
        .join("")}
    </div>`;
  }

  function rangeControl(activeDays, attribute) {
    return segmented(
      RANGES.map((range) => ({ value: range.days, label: range.label })),
      activeDays,
      attribute,
      "Time range"
    );
  }

  function emptyPanel(title, hint, action, iconName) {
    return `<div class="empty-state">${Icons.get(iconName || "info")}
      <h3>${esc(title)}</h3><p>${esc(hint)}</p>${action || ""}</div>`;
  }

  function panelHead(title, sub, actions, iconName) {
    return `<div class="panel-head">
      <div>
        <div class="panel-title">${iconName ? Icons.get(iconName) : ""}<h2>${esc(title)}</h2></div>
        ${sub ? `<div class="panel-sub">${sub}</div>` : ""}
      </div>
      ${actions ? `<div class="panel-actions">${actions}</div>` : ""}
    </div>`;
  }

  function kpi(options) {
    const opts = options || {};
    return `<div class="kpi-card${opts.tone ? ` kpi-card--${opts.tone}` : ""}">
      <div class="kpi-label">${opts.icon ? Icons.get(opts.icon) : ""}<span>${esc(opts.label)}</span></div>
      <div class="kpi-value">${opts.value}</div>
      <div class="kpi-foot"><span>${opts.hint || ""}</span>${opts.spark ? `<span class="kpi-spark">${opts.spark}</span>` : ""}</div>
    </div>`;
  }

  function metaItem(label, value) {
    return `<div class="meta-item"><div class="meta-label">${esc(label)}</div><div class="meta-value">${value}</div></div>`;
  }

  function insightsHtml(items) {
    if (!items || !items.length) {
      return `<div class="empty-state empty-state--inline">${Icons.get("check")}<p>No issues detected across your repositories.</p></div>`;
    }
    return items
      .map((item) => {
        const severity = SEVERITY[item.severity] || SEVERITY.info;
        return `<div class="insight insight--${severity.tone === "danger" ? "error" : severity.tone === "warn" ? "warning" : severity.tone}">
          <span class="insight-icon">${Icons.get(severity.icon)}</span>
          <div class="insight-body">
            <div class="insight-meta">
              ${item.repository_name ? `<span class="insight-repo">${esc(item.repository_name)}</span>` : ""}
              <span class="badge badge--${severity.tone}">${esc(severity.label)}</span>
            </div>
            <div>${esc(item.message)}</div>
            ${item.action ? `<div class="insight-action">${Icons.get("chevronRight")}<span>${esc(item.action)}</span></div>` : ""}
          </div>
        </div>`;
      })
      .join("");
  }

  function repoLink(repository) {
    return `<a class="cell-main" href="/repositories/${repository.id}" data-link>${esc(repository.name)}</a>`;
  }

  function branchCell(branch) {
    return `<span class="mono">${esc(branch.current_branch || "—")}</span>${
      branch.detached_head ? ` <span class="badge badge--warn">detached</span>` : ""
    }`;
  }

  function healthCell(health) {
    if (!health || health.score === undefined || health.score === null) return '<span class="muted">—</span>';
    const score = Math.round(Number(health.score) || 0);
    return Fmt.meter(score, { label: `${health.grade || ""} ${score}`.trim(), color: healthColor(score) });
  }

  function repoTable(rows, options) {
    const opts = options || {};
    if (!rows || !rows.length) {
      return emptyPanel(
        "No repositories yet",
        "Add a path or configure repository roots in Settings, then scan.",
        `<a class="btn btn-primary mt-12" href="/settings" data-link>${Icons.get("settings")}Open settings</a>`,
        "repositories"
      );
    }
    const showActions = opts.actions !== false;
    return `<div class="table-wrap"><table class="table table--rows-hover">
      <thead><tr>
        <th scope="col">Repository</th>
        <th scope="col">Branch</th>
        <th scope="col">Last commit</th>
        <th scope="col" class="right">Commits</th>
        <th scope="col" class="right">Changes</th>
        <th scope="col">Health</th>
        <th scope="col">Status</th>
        ${showActions ? '<th scope="col"><span class="sr-only">Actions</span></th>' : ""}
      </tr></thead>
      <tbody>
        ${rows
          .map(
            (repository) => `<tr class="clickable" data-repository="${repository.id}">
            <td>
              <div class="row">${repoLink(repository)}</div>
              <div class="cell-sub mono truncate" title="${esc(repository.path)}">${esc(repository.path)}</div>
            </td>
            <td>${branchCell(repository)}</td>
            <td class="nowrap">${
              repository.last_commit_at
                ? `${day(repository.last_commit_at)}<div class="cell-sub">${duration(repository.days_since_last_commit)}</div>`
                : '<span class="muted">never</span>'
            }</td>
            <td class="right mono num">${num(repository.total_commits)}</td>
            <td class="right">${
              repository.uncommitted_files
                ? `<span class="badge badge--warn">${num(repository.uncommitted_files)}</span>`
                : '<span class="muted">clean</span>'
            }</td>
            <td>${healthCell(repository.health)}</td>
            <td><div class="row-wrap">${stateBadge(repository)}${stalenessBadge(repository.staleness, repository.staleness_label)}</div></td>
            ${
              showActions
                ? `<td class="right nowrap">
                    <div class="row" style="justify-content:flex-end">
                      <button class="btn btn-ghost btn-icon" data-scan="${repository.id}" title="Scan this repository now" aria-label="Scan ${esc(repository.name)}">${Icons.get("scan")}</button>
                      <a class="btn btn-sm" href="/repositories/${repository.id}" data-link>Open</a>
                    </div>
                  </td>`
                : ""
            }
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
    UI.wireCopy(root);
  }

  /* --------------------------------------------------------------- dashboard */
  async function dashboard(root, ctx) {
    const days = ctx.state.activityDays || 30;
    const data = await Api.dashboard(days, "day");
    const cards = data.cards;
    const summary = data.activity.summary;
    const seriesValues = (data.activity.series || []).map((point) => Number(point.commits) || 0);
    const findingCount = data.insights.length;

    root.innerHTML = `
      <section class="kpis">
        ${kpi({
          label: "Repositories",
          icon: "repositories",
          value: num(cards.repositories),
          hint: `${num(cards.dirty_repositories)} with uncommitted changes`,
          tone: cards.failing_repositories ? "warn" : null,
        })}
        ${kpi({
          label: "Uncommitted files",
          icon: "file",
          value: num(cards.uncommitted_changes),
          hint: `across ${num(cards.dirty_repositories)} repositor${cards.dirty_repositories === 1 ? "y" : "ies"}`,
          tone: cards.uncommitted_changes ? "warn" : null,
        })}
        ${kpi({
          label: "Branches",
          icon: "branches",
          value: num(cards.branches),
          hint: `${num(cards.stale_branches)} stale`,
        })}
        ${kpi({
          label: "Commits",
          icon: "commit",
          value: num(cards.commits),
          hint: `${num(cards.commits_last_30d)} in the last 30 days`,
          spark: Charts.sparkline(seriesValues.slice(-30), 96, 26),
        })}
        ${kpi({
          label: "Contributors",
          icon: "user",
          value: num(cards.contributors),
          hint: "unique author identities",
        })}
        ${kpi({
          label: "Average health",
          icon: "zap",
          value: `${num(cards.average_health)}<small> / 100</small>`,
          hint: `${num(cards.stale_repositories)} stale · ${num(cards.detached_repositories)} detached`,
          tone: cards.average_health >= 75 ? "ok" : cards.average_health >= 50 ? "warn" : "danger",
        })}
      </section>

      <section class="panel">
        ${panelHead(
          "Commit activity",
          `Commits per day across every repository · last ${num(days)} days`,
          rangeControl(days, "range"),
          "activity"
        )}
        <div id="activity-chart"></div>
        <div class="chart-legend">
          <span>Total in range: <strong>${num(summary.total)}</strong></span>
          <span>Peak bucket: <strong>${num(summary.peak)}</strong></span>
          <span>Average per bucket: <strong>${num(summary.average)}</strong></span>
          <span>Last updated: <strong>${date(data.last_updated)}</strong></span>
        </div>
      </section>

      <section class="grid-2">
        <div class="panel">
          ${panelHead(
            "Repositories",
            "Most recently active first",
            `<a href="/repositories" data-link class="btn btn-sm">${Icons.get("chevronRight")}View all</a>`,
            "repositories"
          )}
          ${repoTable(data.repositories.slice(0, 8), { actions: false })}
        </div>
        <div class="panel">
          ${panelHead(
            "Recommendations",
            `${num(Math.min(data.insights.length, 8))} of ${num(findingCount)} finding${findingCount === 1 ? "" : "s"} shown`,
            "",
            "bulb"
          )}
          <div id="insights">${insightsHtml(data.insights.slice(0, 8))}</div>
        </div>
      </section>

      <section class="panel">
        ${panelHead("Recently active", "Repositories with the newest commits", "", "clock")}
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
    const statuses = ["all", "clean", "dirty", "detached", "bare", "empty", "error", "unknown"];
    const stalenesses = ["all", "active", "inactive", "stale", "abandoned"];
    const sorts = ["last_commit", "name", "commits", "branches", "changes", "health", "scanned"];

    root.innerHTML = `
      <section class="panel">
        <div class="toolbar toolbar--between">
          <div class="toolbar">
            <div class="field search" style="min-width:230px">
              <label for="filter-search">Search</label>
              ${Icons.get("search")}
              <input id="filter-search" type="search" placeholder="name, path or branch" value="${esc(filters.search || "")}" />
            </div>
            <div class="field"><label for="filter-status">State</label>
              <select id="filter-status">
                ${statuses.map((value) => `<option value="${value}" ${filters.status === value ? "selected" : ""}>${value}</option>`).join("")}
              </select></div>
            <div class="field"><label for="filter-staleness">Staleness</label>
              <select id="filter-staleness">
                ${stalenesses.map((value) => `<option value="${value}" ${filters.staleness === value ? "selected" : ""}>${value}</option>`).join("")}
              </select></div>
            <div class="field"><label for="filter-sort">Sort</label>
              <select id="filter-sort">
                ${sorts.map((value) => `<option value="${value}" ${filters.sort === value ? "selected" : ""}>${value.replace("_", " ")}</option>`).join("")}
              </select></div>
            <div class="field"><label>Order</label>
              ${segmented([{ value: "desc", label: "Desc" }, { value: "asc", label: "Asc" }], filters.order, "order", "Sort order")}
              <select id="filter-order" class="sr-only" tabindex="-1" aria-hidden="true">
                <option value="desc" ${filters.order === "desc" ? "selected" : ""}>desc</option>
                <option value="asc" ${filters.order === "asc" ? "selected" : ""}>asc</option>
              </select>
            </div>
          </div>
          <div class="toolbar">
            <button class="btn" id="btn-discover">${Icons.get("search")}Discover</button>
            <button class="btn btn-primary" id="btn-add-repo">${Icons.get("plus")}Add repository</button>
          </div>
        </div>
      </section>

      <section class="panel panel--flush">
        ${panelHead(
          `${num(pagination.total)} registered repositor${pagination.total === 1 ? "y" : "ies"}`,
          `Page ${num(pagination.page)} of ${num(pagination.pages)} · ${num(perPage)} per page`,
          ""
        )}
        ${repoTable(data.items)}
        ${
          pagination.pages > 1
            ? `<div class="pager" style="padding:0 18px">
                <span class="muted">Showing ${num((pagination.page - 1) * pagination.per_page + 1)}–${num(
                Math.min(pagination.page * pagination.per_page, pagination.total)
              )} of ${num(pagination.total)}</span>
                <div class="pager-buttons">
                  <button class="btn btn-sm" id="page-prev" ${pagination.page <= 1 ? "disabled" : ""}>${Icons.get("chevronLeft")}Previous</button>
                  <span class="mono num">${num(pagination.page)} / ${num(pagination.pages)}</span>
                  <button class="btn btn-sm" id="page-next" ${pagination.page >= pagination.pages ? "disabled" : ""}>Next${Icons.get("chevronRight")}</button>
                </div>
              </div>`
            : ""
        }
      </section>
    `;

    wireRepoTable(root, ctx);
    const reload = () => ctx.reload();
    const applyFilters = () => {
      ctx.state.repoFilters.page = 1;
      ctx.persistState();
      reload();
    };

    root.querySelector("#filter-search").addEventListener(
      "input",
      Fmt.debounce((event) => {
        ctx.state.repoFilters.search = event.target.value;
        applyFilters();
      }, 320)
    );
    ["status", "staleness", "sort", "order"].forEach((key) => {
      root.querySelector(`#filter-${key}`).addEventListener("change", (event) => {
        ctx.state.repoFilters[key] = event.target.value;
        applyFilters();
      });
    });
    root.querySelectorAll("[data-order]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.repoFilters.order = button.dataset.order;
        applyFilters();
      });
    });
    const prev = root.querySelector("#page-prev");
    const next = root.querySelector("#page-next");
    if (prev) {
      prev.addEventListener("click", () => {
        ctx.state.repoFilters.page = pagination.page - 1;
        ctx.persistState();
        reload();
      });
    }
    if (next) {
      next.addEventListener("click", () => {
        ctx.state.repoFilters.page = pagination.page + 1;
        ctx.persistState();
        reload();
      });
    }

    root.querySelector("#btn-add-repo").addEventListener("click", async () => {
      const value = await UI.modal.prompt({
        title: "Register a repository",
        label: "Absolute path of a local Git repository",
        placeholder: "/home/me/projects/api",
        hint: "The dashboard never copies your code — it only reads Git metadata with the git CLI.",
        confirmLabel: "Register",
        icon: "plus",
      });
      if (!value) return;
      try {
        const result = await Api.createRepository({ path: value });
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
        ctx.toast(`Discovered ${num(result.count)} repositories, registered ${num(registered)} new.`, "ok");
        if (result.errors && result.errors.length) {
          ctx.toast(`${num(result.errors.length)} directory(ies) could not be read (see server log).`, "warn", 6000);
        }
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
        <div class="repo-head">
          <div class="grow">
            <div class="row-wrap">
              <h2>${esc(repository.name)}</h2>
              ${stateBadge(repository)}
              ${stalenessBadge(repository.staleness, repository.staleness_label)}
            </div>
            <div class="row mt-8">
              <span class="mono truncate muted" title="${esc(repository.path)}">${esc(repository.path)}</span>
              ${UI.copyButton(repository.path, "repository path")}
            </div>
          </div>
          <div class="panel-actions">
            <button class="btn btn-primary" id="btn-scan">${Icons.get("scan")}Refresh</button>
            <button class="btn" id="btn-scan-full" title="Re-walk the complete history">${Icons.get("database")}Full rescan</button>
            <button class="btn btn-danger" id="btn-remove">${Icons.get("trash")}Remove</button>
          </div>
        </div>
        <div class="repo-meta mt-16">
          ${metaItem("Current branch", branchCell(repository))}
          ${metaItem(
            "HEAD commit",
            `<span class="row"><span class="mono">${shortSha(repository.head_commit)}</span>${
              repository.head_commit ? UI.copyButton(repository.head_commit, "HEAD commit SHA") : ""
            }</span><div class="cell-sub truncate" title="${esc(repository.head_subject || "")}">${esc(repository.head_subject || "")}</div>`
          )}
          ${metaItem("Last scan", repository.last_scanned_at ? date(repository.last_scanned_at) : '<span class="muted">never scanned</span>')}
          ${metaItem("Remote", `<span class="mono truncate" title="${esc(repository.remote_url || "")}">${esc(repository.remote_url || "none")}</span>`)}
          ${metaItem("Scan history", `${num(detail.scans.length)} recent run(s)`)}
        </div>
        ${
          repository.last_error
            ? `<div class="insight insight--error mt-12"><span class="insight-icon">${Icons.get("error")}</span><div class="insight-body">${esc(repository.last_error)}</div></div>`
            : ""
        }
      </section>

      <section class="grid-2">
        <div class="panel">
          ${panelHead("Health score", "Transparent, weighted signals", "", "zap")}
          <div class="health-summary">
            <div class="ring">${Charts.healthRing(health.score, 112)}</div>
            <div class="grow">
              <div class="row-wrap">
                <strong style="font-size:17px">${esc(health.level)}</strong>
                <span class="badge badge--${Fmt.healthTone(health.score)}">grade ${esc(health.grade)}</span>
                <span class="badge badge--neutral">${num(health.counts.commits_30d)} commits / 30d</span>
              </div>
              <p class="muted mt-8">${esc(health.staleness.message)}</p>
              <p class="muted">${num(health.counts.local_branches)} local branch(es) · ${num(health.counts.contributors)} contributor(s)</p>
            </div>
          </div>
          <div class="mt-16">
            ${health.signals
              .map(
                (signal) => `<div class="signal">
                  <span class="signal-label">${esc(signal.label)} <span class="signal-weight">${(signal.weight * 100).toFixed(0)}%</span></span>
                  <span class="signal-track" role="img" aria-label="${esc(signal.label)}: ${esc(String(signal.score))} of 100">
                    <span class="signal-fill" style="width:${Math.max(2, signal.score).toFixed(1)}%;background:${healthColor(signal.score)}"></span>
                  </span>
                  <span class="signal-score">${esc(String(signal.score))}</span>
                </div>
                <div class="signal-detail">${esc(signal.detail)}</div>`
              )
              .join("")}
          </div>
        </div>
        <div class="panel">
          ${panelHead(
            "Actionable findings",
            `${num(health.recommendations.length)} recommendation(s)`,
            "",
            "bulb"
          )}
          ${insightsHtml(health.recommendations.map((item) => Object.assign({}, item, { repository_name: repository.name })))}
          <h3 class="mt-16">Working tree</h3>
          <div class="mt-8">
            ${
              health.working_tree_warnings.length
                ? health.working_tree_warnings
                    .map(
                      (warning) => `<div class="insight insight--${warning.severity === "error" ? "error" : "warning"}">
                        <span class="insight-icon">${Icons.get(warning.severity === "error" ? "error" : "alert")}</span>
                        <div class="insight-body">${esc(warning.message)}</div>
                      </div>`
                    )
                    .join("")
                : `<div class="empty-state empty-state--inline">${Icons.get("check")}<p>Working tree is clean.</p></div>`
            }
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="tabs" role="tablist" aria-label="Repository details">
          ${["overview", "commits", "branches", "contributors", "activity", "insights"]
            .map(
              (name) =>
                `<button type="button" role="tab" data-tab="${name}" aria-selected="${tab === name}">${
                  name[0].toUpperCase() + name.slice(1)
                }</button>`
            )
            .join("")}
        </div>
        <div id="tab-content" role="tabpanel">${UI.loading()}</div>
      </section>
    `;

    UI.wireCopy(root);

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
      const confirmed = await UI.modal.confirm({
        title: "Full rescan",
        message: `Re-walk the complete history of '${repository.name}'?`,
        detail: "Existing commits are kept; the scan re-reads Git metadata only.",
        confirmLabel: "Full rescan",
        icon: "database",
      });
      if (!confirmed) return;
      try {
        await Api.scanRepository(repositoryId, { incremental: false, full_history: true, background: true });
        ctx.toast("Full rescan started…", "info");
        ctx.pollScan();
      } catch (error) {
        ctx.toast(error.message, "error");
      }
    });
    root.querySelector("#btn-remove").addEventListener("click", async () => {
      const confirmed = await UI.modal.confirm({
        title: "Remove repository",
        message: `Remove '${repository.name}' from the dashboard?`,
        detail: "Collected data is deleted. The Git repository itself is untouched.",
        confirmLabel: "Remove",
        danger: true,
        icon: "trash",
      });
      if (!confirmed) return;
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
        root.querySelectorAll("[data-tab]").forEach((other) => other.setAttribute("aria-selected", String(other === button)));
        renderTab(button.dataset.tab);
      });
    });

    async function renderTab(name) {
      tabContainer.innerHTML = UI.loading();
      try {
        if (name === "overview") await overviewTab(tabContainer, repositoryId);
        else if (name === "commits") await commitsTab(tabContainer, repositoryId, ctx);
        else if (name === "branches") await branchesTab(tabContainer, repositoryId, ctx);
        else if (name === "contributors") await contributorsTab(tabContainer, repositoryId);
        else if (name === "activity") await activityTab(tabContainer, repositoryId, ctx);
        else await insightsTab(tabContainer, repositoryId, ctx, health, detail);
      } catch (error) {
        tabContainer.innerHTML = emptyPanel("Could not load this tab", error.message, "", "error");
      }
    }

    await renderTab(tab);
  }

  async function overviewTab(root, repositoryId) {
    const [metricsPayload, churn, heatmap] = await Promise.all([
      Api.metrics(repositoryId),
      Api.fileChurn(repositoryId).catch(() => ({ items: [] })),
      Api.heatmap(repositoryId, 365).catch(() => null),
    ]);
    const metrics = metricsPayload.metrics;
    const changes = metricsPayload.changes;
    const netLines = Number(changes.net_lines) || 0;

    root.innerHTML = `
      <section class="kpis">
        ${kpi({ label: "Total commits", icon: "commit", value: num(metrics.total_commits), hint: `${num(metrics.stored_commits)} stored locally` })}
        ${kpi({ label: "Contributors", icon: "user", value: num(metrics.contributors) })}
        ${kpi({ label: "Branches", icon: "branches", value: num(metrics.branches), hint: `${num(metrics.remote_branches)} remote` })}
        ${kpi({ label: "Tracked files", icon: "file", value: num(metrics.tracked_files) })}
        ${kpi({ label: "Repository age", icon: "clock", value: `${num(metrics.age_days)}<small> days</small>`, hint: "first to last commit" })}
        ${kpi({
          label: "Last commit",
          icon: "activity",
          value: metrics.latest_commit.date ? day(metrics.latest_commit.date) : "—",
          hint: esc(metrics.latest_commit.author || ""),
        })}
      </section>

      <section class="grid-2 mt-16">
        <div>
          <h3>Code changes</h3>
          <div class="kpis mt-8">
            ${kpi({ label: "Lines added", value: `<span class="diff-add">+${num(changes.lines_added)}</span>` })}
            ${kpi({ label: "Lines deleted", value: `<span class="diff-del">-${num(changes.lines_deleted)}</span>` })}
            ${kpi({ label: "Net", value: `${netLines >= 0 ? "+" : ""}${num(netLines)}` })}
            ${kpi({ label: "Files touched", value: num(changes.files_touched) })}
            ${kpi({ label: "Avg / commit", value: num(changes.average_changes_per_commit), hint: "lines changed" })}
            ${kpi({ label: "Last 30 days", value: num(changes.last_30_days.lines_added + changes.last_30_days.lines_deleted), hint: "lines changed" })}
          </div>
          <h3 class="mt-16">First commit</h3>
          <p class="muted">${
            metrics.first_commit.date
              ? `${esc(metrics.first_commit.subject || "")} — ${esc(metrics.first_commit.author || "")} on ${day(metrics.first_commit.date)}`
              : "No commits stored yet."
          }</p>
        </div>
        <div>
          <h3>Most changed files</h3>
          <div id="churn-chart" class="mt-8"></div>
        </div>
      </section>

      <h3 class="mt-20">Commit heatmap</h3>
      <p class="muted">Weekday × hour distribution over the last year. Peak hours are the darkest cells.</p>
      <div id="heatmap" class="mt-8"></div>
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
    const data = await Api.commits(repositoryId, queryString(commitState));
    const pagination = data.pagination;
    root.innerHTML = `
      <div class="toolbar toolbar--between">
        <div class="toolbar">
          <div class="field search"><label for="commit-search">Search</label>${Icons.get("search")}
            <input id="commit-search" type="search" value="${esc(commitState.search)}" placeholder="subject or SHA" /></div>
          <div class="field"><label for="commit-author">Author</label>
            <input id="commit-author" value="${esc(commitState.author)}" placeholder="name or email" /></div>
          <div class="field"><label for="commit-since">Since</label>
            <input id="commit-since" type="date" value="${esc(commitState.since)}" /></div>
          <div class="field"><label for="commit-until">Until</label>
            <input id="commit-until" type="date" value="${esc(commitState.until)}" /></div>
          <button class="btn" id="commit-clear">${Icons.get("close")}Clear</button>
        </div>
        <span class="panel-sub">${num(pagination.total)} commit(s) stored · page ${num(pagination.page)} of ${num(pagination.pages)}</span>
      </div>
      <div class="table-wrap table-wrap--scroll mt-12"><table class="table table--rows-hover">
        <thead><tr><th scope="col">Commit</th><th scope="col">Author</th><th scope="col">Date</th><th scope="col">Message</th>
          <th scope="col" class="right">Changes</th><th scope="col" class="right">Files</th></tr></thead>
        <tbody>
          ${
            data.items
              .map(
                (commit) => `<tr class="clickable" data-sha="${esc(commit.sha)}">
              <td class="mono nowrap">${shortSha(commit.sha)}${
                  commit.is_merge ? ` <span class="badge badge--violet">${Icons.get("merge")}merge</span>` : ""
                }</td>
              <td><div class="row">${avatar(commit.author_name)}<span>${esc(commit.author_name)}<div class="cell-sub">${esc(commit.author_email)}</div></span></div></td>
              <td class="nowrap">${day(commit.authored_at)}</td>
              <td><span class="cell-main">${esc(commit.subject)}</span>${commit.refs ? `<div class="cell-sub mono truncate">${esc(commit.refs)}</div>` : ""}</td>
              <td class="right nowrap"><span class="diff-add">+${num(commit.additions)}</span> <span class="diff-del">-${num(commit.deletions)}</span></td>
              <td class="right mono num">${num(commit.files_changed)}</td>
            </tr>`
              )
              .join("") || `<tr><td colspan="6" class="muted center">No commits match these filters.</td></tr>`
          }
        </tbody>
      </table></div>
      ${
        pagination.pages > 1
          ? `<div class="pager">
              <button class="btn btn-sm" id="c-prev" ${pagination.page <= 1 ? "disabled" : ""}>${Icons.get("chevronLeft")}Previous</button>
              <span class="mono num">${num(pagination.page)} / ${num(pagination.pages)}</span>
              <button class="btn btn-sm" id="c-next" ${pagination.page >= pagination.pages ? "disabled" : ""}>Next${Icons.get("chevronRight")}</button>
            </div>`
          : ""
      }
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
    if (prev) {
      prev.addEventListener("click", () => {
        commitState.page = pagination.page - 1;
        commitsTab(root, repositoryId, ctx);
      });
    }
    if (next) {
      next.addEventListener("click", () => {
        commitState.page = pagination.page + 1;
        commitsTab(root, repositoryId, ctx);
      });
    }

    root.querySelectorAll("tr[data-sha]").forEach((row) => {
      row.addEventListener("click", async () => {
        try {
          const payload = await Api.commit(repositoryId, row.dataset.sha);
          const commit = payload.commit;
          const parents = commit.parents ? commit.parents.split(" ").filter(Boolean) : [];
          UI.modal.open({
            title: `Commit ${shortSha(commit.sha)}`,
            icon: commit.is_merge ? "merge" : "commit",
            wide: true,
            html: `
              <div class="row-wrap">
                ${avatar(commit.author_name, "avatar--lg")}
                <div class="grow">
                  <div><strong>${esc(commit.author_name)}</strong> <span class="muted">${esc(commit.author_email)}</span></div>
                  <div class="cell-sub">Authored ${date(commit.authored_at)} · committed ${date(commit.committed_at)}</div>
                </div>
                <div class="row">
                  <span class="badge badge--ok">${Icons.get("plus")}${num(payload.additions)}</span>
                  <span class="badge badge--danger">${Icons.get("close")}${num(payload.deletions)}</span>
                  <span class="badge badge--neutral">${num(payload.file_count)} file(s)</span>
                  ${UI.copyButton(commit.sha, "full commit SHA")}
                </div>
              </div>
              <h3 class="mt-16">${esc(commit.subject)}</h3>
              ${commit.body ? `<pre class="commit-body">${esc(commit.body)}</pre>` : ""}
              <div class="kv mt-16">
                ${metaItem("SHA", `<span class="mono">${esc(commit.sha)}</span>`)}
                ${metaItem("Parents", parents.length ? `<span class="mono">${parents.map((sha) => shortSha(sha)).join(", ")}</span>` : '<span class="muted">root commit</span>')}
                ${metaItem("Refs", `<span class="mono">${esc(commit.refs || "—")}</span>`)}
                ${metaItem("Merge commit", commit.is_merge ? "yes" : "no")}
              </div>
              <div class="table-wrap mt-16"><table class="table">
                <thead><tr><th scope="col">File</th><th scope="col">Change</th><th scope="col" class="right">Added</th><th scope="col" class="right">Deleted</th></tr></thead>
                <tbody>
                  ${
                    payload.files
                      .map(
                        (file) => `<tr><td class="mono">${esc(file.path)}</td>
                        <td><span class="badge badge--neutral">${esc(file.change_type)}</span></td>
                        <td class="right diff-add">+${num(file.additions)}</td>
                        <td class="right diff-del">-${num(file.deletions)}</td></tr>`
                      )
                      .join("") ||
                    `<tr><td colspan="4" class="muted">${esc(
                      payload.note || "No file statistics stored for this commit."
                    )}</td></tr>`
                  }
                </tbody>
              </table></div>
            `,
          });
          UI.wireCopy(document.getElementById("modal-body"));
        } catch (error) {
          ctx.toast(error.message, "error");
        }
      });
    });
  }

  function branchStatusBadge(branch) {
    if (branch.is_stale) return '<span class="badge badge--warn">stale</span>';
    if (branch.is_inactive) return '<span class="badge badge--info">inactive</span>';
    if (branch.is_merged) return '<span class="badge badge--violet">merged</span>';
    if (branch.is_current) return '<span class="badge badge--ok">current</span>';
    return '<span class="badge badge--neutral">active</span>';
  }

  async function branchesTab(root, repositoryId, ctx, filter) {
    const activeFilter = filter || "all";
    const data = await Api.branches(repositoryId, queryString({ filter: activeFilter }));
    const summary = data.summary || {};
    const filters = ["all", "current", "active", "inactive", "stale", "merged"];
    root.innerHTML = `
      <div class="toolbar toolbar--between">
        ${segmented(
          filters.map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })),
          activeFilter,
          "branch-filter",
          "Branch filter"
        )}
        <span class="panel-sub">${num(summary.local_branches || 0)} local · ${num(summary.remote_branches || 0)} remote · ${num(
      summary.stale_branches || 0
    )} stale (≥ ${num(summary.thresholds ? summary.thresholds.stale_days : 90)} days)</span>
      </div>
      <div class="table-wrap table-wrap--scroll mt-12"><table class="table table--rows-hover">
        <thead><tr><th scope="col">Branch</th><th scope="col">Last commit</th><th scope="col">Subject</th>
          <th scope="col" class="right">Age</th><th scope="col">Track</th><th scope="col">Status</th></tr></thead>
        <tbody>
          ${
            data.items
              .map(
                (branch) => `<tr>
              <td class="mono">${esc(branch.name)}${branch.is_current ? ' <span class="badge badge--ok">head</span>' : ""}</td>
              <td class="nowrap">${branch.last_commit_at ? day(branch.last_commit_at) : "—"}</td>
              <td><span class="truncate" title="${esc(branch.subject || "")}">${esc(branch.subject || "")}</span></td>
              <td class="right num">${num(branch.age_days)} d</td>
              <td class="mono muted">${
                branch.upstream
                  ? `${esc(branch.upstream)}${
                      branch.ahead ? ` <span class="diff-add">↑${num(branch.ahead)}</span>` : ""
                    }${branch.behind ? ` <span class="diff-del">↓${num(branch.behind)}</span>` : ""}`
                  : "—"
              }</td>
              <td>${branchStatusBadge(branch)}</td>
            </tr>`
              )
              .join("") || `<tr><td colspan="6" class="muted center">No branches match this filter.</td></tr>`
          }
        </tbody>
      </table></div>
    `;
    root.querySelectorAll("[data-branch-filter]").forEach((button) => {
      button.addEventListener("click", () => branchesTab(root, repositoryId, ctx, button.dataset.branchFilter));
    });
  }

  async function contributorsTab(root, repositoryId) {
    const data = await Api.contributors(repositoryId);
    const items = data.items || [];
    const top = items[0];
    root.innerHTML = `
      <div class="grid-2">
        <div class="table-wrap table-wrap--scroll"><table class="table table--rows-hover">
          <thead><tr><th scope="col">Contributor</th><th scope="col" class="right">Commits</th><th scope="col" class="right">Added</th>
            <th scope="col" class="right">Deleted</th><th scope="col" class="right">Net</th><th scope="col">Last activity</th><th scope="col" class="right">Share</th></tr></thead>
          <tbody>
            ${
              items
                .map(
                  (item) => `<tr>
                <td><div class="row">${avatar(item.name)}<span>${esc(item.name)}<div class="cell-sub">${esc(item.email || "no email")}</div></span></div></td>
                <td class="right mono num">${num(item.commit_count)}</td>
                <td class="right diff-add">+${num(item.additions)}</td>
                <td class="right diff-del">-${num(item.deletions)}</td>
                <td class="right mono num">${item.net_lines >= 0 ? "+" : ""}${num(item.net_lines)}</td>
                <td class="nowrap">${item.last_commit_at ? day(item.last_commit_at) : "—"}</td>
                <td class="right">${Fmt.meter(item.share, { max: 100, label: `${item.share}%`, color: "var(--accent)" })}</td>
              </tr>`
                )
                .join("") || `<tr><td colspan="7" class="muted center">No contributors collected yet.</td></tr>`
            }
          </tbody>
        </table></div>
        <div>
          ${panelHead("Commits per contributor", "Ranked by stored commits", "", "user")}
          <div id="contributor-chart"></div>
          ${top ? `<p class="tooltip-note mt-12">${esc(top.name)} leads with ${num(top.commit_count)} commit(s), ${num(top.share)}% of the stored history.</p>` : ""}
        </div>
      </div>
    `;
    Charts.barChart(
      root.querySelector("#contributor-chart"),
      items.slice(0, 12).map((item) => ({ label: item.name, value: item.commit_count })),
      { emptyMessage: "No contributors collected yet." }
    );
  }

  async function activityTab(root, repositoryId, ctx) {
    const days = ctx.state.detailDays || 90;
    const data = await Api.repoActivity(repositoryId, days, "day");
    const metrics = data.metrics;
    const trendTone = /up|grow|rising|increas/i.test(metrics.trend) ? "up" : /down|declin|fall|decreas/i.test(metrics.trend) ? "down" : "flat";
    root.innerHTML = `
      <div class="toolbar toolbar--between">
        ${rangeControl(days, "detail-range")}
        <span class="panel-sub">Trend: <span class="kpi-delta kpi-delta--${trendTone}"><strong>${esc(metrics.trend)}</strong></span>
          · this week ${num(metrics.week_over_week.current)} vs ${num(metrics.week_over_week.previous)} last week</span>
      </div>
      <div id="detail-chart" class="mt-12"></div>
      <div class="chart-legend">
        <span>Total: <strong>${num(data.summary.total)}</strong></span>
        <span>Peak: <strong>${num(data.summary.peak)}</strong></span>
        <span>Average/day: <strong>${num(data.summary.average)}</strong></span>
        <span>Buckets: <strong>${num(data.summary.buckets)}</strong></span>
      </div>
      <section class="kpis mt-16">
        ${kpi({ label: "Today", icon: "commit", value: num(metrics.commits.today) })}
        ${kpi({ label: "This week", icon: "activity", value: num(metrics.commits.week) })}
        ${kpi({ label: "This month", icon: "chart", value: num(metrics.commits.month) })}
        ${kpi({ label: "Commits / day", icon: "clock", value: metrics.commits_per_day, hint: "lifetime average" })}
        ${kpi({ label: "Commits / week", icon: "clock", value: metrics.commits_per_week, hint: "last 90 days" })}
        ${kpi({
          label: "Active contributors",
          icon: "user",
          value: num(metrics.active_contributors_30d),
          hint: `${num(metrics.inactive_contributors_30d)} inactive before that`,
        })}
      </section>
      <p class="tooltip-note mt-12">Days since last commit: ${num(metrics.days_since_last_commit)} · repository age: ${num(
      metrics.lifetime_days
    )} days · first commit ${metrics.first_commit_at ? day(metrics.first_commit_at) : "—"}</p>
    `;
    Charts.lineChart(root.querySelector("#detail-chart"), data.series);
    root.querySelectorAll("[data-detail-range]").forEach((button) => {
      button.addEventListener("click", () => {
        ctx.state.detailDays = Number(button.dataset.detailRange);
        ctx.persistState();
        activityTab(root, repositoryId, ctx);
      });
    });
  }

  async function insightsTab(root, repositoryId, ctx, health, detail) {
    root.innerHTML = `
      <div class="grid-2">
        <div>
          <h3>Recommendations</h3>
          <div class="mt-8">${insightsHtml(health.recommendations)}</div>
          <h3 class="mt-16">Staleness</h3>
          <p>${stalenessBadge(health.staleness.bucket, health.staleness.label)} ${esc(health.staleness.message)}</p>
          <h3 class="mt-16">Branch hygiene</h3>
          <ul class="muted">
            <li>${num(health.branch_health.total_branches)} branch(es) total, ${num(health.branch_health.local_branches)} local</li>
            <li>${num(health.branch_health.stale_branches)} stale, ${num(health.branch_health.inactive_branches)} inactive, ${num(
      health.branch_health.merged_branches
    )} merged</li>
            ${
              health.branch_health.stale_branch_names.length
                ? `<li>Stale: <span class="mono">${esc(health.branch_health.stale_branch_names.slice(0, 8).join(", "))}</span></li>`
                : ""
            }
          </ul>
        </div>
        <div>
          <h3>Recent scans</h3>
          <div class="table-wrap table-wrap--scroll mt-8"><table class="table table--rows-hover table--compact">
            <thead><tr><th scope="col">Started</th><th scope="col">Kind</th><th scope="col">Status</th>
              <th scope="col" class="right">Records</th><th scope="col" class="right">Duration</th></tr></thead>
            <tbody>
              ${
                detail.scans
                  .map(
                    (scan) => `<tr>
                  <td class="nowrap">${date(scan.started_at)}</td>
                  <td>${esc(scan.kind)}</td>
                  <td><span class="badge badge--${
                    scan.status === "completed" ? "ok" : scan.status === "failed" ? "danger" : "warn"
                  }">${esc(scan.status)}</span></td>
                  <td class="right mono num">${num(scan.records_processed)}</td>
                  <td class="right mono num">${scan.duration_ms ? `${num(scan.duration_ms)} ms` : "—"}</td>
                </tr>`
                  )
                  .join("") || `<tr><td colspan="5" class="muted center">No scans recorded yet.</td></tr>`
              }
            </tbody>
          </table></div>
          ${
            detail.scans.some((scan) => scan.error)
              ? `<p class="tooltip-note mt-8">Last error: ${esc((detail.scans.find((scan) => scan.error) || {}).error || "")}</p>`
              : ""
          }
        </div>
      </div>
    `;
  }

  /* ---------------------------------------------------------------- activity */
  async function activity(root, ctx) {
    const days = ctx.state.activityDays || 30;
    const bucket = ctx.state.bucket || "day";
    const [data, byRepo] = await Promise.all([Api.activity(days, bucket), Api.activityByRepository(days, bucket)]);
    const chartId = bucket === "day" && days <= 14 ? "activity-chart" : "activity-chart";
    root.innerHTML = `
      <section class="panel">
        ${panelHead(
          "Commit activity",
          `Across every registered repository · last ${num(days)} days`,
          `${rangeControl(days, "range")}
           <div class="field" style="min-width:120px"><label for="bucket">Bucket</label>
             <select id="bucket">${["day", "week", "month"]
               .map((value) => `<option value="${value}" ${bucket === value ? "selected" : ""}>${value}</option>`)
               .join("")}</select></div>`,
          "activity"
        )}
        <div id="${chartId}"></div>
        <div class="chart-legend">
          <span>Total: <strong>${num(data.summary.total)}</strong></span>
          <span>Peak: <strong>${num(data.summary.peak)}</strong></span>
          <span>Average: <strong>${num(data.summary.average)}</strong></span>
          <span>Buckets: <strong>${num(data.summary.buckets)}</strong></span>
        </div>
      </section>
      <section class="panel">
        ${panelHead("Per repository", `Commits in the last ${num(days)} days`, "", "repositories")}
        <div class="table-wrap table-wrap--scroll"><table class="table table--rows-hover">
          <thead><tr><th scope="col">Repository</th><th scope="col" class="right">Commits in range</th>
            <th scope="col" class="right">All time</th><th scope="col">Last commit</th><th scope="col">Health</th><th scope="col">Staleness</th></tr></thead>
          <tbody>
            ${
              (byRepo.items || [])
                .map(
                  (row) => `<tr class="clickable" data-repository="${row.id}">
                <td><span class="cell-main">${esc(row.name)}</span><div class="cell-sub mono truncate">${esc(row.path)}</div></td>
                <td class="right mono num">${num(row.commits)}</td>
                <td class="right mono num">${num(row.total_commits)}</td>
                <td class="nowrap">${row.last_commit_at ? day(row.last_commit_at) : '<span class="muted">never</span>'}</td>
                <td>${healthBadge({ score: row.health_score, grade: row.health_grade })}</td>
                <td>${stalenessBadge(row.staleness, row.staleness)}</td>
              </tr>`
                )
                .join("") || `<tr><td colspan="6" class="muted center">No repositories registered yet.</td></tr>`
            }
          </tbody>
        </table></div>
      </section>
    `;
    Charts.lineChart(root.querySelector(`#${chartId}`), data.series);
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
    const filters = ["all", "current", "active", "stale", "merged"];
    root.innerHTML = `
      <section class="panel panel--flush">
        ${panelHead(
          "Branches",
          `${num(data.count)} branch(es) · stale threshold ${num(data.thresholds.stale_days)} days`,
          `<div class="field search" style="min-width:210px">${Icons.get("search")}
             <input id="branch-search" type="search" value="${esc(search)}" placeholder="branch or repository" aria-label="Search branches" /></div>
           ${segmented(
             filters.map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })),
             filter,
             "branch-filter",
             "Branch filter"
           )}`,
          "branches"
        )}
        <div class="table-wrap table-wrap--scroll"><table class="table table--rows-hover">
          <thead><tr><th scope="col">Repository</th><th scope="col">Branch</th><th scope="col">Last commit</th>
            <th scope="col" class="right">Age</th><th scope="col">Track</th><th scope="col">Status</th></tr></thead>
          <tbody>
            ${
              data.items
                .map(
                  (branch) => `<tr class="clickable" data-repository="${branch.repository_id}">
                <td class="cell-main">${esc(branch.repository_name)}</td>
                <td class="mono">${esc(branch.name)}${branch.is_current ? ' <span class="badge badge--ok">head</span>' : ""}</td>
                <td class="nowrap">${branch.last_commit_at ? day(branch.last_commit_at) : "—"}</td>
                <td class="right num">${num(branch.age_days)} d</td>
                <td class="mono muted">${branch.upstream ? esc(branch.upstream) : "—"}</td>
                <td>${branchStatusBadge(branch)}</td>
              </tr>`
                )
                .join("") ||
              `<tr><td colspan="6" class="muted center">No branches match these filters. Scan a repository to collect branches.</td></tr>`
            }
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
    root.querySelector("#branch-search").addEventListener(
      "input",
      Fmt.debounce((event) => {
        ctx.state.branchSearch = event.target.value;
        ctx.persistState();
        ctx.reload();
      }, 320)
    );
  }

  /* ---------------------------------------------------------------- settings */
  async function settings(root, ctx) {
    const [payload, health] = await Promise.all([Api.settings(), Api.health()]);
    const settingsPayload = payload.settings;
    const numberField = (key, label, options) => {
      const opts = options || {};
      return `<div class="field"><label for="s-${key}">${esc(label)}</label>
        <input id="s-${key}" type="number" min="${opts.min === undefined ? 0 : opts.min}"${
        opts.max ? ` max="${opts.max}"` : ""
      } value="${settingsPayload[key]}" /></div>`;
    };
    const textField = (key, label) => `<div class="field"><label for="s-${key}">${esc(label)}</label>
      <input id="s-${key}" value="${esc(settingsPayload[key])}" /></div>`;

    root.innerHTML = `
      <section class="grid-2">
        <div class="panel">
          ${panelHead("Repository roots", "Folders scanned for Git repositories", "", "search")}
          <div class="field" id="settings-roots">
            <label for="roots">One absolute path per line</label>
            <textarea id="roots" rows="5" placeholder="/home/me/projects">${esc((settingsPayload.repository_roots || []).join("\n"))}</textarea>
          </div>
          <div class="toolbar mt-12">
            <button class="btn btn-primary" id="save-roots">${Icons.get("check")}Save roots</button>
            <button class="btn" id="discover">${Icons.get("search")}Discover now</button>
            <button class="btn" id="register-new" title="Register every newly discovered repository">${Icons.get("plus")}Register new &amp; scan</button>
          </div>
          <div id="roots-status" class="mt-12"></div>
        </div>

        <div class="panel">
          ${panelHead("System", `git-dashboard ${esc(health.version)}`, "", "database")}
          <div class="kv">
            ${metaItem("Git", health.git_available ? `<span class="badge badge--ok">v${esc(health.git_version || "?")}</span>` : '<span class="badge badge--danger">not found</span>')}
            ${metaItem("Git binary", `<span class="mono">${esc(health.git_binary)}</span>`)}
            ${metaItem("Schema", `<span class="mono">v${num(health.database.schema_version)}</span>`)}
            ${metaItem("Repositories", `<span class="mono">${num(health.database.imported_repositories)}</span>`)}
            ${metaItem("Database size", `<span class="mono">${bytes(health.database.size_bytes)}</span>`)}
            ${metaItem("Status", health.warnings.length ? '<span class="badge badge--warn">degraded</span>' : '<span class="badge badge--ok">ok</span>')}
          </div>
          <div class="mt-12">
            <div class="meta-label">Database file</div><div class="settings-readonly">${esc(health.database.path)}</div>
            <div class="meta-label mt-12">Config file</div><div class="settings-readonly">${esc(payload.paths.config_file || "(defaults in use)")}</div>
          </div>
          ${health.warnings
            .map((warning) => `<div class="insight insight--warning mt-12"><span class="insight-icon">${Icons.get("alert")}</span><div class="insight-body">${esc(warning)}</div></div>`)
            .join("")}
        </div>
      </section>

      <section class="panel">
        ${panelHead("Scanning &amp; analysis thresholds", "Stored in config.json · restart the server for host and port changes", "", "settings")}
        <div class="form-section">
          <div class="form-section-title">History collection</div>
          <div class="form-grid">
            ${numberField("history_depth", "history_depth — commits stored per scan", { min: 1 })}
            ${numberField("max_scan_depth", "max_scan_depth — discovery recursion depth", { min: 1, max: 64 })}
            ${textField("git_binary", "git_binary")}
            ${numberField("git_timeout_seconds", "git_timeout_seconds", { min: 1 })}
            ${numberField("refresh_interval_minutes", "refresh_interval_minutes (0 = off)", { min: 0 })}
          </div>
        </div>
        <div class="form-section">
          <div class="form-section-title">Thresholds</div>
          <div class="form-grid">
            ${numberField("inactive_branch_days", "inactive_branch_days")}
            ${numberField("stale_branch_days", "stale_branch_days", { min: 1 })}
            ${numberField("repo_inactive_days", "repo_inactive_days")}
            ${numberField("repo_stale_days", "repo_stale_days", { min: 1 })}
            ${numberField("repo_abandoned_days", "repo_abandoned_days", { min: 1 })}
          </div>
          <p class="label-hint">Thresholds must satisfy inactive &lt; stale &lt; abandoned.</p>
        </div>
        <div class="form-section">
          <div class="form-section-title">Server</div>
          <div class="form-grid">
            ${textField("host", "host")}
            ${numberField("port", "port", { min: 1, max: 65535 })}
            <div class="field"><label for="s-log_level">log_level</label>
              <select id="s-log_level">${["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                .map((level) => `<option ${settingsPayload.log_level === level ? "selected" : ""}>${level}</option>`)
                .join("")}</select></div>
          </div>
        </div>
        <div class="toolbar mt-16">
          <button class="btn btn-primary" id="save-settings">${Icons.get("check")}Save settings</button>
        </div>
      </section>

      <section class="panel">
        ${panelHead("Data &amp; exports", "Everything stays on this machine", "", "download")}
        <div class="toolbar">
          <button class="btn" id="export-json">${Icons.get("download")}JSON snapshot</button>
          <button class="btn" id="write-snapshot">${Icons.get("database")}Write snapshot to data/exports</button>
          <button class="btn" id="backup">${Icons.get("database")}Backup SQLite database</button>
          <button class="btn" id="download-repos">${Icons.get("download")}CSV: repositories</button>
          <button class="btn" id="download-commits">${Icons.get("download")}CSV: commits</button>
          <button class="btn" id="download-branches">${Icons.get("download")}CSV: branches</button>
          <button class="btn" id="download-contributors">${Icons.get("download")}CSV: contributors</button>
          <button class="btn" id="download-scans">${Icons.get("download")}CSV: scan runs</button>
        </div>
        <p class="tooltip-note mt-8">CSV exports include every repository; use the repository page for per-repository data.</p>
      </section>
    `;

    const inputs = [
      "history_depth",
      "max_scan_depth",
      "git_binary",
      "git_timeout_seconds",
      "inactive_branch_days",
      "stale_branch_days",
      "repo_inactive_days",
      "repo_stale_days",
      "repo_abandoned_days",
      "refresh_interval_minutes",
      "log_level",
      "host",
      "port",
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
    [
      ["download-repos", "repositories"],
      ["download-commits", "commits"],
      ["download-branches", "branches"],
      ["download-contributors", "contributors"],
      ["download-scans", "scan_runs"],
    ].forEach(([id, table]) => {
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
              (entry) => `<div class="insight ${entry.exists ? "insight--info" : "insight--warning"}">
                <span class="insight-icon">${Icons.get(entry.exists ? "file" : "alert")}</span>
                <div class="insight-body mono">${esc(entry.path)}${entry.exists ? "" : " — does not exist"}</div>
              </div>`
            )
            .join("")
        : `<p class="muted">No roots configured yet. Add one so the dashboard can discover repositories automatically.</p>`;
    } catch (error) {
      container.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
    }
  }

  async function runDiscovery(root, ctx, register) {
    const container = root.querySelector("#roots-status");
    container.innerHTML = UI.loading("Scanning configured roots…");
    try {
      const result = await Api.discover({ register });
      const repositories = (result.roots || []).flatMap((entry) => entry.repositories || []);
      container.innerHTML = `
        <p class="muted">${num(result.count)} repository(ies) found${register ? `, ${num(result.registered_count || 0)} registered` : ""}.</p>
        <div class="table-wrap table-wrap--scroll" style="max-height:280px"><table class="table table--compact">
          <thead><tr><th scope="col">Path</th><th scope="col">Status</th></tr></thead>
          <tbody>${
            repositories
              .map(
                (repository) =>
                  `<tr><td class="mono">${esc(repository.path)}</td><td>${
                    repository.already_registered
                      ? '<span class="badge badge--neutral">registered</span>'
                      : '<span class="badge badge--info">new</span>'
                  }</td></tr>`
              )
              .join("") || `<tr><td colspan="2" class="muted center">Nothing found. Check the root paths.</td></tr>`
          }</tbody>
        </table></div>
        ${
          result.errors && result.errors.length
            ? `<p class="tooltip-note mt-8">${num(result.errors.length)} directory(ies) could not be read.</p>`
            : ""
        }
      `;
      if (register && (result.registered_count || 0) > 0) {
        ctx.toast(`Registered ${num(result.registered_count)} repository(ies) — starting a scan.`, "ok");
        ctx.startScanAll({ discover: false });
      }
    } catch (error) {
      container.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
      ctx.toast(error.message, "error", 7000);
    }
  }

  global.Views = { dashboard, repositories, repositoryDetail, activity, branches, settings, repoTable, wireRepoTable, insightsHtml };
})(window);
