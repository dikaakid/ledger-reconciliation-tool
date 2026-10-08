# Contributing

Thanks for taking a look. This is a small project, so the process is short.

## Setup

    git clone https://github.com/dikaakid/ledger-reconciliation-tool.git
    cd ledger-reconciliation-tool
    python -m venv .venv
    .venv\Scripts\activate        # Windows PowerShell (Linux/macOS: source .venv/bin/activate)
    pip install -e ".[dev]"

## Before opening a pull request

    ruff format .
    ruff check .
    pytest

CI runs the same checks on Python 3.10, 3.12 and 3.13 on Linux and Windows.

## Guidelines

* **Add a test for every behaviour change.** Tests live in `tests/` and use tiny hand-built
  ledgers, so the rule being tested is visible in the test itself.
* **Keep provider-specific knowledge out of the engine.** Formats, prefixes and thresholds belong
  in `ReconConfig`, not in `core.py`.
* **Never commit real financial data.** Only the synthetic files under `examples/dummy_data/`.
  If you change the generator, regenerate them with `python examples/generate_sample_data.py`
  and update the expected numbers in `tests/test_pipeline.py` and the README.
* Add an entry under `Unreleased` in `CHANGELOG.md`.
