# PoolOS Development Environment

PoolOS uses standard Python packaging through `pyproject.toml`. Development
utilities are optional and are not required to run PoolOS in production.

## Supported Python versions

PoolOS currently requires Python 3.13 or newer, as declared in `pyproject.toml`.

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
python3 -m compileall poolos intellicenter
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
python3 -m ruff check poolos intellicenter tests
```

Run type analysis:

```bash
python3 -m mypy poolos
```

MyPy currently checks only the installable `poolos` package. This is an explicit
tooling boundary: the IntelliCenter Home Assistant integration has separate runtime
and typing dependencies. Compilation, Ruff, MyPy for PoolOS, and pytest are required.

## Updating development dependencies

The canonical dependency definitions are in `pyproject.toml` under
`[project.optional-dependencies].dev`.

`requirements-dev.txt` is a convenience entry point, so this is equivalent:

```bash
python3 -m pip install -r requirements-dev.txt
```

## Continuous integration

GitHub Actions runs on every pull request and every push.

The workflow:

1. Installs PoolOS in editable mode with development dependencies.
2. Compiles `poolos` and `intellicenter`.
3. Runs Ruff across `poolos`, `intellicenter`, and `tests`.
4. Runs MyPy against `poolos`.
5. Runs the complete pytest suite on Python 3.13.

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
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m mypy poolos
python -m pytest
```

Package initializer modules intentionally re-export convenience symbols. Ruff's F401 rule is
therefore disabled only for `poolos/__init__.py` and `poolos/hal/__init__.py`; unused imports
remain enforced everywhere else.

