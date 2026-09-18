# GridWise Frontend

A minimalistic, dark-themed single-page UI for the GridWise API.

## What's inside

```
frontend/
├── index.html   # Single-page UI
├── styles.css   # Dark theme — CSS variables, no framework
├── app.js       # Vanilla JS — form, API calls, SVG chart
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
#    Serving from the project root (not from frontend/) is what lets the
#    "Load example" button reach data/example_request.json.
python -m http.server 8001 --directory .
```

Then open <http://localhost:8001/frontend/> in your browser.

The CORS middleware added to `app/main.py` allows the static origin
(`localhost:8001`) to POST to the API (`localhost:8000`) without any
extra configuration. The frontend defaults to `http://localhost:8000`
for the API endpoint, so no tweaking is required for the standard
local setup.

If you serve the frontend from a different host (for example a remote
staging server), update the **API endpoint** field in the top-right of
the page to point at the API host. Click **Health check** to verify
connectivity — the dot turns green when the API responds.

## Features

* **Health check** — pings `/health` and shows a green/red status dot.
* **Load example** — fetches `data/example_request.json` from the
  project and prefills the form (scenario id, notes, battery, 24-hour
  horizon).
* **Run optimization** — POSTs the form to `/optimize-energy` and
  renders:
  * **KPI tiles** — total grid, total cost, peak grid.
  * **Plan summary** — the one-line summary returned by the API.
  * **SVG schedule chart** — 24 stacked columns (solar / battery /
    grid) plus a purple battery-SOC line against a right-side y-axis.
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
  --bg: #0b0d10;
  --surface: #14181d;
  --accent: #4ade80;
  /* ... */
}
```

Change any of them and the whole UI follows. The chart reuses the
same variables via `var(--chart-solar)`, etc., so the chart palette
is consistent with the rest of the page.

## Production deployment

For production, tighten CORS in `app/main.py` by replacing
`allow_origins=["*"]` with the actual frontend origin. Then serve
`frontend/` from any static host (nginx, S3 + CloudFront, Vercel,
GitHub Pages, etc.) and point the API at the static origin.

## Troubleshooting

* **Health dot stays red** — the API isn't reachable. Verify the URL
  in the top-right and that the uvicorn process is running.
* **Run optimization returns 422** — the request payload failed
  validation. The API's error `detail` is shown next to the button.
  Most often this means the hours table doesn't cover 0..23 or a
  numeric field is empty.
* **The chart looks flat** — your solar/grid values are all zero;
  use **Load example** to see a realistic scenario.
