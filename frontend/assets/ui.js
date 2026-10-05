/* UI kit: inline SVG icons, theme switching, toasts, modal, command palette.
   Dependency-free, no build step. Exposes `window.Icons` and `window.UI`. */
(function (global) {
  "use strict";

  /* --------------------------------------------------------------- icons --- */
  const PATHS = {
    dashboard:
      '<rect x="3" y="3" width="7.5" height="8.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="5" rx="2"/><rect x="13.5" y="11" width="7.5" height="10" rx="2"/><rect x="3" y="14.5" width="7.5" height="6.5" rx="2"/>',
    repositories:
      '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19a1 1 0 0 1 1 1v13"/><path d="M4 5.5v13A2.5 2.5 0 0 0 6.5 21H19"/><path d="M8 7h8"/><path d="M8 11h6"/>',
    activity: '<path d="M3 12h3.5l2.5-7 4 14 2.5-7H21"/>',
    branches:
      '<circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><circle cx="18" cy="9" r="2.6"/><path d="M6 8.6v6.8"/><path d="M8.6 6H14a4 4 0 0 1 4 4v0"/>',
    settings:
      '<path d="M4 7h10"/><path d="M18 7h2"/><circle cx="16" cy="7" r="2.2"/><path d="M4 17h4"/><path d="M12 17h8"/><circle cx="10" cy="17" r="2.2"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4.2-4.2"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-.7 4"/><path d="M20 4v7h-7"/>',
    scan: '<path d="M4 12a8 8 0 0 1 13.7-5.6"/><path d="M20 12a8 8 0 0 1-13.7 5.6"/><path d="M17.5 3v3.6h-3.6"/><path d="M6.5 21v-3.6h3.6"/>',
    plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    download: '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
    database:
      '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
    alert: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.5 17.2A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.8L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
    error: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.5h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
    bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.3.3.5.7.5 1.1h6c0-.4.2-.8.5-1.1A6 6 0 0 0 12 3Z"/>',
    close: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    chevronLeft: '<path d="m14 6-6 6 6 6"/>',
    chevronRight: '<path d="m10 6 6 6-6 6"/>',
    arrowUp: '<path d="M12 19V5"/><path d="m5.5 11.5 6.5-6.5 6.5 6.5"/>',
    arrowDown: '<path d="M12 5v14"/><path d="m5.5 12.5 6.5 6.5 6.5-6.5"/>',
    commit: '<circle cx="12" cy="12" r="3.4"/><path d="M3 12h5.6M15.4 12H21"/>',
    merge:
      '<circle cx="7" cy="18" r="2.4"/><circle cx="7" cy="6" r="2.4"/><circle cx="17" cy="12" r="2.4"/><path d="M7 8.4v7.2"/><path d="M9.4 6.6c1 .6 1.6 1.4 2.6 2.4 1.2 1.2 2 2.2 3 2.7"/>',
    user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-6A2.5 2.5 0 0 0 4 5.5v6A2.5 2.5 0 0 0 6.5 14"/>',
    external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    filter: '<path d="M4 6h16"/><path d="M7 12h10"/><path d="M10 18h4"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7.5 9 2.5 3-2.5 3"/><path d="M13 15h4"/>',
    chart: '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
    zap: '<path d="M13 2 4.5 13.5H11l-1 8.5 9-11.5h-6.5Z"/>',
  };

  function icon(name, extraClass) {
    const path = PATHS[name];
    if (!path) return "";
    const cls = extraClass ? ` class="${extraClass}"` : "";
    return `<svg${cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${path}</svg>`;
  }

  const Icons = { get: icon, has: (name) => Boolean(PATHS[name]), names: Object.keys(PATHS) };
  global.Icons = Icons;

  /* --------------------------------------------------------------- theme --- */
  const THEME_KEY = "git-dashboard-theme";
  const THEMES = ["light", "dark"];

  function prefersDark() {
    return Boolean(global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  const theme = {
    /** Stored choice, or null when the dashboard follows the system. */
    stored() {
      try {
        const value = localStorage.getItem(THEME_KEY);
        return THEMES.includes(value) ? value : null;
      } catch (error) {
        return null;
      }
    },
    /** Theme currently in effect. */
    current() {
      return this.stored() || (prefersDark() ? "dark" : "light");
    },
    /** Apply a theme. `null` restores "follow the system". */
    set(value) {
      if (value === null) document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", value);
      try {
        if (value === null) localStorage.removeItem(THEME_KEY);
        else localStorage.setItem(THEME_KEY, value);
      } catch (error) {
        /* storage unavailable: the attribute still applies for this session */
      }
      this.paint();
    },
    /** Cycle light → dark → (system) → light … only when the user asks for it. */
    toggle() {
      const order = ["light", "dark", null];
      const next = order[(order.indexOf(this.stored()) + 1) % order.length];
      this.set(next);
      return next;
    },
    /** Render the toggle button in the top bar. */
    paint() {
      const button = document.getElementById("theme-toggle");
      if (!button) return;
      const current = this.current();
      button.setAttribute("aria-label", `Switch to ${current === "dark" ? "light" : "dark"} theme`);
      button.setAttribute("title", `Colour theme: ${current}${this.stored() ? "" : " (system)"} — click to cycle`);
      const iconSlot = button.querySelector("[data-theme-icon]");
      const labelSlot = button.querySelector("[data-theme-label]");
      if (iconSlot) iconSlot.innerHTML = icon(current === "dark" ? "moon" : "sun");
      if (labelSlot) labelSlot.textContent = this.stored() ? current[0].toUpperCase() + current.slice(1) : "System";
    },
    init() {
      this.paint();
      if (global.matchMedia) {
        const media = global.matchMedia("(prefers-color-scheme: dark)");
        const listener = () => {
          if (!this.stored()) this.paint();
        };
        if (media.addEventListener) media.addEventListener("change", listener);
        else if (media.addListener) media.addListener(listener);
      }
    },
  };

  /* --------------------------------------------------------------- toasts --- */
  const TOAST_ICONS = { ok: "check", error: "error", warn: "alert", info: "info" };

  function toast(message, kind, timeout) {
    const container = document.getElementById("toasts");
    if (!container) return null;
    const type = TOAST_ICONS[kind] ? kind : "info";
    const element = document.createElement("div");
    element.className = `toast toast-${type}`;
    element.setAttribute("role", type === "error" ? "alert" : "status");
    element.innerHTML = `${icon(TOAST_ICONS[type])}<div class="toast-body">${Fmt.escapeHtml(message)}</div>
      <button class="btn btn-ghost btn-icon" type="button" aria-label="Dismiss">${icon("close")}</button>`;
    container.appendChild(element);
    const dismiss = () => {
      element.style.opacity = "0";
      element.style.transform = "translateY(6px)";
      element.style.transition = "opacity 160ms ease, transform 160ms ease";
      setTimeout(() => element.remove(), 170);
    };
    element.querySelector("button").addEventListener("click", dismiss);
    setTimeout(dismiss, timeout || 4600);
    return element;
  }

  /* ---------------------------------------------------------------- modal --- */
  let lastFocused = null;
  let trapHandler = null;
  let onCloseHook = null;

  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function trapFocus(container) {
    return (event) => {
      if (event.key !== "Tab") return;
      const items = Array.from(container.querySelectorAll(FOCUSABLE)).filter((node) => node.offsetParent !== null || node === document.activeElement);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
  }

  function lockScroll(lock) {
    document.documentElement.style.overflow = lock ? "hidden" : "";
  }

  const modal = {
    isOpen() {
      const element = document.getElementById("modal");
      return Boolean(element && !element.classList.contains("hidden"));
    },
    open(options) {
      const opts = options || {};
      const element = document.getElementById("modal");
      const title = document.getElementById("modal-title");
      const body = document.getElementById("modal-body");
      if (!element || !body) return;
      lastFocused = document.activeElement;
      title.innerHTML = `${opts.icon ? icon(opts.icon) : ""}<span>${Fmt.escapeHtml(opts.title || "Details")}</span>`;
      body.innerHTML = opts.html || "";
      element.classList.remove("hidden");
      lockScroll(true);
      const card = element.querySelector(".modal-card");
      if (card) {
        card.style.width = opts.wide ? "min(1100px, 100%)" : "";
      }
      if (trapHandler) document.removeEventListener("keydown", trapHandler);
      trapHandler = trapFocus(element);
      document.addEventListener("keydown", trapHandler);
      const focusTarget = element.querySelector("[autofocus], button, a[href], input") || card;
      if (focusTarget && focusTarget.focus) focusTarget.focus();
      document.dispatchEvent(new CustomEvent("ui:modal-open"));
    },
    close() {
      const element = document.getElementById("modal");
      if (!element) return;
      element.classList.add("hidden");
      lockScroll(false);
      if (trapHandler) {
        document.removeEventListener("keydown", trapHandler);
        trapHandler = null;
      }
      const hook = onCloseHook;
      onCloseHook = null;
      if (hook) hook(null);
      if (lastFocused && lastFocused.focus) lastFocused.focus();
      lastFocused = null;
    },
    /** Promise-based confirm dialog replacing window.confirm. */
    confirm(options) {
      const opts = options || {};
      return new Promise((resolve) => {
        onCloseHook = resolve;
        modal.open({
          title: opts.title || "Please confirm",
          icon: opts.icon || (opts.danger ? "alert" : "info"),
          html: `<p>${Fmt.escapeHtml(opts.message || "Are you sure?")}</p>
            ${opts.detail ? `<p class="muted">${Fmt.escapeHtml(opts.detail)}</p>` : ""}`,
        });
        const body = document.getElementById("modal-body");
        const footer = document.createElement("div");
        footer.className = "modal-foot";
        footer.innerHTML = `<button class="btn" data-cancel>${Fmt.escapeHtml(opts.cancelLabel || "Cancel")}</button>
          <button class="btn ${opts.danger ? "btn-danger" : "btn-primary"}" data-confirm>${Fmt.escapeHtml(opts.confirmLabel || "Confirm")}</button>`;
        body.appendChild(footer);
        footer.querySelector("[data-confirm]").addEventListener("click", () => {
          onCloseHook = null;
          modal.close();
          resolve(true);
        });
        footer.querySelector("[data-cancel]").addEventListener("click", () => {
          onCloseHook = null;
          modal.close();
          resolve(false);
        });
        const confirmButton = footer.querySelector("[data-confirm]");
        if (confirmButton) confirmButton.focus();
      });
    },
    /** Promise-based single-input dialog replacing window.prompt. */
    prompt(options) {
      const opts = options || {};
      return new Promise((resolve) => {
        onCloseHook = resolve;
        modal.open({
          title: opts.title || "Enter a value",
          icon: opts.icon || "plus",
          html: `<form class="stack" id="prompt-form">
            <div class="field"><label for="prompt-input">${Fmt.escapeHtml(opts.label || "Value")}</label>
              <input id="prompt-input" autofocus type="text" placeholder="${Fmt.escapeHtml(opts.placeholder || "")}" value="${Fmt.escapeHtml(opts.value || "")}" /></div>
            ${opts.hint ? `<p class="label-hint">${Fmt.escapeHtml(opts.hint)}</p>` : ""}
          </form>`,
        });
        const body = document.getElementById("modal-body");
        const footer = document.createElement("div");
        footer.className = "modal-foot";
        footer.innerHTML = `<button class="btn" data-cancel>Cancel</button>
          <button class="btn btn-primary" data-confirm form="prompt-form">${Fmt.escapeHtml(opts.confirmLabel || "Continue")}</button>`;
        body.appendChild(footer);
        const input = body.querySelector("#prompt-input");
        const form = body.querySelector("#prompt-form");
        const submit = () => {
          const value = input.value.trim();
          if (!value) {
            input.focus();
            return;
          }
          onCloseHook = null;
          modal.close();
          resolve(value);
        };
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          submit();
        });
        footer.querySelector("[data-confirm]").addEventListener("click", (event) => {
          event.preventDefault();
          submit();
        });
        footer.querySelector("[data-cancel]").addEventListener("click", () => {
          onCloseHook = null;
          modal.close();
          resolve(null);
        });
        if (input) input.focus();
      });
    },
  };

  /* --------------------------------------------------------- command menu --- */
  const palette = {
    element: null,
    items: [],
    filtered: [],
    index: 0,

    build() {
      const backdrop = document.createElement("div");
      backdrop.className = "palette-backdrop hidden";
      backdrop.innerHTML = `<div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="palette-search">${icon("search")}
          <input class="palette-input" id="palette-input" type="text" placeholder="Jump to a view, repository or action…" autocomplete="off" spellcheck="false" aria-controls="palette-list" />
          <span class="kbd">Esc</span>
        </div>
        <ul class="palette-list" id="palette-list" role="listbox" aria-label="Commands"></ul>
        <div class="palette-hint"><span><span class="kbd">↑</span> <span class="kbd">↓</span> navigate</span><span><span class="kbd">↵</span> open</span><span><span class="kbd">Esc</span> close</span></div>
      </div>`;
      document.body.appendChild(backdrop);
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) this.close();
      });
      const input = backdrop.querySelector("#palette-input");
      input.addEventListener("input", () => {
        this.index = 0;
        this.filter(input.value);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          this.move(1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          this.move(-1);
        } else if (event.key === "Enter") {
          event.preventDefault();
          this.run();
        } else if (event.key === "Escape") {
          event.preventDefault();
          this.close();
        }
      });
      backdrop.querySelector("#palette-list").addEventListener("click", (event) => {
        const row = event.target.closest("[data-index]");
        if (!row) return;
        this.index = Number(row.dataset.index);
        this.run();
      });
      this.element = backdrop;
      return backdrop;
    },

    open(items) {
      const backdrop = this.element || this.build();
      this.items = items || [];
      this.index = 0;
      backdrop.classList.remove("hidden");
      lockScroll(true);
      lastFocused = document.activeElement;
      const input = backdrop.querySelector("#palette-input");
      input.value = "";
      this.query = "";
      this.filter("");
      input.focus();
    },

    close() {
      if (this.element) this.element.classList.add("hidden");
      lockScroll(false);
      if (lastFocused && lastFocused.focus) lastFocused.focus();
      lastFocused = null;
    },

    isOpen() {
      return Boolean(this.element && !this.element.classList.contains("hidden"));
    },

    filter(query) {
      this.query = String(query === undefined ? this.query || "" : query);
      const needle = String(this.query).trim().toLowerCase();
      this.filtered = this.items
        .map((item) => {
          const haystack = `${item.label} ${item.group || ""} ${item.keywords || ""}`.toLowerCase();
          if (!needle) return { item, score: 1 };
          if (!haystack.includes(needle)) return null;
          const label = String(item.label).toLowerCase();
          return { item, score: label.startsWith(needle) ? 0 : label.includes(needle) ? 1 : 2 };
        })
        .filter(Boolean)
        .sort((a, b) => a.score - b.score)
        .map((entry) => entry.item);
      if (this.index >= this.filtered.length) this.index = Math.max(0, this.filtered.length - 1);
      this.paint();
    },

    /** Replace the item list while the palette stays open (keeps the query). */
    setItems(items) {
      this.items = items || [];
      this.index = 0;
      this.filter(this.query || "");
    },

    paint() {
      if (!this.element) return;
      const list = this.element.querySelector("#palette-list");
      if (!this.filtered.length) {
        list.innerHTML = `<li class="palette-empty">Nothing matches. Try another word.</li>`;
        return;
      }
      let group = null;
      list.innerHTML = this.filtered
        .map((item, index) => {
          const header = item.group && item.group !== group ? ((group = item.group), `<li class="palette-group" role="presentation">${Fmt.escapeHtml(item.group)}</li>`) : "";
          const active = index === this.index ? " palette-item--active" : "";
          return `${header}<li class="palette-item${active}" role="option" aria-selected="${index === this.index}" data-index="${index}">
            ${icon(item.icon || "chevronRight")}
            <span class="palette-item-label">${Fmt.escapeHtml(item.label)}</span>
            ${item.hint ? `<span class="palette-item-hint">${Fmt.escapeHtml(item.hint)}</span>` : ""}
          </li>`;
        })
        .join("");
      const active = list.querySelector(".palette-item--active");
      if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
    },

    move(delta) {
      if (!this.filtered.length) return;
      this.index = (this.index + delta + this.filtered.length) % this.filtered.length;
      this.paint();
    },

    run() {
      const item = this.filtered[this.index];
      if (!item) return;
      this.close();
      item.run();
    },
  };

  /* -------------------------------------------------------------- helpers --- */
  function progress(value) {
    const bar = document.getElementById("scan-progress");
    if (!bar) return;
    const fill = bar.querySelector("span") || bar;
    const bounded = Math.max(0, Math.min(100, Number(value) || 0));
    bar.hidden = false;
    bar.setAttribute("aria-valuenow", String(Math.round(bounded)));
    fill.style.width = `${bounded}%`;
  }

  async function copy(text) {
    const value = String(text);
    try {
      if (navigator.clipboard && global.isSecureContext !== false) {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch (error) {
      /* fall through to execCommand */
    }
    try {
      const area = document.createElement("textarea");
      area.value = value;
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

  function copyButton(text, label) {
    return `<button class="btn btn-ghost btn-icon copy-btn" type="button" data-copy="${Fmt.escapeHtml(String(text))}" aria-label="Copy ${Fmt.escapeHtml(label || text)}" title="Copy">${icon("copy")}</button>`;
  }

  function wireCopy(root) {
    (root || document).querySelectorAll("[data-copy]").forEach((button) => {
      if (button.dataset.copyWired) return;
      button.dataset.copyWired = "1";
      button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = await copy(button.dataset.copy);
        if (ok) {
          const previous = button.innerHTML;
          button.innerHTML = icon("check");
          setTimeout(() => {
            button.innerHTML = previous;
          }, 1200);
        }
        toast(ok ? "Copied to clipboard." : "Copy failed — select the text manually.", ok ? "ok" : "warn", 2600);
      });
    });
  }

  function loading(label) {
    return `<div class="loading">${Fmt.escapeHtml(label || "Loading…")}</div>`;
  }

  function errorBox(message, retryId) {
    return `<div class="error-box">${icon("error")}<div class="grow"><div>${Fmt.escapeHtml(message)}</div>
      ${retryId ? `<button class="btn btn-sm mt-12" id="${retryId}">Retry</button>` : ""}</div></div>`;
  }

  global.UI = {
    icons: Icons,
    icon,
    theme,
    toast,
    modal,
    palette,
    progress,
    copy,
    copyButton,
    wireCopy,
    loading,
    errorBox,
  };
})(window);
