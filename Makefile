# GridWise Makefile
# Common developer commands. Targets are intentionally simple and
# have no undocumented dependencies.

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
HOST ?= 0.0.0.0
PORT ?= 8000
LLM_PROVIDER ?= mock
APP_ENABLE_CACHE ?= true

.PHONY: help install install-dev test test-unit test-integration test-property test-public test-generated lint run sample-test benchmark generate-samples docker-build docker-run clean

help:
	@echo "GridWise targets:"
	@echo "  install         - install runtime dependencies"
	@echo "  install-dev     - install runtime + dev dependencies"
	@echo "  test            - run the full test suite"
	@echo "  test-unit       - run unit tests only"
	@echo "  test-integration - run integration tests only"
	@echo "  test-property   - run property-based tests only"
	@echo "  test-public     - run official public sample tests"
	@echo "  test-generated  - run self-generated sample tests"
	@echo "  run             - run uvicorn locally with mock LLM"
	@echo "  sample-test     - validate against samples.json"
	@echo "  generate-samples - regenerate data/generated_samples.json"
	@echo "  benchmark       - run scripts/benchmark.py"
	@echo "  docker-build    - build the Docker image"
	@echo "  docker-run      - run the Docker image"
	@echo "  clean           - remove Python build artefacts"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install hypothesis

test:
	$(PYTHON) -m pytest -q

test-unit:
	$(PYTHON) -m pytest tests/unit -q

test-integration:
	$(PYTHON) -m pytest tests/integration -q

test-property:
	$(PYTHON) -m pytest tests/property -q

test-public:
	$(PYTHON) -m pytest tests/test_public_samples.py -q

test-generated:
	$(PYTHON) -m pytest tests/test_generated_samples.py -q

lint:
	$(PYTHON) -m pyflakes app tests scripts

run:
	LLM_PROVIDER=$(LLM_PROVIDER) APP_ENABLE_CACHE=$(APP_ENABLE_CACHE) \
		$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

sample-test:
	$(PYTHON) scripts/validate_samples.py

benchmark:
	$(PYTHON) scripts/benchmark.py

generate-samples:
	$(PYTHON) scripts/generate_samples.py

docker-build:
	docker build -t gridwise:latest .

docker-run:
	docker run --rm -p $(PORT):$(PORT) --env-file .env gridwise:latest

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .hypothesis
	find . -name __pycache__ -type d -exec rm -rf {} +