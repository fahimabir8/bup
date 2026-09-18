"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _env_setup() -> None:
    # Default the test suite to the mock provider so tests are hermetic.
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("APP_ENABLE_CACHE", "false")