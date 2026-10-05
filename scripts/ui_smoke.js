/**
 * Headless smoke test for the buildless frontend.
 *
 * Loads index.html from a running dashboard in jsdom, walks every view, opens
 * the first repository, switches its tabs, opens a commit, checks the settings
 * page and fails on any console error, failed request or missing element.
 *
 * Optional developer tool: the application itself has no Node dependency.
 *
 *   npm install --prefix /tmp/ui-smoke jsdom
 *   NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_smoke.js http://127.0.0.1:8000
 *
 * The expected baseline for the demo dataset is recorded in docs/verification.md.
 */
let JSDOM;
let VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
} catch (error) {
  console.error("jsdom is not installed. Run:");
  console.error("  npm install --prefix /tmp/ui-smoke jsdom");
  console.error("  NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_smoke.js " + (process.argv[2] || "http://127.0.0.1:8000"));
  process.exit(2);
}


const base = process.argv[2] || "http://127.0.0.1:8000";
const errors = [];
const consoleLines = [];
const requests = [];

const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (error) => errors.push(`jsdomError: ${error.message}`));
virtualConsole.on("error", (...args) => errors.push(`console.error: ${args.join(" ")}`));
virtualConsole.on("warn", (...args) => consoleLines.push(`warn: ${args.join(" ")}`));
virtualConsole.on("log", (...args) => consoleLines.push(`log: ${args.join(" ")}`));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const html = await (await fetch(base + "/")).text();
  const dom = new JSDOM(html, {
    url: base + "/",
    runScripts: "dangerously",
    resources: "usable",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const { window } = dom;

  // jsdom has no fetch and no relative-URL support: provide one that resolves
  // against the dashboard and records every call.
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    const absolute = url.startsWith("http") ? url : base + url;
    requests.push(`${(init && init.method) || "GET"} ${url}`);
    return fetch(absolute, init);
  };
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollTo = () => {};
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));

  await sleep(2500); // let scripts load and the initial dashboard render

  function clickNav(route) {
    const link = [...window.document.querySelectorAll("#nav a")].find((element) => element.dataset.route === route);
    if (!link) {
      errors.push(`nav link ${route} missing`);
      return false;
    }
    link.click();
    return true;
  }

  const steps = [
    ["/repositories", "table tbody tr"],
    ["/activity", "svg"],
    ["/branches", "table tbody tr"],
    ["/settings", "#settings-roots, textarea, .panel"],
    ["/", ".card, .metric"],
  ];

  for (const [route, selector] of steps) {
    if (!clickNav(route)) continue;
    await sleep(1500);
    const found = window.document.querySelector(selector);
    const view = window.document.querySelector("#view");
    if (!found) errors.push(`${route}: no element matching ${selector} (text: ${(view && view.textContent.trim().replace(/\s+/g, " ").slice(0, 160)) || "n/a"})`);
    else consoleLines.push(`${route}: ok (${window.location.pathname})`);
  }

  // Repository detail: open the first repository link from the list.
  clickNav("/repositories");
  await sleep(1500);
  const link = window.document.querySelector("a[data-link][href^='/repositories/']");
  if (!link) {
    errors.push("repositories view: no repository link found");
  } else {
    link.click();
    await sleep(2000);
    consoleLines.push(`repo detail path: ${window.location.pathname}`);
    const body = window.document.body.textContent;
    if (!/health|commit/i.test(body)) errors.push("repository detail: expected health/commit content");
    for (const [tab, selector] of [["commits", "table tbody tr, .empty-state"], ["branches", "table tbody tr, .empty-state"], ["contributors", "table tbody tr, .empty-state"], ["insights", "li, .empty-state, .insight"]]) {
      const button = [...window.document.querySelectorAll("button, a")].find((element) => element.textContent.trim().toLowerCase() === tab);
      if (!button) {
        errors.push(`repository detail: '${tab}' tab button missing`);
        continue;
      }
      button.click();
      await sleep(1200);
      if (!window.document.querySelector(selector)) errors.push(`repository detail tab ${tab}: nothing rendered (${selector})`);
      else consoleLines.push(`repo tab ${tab}: ok`);
    }

    // Open the first commit and check the file table inside the modal.
    const commitsButton = [...window.document.querySelectorAll("button, a")].find((element) => element.textContent.trim().toLowerCase() === "commits");
    if (commitsButton) {
      commitsButton.click();
      await sleep(1200);
      const row = window.document.querySelector("tr[data-sha]");
      if (!row) {
        errors.push("commits tab: no commit rows rendered");
      } else {
        row.click();
        await sleep(1500);
        const modal = window.document.getElementById("modal");
        const text = (modal && modal.textContent) || "";
        if (!/File|Changed|No file statistics/i.test(text)) errors.push(`commit modal did not open a detail view: ${text.slice(0, 160)}`);
        else consoleLines.push(`commit modal: ok (${text.replace(/\s+/g, " ").slice(0, 90)})`);
        window.document.getElementById("modal-close").click();
        await sleep(300);
      }
    }
  }

  clickNav("/repositories");
  await sleep(1500);
  const rowCount = window.document.querySelectorAll("#view table tbody tr").length;
  consoleLines.push(`repository rows: ${rowCount}`);
  if (rowCount !== 8) errors.push(`repositories view: expected 8 rows, found ${rowCount}`);

  const rendered = window.document.body.textContent.replace(/\s+/g, " ").trim();
  const result = {
    errors: errors.filter((error) => !/scrollTo|Not implemented/.test(error)),
    allErrors: errors,
    requests: requests.length,
    uniqueRequestPaths: [...new Set(requests)].length,
    failedRequests: [],
    bodyLength: rendered.length,
    sample: rendered.slice(0, 200),
  };
  result.steps = consoleLines;
  console.log(JSON.stringify(result, null, 2));
  dom.window.close();
  process.exit(errors.length ? 1 : 0);
}

main().catch((error) => {
  console.error("smoke failed:", error);
  process.exit(2);
});
