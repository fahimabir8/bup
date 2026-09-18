# GridWise

LLM-Assisted Smart Campus Energy Optimization API for the BUP CSE Fest
2026 preliminary round.

GridWise accepts a 24-hour energy scenario plus 1-3 natural-language
operator notes and returns a cost-optimal energy schedule that respects
all directives. The LLM is responsible for **semantic interpretation**
of the operator notes only; everything else (validation, optimization,
replay) is deterministic code.

---

## Highlights

* **Architecture**

  ```
  POST /optimize-energy
     |
     v
  Pydantic validation (request schema)
     |
     v
  LLM interpretation (real provider in production)
     |
     v
  Deterministic guardrails (coverage, types, hours, numerics)
     |
     v
  Directive applier (typed effective scenario)
     |
     v
  HiGHS MILP optimizer (minimises grid cost)
     |
     v
  Deterministic replay validator
     |
     v
  JSON response (totals recalculated from final plan)
  ```

* **Supported directive types**: `solar_reduction`,
  `minimum_battery_reserve`, `no_charge_window`,
  `no_discharge_window`, `max_grid_window`, `no_op`.
* **Optimizer**: SciPy `optimize.milp` with HiGHS (binary action
  exclusivity is enforced with exact MILP constraints).
* **LLM providers**: any OpenAI-compatible chat-completions endpoint
  (OpenAI, Ollama, vLLM, gateways). A `mock` provider is bundled for
  hermetic testing.
* **Security**: `.env` in `.gitignore`, no secrets in source or image,
  non-root Docker user, controlled exception handling, structured
  logging without tokens.

---

## Quick start

```bash
# 1. Clone and install
git clone <repo>
cd gridwise
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install hypothesis   # dev only

# 2. Configure
cp .env.example .env
# edit .env to set LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 3. Run
LLM_PROVIDER=mock python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. Smoke test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/optimize-energy \
     -H "Content-Type: application/json" \
     --data-binary @data/example_request.json
```

For local development without an LLM API key, use the `mock` provider
(`LLM_PROVIDER=mock`). The mock is a deterministic rule engine that
interprets the official public sample notes; it is **never** the
production default.

### Using Google Gemini

GridWise ships with a **native** Gemini interpreter
(`GeminiInterpreter`) that talks to Google's `generateContent` REST
API directly — there is no OpenAI dependency. To enable it, paste
your Google AI Studio key into `.env`:

```bash
# .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key
LLM_MODEL=gemini-2.0-flash        # any Gemini model id works
```

Optional overrides:

```bash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com  # default
```

The interpreter forces JSON output via
`generationConfig.response_mime_type="application/json"` and expects
the structured envelope described in the system prompt. Any current
Gemini model works (`gemini-2.0-flash`, `gemini-2.0-flash-lite`,
`gemini-1.5-flash`, `gemini-1.5-pro`, ...).

---

## Endpoints

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /optimize-energy`

#### Request

```json
{
  "scenario_id": "GRID-001",
  "operator_notes": [
    "Panel washing from 1 PM to 3 PM will leave 20% of normal solar.",
    "The cafeteria menu has changed next week."
  ],
  "hours": [
    {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6}
    /* ... exactly 24 ascending entries ... */
  ],
  "battery": {
    "capacity_kwh": 220,
    "initial_energy_kwh": 110,
    "minimum_energy_kwh": 40,
    "max_charge_kwh_per_hour": 50,
    "max_discharge_kwh_per_hour": 50
  }
}
```

#### Response

```json
{
  "scenario_id": "GRID-001",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
      "explanation": "..."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "..."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 50.0,
      "solar_used_kwh": 0.0,
      "battery_action": "discharge",
      "battery_kwh": 40.0,
      "battery_energy_after_kwh": 70.0
    }
    /* ... exactly 24 entries ... */
  ],
  "total_grid_kwh": 2492.0,
  "total_cost_bdt": 35440.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "..."
}
```

Errors return controlled JSON:

```json
{ "detail": "Invalid request: hours must contain exactly 24 entries" }
```

Status codes:

| Code | Meaning |
|------|---------|
| 200  | Successful optimization. |
| 400  | Malformed structural input (missing fields, wrong types, etc.). |
| 422  | Semantically invalid scenario or unsupported LLM output. |
| 500  | Internal failure (replay mismatch, solver error, etc.). |

---

## Project layout

```
gridwise/
|-- app/
|   |-- api/             # FastAPI endpoints (health, optimize)
|   |-- config.py        # Environment-driven configuration
|   |-- directives/      # Validator + applier (typed)
|   |-- llm/             # LLM provider abstraction
|   |   |-- base.py
|   |   |-- openai_compatible.py
|   |   |-- mock.py
|   |   |-- prompts.py
|   |   `-- interpreter.py
|   |-- optimization/    # MILP model, solver, postprocess
|   |-- schemas/         # Pydantic request/response/directive models
|   |-- services/        # End-to-end orchestration
|   |-- validation/      # Canonical replay validator
|   `-- main.py          # FastAPI app + lifespan
|-- data/                # Sample data
|-- scripts/             # generate_samples / validate_samples / benchmark / replay_plan
|-- tests/               # unit / integration / property / public_samples / generated_samples
|-- Dockerfile
|-- docker-compose.yml
|-- Makefile
|-- pyproject.toml
|-- requirements.txt
|-- .env.example
`-- README.md
```

---

## Environment variables

| Variable | Default | Notes |
|----------|---------|-------|
| `LLM_PROVIDER` | `gemini` | `gemini`, `openai_compatible`, or `mock`. Production deployments must NOT use `mock`. |
| `GEMINI_API_KEY` | (empty) | Google AI Studio API key. Used when `LLM_PROVIDER=gemini`. Never commit. |
| `GEMINI_BASE_URL` | (empty) | Optional override for the Gemini API host. Defaults to `https://generativelanguage.googleapis.com`. |
| `LLM_BASE_URL` | (empty) | Required only when `LLM_PROVIDER=openai_compatible`. |
| `LLM_API_KEY` | (empty) | Bearer token for non-Gemini providers. |
| `LLM_MODEL` | `gemini-2.0-flash` | e.g. `gemini-2.0-flash`, `gemini-1.5-pro`, `gpt-4o-mini`, `llama3.1`. |
| `LLM_TIMEOUT_SECONDS` | `12` | Per-call HTTP timeout. |
| `LLM_MAX_RETRIES` | `1` | Retries on transient errors. |
| `LLM_CACHE_MAX_ENTRIES` | `256` | TTL+LRU cache for interpretation results. |
| `LLM_CACHE_TTL_SECONDS` | `300` | Cache entry lifetime. |
| `APP_HOST` | `0.0.0.0` | Bind address. |
| `APP_PORT` | `8000` | Bind port. |
| `APP_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |
| `APP_ENABLE_CACHE` | `true` | Disable for strict tests. |
| `GRIDWISE_REQUIRE_PROD_PROVIDER` | unset | Set to `true` to refuse startup with `LLM_PROVIDER=mock`. |
| `GRIDWISE_ABS_TOL` | `0.001` | Numerical tolerance for replay. |
| `GRIDWISE_ACTION_TOL` | `0.0001` | Tolerance for action indicators. |
| `GRIDWISE_OUTPUT_PRECISION` | `4` | Rounding precision for API output. |
| `GRIDWISE_SOLVER_TIMEOUT` | `25` | MILP time limit (seconds). |

---

## LLM architecture

The LLM is the **only** component that interprets natural language. It
returns a JSON envelope that maps every input note to exactly one
directive. The envelope is parsed by Pydantic and then verified by a
deterministic validator that enforces:

* one interpretation per note (`note_index` contiguous, no duplicates)
* allowed directive types
* `applies` and `structured_adjustment` semantics for `no_op`
* hour invariant (integer, 0-23, unique, ascending)
* numeric range checks (factor, reserve, grid cap)

The optimizer only ever receives **validated** typed directives via
`ValidatedDirectiveSet`. Any model failure (invalid JSON, malformed
fields, unsupported directive) results in a controlled 422 response;
the LLM is never silently converted into a `no_op`.

The system prompt (`app/llm/prompts.py`) is intentionally explicit
about the directive ontology, time semantics, and percentage
interpretation. The mock interpreter (`app/llm/mock.py`) exists only
for local tests; it is not a phrase dictionary that replaces the LLM.

---

## Optimizer

We minimise

```
sum_h grid_kwh[h] * tariff_bdt_per_kwh[h]
```

subject to:

* Energy balance:
  `grid[h] + solar_used[h] + discharge[h] = demand[h] + charge[h]`
* Battery transition:
  `E_after[h] = E_after[h-1] + charge[h] - discharge[h]`
* Battery bounds:
  `minimum[h] <= E_after[h] <= capacity`
* Charge / discharge limits: `charge[h] <= max_charge[h]`,
  `discharge[h] <= max_discharge[h]`
* Action exclusivity (binary mode indicators):
  `charge[h] <= max_charge[h] * charge_mode[h]`
  `discharge[h] <= max_discharge[h] * discharge_mode[h]`
  `charge_mode[h] + discharge_mode[h] <= 1`
* Effective solar:
  `solar_used[h] <= effective_solar[h]`
* Directive constraints: `no_charge`, `no_discharge`, `max_grid`.
* End-of-day neutrality: `E_after[23] = initial_energy`.

The HiGHS solver is used via `scipy.optimize.milp` for exact action
exclusivity. Numerical drift is normalised by a tiny zero-tolerance
before the response is rounded; the schedule is replayed against the
canonical validator before being returned.

---

## Replay validator

`app/validation/replay.py` is the **single canonical validator** used by:

* the API service before returning any response
* the public sample validator
* the property-based test suite
* the benchmark / debug scripts

It re-derives every constraint from the plan and the original inputs.
If replay fails the API returns 500 and logs a safe diagnostic message
without secrets.

---

## Tests

```bash
# All tests
pytest -q

# By category
pytest tests/unit -q
pytest tests/integration -q
pytest tests/property -q
pytest tests/test_public_samples.py -q
pytest tests/test_generated_samples.py -q
```

The test suite is hermetic: with `LLM_PROVIDER=mock` no network access
is required. The official public sample cases are loaded automatically
when present in `data/` or the project root; otherwise the public
sample test skips and the generated sample + property tests cover the
validation surface.

---

## Public sample validation

If the official public sample file is present, run:

```bash
make sample-test
# or
python scripts/validate_samples.py
python scripts/validate_samples.py --file path/to/samples.json
python scripts/validate_samples.py --start-server
```

The validator POSTs every case to `/optimize-energy`, checks
interpretation, replays the schedule, verifies totals, and compares
cost within the allowed tolerance. Equivalent optimal solutions are
accepted.

---

## Synthetic samples

```bash
python scripts/generate_samples.py
```

Writes `data/generated_samples.json` with 18 deterministic cases. The
header is explicitly labelled `SELF-GENERATED TEST CASE / NOT OFFICIAL
ORGANIZER SAMPLE`.

---

## Benchmark

```bash
make benchmark
# or
python scripts/benchmark.py --provider mock --repeats 1
python scripts/benchmark.py --provider openai_compatible --repeats 3
```

Reports total request latency and cost per scenario. The provider name
is printed so it is obvious whether results are local or remote.

---

## Docker

```bash
docker build -t gridwise:latest .
docker run --rm -p 8000:8000 --env-file .env gridwise:latest

# or
docker compose up --build
```

* Image runs as non-root user `gridwise`.
* Healthcheck hits `GET /health` every 30 s.
* No secrets baked into the image.

---

## Known limitations

* The mock LLM is a small rule engine, **not** a generative model. It
  is intended only for tests. Production deployments must set
  `LLM_PROVIDER` to a real provider.
* Action exclusivity is enforced with binary MILP variables; on
  extremely tight budgets, the HiGHS solver may produce micro-noise
  around zero. We normalise tiny values and re-validate; a perfect
  rounding to two decimal places is preserved.
* The LLM cache is a simple TTL+LRU cache. It is process-local and not
  shared between replicas. Scenarios are not cached by `scenario_id`
  alone; the full operator note list is part of the cache key.
* The prompt (`INTERPRETER_PROMPT_VERSION = "1.0"`) and the directive
  ontology are coupled. Future prompt changes must bump the version so
  cache entries and logs remain consistent.

---

## Implementation status (this repository)

* Implementation status: complete.
* Test status: 131 passed locally with the mock LLM.
* Docker status: builds and runs the service on port 8000.
* Health endpoint status: returns `{"status":"ok"}` within 60 s of
  startup.
* Sample-test status: matches all 10 official public samples within
  tolerance when the public sample file is available.
* Known limitations: see above.

Official sample files were available in the repository root at
`BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`. The CI test suite
skips gracefully if the file is absent.
