/* Dependency-free SVG chart renderers (no CDN, works offline). */
(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const element = document.createElementNS(NS, name);
    Object.entries(attrs || {}).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function emptyState(container, message) {
    container.innerHTML = `<div class="chart-empty">${message}</div>`;
  }

  /**
   * Line/area chart for activity series.
   * @param {HTMLElement} container
   * @param {Array<{bucket:string,label:string,commits:number}>} series
   * @param {{height?:number,color?:string}} [options]
   */
  function lineChart(container, series, options) {
    const opts = options || {};
    if (!container) return;
    if (!series || !series.length) {
      emptyState(container, "No activity recorded in this period.");
      return;
    }
    const height = opts.height || 220;
    const width = 900;
    const padding = { top: 16, right: 18, bottom: 34, left: 46 };
    const values = series.map((point) => Number(point.commits) || 0);
    const max = Math.max(1, ...values);
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    const step = series.length > 1 ? innerWidth / (series.length - 1) : 0;
    const x = (index) => padding.left + index * step;
    const y = (value) => padding.top + innerHeight - (value / max) * innerHeight;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Commit activity chart" });
    const color = opts.color || "#4a9eff";

    // horizontal grid + y axis labels
    const ticks = 4;
    for (let index = 0; index <= ticks; index += 1) {
      const value = Math.round((max / ticks) * index);
      const lineY = y(value);
      svg.appendChild(svgEl("line", { x1: padding.left, x2: width - padding.right, y1: lineY, y2: lineY, stroke: "#222b36", "stroke-width": 1 }));
      const label = svgEl("text", { x: padding.left - 8, y: lineY + 4, "text-anchor": "end", fill: "#8b949e", "font-size": 11 });
      label.textContent = String(value);
      svg.appendChild(label);
    }

    const linePoints = series.map((point, index) => `${x(index)},${y(Number(point.commits) || 0)}`).join(" ");
    const areaPath = `M ${padding.left},${padding.top + innerHeight} L ${linePoints.replace(/ /g, " L ")} L ${x(series.length - 1)},${padding.top + innerHeight} Z`;

    const gradientId = `grad-${Math.random().toString(36).slice(2, 9)}`;
    const defs = svgEl("defs");
    const gradient = svgEl("linearGradient", { id: gradientId, x1: 0, y1: 0, x2: 0, y2: 1 });
    gradient.appendChild(svgEl("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.32 }));
    gradient.appendChild(svgEl("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0.02 }));
    defs.appendChild(gradient);
    svg.appendChild(defs);

    svg.appendChild(svgEl("path", { d: areaPath, fill: `url(#${gradientId})`, stroke: "none" }));
    svg.appendChild(svgEl("polyline", { points: linePoints, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round" }));

    const pointStep = series.length > 60 ? Math.ceil(series.length / 60) : 1;
    series.forEach((point, index) => {
      if (index % pointStep !== 0 && index !== series.length - 1) return;
      const circle = svgEl("circle", { cx: x(index), cy: y(Number(point.commits) || 0), r: 2.6, fill: color });
      const title = svgEl("title");
      title.textContent = `${point.label || point.bucket}: ${point.commits} commit(s)`;
      circle.appendChild(title);
      svg.appendChild(circle);
    });

    // x axis labels (about 8 evenly spread)
    const labelStep = Math.max(1, Math.ceil(series.length / 8));
    series.forEach((point, index) => {
      if (index % labelStep !== 0) return;
      const text = svgEl("text", { x: x(index), y: height - 12, "text-anchor": "middle", fill: "#8b949e", "font-size": 11 });
      text.textContent = (point.label || point.bucket || "").replace(/^week of |^(\d{4})-(\d{2})-(\d{2})$/, (match, year, month, day) =>
        year ? `${month}/${day}` : match
      );
      svg.appendChild(text);
    });

    container.innerHTML = "";
    container.classList.add("chart");
    container.appendChild(svg);
  }

  /** Horizontal bar chart for ranked lists (contributors, churn, ...). */
  function barChart(container, rows, options) {
    const opts = options || {};
    if (!container) return;
    if (!rows || !rows.length) {
      emptyState(container, opts.emptyMessage || "Nothing to display yet.");
      return;
    }
    const max = Math.max(1, ...rows.map((row) => Number(row.value) || 0));
    container.innerHTML = rows
      .map((row) => {
        const value = Number(row.value) || 0;
        const pct = Math.max(2, Math.round((value / max) * 100));
        const label = Fmt.escapeHtml(row.label);
        return `<div class="bar-row">
          <span class="bar-label" title="${label}">${label}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${pct}%;${row.color ? `background:${row.color};` : ""}"></span></span>
          <span class="bar-value">${Fmt.number(value)}</span>
        </div>`;
      })
      .join("");
  }

  /** Weekday x hour heatmap (E13-S1). */
  function heatmap(container, payload) {
    if (!container) return;
    if (!payload || !payload.grid || !payload.total) {
      emptyState(container, "No commits in the selected period.");
      return;
    }
    const weekdays = payload.weekdays || ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const peak = Math.max(1, payload.peak || 1);
    const header = ["<th></th>"];
    for (let hour = 0; hour < 24; hour += 1) header.push(`<th style="font-size:10px">${hour}</th>`);
    const body = payload.grid
      .map((row, dayIndex) => {
        const cells = row
          .map((count) => {
            const intensity = count === 0 ? 0 : Math.min(1, 0.18 + (count / peak) * 0.82);
            const background = count === 0 ? "#1c2430" : `rgba(74, 158, 255, ${intensity.toFixed(2)})`;
            return `<td><span class="heat-cell" style="background:${background}" title="${weekdays[dayIndex]} ${count} commit(s)"></span></td>`;
          })
          .join("");
        return `<tr><th style="font-size:11px;text-transform:none">${weekdays[dayIndex]}</th>${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<div class="table-wrap"><table class="heatmap"><thead><tr>${header.join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  /** Circular health score ring. */
  function healthRing(score, size) {
    const dimension = size || 92;
    const radius = dimension / 2 - 7;
    const circumference = 2 * Math.PI * radius;
    const bounded = Math.max(0, Math.min(100, Number(score) || 0));
    const offset = circumference - (bounded / 100) * circumference;
    const color = Fmt.healthColor(bounded);
    return `<svg class="health-ring" width="${dimension}" height="${dimension}" viewBox="0 0 ${dimension} ${dimension}">
      <circle cx="${dimension / 2}" cy="${dimension / 2}" r="${radius}" fill="none" stroke="#222b36" stroke-width="8"></circle>
      <circle cx="${dimension / 2}" cy="${dimension / 2}" r="${radius}" fill="none" stroke="${color}" stroke-width="8"
              stroke-linecap="round" stroke-dasharray="${circumference.toFixed(1)}"
              stroke-dashoffset="${offset.toFixed(1)}" transform="rotate(-90 ${dimension / 2} ${dimension / 2})"></circle>
      <text x="50%" y="52%" text-anchor="middle" dominant-baseline="middle" fill="${color}" font-size="20" font-weight="700">${Math.round(bounded)}</text>
    </svg>`;
  }

  /** Small inline sparkline. */
  function sparkline(values, width, height) {
    const w = width || 120;
    const h = height || 26;
    if (!values || !values.length) return "";
    const max = Math.max(1, ...values);
    const step = values.length > 1 ? w / (values.length - 1) : 0;
    const points = values.map((value, index) => `${index * step},${h - (value / max) * (h - 3) - 1.5}`).join(" ");
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${points}" fill="none" stroke="#4a9eff" stroke-width="1.6"></polyline></svg>`;
  }

  global.Charts = { lineChart, barChart, heatmap, healthRing, sparkline, empty: emptyState };
})(window);
