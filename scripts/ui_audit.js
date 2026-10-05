/**
 * Structural + accessibility audit of the buildless frontend.
 *
 * Complements `scripts/ui_smoke.js` (which only checks that every view renders):
 * this one asserts the design system is actually wired up - KPI/panel/chart
 * markup, health meters and rings, the heatmap, segmented filters, tab
 * state, modal focus handling, theme cycling, keyboard shortcuts, persisted
 * view state and that every interactive control has an accessible name. It also
 * checks the narrative layer (briefing tone/headline/lines, 'Do this first',
 * severity-grouped findings). The last
 * step clicks "Scan all repositories" and waits for progress, the toast and the
 * reset button, so it does run a real (fast, incremental) scan.
 *
 * Optional developer tool: the application itself has no Node dependency.
 *
 *   npm install --prefix /tmp/ui-smoke jsdom
 *   NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_audit.js http://127.0.0.1:8000
 *
 * Expected results are recorded in docs/verification.md.
 */
let JSDOM;
let VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
} catch (error) {
  console.error("jsdom is not installed. Run:");
  console.error("  npm install --prefix /tmp/ui-smoke jsdom");
  process.exit(2);
}

const base = "http://127.0.0.1:8000";
const errors = [];
const notes = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push(`jsdomError: ${e.message}`));
vc.on("error", (...a) => errors.push(`console.error: ${a.join(" ")}`));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function accessibleName(el) {
  const aria = el.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim();
  const title = el.getAttribute("title");
  const text = (el.textContent || "").replace(/\s+/g, " ").trim();
  if (text) return text;
  if (title && title.trim()) return title.trim();
  return "";
}

(async () => {
  const html = await (await fetch(base + "/")).text();
  const dom = new JSDOM(html, { url: base + "/", runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc });
  const { window } = dom;
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    return fetch(url.startsWith("http") ? url : base + url, init);
  };
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollTo = () => {};
  const doc = window.document;

  const check = (condition, message) => { if (!condition) errors.push(message); };
  const unnamed = (scope) => [...scope.querySelectorAll("button, a[href]")]
    .filter((el) => !accessibleName(el))
    .map((el) => el.outerHTML.slice(0, 90));

  await sleep(2500);

  const expectedRepositories = (await (await fetch(base + "/api/repositories?per_page=1")).json()).pagination.total;

  // --- dashboard
  const kpis = doc.querySelectorAll("#view .kpi-card");
  check(kpis.length === 6, `dashboard: expected 6 KPI cards, found ${kpis.length}`);

  // The briefing leads the dashboard and must be a real narrative, not decoration.
  const briefing = doc.querySelector("#view .briefing");
  check(Boolean(briefing), "dashboard: briefing panel missing");
  if (briefing) {
    check(/\bbriefing--(danger|warn|ok|neutral)\b/.test(briefing.className), `briefing: unexpected tone class ${briefing.className}`);
    const headline = briefing.querySelector(".briefing-headline");
    check(headline && headline.textContent.trim().length > 8, "briefing: headline missing or too short");
    check(Boolean(briefing.querySelector(".briefing-summary")), "briefing: summary line missing");
    const lines = briefing.querySelectorAll(".briefing-line");
    check(lines.length <= 5, `briefing: expected at most 5 lines, found ${lines.length}`);
    const severities = [...lines].map((line) => (line.className.match(/briefing-line--(\w+)/) || [])[1]);
    const ranks = { error: 0, warning: 1, info: 2 };
    check(
      severities.every((value, index) => index === 0 || ranks[severities[index - 1]] <= ranks[value]),
      `briefing: lines are not severity ordered (${severities.join(", ")})`
    );
    check(Boolean(briefing.querySelector(".briefing-foot")), "briefing: scan/delta footer missing");
    const nextAction = briefing.querySelector(".next-action");
    check(Boolean(nextAction) && nextAction.textContent.includes("Do this first"), "briefing: 'Do this first' callout missing");
    notes.push(`briefing: ${headline.textContent.trim()} (${lines.length} lines)`);
  }

  const groups = doc.querySelectorAll("#view .findings-group");
  const findings = doc.querySelectorAll("#view .finding");
  check(groups.length >= 1, "dashboard: findings are not grouped by severity");
  check(findings.length >= 1, "dashboard: no findings rendered");
  notes.push(`findings: ${findings.length} in ${groups.length} severity groups`);
  check(doc.querySelectorAll("#view .chart--line svg polyline").length >= 1, "dashboard: no activity line rendered");
  check(doc.querySelectorAll("#view .sparkline").length >= 1, "dashboard: no sparkline rendered");
  check(doc.querySelectorAll("#view .panel").length >= 4, "dashboard: expected at least 4 panels");
  check(doc.querySelectorAll("#view .finding").length >= 1, "dashboard: no finding rows rendered");
  const dashUnnamed = unnamed(doc.querySelector("#view"));
  check(dashUnnamed.length === 0, `dashboard: controls without accessible name: ${JSON.stringify(dashUnnamed)}`);
  const nav = [...doc.querySelectorAll("#nav a")];
  check(nav.length === 5, `nav: expected 5 links, found ${nav.length}`);
  check(nav.every((link) => link.querySelector("svg")), "nav: icons missing");
  check(
    doc.querySelector("#nav .nav-badge").textContent.trim() === String(expectedRepositories),
    `nav badge: expected ${expectedRepositories}, got ${doc.querySelector("#nav .nav-badge").textContent.trim()}`
  );
  check(
    doc.querySelector("#page-badge").textContent.includes(`${expectedRepositories} repositories`),
    "page badge: repository count missing"
  );

  // --- keyboard shortcut: g then r
  const key = (k) => doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true }));
  key("g"); key("r");
  await sleep(1600);
  check(window.location.pathname === "/repositories", `keyboard: g r did not navigate (at ${window.location.pathname})`);
  const rows = doc.querySelectorAll("#view table tbody tr");
  check(rows.length === expectedRepositories, `repositories: expected ${expectedRepositories} rows, got ${rows.length}`);
  const repUnnamed = unnamed(doc.querySelector("#view"));
  check(repUnnamed.length === 0, `repositories: controls without accessible name: ${JSON.stringify(repUnnamed)}`);
  check(doc.querySelectorAll("#view .meter").length >= expectedRepositories, "repositories: health meters missing");
  check(!doc.querySelector("#view .card"), "repositories: legacy .card markup still present");

  // --- theme cycle light -> dark -> system
  const themeButton = doc.getElementById("theme-toggle");
  const seen = new Set();
  for (let i = 0; i < 3; i += 1) {
    themeButton.click();
    await sleep(120);
    const value = doc.documentElement.getAttribute("data-theme");
    seen.add(value);
    if (i === 0) {
      check(value === "light", `theme: first click expected light, got ${value}`);
      check(window.localStorage.getItem("git-dashboard-theme") === "light", "theme: explicit choice not persisted in localStorage");
    }
    if (i === 2) {
      check(value === null, `theme: third click expected system (null), got ${value}`);
      check(window.localStorage.getItem("git-dashboard-theme") === null, "theme: system choice should clear the stored key");
    }
  }
  notes.push(`theme states: ${[...seen].map((v) => v === null ? "system" : v).join(", ")}`);
  check(seen.has("light") && seen.has("dark") && seen.has(null), "theme: cycle did not cover light, dark and system");

  // --- repository detail: heatmap + churn charts
  doc.querySelector("a[data-link][href^='/repositories/']").click();
  await sleep(2200);
  check(doc.querySelectorAll("#view table.heatmap .heat-cell").length > 100, "detail: heatmap cells missing");
  check(doc.querySelectorAll("#view .bar-list .bar-row").length >= 3, "detail: churn bars missing");
  check(doc.querySelectorAll("#view .ring svg .health-ring, #view svg.health-ring").length >= 1, "detail: health ring missing");
  check(doc.querySelectorAll("#view .signal").length >= 3, "detail: health signals missing");
  check(
    Boolean(doc.querySelector("#view .next-action")),
    "detail: 'Do this first' callout missing even though the repository has recommendations"
  );
  const detailUnnamed = unnamed(doc.querySelector("#view"));
  check(detailUnnamed.length === 0, `detail: controls without accessible name: ${JSON.stringify(detailUnnamed)}`);

  // tabs
  for (const tab of ["commits", "branches", "contributors", "activity", "insights"]) {
    const button = doc.querySelector(`[data-tab='${tab}']`);
    button.click();
    await sleep(1400);
    check(doc.querySelector("[data-tab][aria-selected='true']").dataset.tab === tab, `tab ${tab}: aria-selected not updated`);
    const content = doc.getElementById("tab-content");
    check(content.textContent.trim().length > 40, `tab ${tab}: empty content`);
    const tabErrors = doc.querySelectorAll("#tab-content .error-box").length;
    check(tabErrors === 0, `tab ${tab}: error box rendered`);
  }
  notes.push(`tabs rendered: 5`);

  // commit modal: file table + copy buttons
  doc.querySelector("[data-tab='commits']").click();
  await sleep(1400);
  doc.querySelector("tr[data-sha]").click();
  await sleep(1600);
  const modal = doc.getElementById("modal");
  check(!modal.classList.contains("hidden"), "modal: did not open");
  check(/File/.test(modal.textContent), "modal: file table header missing");
  check(modal.querySelectorAll("[data-copy]").length >= 1, "modal: copy button missing");
  check(doc.activeElement && modal.contains(doc.activeElement), `modal: focus not moved inside (${doc.activeElement && doc.activeElement.tagName})`);
  doc.getElementById("modal-close").click();
  await sleep(200);
  check(modal.classList.contains("hidden"), "modal: did not close");

  // --- settings: form sections and readonly paths
  key("g"); key("s");
  await sleep(1800);
  check(doc.querySelectorAll("#view .form-section").length === 3, "settings: expected 3 form sections");
  check(doc.querySelectorAll("#view #settings-roots").length === 1, "settings: roots field missing");
  check(doc.querySelectorAll("#view input, #view select, #view textarea").length >= 13, "settings: inputs missing");
  check(doc.querySelectorAll("#view .insight").length >= 1, "settings: root status rows missing");

  // --- branches view: segmented filter works
  key("g"); key("b");
  await sleep(1600);
  const branchRows = doc.querySelectorAll("#view table tbody tr").length;
  notes.push(`branch rows: ${branchRows}`);
  check(branchRows > 0, "branches: no rows");
  const staleChip = [...doc.querySelectorAll("#view [data-branch-filter]")].find((b) => b.dataset.branchFilter === "stale");
  staleChip.click();
  await sleep(1500);
  const staleRows = doc.querySelectorAll("#view table tbody tr").length;
  notes.push(`stale branch rows after filter: ${staleRows}`);
  check(staleRows > 0 && staleRows < branchRows, `branches: stale filter did not narrow the list (${staleRows} vs ${branchRows})`);

  // --- activity view: bucket switch re-renders the chart
  key("g"); key("a");
  await sleep(1600);
  check(doc.querySelectorAll("#view .chart svg").length >= 1, "activity: chart missing");
  const bucket = doc.getElementById("bucket");
  bucket.value = "week";
  bucket.dispatchEvent(new window.Event("change", { bubbles: true }));
  await sleep(1600);
  check(doc.getElementById("bucket").value === "week", "activity: bucket selection not restored after re-render");
  check(
    JSON.parse(window.localStorage.getItem("git-dashboard-state-v1") || "{}").bucket === "week",
    "state: view state not persisted in localStorage"
  );
  check(doc.querySelectorAll("#view .chart svg polyline").length >= 1, "activity: weekly chart not rendered");

  // --- scan progress wiring: the sidebar button must drive progress, toasts and refresh
  const scanButton = doc.getElementById("btn-scan-all");
  const progressBar = doc.getElementById("scan-progress");
  const toastCountBefore = doc.getElementById("toasts").children.length;
  scanButton.click();
  let sawProgress = null;
  let sawToast = false;
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await sleep(500);
    if (!progressBar.hidden) sawProgress = doc.querySelector("#scan-status .state-dot").className;
    if (doc.getElementById("toasts").children.length > toastCountBefore) {
      const text = doc.getElementById("toasts").textContent;
      if (/Scan /.test(text)) sawToast = true;
    }
    if (sawToast && progressBar.hidden) break;
  }
  check(sawToast, "scan: no scan toast appeared after clicking Scan all repositories");
  check(progressBar.hidden, "scan: progress bar never returned to hidden");
  check(!scanButton.disabled, "scan: button stayed disabled after the scan finished");
  check(doc.querySelector("#scan-status .state-dot").className === "state-dot state-dot--ok", "scan: indicator did not settle on ok");
  notes.push(`scan progress indicator seen: ${sawProgress || "completed before the first poll"}`);

  const result = { errors, notes, expectedRepositories, audits: 8 };
  console.log(JSON.stringify(result, null, 2));
  window.close();
  process.exit(errors.length ? 1 : 0);
})().catch((error) => { console.error("audit failed:", error); process.exit(2); });
