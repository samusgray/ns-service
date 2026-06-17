# CLAUDE.md

> How I (the developer) want Claude to work in this repo. The **Always** section is law.
> The **Defaults** section is a set of starting proposals for brainstorming — not constraints;
> the actual design is decided per task. Fill the `[PLACEHOLDER]` fields.

## Project

- **Name:** notification-service
- **What it is:** This is an internal service that other microservices or systems will use to send SMS and email notifications to arbitrary destinations (email addresses, and phone numbers).
- **Python:** >= 3.12
- **Specs & plans:** design docs in `docs/specs/`, implementation plans in `docs/plans/`.
  Read the relevant spec before changing behavior; update it if the design changes.

---

## Always — how I work (applies to every project)

### Golden rules
- **Always use `uv run …`** — never call `python`, `pytest`, `ruff`, etc. directly. The venv
  is managed by uv; bare tools may resolve to the wrong interpreter.
- **No `requirements.txt`, no `setup.py`, no `pip install`.** All deps and all tool config
  live in `pyproject.toml`. Add deps with `uv add <pkg>` (`uv add --dev <pkg>` for dev tools).
- **TDD by default:** failing test first, watch it fail for the right reason, minimal code to
  pass, then refactor. Commit in small, working increments.
- **YAGNI / DRY:** build only what the current task needs. No speculative abstractions.
- **A test that can't fail is a bug.** Tests assert real behavior, not mocks echoing
  themselves. If a "default"/"config" test passes regardless of the code, fix the test.
- **Evidence, not vibes.** Never claim something works without showing output (test run /
  curl / smoke run). Run the quality gates before saying "done."

### Fixed tooling
| Concern | Tool | Notes |
|---|---|---|
| Packaging / venv / deps | **uv** | `uv add`, `uv sync`, `uv run`. Commit `uv.lock`. |
| Lint + format | **Ruff** | One tool replaces black/isort/flake8. Config in `[tool.ruff]`. |
| Type checking | **ty** (Astral) | Strict. Young/preview — if it blocks, mypy is the fallback. |
| Tests | **pytest** (+ pytest-cov; pytest-asyncio if async) | `asyncio_mode = "auto"` when async. |
| Pre-commit | **pre-commit** | ruff + ty + fast unit tests before every commit. |

**ty vs mypy:** ty uses `# ty: ignore[<rule>]` (not mypy's `# type: ignore[<rule>]`). Only
suppress a genuine static-vs-runtime gap (e.g. pydantic-settings env-populated fields,
str→`HttpUrl` coercion); never to hide a real bug. If a suppression would mask logic, fix the
code instead.

### Code & structure
TBD

### Tests (always)
- A **`tests/unit/`** tier always exists: fast, no I/O, no DB. This is the TDD inner loop.
- Shared fixtures in `tests/conftest.py`. Any test DB is separate from dev/prod; never touch
  dev/prod data.
- To close a coverage gap, add a *meaningful* test for the uncovered production path — don't
  lower the gate or write no-op tests.

### Git & commits
- Branch for feature work (don't commit straight to `main`/`master`); commit/push only when
  asked.
- **Conventional Commits:** `feat:`, `fix:`, `chore:`, `test:`, `refactor:`, `docs:`. One
  logical change per commit; keep them small and working.
- Don't commit secrets or `.env`. `.gitignore` covers `.venv/`, `__pycache__/`,
  `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `.env`.

### Workflow (how to approach a task)
1. **Spec first** for new features/behavior: agree on a short design before coding.
2. **Plan** non-trivial work into small, ordered, independently-testable steps.
3. **Implement test-first**, one step at a time, committing as you go.
4. **Verify** the quality gates green, then state results plainly with evidence.
---

## Commands

> These assume the standard scaffold exists. In a fresh repo, only `uv sync` / `uv add` work
> until the package, tests, and config are created; the test/coverage/pre-commit commands come
> online once those are scaffolded.

```bash
uv sync                                      # install deps + dev deps, create .venv
uv add <pkg> / uv add --dev <pkg>            # add a runtime / dev dependency
uv run pytest                                # full suite (enforces coverage gate, if configured)
uv run pytest tests/unit -q --no-cov         # fast inner loop (no DB, no coverage gate)
uv run pytest path::test_name -v --no-cov    # one test
uv run ruff check . / uv run ruff check --fix .   # lint / lint+autofix
uv run ruff format .                         # format
uv run ty check                              # type check
uv run pre-commit run --all-files            # everything pre-commit runs
```

**Gates before claiming done** (once configured): `pytest` (with coverage), `ruff check`,
`ruff format --check`, `ty check`. Don't assert "passing" without running them.
