/* Dependency-free SVG chart renderers (no CDN, works offline).
   Every colour comes from a CSS custom property so charts follow the active
   theme without re-rendering. */
(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const element = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function css(properties) {
    return Object.entries(properties)
      .map(([key, value]) => `${key}:${value}`)
      .join(";");
  }

  function emptyState(container, message, iconName) {
    const icon = global.Icons && global.Icons.get ? global.Icons.get(iconName || "chart", "empty-art") : "";
    container.innerHTML = `<div class="empty-state empty-state--inline">${icon}<p>${global.Fmt ? Fmt.escapeHtml(message) : message}</p></div>`;
  }

  function seriesValues(series) {
    return series.map((point) => (point && point.commits !== undefined ? Number(point.commits) || 0 : 0));
  }

  /** Format an x-axis label, shrinking ISO dates and "week of ..." wording. */
  function axisLabel(point) {
    const raw = String((point && (point.label || point.bucket)) || "");
    const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (iso) return `${iso[2]}/${iso[3]}`;
    const week = raw.match(/^week of\s+(.*)$/i);
    if (week) return week[1];
    return raw.length > 12 ? `${raw.slice(0, 11)}…` : raw;
  }

  function niceTicks(max, count) {
    const ticks = [];
    const step = max / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(step, 1))));
    const rounded = Math.max(1, Math.round(step / magnitude) * magnitude);
    for (let value = 0; value <= max + step / 2; value += rounded) ticks.push(Math.round(value));
    if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + rounded);
    return ticks;
  }

  /**
   * Line/area chart for an activity series, with hover crosshair + tooltip.
   * @param {HTMLElement} container
   * @param {Array<{bucket:string,label:string,commits:number}>} series
   * @param {{height?:number,accent?:string,emptyMessage?:string}} [options]
   */
  function lineChart(container, series, options) {
    const opts = options || {};
    if (!container) return;
    container.innerHTML = "";
    container.classList.add("chart", "chart--line");
    if (!series || !series.length) {
      emptyState(container, opts.emptyMessage || "No activity recorded in this period.", "activity");
      return;
    }

    const height = opts.height || 240;
    const width = 960;
    const padding = { top: 18, right: 18, bottom: 30, left: 44 };
    const values = seriesValues(series);
    const peak = Math.max(1, ...values);
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    const step = series.length > 1 ? innerWidth / (series.length - 1) : 0;
    const x = (index) => padding.left + index * step;
    const y = (value) => padding.top + innerHeight - (value / peak) * innerHeight;

    const svg = svgEl("svg", {
      viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: "none",
      role: "img",
      "aria-label": `${values.reduce((sum, value) => sum + value, 0)} commits across ${series.length} buckets`,
    });

    const ticks = niceTicks(peak, 4);
    ticks.forEach((value) => {
      const lineY = y(value);
      svg.appendChild(svgEl("line", { x1: padding.left, x2: width - padding.right, y1: lineY, y2: lineY, style: css({ stroke: "var(--grid)" }) }));
      const label = svgEl("text", {
        x: padding.left - 8,
        y: lineY + 4,
        "text-anchor": "end",
        "font-size": 11,
        style: css({ fill: "var(--text-faint)" }),
      });
      label.textContent = Fmt.compact(value);
      svg.appendChild(label);
    });

    const points = series.map((point, index) => `${x(index)},${y(values[index])}`).join(" ");
    const areaPath = `M ${padding.left},${padding.top + innerHeight} L ${points.replace(/ /g, " L ")} L ${x(series.length - 1)},${padding.top + innerHeight} Z`;

    const gradientId = `chart-grad-${Math.random().toString(36).slice(2, 9)}`;
    const defs = svgEl("defs");
    const gradient = svgEl("linearGradient", { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 });
    gradient.appendChild(svgEl("stop", { offset: "0%", style: css({ "stop-color": "var(--accent)", "stop-opacity": 0.35 }) }));
    gradient.appendChild(svgEl("stop", { offset: "100%", style: css({ "stop-color": "var(--accent)", "stop-opacity": 0.02 }) }));
    defs.appendChild(gradient);
    svg.appendChild(defs);

    svg.appendChild(svgEl("path", { d: areaPath, style: css({ fill: `url(#${gradientId})`, stroke: "none" }) }));
    svg.appendChild(
      svgEl("polyline", {
        points,
        style: css({ fill: "none", stroke: "var(--accent)", "stroke-width": 2.2, "stroke-linejoin": "round", "stroke-linecap": "round" }),
      })
    );

    /* Hover layer: crosshair, marker and tooltip. */
    const crosshair = svgEl("line", {
      x1: 0,
      x2: 0,
      y1: padding.top,
      y2: padding.top + innerHeight,
      style: css({ stroke: "var(--accent)", "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0 }),
    });
    const marker = svgEl("circle", {
      r: 4.5,
      cx: 0,
      cy: 0,
      style: css({ fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2, opacity: 0 }),
    });
    svg.appendChild(crosshair);
    svg.appendChild(marker);

    const labelStep = Math.max(1, Math.ceil(series.length / 8));
    series.forEach((point, index) => {
      if (index % labelStep !== 0 && index !== series.length - 1) return;
      const text = svgEl("text", {
        x: x(index),
        y: height - 10,
        "text-anchor": "middle",
        "font-size": 11,
        style: css({ fill: "var(--text-faint)" }),
      });
      text.textContent = axisLabel(point);
      svg.appendChild(text);
    });

    container.appendChild(svg);

    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.hidden = true;
    container.appendChild(tooltip);

    const total = values.reduce((sum, value) => sum + value, 0);
    const overlay = svgEl("rect", {
      x: padding.left,
      y: padding.top,
      width: Math.max(1, innerWidth),
      height: innerHeight,
      style: css({ fill: "transparent" }),
    });
    svg.appendChild(overlay);

    function nearestIndex(clientX) {
      const box = svg.getBoundingClientRect();
      if (!box.width) return -1;
      const relative = ((clientX - box.left) / box.width) * width;
      const index = Math.round((relative - padding.left) / (step || 1));
      return Math.max(0, Math.min(series.length - 1, index));
    }

    function show(index) {
      if (index < 0) return;
      const point = series[index];
      const value = values[index];
      crosshair.setAttribute("x1", x(index));
      crosshair.setAttribute("x2", x(index));
      crosshair.style.opacity = "1";
      marker.setAttribute("cx", x(index));
      marker.setAttribute("cy", y(value));
      marker.style.opacity = "1";
      const share = total ? Math.round((value / total) * 100) : 0;
      tooltip.innerHTML = `<div class="chart-tooltip-title">${Fmt.escapeHtml(point.label || point.bucket || "")}</div>
        <div class="chart-tooltip-row"><span>Commits</span><strong>${Fmt.number(value)}</strong></div>
        <div class="chart-tooltip-row"><span>Share</span><span>${share}%</span></div>`;
      tooltip.hidden = false;
      const box = svg.getBoundingClientRect();
      const ratio = box.width && width ? box.width / width : 1;
      const left = x(index) * ratio;
      tooltip.style.left = `${Math.max(8, Math.min(box.width - 8, left))}px`;
      tooltip.style.top = `${Math.max(8, y(value) * (height ? box.height / height : 1) - 12)}px`;
      tooltip.style.transform = index > series.length / 2 ? "translate(-100%, -100%)" : "translate(-8px, -100%)";
    }

    function hide() {
      crosshair.style.opacity = "0";
      marker.style.opacity = "0";
      tooltip.hidden = true;
    }

    overlay.addEventListener("mousemove", (event) => show(nearestIndex(event.clientX)));
    overlay.addEventListener("mouseleave", hide);
    overlay.addEventListener("touchstart", (event) => {
      const touch = event.touches && event.touches[0];
      if (touch) show(nearestIndex(touch.clientX));
    });
  }

  /** Vertical columns — used for short series where individual buckets matter. */
  function columnChart(container, series, options) {
    const opts = options || {};
    if (!container) return;
    container.innerHTML = "";
    container.classList.add("chart", "chart--bars");
    if (!series || !series.length) {
      emptyState(container, opts.emptyMessage || "No activity recorded in this period.", "activity");
      return;
    }
    const values = seriesValues(series);
    const peak = Math.max(1, ...values);
    container.innerHTML = `<div class="vbar-list">${series
      .map((point, index) => {
        const value = values[index];
        const height = Math.max(value ? 4 : 2, Math.round((value / peak) * 100));
        return `<div class="vbar" title="${Fmt.escapeHtml(`${point.label || point.bucket}: ${value} commit(s)`)}">
          <span class="vbar-value">${value ? Fmt.number(value) : ""}</span>
          <span class="vbar-track"><span class="vbar-fill" style="height:${height}%"></span></span>
          <span class="vbar-label">${Fmt.escapeHtml(axisLabel(point))}</span>
        </div>`;
      })
      .join("")}</div>`;
  }

  /**
   * Ranked horizontal bars (contributors, churn, branch counts, ...).
   * @param {Array<{label:string,value:number,color?:string,href?:string,meta?:string}>} rows
   */
  function barChart(container, rows, options) {
    const opts = options || {};
    if (!container) return;
    if (!rows || !rows.length) {
      emptyState(container, opts.emptyMessage || "Nothing to display yet.", "chart");
      return;
    }
    const max = Math.max(1, ...rows.map((row) => Number(row.value) || 0));
    container.innerHTML = `<ul class="bar-list">${rows
      .map((row) => {
        const value = Number(row.value) || 0;
        const percentage = Math.max(1.5, (value / max) * 100);
        const label = Fmt.escapeHtml(row.label);
        const name = row.href ? `<a class="bar-label" href="${row.href}" title="${label}">${label}</a>` : `<span class="bar-label" title="${label}">${label}</span>`;
        return `<li class="bar-row">
          ${name}
          <span class="bar-track" role="img" aria-label="${value}">
            <span class="bar-fill" style="width:${percentage.toFixed(1)}%${row.color ? `;background:${row.color}` : ""}"></span>
          </span>
          <span class="bar-value">${Fmt.number(value)}${row.meta ? `<span class="bar-meta">${Fmt.escapeHtml(row.meta)}</span>` : ""}</span>
        </li>`;
      })
      .join("")}</ul>`;
  }

  /** Weekday x hour heat grid. */
  function heatmap(container, payload) {
    if (!container) return;
    container.innerHTML = "";
    if (!payload || !payload.grid || !payload.total) {
      emptyState(container, "No commits in the selected period.", "clock");
      return;
    }
    const weekdays = payload.weekdays || ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const peak = Math.max(1, Number(payload.peak) || 1);
    const head = ['<th scope="col" class="heat-hour-head"></th>'];
    for (let hour = 0; hour < 24; hour += 1) {
      head.push(`<th scope="col" class="heat-hour-head">${hour % 3 === 0 ? hour : ""}</th>`);
    }
    const rows = payload.grid
      .map((row, dayIndex) => {
        const cells = row
          .map((count, hour) => {
            const intensity = count === 0 ? 0 : Math.min(1, 0.16 + (count / peak) * 0.84);
            const background = count === 0 ? "var(--heat-0)" : `color-mix(in srgb, var(--accent) ${(intensity * 100).toFixed(0)}%, var(--heat-0))`;
            return `<td><span class="heat-cell" style="background:${background}" title="${weekdays[dayIndex]} ${hour}:00 — ${count} commit(s)" aria-label="${weekdays[dayIndex]} ${hour}:00, ${count} commits"></span></td>`;
          })
          .join("");
        return `<tr><th scope="row" class="heat-day-head">${weekdays[dayIndex]}</th>${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<div class="table-wrap"><table class="heatmap">
      <caption class="sr-only">Commit distribution by weekday and hour</caption>
      <thead><tr>${head.join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="heat-legend">
      <span class="heat-legend-label">${Fmt.number(payload.total)} commits · peak ${Fmt.number(peak)}/hour</span>
      <span class="heat-legend-scale" aria-hidden="true">${Array.from({ length: 5 })
        .map((_, index) => `<span class="heat-cell" style="background:${index === 0 ? "var(--heat-0)" : `color-mix(in srgb, var(--accent) ${(index * 25).toFixed(0)}%, var(--heat-0))`}"></span>`)
        .join("")}</span>
    </div>`;
  }

  /** Circular health score ring. */
  function healthRing(score, size) {
    const dimension = size || 96;
    const radius = dimension / 2 - 7;
    const circumference = 2 * Math.PI * radius;
    const bounded = Math.max(0, Math.min(100, Number(score) || 0));
    const offset = circumference - (bounded / 100) * circumference;
    const tone = Fmt.healthTone(bounded);
    return `<svg class="health-ring health-ring--${tone}" width="${dimension}" height="${dimension}" viewBox="0 0 ${dimension} ${dimension}" role="img" aria-label="Health score ${Math.round(bounded)} of 100">
      <circle cx="${dimension / 2}" cy="${dimension / 2}" r="${radius}" fill="none" style="stroke:var(--track)" stroke-width="8"></circle>
      <circle cx="${dimension / 2}" cy="${dimension / 2}" r="${radius}" fill="none" style="stroke:var(--ring-color, var(--accent))" stroke-width="8"
              stroke-linecap="round" stroke-dasharray="${circumference.toFixed(1)}"
              stroke-dashoffset="${offset.toFixed(1)}" transform="rotate(-90 ${dimension / 2} ${dimension / 2})"></circle>
      <text x="50%" y="52%" text-anchor="middle" dominant-baseline="middle" font-size="20" font-weight="700" style="fill:var(--ring-color, var(--accent))">${Math.round(bounded)}</text>
    </svg>`;
  }

  /** Small inline sparkline. */
  function sparkline(values, width, height) {
    const w = width || 120;
    const h = height || 28;
    if (!values || !values.length) return "";
    const max = Math.max(1, ...values.map((value) => Number(value) || 0));
    const step = values.length > 1 ? w / (values.length - 1) : 0;
    const points = values
      .map((value, index) => `${(index * step).toFixed(1)},${(h - (Number(value) || 0) / max * (h - 4) - 2).toFixed(1)}`)
      .join(" ");
    return `<svg class="sparkline" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-hidden="true"><polyline points="${points}" style="fill:none;stroke:var(--accent);stroke-width:1.8;stroke-linejoin:round;stroke-linecap:round"></polyline></svg>`;
  }

  global.Charts = {
    lineChart,
    barChart,
    columnChart,
    heatmap,
    healthRing,
    sparkline,
    empty: emptyState,
  };
})(window);
