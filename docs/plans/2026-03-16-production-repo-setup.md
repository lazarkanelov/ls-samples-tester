# Production Repository Setup Implementation Plan

Created: 2026-03-16
Status: PENDING
Approved: Yes
Iterations: 1
Worktree: No
Type: Feature

## Summary

**Goal:** Turn the existing localstack-sample-tester project into a production-ready, standalone GitHub repository with proper git setup, CI fixes, pre-commit hooks, documentation, and an environment setup guide — then push to `github.com/lazarkanelov/localstack-sample-tester`.

**Architecture:** No architectural changes to the scanner itself. This is purely infrastructure/config work: git initialization, .gitignore, CI path fixes, pre-commit hooks, README with setup guide, and repo creation via `gh` CLI.

**Tech Stack:** git, gh CLI, pre-commit, ruff 0.15.2, GitHub Actions

## Scope

### In Scope
- Git init with comprehensive .gitignore
- Fix CI workflow `working-directory` paths (standalone repo)
- Fix CI commit step operator precedence bug
- Pre-commit hooks (ruff format + check)
- README.md with project overview, usage, architecture
- .env.example with all required environment variables
- GitHub environment setup guide (Secrets, Pages, branch protection)
- Create public repo on GitHub and push

### Out of Scope
- LICENSE file (user chose to skip)
- Dependabot config (not selected)
- Code changes to the scanner itself
- Actual environment variable values (user configures those)

## Context for Implementer

> The project is a Python 3.12+ CLI tool built with Click. It scans GitHub orgs for IaC sample apps and deploys them against LocalStack. No git repo exists yet — it's a bare directory.

- **Patterns to follow:** CI is in `.github/workflows/weekly-scan.yml` — currently has `working-directory: localstack-sample-tester` on several steps, which needs removal
- **Conventions:** Uses `uv` for package management, `ruff` for linting/formatting, `pytest` for tests
- **Key files:**
  - `pyproject.toml` — project config, no ruff section yet
  - `.github/workflows/weekly-scan.yml` — weekly scan pipeline with `working-directory` issues
  - `src/scanner/cli.py` — entry point, CLI commands: `discover`, `scan`, `report`, `run`
- **Gotchas:**
  - `data/` directory is created at runtime and committed back by CI — **must NOT be in .gitignore**. Add `data/.gitkeep` to track the directory structure. CI runs `git add data/` to persist scan results, registry, and trend data.
  - `reports/` is generated at runtime and deployed to GitHub Pages — add to .gitignore
  - `.claude/` directory should be gitignored (user's choice for public repo)
  - The CI workflow references `localstack-sample-tester` as a subdirectory in **4 steps** plus 1 path reference — all need fixing
  - The CI commit step has an operator precedence bug: `|| A && B` is parsed as `(|| A) && B` — fix with parentheses
  - `gh` CLI is not installed in WSL — needs installation first
- **Domain context:** The scanner requires `GITHUB_TOKEN` and `LOCALSTACK_AUTH_TOKEN` as secrets in GitHub Actions. `PULUMI_CONFIG_PASSPHRASE` is set inline in the workflow (not a real secret).

## Progress Tracking

- [x] Task 1: Git init + .gitignore
- [x] Task 2: Fix CI workflow paths + commit step bug
- [x] Task 3: Pre-commit hooks
- [x] Task 4: .env.example + ruff config
- [x] Task 5: README.md with setup guide
- [x] Task 6: Create GitHub repo and push

**Total Tasks:** 6 | **Completed:** 6 | **Remaining:** 0

## Implementation Tasks

### Task 1: Git init + .gitignore

**Objective:** Initialize the git repository and create a comprehensive .gitignore for Python/this project.
**Dependencies:** None

**Files:**
- Create: `.gitignore`
- Create: `data/.gitkeep`
- Run: `git init`

**Key Decisions / Notes:**
- .gitignore must cover: `__pycache__/`, `*.pyc`, `.venv/`, `.env`, `.coverage`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`, `build/`, `reports/` (generated HTML), `.claude/` (AI instructions — user chose to exclude from public repo)
- **Do NOT gitignore `data/`** — CI commits `data/` back to the repo (registry.json, results/, trends.json). Add `data/.gitkeep` so the directory structure is visible on clone.
- Include IDE patterns: `.idea/`, `.vscode/`, `*.swp`
- `uv.lock` should be committed (lock file)
- `docs/plans/` should be committed (spec plans)

**Definition of Done:**
- [ ] `git init` succeeds
- [ ] `.gitignore` exists with Python + project-specific patterns
- [ ] `data/.gitkeep` exists
- [ ] `git status` does not show `__pycache__/`, `.venv/`, `.coverage`, `.ruff_cache/`, `.pytest_cache/`, `.claude/`
- [ ] `git status` DOES show `data/.gitkeep` (not ignored)

**Verify:**
```bash
git status
git check-ignore data/.gitkeep  # should return nothing (not ignored)
```

---

### Task 2: Fix CI workflow paths + commit step bug

**Objective:** Remove `working-directory: localstack-sample-tester` from the weekly-scan.yml so it works as a standalone repo, and fix the operator precedence bug in the commit step.
**Dependencies:** None

**Files:**
- Modify: `.github/workflows/weekly-scan.yml`

**Key Decisions / Notes:**
- **Four steps** have `working-directory: localstack-sample-tester`: "Install project dependencies" (line 54), "Install IaC wrapper tools" (line 58), "Run full scan pipeline" (line 86), "Commit data changes" (line 90). Remove `working-directory` from all four.
- The "Upload Pages artifact" step has `path: localstack-sample-tester/reports/` — change to `path: reports/`
- Fix the commit step shell logic: change `git diff --staged --quiet || git commit -m "..." && git push` to `git diff --staged --quiet || (git commit -m "..." && git push)` — parentheses make intent explicit and prevent `git push` from running when nothing is staged.

**Definition of Done:**
- [ ] No `localstack-sample-tester` references remain in the workflow file
- [ ] YAML is valid
- [ ] All 4 `working-directory` lines for the scanner subdirectory are removed
- [ ] Commit step uses proper grouping: `|| (git commit ... && git push)`

**Verify:**
```bash
grep -c "localstack-sample-tester" .github/workflows/weekly-scan.yml  # should be 0
grep "|| (" .github/workflows/weekly-scan.yml  # should match the commit step
```

---

### Task 3: Pre-commit hooks

**Objective:** Add pre-commit configuration with ruff format and lint hooks.
**Dependencies:** None

**Files:**
- Create: `.pre-commit-config.yaml`

**Key Decisions / Notes:**
- Use `astral-sh/ruff-pre-commit` mirror for fast native hooks
- Two hooks: `ruff-format` (formatter) and `ruff` (linter with `--fix`)
- Pin to ruff v0.15.2 (verified installed version via `ruff --version` = 0.15.2)
- Don't add pre-commit to dev dependencies — it's installed globally by the developer

**Definition of Done:**
- [ ] `.pre-commit-config.yaml` exists with ruff format + check hooks
- [ ] File is valid YAML

**Verify:**
```bash
uv run python -c "from ruamel.yaml import YAML; YAML().load(open('.pre-commit-config.yaml'))"
```

---

### Task 4: .env.example + ruff config

**Objective:** Create an .env.example template and add ruff configuration to pyproject.toml.
**Dependencies:** None

**Files:**
- Create: `.env.example`
- Modify: `pyproject.toml`

**Key Decisions / Notes:**
- `.env.example` lists all env vars with placeholder comments: `GITHUB_TOKEN`, `LOCALSTACK_AUTH_TOKEN`, `PULUMI_CONFIG_PASSPHRASE`
- Add `[tool.ruff]` section to `pyproject.toml`: target Python 3.12, line-length 100, select sensible rule sets (E, F, I, UP, B)
- Add `ruff` to the dev dependency group so the version is tracked: `uv add --dev ruff`

**Definition of Done:**
- [ ] `.env.example` exists with all 3 env vars documented
- [ ] `pyproject.toml` has `[tool.ruff]` section
- [ ] `ruff` is in dev dependencies
- [ ] `uv run ruff check .` still passes with new config

**Verify:**
```bash
uv run ruff check . && echo "OK"
```

---

### Task 5: README.md with setup guide

**Objective:** Create a comprehensive README covering project overview, setup, usage, CI, and production configuration guide.
**Dependencies:** Task 2 (CI paths fixed — README references correct commands)

**Files:**
- Create: `README.md`

**Key Decisions / Notes:**
- Sections: Overview, Features, Prerequisites, Quick Start, CLI Commands, Environment Variables (table), CI/CD (how the workflow runs), GitHub Production Setup (Secrets, Pages, Branch Protection), Architecture, Contributing
- The "GitHub Production Setup" section documents:
  - Required GitHub Secrets (LOCALSTACK_AUTH_TOKEN)
  - GitHub Pages configuration (source: GitHub Actions)
  - Recommended branch protection rules (require PR reviews, require status checks, no force push to main)
- Keep it factual, no badges yet (can add after first CI run)
- data/ directory note: populated by first CI run, data/.gitkeep included for directory structure

**Definition of Done:**
- [ ] `README.md` exists with all required sections
- [ ] Environment variables table lists all 3 vars with descriptions
- [ ] GitHub Production Setup section documents secrets, Pages, and branch protection
- [ ] CLI commands match actual Click commands (discover, scan, report, run)

**Verify:**
```bash
# Check required top-level sections present
for section in "Overview" "Prerequisites" "Quick Start" "CLI Commands" "Environment Variables" "CI/CD" "GitHub Production Setup" "Architecture"; do
  grep -q "^## $section" README.md && echo "OK: $section" || echo "MISSING: $section"
done
```

---

### Task 6: Create GitHub repo and push

**Objective:** Install `gh` CLI, create the public repo, and push all code.
**Dependencies:** Tasks 1-5 (all files ready before push)

**Files:**
- No new files — uses `gh` CLI and git commands

**Key Decisions / Notes:**
- Install `gh` via apt (Ubuntu/WSL): `sudo apt install gh` or via official instructions
- For auth: set `GH_TOKEN` environment variable (non-interactive), or run `echo <token> | gh auth login --with-token`. `gh repo create` respects `GH_TOKEN` directly.
- `gh repo create lazarkanelov/localstack-sample-tester --public --source=. --push`
- Initial commit message: "Initial commit: LocalStack sample tester"
- User will configure secrets and Pages after push

**Definition of Done:**
- [ ] `gh` CLI installed and authenticated
- [ ] Repo exists at `github.com/lazarkanelov/localstack-sample-tester`
- [ ] All code pushed to `main` branch
- [ ] `git log` shows the initial commit

**Verify:**
```bash
gh repo view lazarkanelov/localstack-sample-tester --json name,visibility
```

## Testing Strategy

- **No unit tests needed** — this task creates no production code
- **Verification:** Each task has a concrete verify step (git status, grep, ruff check, gh repo view)
- **Integration check:** After push, verify repo is accessible and files are present

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `gh` CLI installation fails in WSL | Low | Blocks Task 6 | Fall back to manual `git remote add origin` + `git push -u origin main` |
| `gh` auth requires browser on WSL | Medium | Blocks Task 6 | Set `GH_TOKEN` env var: `export GH_TOKEN=<token>` then `gh auth status` to verify. Or: `echo <token> \| gh auth login --with-token` |
| Ruff config changes cause lint failures | Low | Medium | Run `ruff check .` after adding config, fix any new violations |
| CI workflow still references wrong paths | Low | High | Grep for `localstack-sample-tester` after edit to confirm zero matches |

## Goal Verification

### Truths
1. A public GitHub repo exists at `github.com/lazarkanelov/localstack-sample-tester`
2. The repo has a clean `.gitignore` that excludes `__pycache__/`, `.venv/`, `.coverage`, `.claude/`, `reports/` but NOT `data/`
3. The CI workflow runs from repo root (no `working-directory` subdirectory references)
4. The CI commit step uses correct operator grouping
5. Pre-commit hooks enforce ruff formatting and linting
6. README documents all environment variables, GitHub Secrets, Pages config, and branch protection rules
7. `.env.example` provides a template for local development

### Artifacts
1. `.gitignore` — git ignore rules
2. `data/.gitkeep` — directory placeholder for CI-committed scan data
3. `.github/workflows/weekly-scan.yml` — fixed CI workflow
4. `.pre-commit-config.yaml` — pre-commit hooks
5. `.env.example` — environment variable template
6. `README.md` — project documentation with setup guide
7. `pyproject.toml` — ruff config section added

### Key Links
1. `pyproject.toml` [tool.ruff] → `.pre-commit-config.yaml` ruff hooks (same version)
2. `.env.example` vars → `README.md` environment variables table (same vars documented)
3. `.github/workflows/weekly-scan.yml` secrets → `README.md` GitHub Secrets section (same secrets documented)
4. `README.md` CLI commands → `src/scanner/cli.py` Click commands (must match)

## Open Questions

None — all decisions made.
