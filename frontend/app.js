/* GridWise frontend — vanilla JS, no build step.
 *
 * Responsibilities:
 *   - Build an OptimizeEnergyRequest from the DOM
 *   - Call the API (/health, /optimize-energy)
 *   - Render the response into the redesigned UI:
 *     KPI tiles (with sparklines), directive cards, refined SVG chart
 *     with hover tooltip, hourly plan table, and animated counters.
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
  // evening peak tariff.
  const DEFAULT_HOURS = [
    { hour: 0,  demand_kwh:  92, solar_kwh:   0, tariff_bdt_per_kwh:  6.2 },
    { hour: 1,  demand_kwh:  86, solar_kwh:   0, tariff_bdt_per_kwh:  5.8 },
    { hour: 2,  demand_kwh:  81, solar_kwh:   0, tariff_bdt_per_kwh:  5.4 },
    { hour: 3,  demand_kwh:  79, solar_kwh:   0, tariff_bdt_per_kwh:  5.1 },
    { hour: 4,  demand_kwh:  84, solar_kwh:   0, tariff_bdt_per_kwh:  5.0 },
    { hour: 5,  demand_kwh:  97, solar_kwh:   0, tariff_bdt_per_kwh:  6.3 },
    { hour: 6,  demand_kwh: 112, solar_kwh:   6, tariff_bdt_per_kwh:  8.4 },
    { hour: 7,  demand_kwh: 131, solar_kwh:  21, tariff_bdt_per_kwh: 10.7 },
    { hour: 8,  demand_kwh: 152, solar_kwh:  51, tariff_bdt_per_kwh: 12.2 },
    { hour: 9,  demand_kwh: 164, solar_kwh:  89, tariff_bdt_per_kwh: 13.8 },
    { hour: 10, demand_kwh: 173, solar_kwh: 128, tariff_bdt_per_kwh: 15.7 },
    { hour: 11, demand_kwh: 181, solar_kwh: 159, tariff_bdt_per_kwh: 16.1 },
    { hour: 12, demand_kwh: 187, solar_kwh: 178, tariff_bdt_per_kwh: 14.6 },
    { hour: 13, demand_kwh: 179, solar_kwh: 168, tariff_bdt_per_kwh: 13.9 },
    { hour: 14, demand_kwh: 168, solar_kwh: 137, tariff_bdt_per_kwh: 12.8 },
    { hour: 15, demand_kwh: 163, solar_kwh:  88, tariff_bdt_per_kwh: 14.3 },
    { hour: 16, demand_kwh: 172, solar_kwh:  43, tariff_bdt_per_kwh: 18.6 },
    { hour: 17, demand_kwh: 188, solar_kwh:  11, tariff_bdt_per_kwh: 22.4 },
    { hour: 18, demand_kwh: 207, solar_kwh:   0, tariff_bdt_per_kwh: 28.1 },
    { hour: 19, demand_kwh: 218, solar_kwh:   0, tariff_bdt_per_kwh: 30.6 },
    { hour: 20, demand_kwh: 204, solar_kwh:   0, tariff_bdt_per_kwh: 26.0 },
    { hour: 21, demand_kwh: 173, solar_kwh:   0, tariff_bdt_per_kwh: 18.2 },
    { hour: 22, demand_kwh: 133, solar_kwh:   0, tariff_bdt_per_kwh: 10.1 },
    { hour: 23, demand_kwh: 102, solar_kwh:   0, tariff_bdt_per_kwh:  6.8 },
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

  function fmtNumber(n, digits = 1) {
    if (n === null || n === undefined || Number.isNaN(n)) return "–";
    if (Math.abs(n) >= 1000) return n.toFixed(0);
    return Number(n).toFixed(digits);
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

  function setLivePill(kind, text) {
    const pill = $("#live-pill");
    pill.classList.remove("is-loading", "is-error", "is-success");
    if (kind && kind !== "idle") pill.classList.add("is-" + kind);
    $("#live-label").textContent = text;
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

  // ------------------------------------------------------------------
  // Animated counter
  // ------------------------------------------------------------------

  function animateCounter(node, target, opts = {}) {
    const duration = opts.duration ?? 800;
    const decimals = opts.decimals ?? 0;
    const start = parseFloat(node.dataset.counter || 0);
    if (target === start) {
      node.textContent = target.toFixed(decimals);
      return;
    }
    const t0 = performance.now();
    const ease = (t) => 1 - Math.pow(1 - t, 3); // easeOutCubic
    function step(now) {
      const p = Math.min(1, (now - t0) / duration);
      const v = start + (target - start) * ease(p);
      node.textContent = v.toFixed(decimals);
      if (p < 1) requestAnimationFrame(step);
      else node.dataset.counter = String(target);
    }
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------------
  // State + references
  // ------------------------------------------------------------------

  const state = {
    hours: DEFAULT_HOURS.map((h) => ({ ...h })),
    lastResult: null,
    stats: {
      scenarios: 0,
      savedKwh: 0,
      savedBdt: 0,
    },
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
      "Plain English; the LLM turns it into a structured directive."));

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
      const tr = el("tr", { dataset: { hr: h.hour } });

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

    const list = $("#notes-list");
    list.innerHTML = "";
    const notes = Array.isArray(data.operator_notes)
      ? data.operator_notes.slice(0, MAX_NOTES)
      : [];
    (notes.length ? notes : [""]).forEach((n) => addNoteRow(n));
    refreshNoteButtons();

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
    const label = $("#health-label");
    dot.className = "dot dot-unknown";
    label.textContent = "Checking…";
    const url = `${apiBase()}/health`;
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body && body.status === "ok") {
        dot.className = "dot dot-ok";
        dot.title = `OK · ${body.service || ""}`;
        label.textContent = "OK";
      } else {
        dot.className = "dot dot-fail";
        dot.title = "Unexpected response";
        label.textContent = "Failed";
      }
    } catch (err) {
      dot.className = "dot dot-fail";
      dot.title = `Failed: ${err.message}`;
      label.textContent = "Failed";
    }
  }

  async function loadExample() {
    setStatus("Loading example…", "loading");
    setLivePill("loading", "Loading example");
    try {
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
      setLivePill("success", "Example loaded");
    } catch (err) {
      setStatus(`Could not load example: ${err.message}`, "error");
      setLivePill("error", "Example failed");
    }
  }

  function showState(name) {
    ["empty-state", "loading-state", "error-state", "results-panel"]
      .forEach((id) => $("#" + id).classList.toggle("is-hidden", id !== name));
  }

  async function runOptimization() {
    setStatus("Calling /optimize-energy…", "loading");
    setLivePill("loading", "Optimizing");
    showState("loading-state");
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
      $("#error-msg").textContent = err.message;
      setLivePill("error", "Network error");
      showState("error-state");
      return;
    }

    let body;
    try {
      body = await res.json();
    } catch (err) {
      setStatus(`Bad response (not JSON): HTTP ${res.status}`, "error");
      $("#error-msg").textContent = `HTTP ${res.status} returned non-JSON.`;
      setLivePill("error", "Bad response");
      showState("error-state");
      return;
    }

    if (!res.ok) {
      const detail =
        (body && (body.detail || body.message)) || `HTTP ${res.status}`;
      setStatus(`API error: ${detail}`, "error");
      $("#error-msg").textContent = detail;
      setLivePill("error", "API error");
      showState("error-state");
      return;
    }

    state.lastResult = body;
    renderResult(body);
    setStatus(`Done in scenario ${body.scenario_id}.`, "success");
    setLivePill("success", "Ready");
    bumpCounters(body);
  }

  function bumpCounters(result) {
    state.stats.scenarios += 1;
    // very rough, illustrative savings for the hero counters
    const savedKwh = Math.max(
      0,
      state.hours.reduce((s, h) => s + h.demand_kwh, 0) -
      (result.total_grid_kwh || 0)
    );
    state.stats.savedKwh += savedKwh;
    state.stats.savedBdt += Math.max(0, (result.total_cost_bdt || 0) * 0.18);

    animateCounter($("#hero-stats .stat:nth-child(1) .stat-num"),
      state.stats.scenarios);
    animateCounter($("#hero-stats .stat:nth-child(2) .stat-num"),
      state.stats.savedKwh, { decimals: 0 });
    animateCounter($("#hero-stats .stat:nth-child(3) .stat-num"),
      state.stats.savedBdt, { decimals: 0 });
  }

  // ------------------------------------------------------------------
  // Results rendering
  // ------------------------------------------------------------------

  function sparkline(polyId, values) {
    const poly = document.getElementById(polyId);
    if (!poly || !values.length) return;
    const w = 80, h = 24, pad = 2;
    const max = Math.max(...values, 0.001);
    const min = Math.min(...values, 0);
    const range = max - min || 1;
    const step = (w - pad * 2) / (values.length - 1 || 1);
    const points = values.map((v, i) => {
      const x = pad + i * step;
      const y = h - pad - ((v - min) / range) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    poly.setAttribute("points", points.join(" "));
  }

  function renderResult(data) {
    showState("results-panel");
    $("#result-scenario").textContent = data.scenario_id || "–";

    // KPIs
    $("#kpi-grid").textContent = fmtNumber(data.total_grid_kwh, 1);
    $("#kpi-cost").textContent = fmtNumber(data.total_cost_bdt, 2);
    $("#kpi-peak").textContent = fmtNumber(data.peak_grid_kwh, 1);

    const plan = data.hourly_plan || [];
    sparkline("spark-grid",   plan.map((p) => p.grid_kwh || 0));
    sparkline("spark-tariff", plan.map((p) => state.hours[p.hour]
      ? state.hours[p.hour].tariff_bdt_per_kwh
      : 0));
    sparkline("spark-soc",    plan.map((p) => p.battery_energy_after_kwh || 0));

    $("#plan-summary").innerHTML = data.plan_summary
      ? escapeHtml(data.plan_summary)
      : "<em style='color:var(--text-faint)'>No plan summary returned.</em>";

    // Directive cards
    const wrap = $("#directives");
    wrap.innerHTML = "";
    const dirs = data.directive_interpretation || [];
    if (!dirs.length) {
      wrap.appendChild(
        el("p", { class: "panel-foot" },
          "No directives parsed — every operator note was either empty or ignored.")
      );
    } else {
      dirs.forEach((d) => wrap.appendChild(renderDirectiveCard(d)));
    }

    // Hourly table
    const planBody = $("#plan-body");
    planBody.innerHTML = "";
    plan.forEach((p) => {
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

    $("#hourly-meta").textContent =
      `${plan.length} rows · peak ${fmtNumber(data.peak_grid_kwh, 1)} kWh`;

    drawChart(plan);
    attachChartHover(plan);
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
  // SVG chart (refined palette, hover overlay, dual axes)
  // ------------------------------------------------------------------

  const CHART = {
    vbW: 720,
    vbH: 320,
    pad: { top: 18, right: 56, bottom: 32, left: 44 },
  };

  // Read theme tokens from CSS so the chart re-paints with light/dark.
  function cssVar(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }
  function chartColors() {
    return {
      grid:      cssVar("--chart-grid"),
      solar:     cssVar("--series-solar"),
      battery:   cssVar("--series-battery"),
      supply:    cssVar("--series-grid"),
      soc:       cssVar("--series-soc"),
      text:      cssVar("--chart-axis"),
      textBright:cssVar("--chart-fg"),
    };
  }

  function drawChart(plan) {
    const root = $("#chart");
    root.innerHTML = "";
    if (!plan.length) return;

    const { vbW, vbH, pad } = CHART;
    const COLORS = chartColors();
    const innerW = vbW - pad.left - pad.right;
    const innerH = vbH - pad.top - pad.bottom;

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

    // Background grid lines (left axis)
    const gridSteps = 4;
    for (let i = 0; i <= gridSteps; i++) {
      const y = pad.top + (innerH * i) / gridSteps;
      root.appendChild(
        svg("line", {
          x1: pad.left, x2: pad.left + innerW,
          y1: y, y2: y,
          stroke: COLORS.grid, "stroke-width": 1,
          "stroke-dasharray": i === gridSteps ? null : "2 3",
        })
      );
      const val = maxStack * (1 - i / gridSteps);
      root.appendChild(
        svg("text", {
          x: pad.left - 6, y: y + 3,
          fill: COLORS.text, "font-size": 9,
          "text-anchor": "end",
          "font-family": "Geist Mono, monospace",
        }, [fmtNumber(val, 0)])
      );
    }

    // Bars
    const slot = innerW / plan.length;
    const barW = Math.max(2, slot * 0.72);
    plan.forEach((p, i) => {
      const x = pad.left + slot * i + (slot - barW) / 2;
      const solarH  = ((p.solar_used_kwh || 0) / maxStack) * innerH;
      const gridH   = ((p.grid_kwh     || 0) / maxStack) * innerH;
      const batRaw  = p.battery_kwh || 0;
      const batAbsH = (Math.abs(batRaw) / maxStack) * innerH;

      let yCursor = pad.top + innerH;

      // solar (bottom)
      yCursor -= solarH;
      root.appendChild(
        svg("rect", {
          x, y: yCursor, width: barW, height: solarH,
          fill: COLORS.solar, opacity: 0.85,
          rx: 1,
        })
      );

      // battery band (between solar and grid)
      yCursor -= batAbsH;
      if (batRaw !== 0) {
        root.appendChild(
          svg("rect", {
            x, y: yCursor, width: barW, height: batAbsH,
            fill: COLORS.battery,
            opacity: batRaw > 0 ? 0.9 : 0.5,
            rx: 1,
          })
        );
      }

      // grid (top)
      yCursor -= gridH;
      root.appendChild(
        svg("rect", {
          x, y: yCursor, width: barW, height: gridH,
          fill: COLORS.supply, opacity: 0.85,
          rx: 1,
        })
      );
    });

    // X-axis hour labels (subset to avoid clutter)
    [0, 4, 8, 12, 16, 20, 23].forEach((h) => {
      const x = pad.left + slot * h + slot / 2;
      root.appendChild(
        svg("text", {
          x, y: pad.top + innerH + 16,
          fill: COLORS.text, "font-size": 9,
          "text-anchor": "middle",
          "font-family": "Geist Mono, monospace",
        }, [String(h).padStart(2, "0") + ":00"])
      );
    });

    // SOC smooth line (Catmull–Rom → Bézier for organic feel)
    const socPoints = plan.map((p, i) => ({
      x: pad.left + slot * i + slot / 2,
      y: pad.top + innerH -
          ((p.battery_energy_after_kwh || 0) / maxSoc) * innerH,
    }));
    const pathD = smoothPath(socPoints);
    root.appendChild(
      svg("path", {
        d: pathD, fill: "none",
        stroke: COLORS.soc, "stroke-width": 1.5,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        opacity: 0.95,
      })
    );

    // SOC dots
    socPoints.forEach((pt) => {
      root.appendChild(
        svg("circle", {
          cx: pt.x, cy: pt.y, r: 1.8,
          fill: cssVar("--chart-bg"), stroke: COLORS.soc,
          "stroke-width": 1.25,
        })
      );
    });

    // Right axis ticks (SOC scale)
    for (let i = 0; i <= gridSteps; i++) {
      const y = pad.top + (innerH * i) / gridSteps;
      const val = maxSoc * (1 - i / gridSteps);
      root.appendChild(
        svg("text", {
          x: pad.left + innerW + 6, y: y + 3,
          fill: COLORS.soc, "font-size": 9,
          "text-anchor": "start",
          "font-family": "Geist Mono, monospace",
          opacity: 0.9,
        }, [fmtNumber(val, 0)])
      );
    }

    // Axis labels
    root.appendChild(
      svg("text", {
        x: pad.left, y: pad.top - 6,
        fill: COLORS.text, "font-size": 9,
        "font-family": "Geist Mono, monospace",
        "letter-spacing": "0.1em",
      }, ["kWh / h"])
    );
    root.appendChild(
      svg("text", {
        x: pad.left + innerW, y: pad.top - 6,
        fill: COLORS.soc, "font-size": 9,
        "font-family": "Geist Mono, monospace",
        "text-anchor": "end",
        "letter-spacing": "0.1em",
      }, ["SOC kWh"])
    );

    // hover hit-area (one big rect to capture mouse)
    root.appendChild(
      svg("rect", {
        x: pad.left, y: pad.top,
        width: innerW, height: innerH,
        fill: "transparent", id: "chart-hit",
      })
    );
  }

  function smoothPath(points) {
    if (points.length < 2) return "";
    let d = `M ${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ` +
          `${cp2x.toFixed(1)},${cp2y.toFixed(1)} ` +
          `${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
    }
    return d;
  }

  function attachChartHover(plan) {
    const root = $("#chart");
    const tip = $("#chart-tip");
    if (!root || !tip || !plan.length) return;
    const { pad } = CHART;

    const onMove = (ev) => {
      const rect = root.getBoundingClientRect();
      const vb = root.getAttribute("viewBox").split(" ").map(Number);
      const vbW = vb[2];
      const vbH = vb[3];
      const x = (ev.clientX - rect.left) * (vbW / rect.width);
      const innerW = vbW - pad.left - pad.right;
      const innerH = vbH - pad.top - pad.bottom;
      const slot = innerW / plan.length;
      let i = Math.floor((x - pad.left) / slot);
      if (i < 0) i = 0;
      if (i >= plan.length) i = plan.length - 1;
      const p = plan[i];
      const hour = String(p.hour).padStart(2, "0") + ":00";
      tip.innerHTML =
        `<strong>hr ${hour}</strong><br>` +
        `grid ${fmtNumber(p.grid_kwh, 1)} · ` +
        `solar ${fmtNumber(p.solar_used_kwh, 1)}<br>` +
        `battery ${fmtNumber(p.battery_kwh, 1)} · ` +
        `SOC ${fmtNumber(p.battery_energy_after_kwh, 1)}`;
      // tip.position is relative to the chart-wrap parent, which shares
      // the SVG's coordinate scale (both occupy the same horizontal space).
      const barCx = pad.left + slot * i + slot / 2;
      tip.style.left = (barCx / vbW) * rect.width + "px";
      tip.style.top  = (pad.top / vbH) * rect.height + "px";
      tip.classList.remove("is-hidden");
    };
    const onLeave = () => tip.classList.add("is-hidden");

    root.addEventListener("mousemove", onMove);
    root.addEventListener("mouseleave", onLeave);
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

  function smoothScrollOnNav() {
    $$(".topnav-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const id = a.getAttribute("href").slice(1);
        const target = document.getElementById(id);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          $$(".topnav-link").forEach((n) => n.classList.remove("is-active"));
          a.classList.add("is-active");
        }
      });
    });
  }

  // ------------------------------------------------------------------
  // Theme switcher
  // ------------------------------------------------------------------

  const THEME_KEY = "gridwise-theme";
  const VALID = new Set(["light", "dark"]);

  function prefersDark() {
    return window.matchMedia &&
           window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function currentTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (VALID.has(stored)) return stored;
    return prefersDark() ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const btn = $("#btn-theme");
    if (btn) {
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.title = btn.getAttribute("aria-label");
    }
  }

  function setTheme(theme) {
    if (!VALID.has(theme)) return;
    applyTheme(theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
    // re-paint chart if a result is on screen so colors track the theme
    if (state.lastResult && state.lastResult.hourly_plan) {
      drawChart(state.lastResult.hourly_plan);
      attachChartHover(state.lastResult.hourly_plan);
    }
  }

  function toggleTheme() {
    const next =
      document.documentElement.getAttribute("data-theme") === "dark"
        ? "light" : "dark";
    setTheme(next);
  }

  function watchSystemTheme() {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      // only react if the user hasn't explicitly chosen a theme
      const stored = (() => {
        try { return localStorage.getItem(THEME_KEY); }
        catch (_) { return null; }
      })();
      if (!VALID.has(stored)) applyTheme(prefersDark() ? "dark" : "light");
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange); // legacy Safari
  }

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
    $("#btn-theme").addEventListener("click", toggleTheme);

    // apply theme ASAP — before any chart paint
    applyTheme(currentTheme());
    watchSystemTheme();

    smoothScrollOnNav();

    // Run health check automatically on load so users see the status.
    checkHealth();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
