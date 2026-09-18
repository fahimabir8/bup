# GridWise LLM-Assisted Energy Optimization - Implementation Plan

## Problem Overview
Build a FastAPI HTTP API service for the BUP CSE Fest 2026 Hackathon Preliminary Round:
- **Endpoints**: `GET /health`, `POST /optimize-energy`
- **Core Task**: Interpret 1-3 natural-language operator notes using LLM, convert to structured directives, validate via guardrails, then optimize 24-hour energy schedule minimizing grid cost
- **Directives**: solar_reduction, minimum_battery_reserve, no_charge_window, no_discharge_window, max_grid_window, no_op
- **Constraints**: Battery physics, energy balance, end-of-day neutrality, directive-specific limits

## Project Structure (FastAPI Full-Stack Template)

```
bup/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── health.py       # GET /health
│   │   │   │   └── optimize.py     # POST /optimize-energy
│   │   │   └── main.py
│   │   ├── core/
│   │   │   ├── config.py           # Settings, LLM config
│   │   │   └── security.py
│   │   ├── models/
│   │   │   ├── request.py          # Pydantic models for request
│   │   │   ├── response.py         # Pydantic models for response
│   │   │   └── directives.py       # Directive types & validation
│   │   ├── services/
│   │   │   ├── llm_interpreter.py  # LLM note interpretation
│   │   │   ├── guardrails.py       # Deterministic validation
│   │   │   └── optimizer.py        # Energy optimization (LP/DP)
│   │   └── main.py                 # FastAPI app factory
│   ├── tests/
│   │   ├── test_health.py
│   │   ├── test_optimize.py
│   │   └── test_public_samples.py  # Validate against sample cases
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── alembic.ini (remove - not needed)
├── frontend/ (remove - not needed)
├── compose.yml
├── compose.override.yml
├── pyproject.toml (root)
├── README.md
├── .env.example
└── .gitignore
```

## Implementation Phases

### Phase 1: Project Setup & Core Models
- [ ] Initialize backend using FastAPI template structure
- [ ] Define Pydantic models for request/response schemas (matching Problem Statement exactly)
- [ ] Define directive types as enums with structured_adjustment shapes
- [ ] Set up configuration management (LLM provider, API keys, model name)

### Phase 2: LLM Interpretation Pipeline
- [ ] Implement `llm_interpreter.py`:
  - Prompt engineering for directive extraction
  - Support for all 5 directive types + no_op
  - Handle paraphrasing, percentage/time parsing
  - Return structured JSON for each note
- [ ] Implement `guardrails.py`:
  - Validate directive_type against allowed enums
  - Validate hours: unique 0-23, ascending
  - Validate numeric ranges (factor 0-1, reserve <= capacity, etc.)
  - Enforce applies semantics (no_op -> false/null, others -> true)
  - Safe failure on malformed LLM output

### Phase 3: Energy Optimizer
- [ ] Implement `optimizer.py`:
  - Linear Programming (PuLP/SciPy) or Dynamic Programming
  - Variables per hour: grid_kwh, solar_used_kwh, battery_charge_kwh, battery_discharge_kwh
  - Constraints:
    - Energy balance: grid + solar_used + discharge = demand + charge
    - Battery bounds: min <= energy_after <= capacity
    - Rate limits: charge <= max_charge, discharge <= max_discharge
    - Solar limit: solar_used <= effective_solar (after solar_reduction)
    - Directive constraints: no_charge, no_discharge, min_reserve, max_grid
    - End-of-day: energy_after[23] = initial_energy
  - Objective: Minimize SUM(grid_kwh[h] * tariff[h])

### Phase 4: API Endpoints
- [ ] `GET /health` -> `{"status": "ok"}`
- [ ] `POST /optimize-energy`:
  - Validate request schema
  - Call LLM interpreter for each note
  - Run guardrails on all interpretations
  - Apply valid directives to optimizer
  - Return full response with directive_interpretation + hourly_plan + totals + plan_summary

### Phase 5: Testing & Validation
- [ ] Unit tests for guardrails, directive parsing
- [ ] Integration tests against all 10 public sample cases
- [ ] Verify exact schema compliance (field names, types, order)
- [ ] Test edge cases: malformed LLM output, invalid requests, no_op handling

### Phase 6: Deployment & Documentation
- [ ] Dockerfile (multi-stage, non-root, bind 0.0.0.0:8000)
- [ ] docker-compose for local dev
- [ ] README.md with:
  - Quickstart (clone, env vars, run)
  - LLM provider/model configuration
  - Guardrails explanation
  - Optimizer/solver details
  - curl examples for /health and /optimize-energy
  - Public sample test command
  - Dependencies, limitations, secret handling
- [ ] .env.example with required variables
- [ ] Push to GitHub (private during event)

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Provider | OpenAI GPT-4o-mini / Local Ollama | Configurable via env var |
| Optimizer | PuLP (LP) | Reliable, handles constraints well |
| Validation | Pydantic v2 | FastAPI native, strict schemas |
| Battery Model | Linear (charge/discharge separate) | Matches problem physics |
| Time Windows | Half-open [start, end) | Per spec: 1PM-3PM = [13,14] |

## Risk Mitigation

- **LLM Hallucination**: Guardrails reject invalid types/values; fallback to no_op on failure
- **Infeasible Optimization**: PuLP returns status; if infeasible, return error with diagnostics
- **Latency**: Cache LLM responses for identical notes; target p95 < 5s
- **Secrets**: Never commit .env; use Docker secrets / env vars only

## Success Criteria (per Evaluation Rubric)
1. **LLM Interpretation (25pts)**: Correct directive_type, hours, values, paraphrase robustness
2. **Directive Application (25pts)**: All ground-truth directives enforced in schedule
3. **Optimization (10pts)**: Cost within tolerance of organizer optimal
4. **API Contract (10pts)**: Exact schema, status codes, field order
5. **Performance (10pts)**: p95 <= 5s, stable under repeated requests
6. **Deployment (10pts)**: Public endpoint + working Docker fallback
7. **Documentation (10pts)**: Reproducible local quickstart, all required sections

## Next Steps
1. Scaffold backend structure from template
2. Implement request/response Pydantic models
3. Build LLM interpreter with prompt templates
4. Build guardrails validator
5. Build LP optimizer
6. Wire up API endpoints
7. Test against public samples
8. Dockerize, document, deploy
