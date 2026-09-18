/* GridWise frontend — vanilla JS, no build step.
 *
 * Responsibilities:
 *   - Build an OptimizeEnergyRequest from the DOM
 *   - Call the API (/health, /optimize-energy)
 *   - Render the response: KPI tiles, directive cards, hourly table,
 *     and a hand-rolled SVG chart with a battery-SOC overlay line.
 */

(function () {
  "use strict";

  // ------------------------------------------------------------------
  // Constants / defaults
  // ------------------------------------------------------------------

  const DEFAULT_NOTES = [
    "Panel maintenance from 1 PM to 3 PM means only 20% of normal solar should be counted.",
  ];

  // A realistic 24-hour default horizon: gentle demand, daytime solar,
  // evening peak tariff. Matches the data/example_request.json shape.
  const DEFAULT_HOURS = [
    { hour: 0,  demand_kwh:  90, solar_kwh:   0, tariff_bdt_per_kwh:  6 },
    { hour: 1,  demand_kwh:  85, solar_kwh:   0, tariff_bdt_per_kwh:  6 },
    { hour: 2,  demand_kwh:  80, solar_kwh:   0, tariff_bdt_per_kwh:  5 },
    { hour: 3,  demand_kwh:  80, solar_kwh:   0, tariff_bdt_per_kwh:  5 },
    { hour: 4,  demand_kwh:  85, solar_kwh:   0, tariff_bdt_per_kwh:  5 },
    { hour: 5,  demand_kwh:  95, solar_kwh:   0, tariff_bdt_per_kwh:  6 },
    { hour: 6,  demand_kwh: 110, solar_kwh:   5, tariff_bdt_per_kwh:  8 },
    { hour: 7,  demand_kwh: 130, solar_kwh:  20, tariff_bdt_per_kwh: 10 },
    { hour: 8,  demand_kwh: 150, solar_kwh:  50, tariff_bdt_per_kwh: 12 },
    { hour: 9,  demand_kwh: 165, solar_kwh:  90, tariff_bdt_per_kwh: 14 },
    { hour: 10, demand_kwh: 175, solar_kwh: 130, tariff_bdt_per_kwh: 16 },
    { hour: 11, demand_kwh: 180, solar_kwh: 160, tariff_bdt_per_kwh: 16 },
    { hour: 12, demand_kwh: 185, solar_kwh: 180, tariff_bdt_per_kwh: 15 },
    { hour: 13, demand_kwh: 180, solar_kwh: 170, tariff_bdt_per_kwh: 14 },
    { hour: 14, demand_kwh: 170, solar_kwh: 140, tariff_bdt_per_kwh: 13 },
    { hour: 15, demand_kwh: 165, solar_kwh:  90, tariff_bdt_per_kwh: 14 },
    { hour: 16, demand_kwh: 170, solar_kwh:  45, tariff_bdt_per_kwh: 18 },
    { hour: 17, demand_kwh: 185, solar_kwh:  10, tariff_bdt_per_kwh: 22 },
    { hour: 18, demand_kwh: 205, solar_kwh:   0, tariff_bdt_per_kwh: 28 },
    { hour: 19, demand_kwh: 215, solar_kwh:   0, tariff_bdt_per_kwh: 30 },
    { hour: 20, demand_kwh: 205, solar_kwh:   0, tariff_bdt_per_kwh: 26 },
    { hour: 21, demand_kwh: 175, solar_kwh:   0, tariff_bdt_per_kwh: 18 },
    { hour: 22, demand_kwh: 135, solar_kwh:   0, tariff_bdt_per_kwh: 10 },
    { hour: 23, demand_kwh: 105, solar_kwh:   0, tariff_bdt_per_kwh:  7 },
  ];

  const MAX_NOTES = 3;
  const MIN_NOTES = 1;

  // ------------------------------------------------------------------
  // Tiny DOM helpers
  // ------------------------------------------------------------------

  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (k === "html") {
        node.innerHTML = v;
      } else if (v !== false && v != null) {
        node.setAttribute(k, v);
      }
    }
    for (const c of [].concat(children)) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  function svg(tag, attrs = {}, children = []) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v != null && v !== false) node.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
      if (c == null) continue;
      node.appendChild(c);
    }
    return node;
  }

  function clamp(n, lo, hi) { return Math.min(hi, Math.max(lo, n)); }

  function fmtNumber(n, digits = 1) {
    if (n === null || n === undefined || Number.isNaN(n)) return "–";
    if (Math.abs(n) >= 1000) return n.toFixed(0);
    return Number(n).toFixed(digits);
  }

  function setStatus(text, kind = "") {
    const node = $("#run-status");
    node.className = "status" + (kind ? " is-" + kind : "");
    if (kind === "loading") {
      node.innerHTML = `<span class="spinner"></span>${escapeHtml(text)}`;
    } else {
      node.textContent = text;
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------

  const state = {
    hours: DEFAULT_HOURS.map((h) => ({ ...h })),
    lastResult: null,
  };

  // ------------------------------------------------------------------
  // Form rendering
  // ------------------------------------------------------------------

  function renderNotes() {
    const list = $("#notes-list");
    list.innerHTML = "";
    const noteValues = $$("#notes-list textarea").map((t) => t.value);
    if (noteValues.length === 0) {
      DEFAULT_NOTES.forEach((n) => addNoteRow(n));
    } else {
      noteValues.forEach((v) => addNoteRow(v));
    }
    refreshNoteButtons();
  }

  function addNoteRow(value = "") {
    const list = $("#notes-list");
    const idx = list.children.length;
    const row = el("div", { class: "note-row" });

    const left = el("div", {});
    const ta = el("textarea", {
      rows: 2,
      placeholder: `Operator note #${idx + 1}…`,
      spellcheck: "false",
    });
    ta.value = value;
    left.appendChild(ta);
    left.appendChild(el("div", { class: "meta" },
      "Plain English; the LLM turns it into a directive."));

    const removeBtn = el("button", {
      class: "btn btn-icon",
      type: "button",
      title: "Remove note",
      "aria-label": "Remove note",
      onclick: () => {
        const rows = $$("#notes-list .note-row");
        if (rows.length <= MIN_NOTES) return;
        row.remove();
        refreshNoteButtons();
      },
    }, "×");

    row.appendChild(left);
    row.appendChild(removeBtn);
    list.appendChild(row);
  }

  function refreshNoteButtons() {
    const list = $("#notes-list");
    const count = list.children.length;
    $$("#notes-list .note-row .btn-icon").forEach((b) => {
      b.disabled = count <= MIN_NOTES;
    });
    $("#btn-add-note").disabled = count >= MAX_NOTES;
  }

  function renderHoursTable() {
    const body = $("#hours-body");
    body.innerHTML = "";
    state.hours.forEach((h, i) => {
      const tr = el("tr");

      tr.appendChild(el("td", {}, [String(h.hour).padStart(2, "0")]));

      const demandInput = el("input", {
        type: "number",
        min: "0",
        step: "0.1",
        value: h.demand_kwh,
      });
      demandInput.addEventListener("input", (e) => {
        state.hours[i].demand_kwh = parseFloat(e.target.value) || 0;
      });
      tr.appendChild(el("td", {}, [demandInput]));

      const solarInput = el("input", {
        type: "number",
        min: "0",
        step: "0.1",
        value: h.solar_kwh,
      });
      solarInput.addEventListener("input", (e) => {
        state.hours[i].solar_kwh = parseFloat(e.target.value) || 0;
      });
      tr.appendChild(el("td", {}, [solarInput]));

      const tariffInput = el("input", {
        type: "number",
        min: "0",
        step: "0.1",
        value: h.tariff_bdt_per_kwh,
      });
      tariffInput.addEventListener("input", (e) => {
        state.hours[i].tariff_bdt_per_kwh = parseFloat(e.target.value) || 0;
      });
      tr.appendChild(el("td", {}, [tariffInput]));

      body.appendChild(tr);
    });
  }

  // ------------------------------------------------------------------
  // Form -> request payload
  // ------------------------------------------------------------------

  function readForm() {
    const notes = $$("#notes-list textarea")
      .map((t) => t.value.trim())
      .filter((t) => t.length > 0);

    return {
      scenario_id: $("#scenario-id").value.trim() || "GRID-UNNAMED",
      operator_notes: notes.length ? notes : [""],
      hours: state.hours.map((h) => ({
        hour: h.hour,
        demand_kwh: Number(h.demand_kwh) || 0,
        solar_kwh: Number(h.solar_kwh) || 0,
        tariff_bdt_per_kwh: Number(h.tariff_bdt_per_kwh) || 0,
      })),
      battery: {
        capacity_kwh: parseFloat($("#bat-capacity").value) || 0,
        initial_energy_kwh: parseFloat($("#bat-initial").value) || 0,
        minimum_energy_kwh: parseFloat($("#bat-min").value) || 0,
        max_charge_kwh_per_hour: parseFloat($("#bat-max-charge").value) || 0,
        max_discharge_kwh_per_hour:
          parseFloat($("#bat-max-discharge").value) || 0,
      },
    };
  }

  function applyExample(data) {
    if (data.scenario_id) $("#scenario-id").value = data.scenario_id;

    // notes
    const list = $("#notes-list");
    list.innerHTML = "";
    const notes = Array.isArray(data.operator_notes)
      ? data.operator_notes.slice(0, MAX_NOTES)
      : [];
    (notes.length ? notes : [""]).forEach((n) => addNoteRow(n));
    refreshNoteButtons();

    // battery
    if (data.battery) {
      const b = data.battery;
      if (b.capacity_kwh != null)        $("#bat-capacity").value      = b.capacity_kwh;
      if (b.initial_energy_kwh != null)   $("#bat-initial").value       = b.initial_energy_kwh;
      if (b.minimum_energy_kwh != null)   $("#bat-min").value           = b.minimum_energy_kwh;
      if (b.max_charge_kwh_per_hour != null)
        $("#bat-max-charge").value = b.max_charge_kwh_per_hour;
      if (b.max_discharge_kwh_per_hour != null)
        $("#bat-max-discharge").value = b.max_discharge_kwh_per_hour;
    }

    // hours
    if (Array.isArray(data.hours) && data.hours.length === 24) {
      state.hours = data.hours.map((h) => ({
        hour: h.hour,
        demand_kwh: h.demand_kwh,
        solar_kwh: h.solar_kwh,
        tariff_bdt_per_kwh: h.tariff_bdt_per_kwh,
      }));
      renderHoursTable();
    }
  }

  // ------------------------------------------------------------------
  // API plumbing
  // ------------------------------------------------------------------

  function apiBase() {
    const raw = $("#api-base").value.trim();
    return raw.replace(/\/+$/, "");
  }

  async function checkHealth() {
    const dot = $("#health-dot");
    dot.className = "dot dot-unknown";
    const url = `${apiBase()}/health`;
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body && body.status === "ok") {
        dot.className = "dot dot-ok";
        dot.title = `OK · ${body.service || ""}`;
      } else {
        dot.className = "dot dot-fail";
        dot.title = "Unexpected response";
      }
    } catch (err) {
      dot.className = "dot dot-fail";
      dot.title = `Failed: ${err.message}`;
    }
  }

  async function loadExample() {
    setStatus("Loading example…", "loading");
    try {
      // Try a few candidate paths so the page works whether served
      // from the project root or opened directly.
      const candidates = [
        "../data/example_request.json",
        "data/example_request.json",
        "./example_request.json",
      ];
      let data = null;
      let lastErr = null;
      for (const path of candidates) {
        try {
          const res = await fetch(path, { cache: "no-store" });
          if (res.ok) {
            data = await res.json();
            break;
          }
          lastErr = new Error(`${path}: HTTP ${res.status}`);
        } catch (e) {
          lastErr = e;
        }
      }
      if (!data) throw lastErr || new Error("example_request.json not found");
      applyExample(data);
      setStatus("Example loaded.", "success");
    } catch (err) {
      setStatus(`Could not load example: ${err.message}`, "error");
    }
  }

  async function runOptimization() {
    setStatus("Calling /optimize-energy…", "loading");
    const payload = readForm();
    const url = `${apiBase()}/optimize-energy`;

    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      setStatus(`Network error: ${err.message}`, "error");
      return;
    }

    let body;
    try {
      body = await res.json();
    } catch (err) {
      setStatus(`Bad response (not JSON): HTTP ${res.status}`, "error");
      return;
    }

    if (!res.ok) {
      const detail =
        (body && (body.detail || body.message)) || `HTTP ${res.status}`;
      setStatus(`API error: ${detail}`, "error");
      return;
    }

    state.lastResult = body;
    renderResult(body);
    setStatus(`Done in scenario ${body.scenario_id}.`, "success");
  }

  // ------------------------------------------------------------------
  // Results rendering
  // ------------------------------------------------------------------

  function renderResult(data) {
    $("#empty-state").classList.add("hidden");
    $("#results-panel").classList.remove("hidden");

    // KPI tiles
    $("#kpi-grid").textContent = fmtNumber(data.total_grid_kwh, 1);
    $("#kpi-cost").textContent = fmtNumber(data.total_cost_bdt, 2);
    $("#kpi-peak").textContent = fmtNumber(data.peak_grid_kwh, 1);

    $("#plan-summary").textContent = data.plan_summary || "";

    // Directive cards
    const wrap = $("#directives");
    wrap.innerHTML = "";
    (data.directive_interpretation || []).forEach((d) => {
      wrap.appendChild(renderDirectiveCard(d));
    });

    // Hourly table
    const planBody = $("#plan-body");
    planBody.innerHTML = "";
    (data.hourly_plan || []).forEach((p) => {
      const tr = el("tr");
      tr.appendChild(el("td", {}, [String(p.hour).padStart(2, "0")]));
      tr.appendChild(el("td", {}, [fmtNumber(p.grid_kwh, 1)]));
      tr.appendChild(el("td", {}, [fmtNumber(p.solar_used_kwh, 1)]));

      const action = p.battery_action || "idle";
      tr.appendChild(
        el("td", {}, [
          el("span", {
            class: `action-chip action-${action}`,
            title: action,
          }, [action]),
        ])
      );
      tr.appendChild(el("td", {}, [fmtNumber(p.battery_kwh, 1)]));
      tr.appendChild(el("td", {}, [fmtNumber(p.battery_energy_after_kwh, 1)]));
      planBody.appendChild(tr);
    });

    // Chart
    drawChart(data.hourly_plan || []);
  }

  function renderDirectiveCard(d) {
    const card = el("div", { class: "directive" });
    const row = el("div", { class: "row-1" });

    row.appendChild(el("span", { class: "badge" }, [`note #${d.note_index}`]));
    row.appendChild(
      el("span", {
        class: "badge type" + (d.directive_type === "no_op" ? " no-op" : ""),
      }, [d.directive_type || "unknown"])
    );
    row.appendChild(
      el("span", { class: "badge applies-" + (d.applies ? "on" : "off") },
        [d.applies ? "applies" : "no-op"])
    );

    card.appendChild(row);

    if (d.explanation) {
      card.appendChild(el("p", { class: "explanation" }, [d.explanation]));
    }
    if (d.structured_adjustment && d.directive_type !== "no_op") {
      card.appendChild(
        el("pre", {}, [JSON.stringify(d.structured_adjustment, null, 2)])
      );
    }
    return card;
  }

  // ------------------------------------------------------------------
  // Hand-rolled SVG chart
  //
  // 24 columns stacked with: solar / battery / grid. Battery-SOC line
  // is overlaid against a right-side y-axis (kWh, 0..capacity).
  // ------------------------------------------------------------------

  const CHART = {
    vbW: 720,
    vbH: 320,
    pad: { top: 16, right: 50, bottom: 28, left: 40 },
    colors: {
      grid: "var(--chart-grid)",
      solar: "var(--chart-solar)",
      battery: "var(--chart-battery)",
      supply: "var(--chart-supply)",
      soc: "var(--chart-soc)",
      text: "var(--text-dim)",
      textBright: "var(--text)",
    },
  };

  function drawChart(plan) {
    const root = $("#chart");
    root.innerHTML = "";
    if (!plan.length) return;

    const { vbW, vbH, pad } = CHART;
    const innerW = vbW - pad.left - pad.right;
    const innerH = vbH - pad.top - pad.bottom;

    // Find scales. Energy stack uses the max of grid+solar+battery in
    // any single hour. SOC scale uses battery capacity; fall back to
    // the observed max if the read_form value isn't available here.
    let maxStack = 0;
    let maxSoc = 0;
    for (const p of plan) {
      const stack = (p.grid_kwh || 0) +
                    (p.solar_used_kwh || 0) +
                    Math.abs(p.battery_kwh || 0);
      if (stack > maxStack) maxStack = stack;
      if (p.battery_energy_after_kwh > maxSoc) {
        maxSoc = p.battery_energy_after_kwh;
      }
    }
    if (maxStack <= 0) maxStack = 1;
    if (maxSoc <= 0)   maxSoc = 1;

    // Grid lines (left axis)
    const gridSteps = 4;
    for (let i = 0; i <= gridSteps; i++) {
      const y = pad.top + (innerH * i) / gridSteps;
      root.appendChild(
        svg("line", {
          x1: pad.left, x2: pad.left + innerW,
          y1: y, y2: y,
          stroke: CHART.colors.grid, "stroke-width": 1,
        })
      );
      const val = maxStack * (1 - i / gridSteps);
      root.appendChild(
        svg("text", {
          x: pad.left - 6, y: y + 4,
          fill: CHART.colors.text, "font-size": 9,
          "text-anchor": "end",
          "font-family": "ui-monospace, monospace",
        }, [fmtNumber(val, 0)])
      );
    }

    // Bars
    const slot = innerW / plan.length;
    const barW = Math.max(2, slot * 0.7);
    plan.forEach((p, i) => {
      const x = pad.left + slot * i + (slot - barW) / 2;
      const solarH  = ((p.solar_used_kwh || 0) / maxStack) * innerH;
      const gridH   = ((p.grid_kwh     || 0) / maxStack) * innerH;
      // Battery as charge (positive, drawn downward from solar top) or
      // discharge (drawn upward, on top of grid stack).
      const batRaw  = p.battery_kwh || 0;
      const batAbsH = (Math.abs(batRaw) / maxStack) * innerH;

      let yCursor = pad.top + innerH;

      // solar (bottom of stack)
      yCursor -= solarH;
      root.appendChild(
        svg("rect", {
          x: x, y: yCursor, width: barW, height: solarH,
          fill: CHART.colors.solar, opacity: 0.9,
        })
      );

      // battery (charge: green-ish drawn on top of solar; discharge:
      // distinct cyan drawn between solar and grid)
      yCursor -= batAbsH;
      if (batRaw > 0) {
        // charge from grid -- render with cyan just above solar
        root.appendChild(
          svg("rect", {
            x: x, y: yCursor, width: barW, height: batAbsH,
            fill: CHART.colors.battery, opacity: 0.85,
          })
        );
      } else if (batRaw < 0) {
        root.appendChild(
          svg("rect", {
            x: x, y: yCursor, width: barW, height: batAbsH,
            fill: CHART.colors.battery, opacity: 0.55,
          })
        );
      }

      // grid (top)
      yCursor -= gridH;
      root.appendChild(
        svg("rect", {
          x: x, y: yCursor, width: barW, height: gridH,
          fill: CHART.colors.supply, opacity: 0.75,
        })
      );
    });

    // X-axis hour labels
    const labelHours = [0, 6, 12, 18, 23];
    labelHours.forEach((h) => {
      const x = pad.left + slot * h + slot / 2;
      root.appendChild(
        svg("text", {
          x: x, y: pad.top + innerH + 14,
          fill: CHART.colors.text, "font-size": 9,
          "text-anchor": "middle",
          "font-family": "ui-monospace, monospace",
        }, [String(h).padStart(2, "0")])
      );
    });

    // SOC line (right axis)
    const socPath = plan.map((p, i) => {
      const x = pad.left + slot * i + slot / 2;
      const y = pad.top + innerH -
                ((p.battery_energy_after_kwh || 0) / maxSoc) * innerH;
      return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    root.appendChild(
      svg("path", {
        d: socPath, fill: "none",
        stroke: CHART.colors.soc, "stroke-width": 1.5,
        "stroke-linejoin": "round", "stroke-linecap": "round",
      })
    );

    // SOC dots
    plan.forEach((p, i) => {
      const x = pad.left + slot * i + slot / 2;
      const y = pad.top + innerH -
                ((p.battery_energy_after_kwh || 0) / maxSoc) * innerH;
      root.appendChild(
        svg("circle", {
          cx: x, cy: y, r: 2,
          fill: CHART.colors.soc,
        })
      );
    });

    // Right axis ticks (SOC scale)
    for (let i = 0; i <= gridSteps; i++) {
      const y = pad.top + (innerH * i) / gridSteps;
      const val = maxSoc * (1 - i / gridSteps);
      root.appendChild(
        svg("text", {
          x: pad.left + innerW + 6, y: y + 4,
          fill: CHART.colors.soc, "font-size": 9,
          "text-anchor": "start",
          "font-family": "ui-monospace, monospace",
          opacity: 0.85,
        }, [fmtNumber(val, 0)])
      );
    }

    // Axis labels
    root.appendChild(
      svg("text", {
        x: pad.left - 28, y: pad.top - 4,
        fill: CHART.colors.text, "font-size": 9,
        "font-family": "ui-monospace, monospace",
      }, ["kWh"])
    );
    root.appendChild(
      svg("text", {
        x: pad.left + innerW + 28, y: pad.top - 4,
        fill: CHART.colors.soc, "font-size": 9,
        "font-family": "ui-monospace, monospace",
      }, ["SOC"])
    );
  }

  // ------------------------------------------------------------------
  // Misc actions
  // ------------------------------------------------------------------

  function downloadResult() {
    if (!state.lastResult) return;
    const blob = new Blob([JSON.stringify(state.lastResult, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = el("a", {
      href: url,
      download: `gridwise-${state.lastResult.scenario_id || "result"}.json`,
    });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function flattenHours() {
    state.hours = state.hours.map((h) => ({
      hour: h.hour,
      demand_kwh: 150,
      solar_kwh: 100,
      tariff_bdt_per_kwh: 10,
    }));
    renderHoursTable();
  }

  function zeroHours() {
    state.hours = state.hours.map((h) => ({
      hour: h.hour,
      demand_kwh: 0,
      solar_kwh: 0,
      tariff_bdt_per_kwh: 0,
    }));
    renderHoursTable();
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------

  function init() {
    renderNotes();
    renderHoursTable();

    $("#btn-add-note").addEventListener("click", () => {
      const list = $("#notes-list");
      if (list.children.length >= MAX_NOTES) return;
      addNoteRow("");
      refreshNoteButtons();
    });
    $("#btn-health").addEventListener("click", checkHealth);
    $("#btn-example").addEventListener("click", loadExample);
    $("#btn-run").addEventListener("click", runOptimization);
    $("#btn-download").addEventListener("click", downloadResult);
    $("#btn-flat").addEventListener("click", flattenHours);
    $("#btn-zero").addEventListener("click", zeroHours);

    // Run health check automatically on load so users see the status.
    checkHealth();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
