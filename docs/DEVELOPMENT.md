# PoolOS Development Environment

PoolOS uses standard Python packaging through `pyproject.toml`. Development
utilities are optional and are not required to run PoolOS in production.

## Supported Python versions

PoolOS currently targets Python 3.10 through Python 3.13.

Check the active interpreter:

```bash
python3 --version
```

## Recommended local setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

The virtual environment keeps PoolOS development packages separate from the
macOS system Python installation.

After the first setup, reactivate it when returning to the repository:

```bash
source .venv/bin/activate
```

## Validation commands

Compile all PoolOS modules:

```bash
python3 -m compileall poolos
```

Run the full test suite:

```bash
python3 -m pytest
```

Run tests with coverage:

```bash
python3 -m pytest --cov=poolos --cov-report=term-missing
```

Check for definite Python errors and unused imports:

```bash
python3 -m ruff check poolos tests
```

Run type analysis:

```bash
python3 -m mypy poolos
```

Type analysis is initially advisory while older modules are progressively
annotated. CI reports mypy findings without blocking merges. Compilation,
pytest, and Ruff fatal-error checks are required.

## Updating development dependencies

The canonical dependency definitions are in `pyproject.toml` under
`[project.optional-dependencies].dev`.

`requirements-dev.txt` is a convenience entry point, so this is equivalent:

```bash
python3 -m pip install -r requirements-dev.txt
```

## Continuous integration

GitHub Actions runs on every pull request and every push to `main`.

The workflow:

1. Installs PoolOS in editable mode with development dependencies.
2. Compiles the `poolos` package.
3. Runs pytest on Python 3.10, 3.11, 3.12, and 3.13.
4. Runs Ruff static checks.
5. Runs advisory mypy analysis.

## Troubleshooting: pytest is missing

This message:

```text
No module named pytest
```

means pytest is not installed in the active Python environment. It is not a
PoolOS compilation failure. Activate the project virtual environment and run:

```bash
python3 -m pip install -e ".[dev]"
```
## Code quality policy

PoolOS treats compilation, tests, and Ruff as required quality gates:

```bash
python -m compileall poolos
python -m pytest
python -m ruff check poolos tests
```

Package initializer modules intentionally re-export convenience symbols. Ruff's F401 rule is
therefore disabled only for `poolos/__init__.py` and `poolos/hal/__init__.py`; unused imports
remain enforced everywhere else.

