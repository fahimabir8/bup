# GridWise Frontend

A premium, asymmetric single-page UI for the GridWise API.
Vanilla HTML + CSS + JS — no React, no Tailwind, no build step.

## What's inside

```
frontend/
├── index.html   # Asymmetric Hero + Bento layout
├── styles.css   # Light, premium theme — CSS variables drive the palette
├── app.js       # Vanilla JS — form, API calls, SVG chart with hover tooltip
└── README.md    # This file
```

No build step, no `node_modules`, no framework. Just open the HTML
through a static server.

## Run it

You need the API running first.

```bash
# 1. Start the GridWise API (default port 8000)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. In a second terminal, serve the static frontend from the project root.
python -m http.server 8001 --directory .
```

Then open <http://localhost:8001/frontend/> in your browser.

## Design notes

The frontend follows a "design-taste-frontend v1" baseline
(`DESIGN_VARIANCE=8`, `MOTION_INTENSITY=6`, `VISUAL_DENSITY=4`):

* **Typography:** Geist (UI) + Geist Mono (numbers) via Google Fonts.
* **Color:** Off-black ink on warm off-white base. Single accent
  (Emerald 700, desaturated). Data series — amber / electric blue /
  deep rose — used **only** inside the chart, not as buttons or text.
  No AI purple, no neon glows.
* **Layout:** Asymmetric Hero with split metrics on the right. Two-
  column Bento inside the result area (70/30 schedule / directives)
  to dodge the banned "3 equal cards" pattern.
* **Motion:** Spring-style easing (`cubic-bezier(0.16, 1, 0.3, 1)`),
  tactile press feedback on every button, animated KPI counters,
  shimmering skeletons while loading.
* **States:** Empty / loading / error / result — every state is
  intentionally composed (not just a spinner).
* **Theming:** Light + dark themes live in `styles.css` under
  `:root` and `:root[data-theme="dark"]`. The toggle button sits in
  the top bar (sun/moon icon). The chosen theme is persisted in
  `localStorage` (`gridwise-theme`); first load falls back to
  `prefers-color-scheme`. The SVG chart re-reads CSS variables on
  every redraw so it re-paints when the theme changes. An inline
  script in `<head>` applies the theme **before paint** to avoid a
  flash on dark-preference systems.
* **Performance:** Grain overlay is `position: fixed` and
  `pointer-events: none`. Animations target `transform` / `opacity`
  only. `prefers-reduced-motion` is respected.
* **Anti-slop:** No "Acme" / "Nexus" filler, no "Elevate your workflow"
  copy, no gradient text, no custom cursors, no oversized H1s.

## Features

* **Health check** — pings `/health`, shows a green/red pulsing dot.
* **Load example** — fetches `data/example_request.json` from the
  project and prefills the form (scenario id, notes, battery, 24-hour
  horizon).
* **Run optimization** — POSTs the form to `/optimize-energy` and
  renders:
  * **KPI tiles** — total grid, total cost, peak grid, each with a
    sparkline of the per-hour series and an animated counter.
  * **Plan summary** — the one-line summary returned by the API.
  * **SVG schedule chart** — 24 stacked columns (solar / battery /
    grid) plus a smoothed battery-SOC line against a right-side
    y-axis, with a hover tooltip that reads hour-level details.
  * **Directive interpretation cards** — one per operator note, with
    the parsed `directive_type`, the `structured_adjustment` JSON,
    and the LLM's `explanation`.
  * **Hourly plan table** — full 24 rows with colored battery-action
    chips (`charge` / `discharge` / `idle`).
* **Download JSON** — saves the raw API response for debugging.

## Tweaking the theme

All colors live in CSS custom properties at the top of `styles.css`:

```css
:root {
  --bg:        #f7f7f5;
  --surface:   #ffffff;
  --ink:       #1a1a17;
  --accent:    #047857;
  --series-solar:   #b45309;
  --series-battery: #1d4ed8;
  --series-soc:     #be185d;
  /* ... */
}

:root[data-theme="dark"] {
  --bg:        #0e0f0c;
  --surface:   #161710;
  --ink:       #f5f4ee;
  --accent:    #34d399;
  /* ... */
}
```

Change any of them and the whole UI follows — both themes will pick
up the change. The chart reuses the same variables via
`var(--series-*)`, so the chart palette is consistent with the rest
of the page.

## Production deployment

For production, tighten CORS in `app/main.py` by replacing
`allow_origins=["*"]` with the actual frontend origin. Then serve
`frontend/` from any static host (nginx, S3 + CloudFront, Vercel,
GitHub Pages, etc.) and point the API at the static origin.

## Troubleshooting

* **Health dot stays red** — the API isn't reachable. Verify the URL
  in the top-right and that the uvicorn process is running.
* **Run optimization returns 422** — the request payload failed
  validation. The API's error `detail` is shown on a dedicated error
  card in the result area. Most often this means the hours table
  doesn't cover 0..23 or a numeric field is empty.
* **The chart looks flat** — your solar/grid values are all zero;
  use **Load example** to see a realistic scenario.