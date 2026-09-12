"""Central configuration for the Buy or Wait? agent.

Paths, constants, and defaults used across all modules.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# code/config.py -> code/ -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
IMAGES_DIR = DATASET_DIR / "media" / "images"
OUTPUT_CSV = REPO_ROOT / "output.csv"

# Dataset files
CSV_PROFILES = DATASET_DIR / "financial_profiles.csv"
CSV_EVENTS = DATASET_DIR / "financial_events.csv"
CSV_RATES = DATASET_DIR / "exchange_rates.csv"
CSV_REQUESTS = DATASET_DIR / "requests.csv"
CSV_SAMPLES = DATASET_DIR / "sample_requests.csv"
CSV_OPTIONS = DATASET_DIR / "request_payment_options.csv"
CSV_MESSAGES = DATASET_DIR / "messages.csv"
CSV_IMAGES = DATASET_DIR / "images.csv"

# AGENTS.md compliance: log lives next to the top-level AGENTS.md
AGENTS_MD = REPO_ROOT / "AGENTS.md"
LOG_TXT = REPO_ROOT / "log.txt"

# Evaluation artifacts
EVALUATION_DIR = REPO_ROOT / "evaluation"
TOKEN_LEDGER_CSV = EVALUATION_DIR / "token_ledger.csv"

# ---------------------------------------------------------------------------
# Forecast / decision constants
# ---------------------------------------------------------------------------

FORECAST_DAYS = 90

# Maximum spending changes allowed in one recommendation
MAX_SPENDING_CHANGES = 3

# Affordability statuses / payment methods (validation enums)
AFFORDABILITY_STATUSES = (
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
)
PAYMENT_METHODS = (
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
)

# Event statuses that represent real cash movement vs non-cash
CASH_EVENT_STATUSES = frozenset({"settled", "pending", "scheduled"})
NON_CASH_STATUSES = frozenset({"unrealized"})

# LLM configuration (keys come from environment only; never hardcoded)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# When no API key is configured, interpreters fall back to deterministic
# heuristic extraction. This flag records which mode is active.
LLM_ENABLED = bool(OPENAI_API_KEY or ANTHROPIC_API_KEY)

# Estimated cost per 1M tokens (input, output) in USD, used by the ledger.
MODEL_COSTS_PER_1M = {
    # Deterministic fallback path costs nothing.
    "heuristic-v0": (0.0, 0.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
}

DEFAULT_MODEL = "heuristic-v0"
DEFAULT_PROVIDER = "deterministic"
