# GridWise

LLM-assisted 24-hour campus energy optimizer. Send a scenario plus 1–3
operator notes; get a per-hour battery + grid plan with cost math.

- `POST /optimize-energy` — validate, interpret notes with an LLM,
  solve via HiGHS MILP, replay-validate, return the plan.
- `GET /health` — liveness probe.

## Run it

```bash
# 1. install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. run with the bundled mock LLM (no API key needed)
LLM_PROVIDER=mock python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# or with a real Gemini key:
echo 'LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
LLM_MODEL=gemini-2.0-flash' > .env

# 3. smoke test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  --data-binary @data/example_request.json
```

Open the static frontend at <http://localhost:8001/frontend/> while
the API runs on `:8000`:

```bash
python -m http.server 8001 --directory .
```

The console has a **Health** button + a sun/moon **theme toggle**
(persisted in `localStorage`).

## Tests

```bash
make test                # full suite (hermetic with mock LLM)
make sample-test         # validate against the official sample file
make benchmark           # latency + cost per scenario
```

`make help` lists every target.

## Docker

```bash
docker compose up --build
# or:
docker build -t gridwise:latest .
docker run --rm -p 8000:8000 --env-file .env gridwise:latest
```

## Project layout

```
app/                  # FastAPI service
  api/                # routes
  llm/                # provider abstraction (gemini, openai_compat, mock)
  directives/         # typed validator + applier
  optimization/       # MILP model + HiGHS solver
  validation/         # canonical replay validator
  schemas/            # Pydantic models
data/                 # example_request.json
frontend/             # vanilla HTML/CSS/JS UI (light + dark)
scripts/              # validate_samples, generate_samples, benchmark
tests/                # unit / integration / property / sample suites
```

## Environment variables

All optional except when using a real provider. See `.env.example`.

| Var | Default | Used when |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` / `openai_compatible` / `mock` |
| `GEMINI_API_KEY` | — | `LLM_PROVIDER=gemini` |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | — | `LLM_PROVIDER=openai_compatible` |
| `APP_HOST`, `APP_PORT`, `APP_LOG_LEVEL` | `0.0.0.0` / `8000` / `info` | always |
| `GRIDWISE_REQUIRE_PROD_PROVIDER` | unset | set `true` to refuse `mock` at startup |
| `GRIDWISE_SOLVER_TIMEOUT` | `25` | MILP time limit (s) |

## Notes

- The mock LLM is a rule engine for tests only — never use it in
  production.
- Directive types: `solar_reduction`, `minimum_battery_reserve`,
  `no_charge_window`, `no_discharge_window`, `max_grid_window`,
  `no_op`.
- API errors return `{"detail": "..."}` with `400` (structural) /
  `422` (semantic) / `500` (replay mismatch or solver error).