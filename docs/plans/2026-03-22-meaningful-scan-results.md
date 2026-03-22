# Meaningful Scan Results Implementation Plan

Created: 2026-03-22
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Make scanner results actionable for LocalStack developers by fixing deployer bugs (CDK bootstrap, Terraform error capture, SAM/CFN config), adding failure classification via LocalStack log analysis, and improving reports to show root-cause categories.

**Architecture:** Add a `FailureCategory` enum and a `FailureClassifier` that queries LocalStack container logs after each failure to classify errors as LocalStack bugs vs deployer/sample issues. Fix deployer environment setup (AWS_DEFAULT_REGION, error capture). Update report templates to show classification breakdown and skipped counts.

**Tech Stack:** Python 3.12, Click, Jinja2, requests (LocalStack log API), existing deployer infrastructure.

## Scope

### In Scope
- Fix Terraform deployer: capture stdout when stderr is empty
- Fix CDK deployer: set AWS_DEFAULT_REGION, improve bootstrap error handling
- Fix SAM deployer: set --region, handle --resolve-s3 conflicts
- Fix CFN deployer: search subdirectories for templates
- Add FailureCategory enum and failure_category field to DeployResult
- Add FailureClassifier that queries LocalStack logs post-failure
- Update orchestrator to classify failures after each deploy
- Update report templates: show skipped count in index, add failure category column, add category breakdown section
- Update trends.json to track failure categories over time

### Out of Scope
- Pulumi deployer fixes (only 1 sample in registry)
- Serverless/Azure deployer changes
- UI/UX redesign of reports beyond adding classification data
- Changing GitHub Code Search queries or discovery logic

## Context for Implementer

> The scanner discovers IaC sample repos from GitHub orgs, clones each, and deploys against a LocalStack Pro instance. Results are stored in `data/results/<date>.json` and HTML reports deployed to GitHub Pages.

- **Patterns to follow:** All deployers inherit from `Deployer` ABC in `src/scanner/deployer/base.py`. Each implements `prepare()`, `deploy()`, `cleanup()`. The orchestrator in `src/scanner/runner/orchestrator.py:60-183` loops through samples, calling deployer methods.
- **Conventions:** `DeployResult` dataclass in `src/scanner/models.py:80-129` holds per-sample results. Status is `DeployStatus` enum. Use `subprocess.run()` with `capture_output=True, text=True`.
- **Key files:**
  - `src/scanner/models.py` — DeployResult, DeployStatus, ScanReport
  - `src/scanner/deployer/terraform.py` — TerraformDeployer (stderr bug)
  - `src/scanner/deployer/cdk.py` — CdkDeployer (bootstrap fails)
  - `src/scanner/deployer/sam.py` — SamDeployer (build/deploy flags)
  - `src/scanner/deployer/cloudformation.py` — CloudFormationDeployer (template search)
  - `src/scanner/runner/orchestrator.py` — ScanOrchestrator (main loop)
  - `src/scanner/runner/localstack.py` — LocalStackManager (has `get_logs()`)
  - `src/scanner/report/generator.py` — ReportGenerator
  - `src/scanner/report/trends.py` — TrendTracker
  - `src/scanner/report/templates/index.html` — index page (missing skipped)
  - `src/scanner/report/templates/report.html` — report page
- **Gotchas:**
  - `tflocal apply` writes errors to stdout, NOT stderr — this is why all 51 TF failures show "Non-zero exit code" with empty stderr
  - `cdklocal bootstrap` needs `AWS_DEFAULT_REGION` set — without it, all 487 CDK samples are skipped
  - `samlocal deploy --resolve-s3` conflicts with `--s3-bucket` in some samconfig.toml files
  - CFN `_find_template()` only checks root dir — 164 repos have templates in subdirectories
  - `LocalStackManager.get_logs()` exists but is only used in non-external mode; in CI (external mode) we need to fetch logs via the LocalStack API endpoint `/_localstack/diagnose` or docker logs
  - The orchestrator already has access to `ls_manager` — pass it to the classifier
- **Domain context:** For LocalStack developers, the key question is: "Did this fail because of a LocalStack bug, or because the sample/deployer is broken?" The classifier answers this primarily by pattern-matching deployer stdout/stderr output for definitive patterns like `not yet implemented`, `UnsupportedOperation`. Ambiguous patterns like `InternalError`/`ServiceException` are left as NOT_CLASSIFIED to avoid misleading developers. LocalStack's `/diagnose` endpoint provides supplementary signals only.

## Progress Tracking

- [x] Task 1: Add FailureCategory enum and update DeployResult
- [x] Task 2: Fix Terraform deployer error capture
- [x] Task 3: Fix CDK deployer bootstrap
- [x] Task 4: Fix SAM deployer environment and flags
- [x] Task 5: Fix CFN deployer template search
- [x] Task 6: Add FailureClassifier with LocalStack log analysis
- [x] Task 7: Integrate classifier into orchestrator
- [x] Task 8: Update report templates with classification
- [x] Task 9: Update trends tracking with failure categories

**Total Tasks:** 9 | **Completed:** 9 | **Remaining:** 0

## Implementation Tasks

### Task 1: Add FailureCategory enum and update DeployResult

**Objective:** Add a `FailureCategory` enum to classify failures and add a `failure_category` field to `DeployResult`.
**Dependencies:** None

**Files:**
- Modify: `src/scanner/models.py`
- Test: `tests/test_models.py`

**Key Decisions / Notes:**
- Add enum: `FailureCategory` with values: `LOCALSTACK_BUG` (LS returned unsupported/internal error), `DEPLOYER_ERROR` (tooling/env issue), `SAMPLE_ERROR` (sample-specific config issue), `TIMEOUT`, `NOT_CLASSIFIED` (default for failures not yet classified)
- Add `failure_category: FailureCategory | None = None` to `DeployResult` — None for SUCCESS/SKIPPED
- Update `to_dict()` and `from_dict()` to handle the new field
- Backward compatible: `from_dict()` defaults to None if field missing in old JSON

**Definition of Done:**
- [ ] `FailureCategory` enum exists with 5 values
- [ ] `DeployResult` has `failure_category` field
- [ ] Serialization round-trips correctly
- [ ] Old JSON without `failure_category` loads without error

**Verify:**
```bash
uv run pytest tests/test_models.py -q
```

---

### Task 2: Fix Terraform deployer error capture

**Objective:** Fix the Terraform deployer to capture error output from stdout when stderr is empty, making failure reasons visible.
**Dependencies:** Task 1

**Files:**
- Modify: `src/scanner/deployer/terraform.py`
- Test: `tests/test_deployer_terraform.py`

**Key Decisions / Notes:**
- In `deploy()`, when `result.returncode != 0`: use `result.stdout` as `error_message` if `result.stderr` is empty. `tflocal apply` writes error diagnostics to stdout.
- Also apply the same fix to `prepare()` — capture stdout for init failures
- Pattern: `error_message = result.stderr.strip() or result.stdout.strip() or "Non-zero exit code"`
- Same pattern should be applied in all deployers for consistency, but focus on Terraform here since it's the most impactful (201 successes, 65 failures — highest volume)

**Definition of Done:**
- [ ] Terraform failures include actual error text, not just "Non-zero exit code"
- [ ] When stderr has content, stderr is used (not stdout)
- [ ] When both are empty, falls back to "Non-zero exit code"

**Verify:**
```bash
uv run pytest tests/test_deployer_terraform.py -q
```

---

### Task 3: Fix CDK deployer bootstrap

**Objective:** Fix CDK bootstrap to succeed by setting required environment variables and improving error handling.
**Dependencies:** Task 1

**Files:**
- Modify: `src/scanner/deployer/cdk.py`
- Modify: `src/scanner/runner/orchestrator.py` (bootstrap error handling)
- Test: `tests/test_deployer_cdk.py`

**Key Decisions / Notes:**
- `cdklocal bootstrap` needs the following env vars: `AWS_DEFAULT_REGION=us-east-1`, `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`, `CDK_DEFAULT_ACCOUNT=000000000000`, `CDK_DEFAULT_REGION=us-east-1`. Without CDK_DEFAULT_ACCOUNT/CDK_DEFAULT_REGION, CDK fails with "Unable to resolve account".
- Build a shared env dict and apply it to ALL `cdklocal` subprocess calls: `bootstrap()`, `deploy()`, and any subprocess in `prepare()` that calls cdklocal.
- Change orchestrator: when bootstrap fails, set status to `FAILURE` with `failure_category=DEPLOYER_ERROR` instead of `SKIPPED`. This surfaces the error in reports instead of hiding it.
- Capture bootstrap stderr/stdout in the error message for diagnostics.

**Definition of Done:**
- [ ] CDK bootstrap subprocess receives AWS_DEFAULT_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, CDK_DEFAULT_ACCOUNT, CDK_DEFAULT_REGION
- [ ] CDK deploy subprocess receives the same env vars
- [ ] Bootstrap failure results in FAILURE+DEPLOYER_ERROR, not SKIPPED
- [ ] Bootstrap error output is captured in error_message

**Verify:**
```bash
uv run pytest tests/test_deployer_cdk.py -q
```

---

### Task 4: Fix SAM deployer environment and flags

**Objective:** Fix SAM deployer to handle region resolution and flag conflicts that cause 95% failure rate.
**Dependencies:** Task 1

**Files:**
- Modify: `src/scanner/deployer/sam.py`
- Test: `tests/test_deployer_sam.py`

**Key Decisions / Notes:**
- Add `--region us-east-1` to both `samlocal build` and `samlocal deploy` commands — fixes "Unable to resolve a region" errors (5 samples)
- **S3 bucket strategy:** Before adding `--s3-bucket`, check whether `samconfig.toml` (if present) already specifies `s3_bucket`. If it does, create the bucket named in the config (not a hardcoded name) and do NOT pass `--s3-bucket` CLI flag (avoids duplicate argument conflict). If no samconfig.toml or no `s3_bucket` in it, use `--s3-bucket localstack-deployments` and create that bucket in prepare().
- Remove `--resolve-s3` entirely — do NOT use it as a fallback since it reintroduces the original conflict.
- Add `env={**os.environ, "AWS_DEFAULT_REGION": "us-east-1"}` to subprocess calls
- For prepare failures: capture stdout+stderr in a way the orchestrator can log (currently prepare() only returns bool — can't change the interface, but the deployer can log the error)

**Definition of Done:**
- [ ] SAM deploy command includes `--region us-east-1`
- [ ] SAM deploy uses `--s3-bucket` only when samconfig.toml doesn't already specify s3_bucket
- [ ] S3 deployment bucket is created in prepare() (name from samconfig.toml or default)
- [ ] `--resolve-s3` is not used anywhere
- [ ] Environment variables set for subprocess calls

**Verify:**
```bash
uv run pytest tests/test_deployer_sam.py -q
```

---

### Task 5: Fix CFN deployer template search

**Objective:** Search subdirectories for CloudFormation templates, reducing the 164 "No template found" unsupported results.
**Dependencies:** None

**Files:**
- Modify: `src/scanner/deployer/cloudformation.py`
- Test: `tests/test_deployer_cloudformation.py`

**Key Decisions / Notes:**
- Modify `_find_template()`: first check root directory (current behavior). If not found, search one level deep in subdirectories. Use first match found.
- Search pattern: `sample_dir / "*" / template_name` for each template name
- Limit depth to 1 level to avoid accidentally finding nested/example templates
- If multiple subdirs have templates, pick the first alphabetically (deterministic)

**Definition of Done:**
- [ ] Templates found in root dir are still used (no regression)
- [ ] Templates in immediate subdirectories are discovered
- [ ] Search doesn't recurse deeper than 1 level

**Verify:**
```bash
uv run pytest tests/test_deployer_cloudformation.py -q
```

---

### Task 6: Add FailureClassifier with LocalStack log analysis

**Objective:** Create a classifier that queries LocalStack logs after each failure and categorizes the root cause.
**Dependencies:** Task 1

**Files:**
- Create: `src/scanner/classifier.py`
- Test: `tests/test_classifier.py`

**Key Decisions / Notes:**
- Class `FailureClassifier` with method `classify(result: DeployResult, ls_endpoint: str) -> FailureCategory`
- **PRIMARY classification path:** Pattern matching against `result.error_message` (which contains stdout+stderr from deployer output). This is the main signal because deployer output always captures the actual error.
- **SUPPLEMENTARY path:** After pattern matching, optionally query `GET {ls_endpoint}/_localstack/diagnose` for additional LocalStack-side signals not visible in deployer output (e.g., internal LS errors not propagated to the caller). The `/diagnose` endpoint may not contain per-request error logs in grep-able form — treat it as a bonus signal, not the primary source.
- **Conservative LOCALSTACK_BUG patterns** (only definitive LS-at-fault indicators):
  - `not yet implemented`, `not implemented`, `UnsupportedOperation`
  - `NotImplementedError`, `501`
- **Ambiguous patterns → NOT_CLASSIFIED** (not LOCALSTACK_BUG): `InternalError`, `InternalFailure`, `ServiceException` — these can originate from sample config errors too, not just LocalStack bugs. Classifying them as LOCALSTACK_BUG would mislead developers.
- **Error message patterns → DEPLOYER_ERROR:**
  - `prepare() failed`, `bootstrap failed`, `timed out after`
  - `command not found`, `No such file`
- **Error message patterns → SAMPLE_ERROR:**
  - `config profile`, `ParameterValue`, `must have values`
  - `resolve-s3`, `Unable to upload artifact`
- If timeout status → `TIMEOUT`
- If no pattern matches → `NOT_CLASSIFIED`
- The classifier is stateless — takes a result and endpoint, returns a category

**Definition of Done:**
- [ ] FailureClassifier.classify() returns correct category for known error patterns
- [ ] Pattern matching against error_message is the primary classification path
- [ ] LocalStack log fetching (supplementary) handles connection errors gracefully
- [ ] Ambiguous patterns (InternalError, ServiceException) are NOT classified as LOCALSTACK_BUG
- [ ] Timeout results are classified as TIMEOUT

**Verify:**
```bash
uv run pytest tests/test_classifier.py -q
```

---

### Task 7: Integrate classifier into orchestrator

**Objective:** Call the classifier after each failed deployment in the scan loop and store the category in DeployResult.
**Dependencies:** Task 6

**Files:**
- Modify: `src/scanner/runner/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Key Decisions / Notes:**
- Import `FailureClassifier` in orchestrator
- After each deployment that results in FAILURE, TIMEOUT, or UNSUPPORTED status, call `classifier.classify(result, config.localstack_endpoint)`
- Set `result.failure_category = category`
- The classifier call should be wrapped in try/except — classification failure should never crash the scan
- Pass `config.localstack_endpoint` to the classifier (it needs the LS endpoint to fetch logs)
- For SKIPPED results (which we're changing to FAILURE+DEPLOYER_ERROR in Task 3), classification runs too

**Definition of Done:**
- [ ] Every non-SUCCESS result has a failure_category set
- [ ] Classifier errors don't crash the scan loop
- [ ] Category is visible in the results JSON output

**Verify:**
```bash
uv run pytest tests/test_orchestrator.py -q
```

---

### Task 8: Update report templates with classification

**Objective:** Show failure categories in the HTML report and add skipped count to the index page.
**Dependencies:** Task 1

**Files:**
- Modify: `src/scanner/report/templates/index.html`
- Modify: `src/scanner/report/templates/report.html`
- Modify: `src/scanner/report/generator.py` (pass category counts to template)
- Test: `tests/test_report.py`

**Key Decisions / Notes:**
- **Index page (`index.html`):** Add `{{ latest.skipped }} skipped` to the summary line. For category breakdown on the index page, use `{{ latest.by_failure_category }}` — this is a dict key from trends.json, NOT a ScanReport property (index.html receives a plain dict via `TrendTracker.generate_index()`, not a ScanReport).
- **Report page (`report.html`):**
  - Add "Failure Category" column to the results table (after Status column)
  - Add a summary section at the top: "Failure Breakdown" showing counts per category (LOCALSTACK_BUG: N, DEPLOYER_ERROR: N, SAMPLE_ERROR: N, etc.)
  - Add CSS badge styles for each category: `.badge-localstack-bug { background: #d32f2f; }`, `.badge-deployer-error { background: #f57c00; }`, `.badge-sample-error { background: #7b1fa2; }`
  - report.html receives the full `ScanReport` object — use `report.category_counts` here
- Add a `category_counts` property to `ScanReport` that returns a dict of category → count. This property is used ONLY in `report.html` (which gets ScanReport). The `index.html` template uses `latest.by_failure_category` from trends.json instead.

**Definition of Done:**
- [ ] Index page shows skipped count
- [ ] Index page shows category breakdown via `{{ latest.by_failure_category }}` dict key
- [ ] Report table has Failure Category column (using `report.category_counts`)
- [ ] Report has failure breakdown summary section
- [ ] Categories displayed with colored badges

**Verify:**
```bash
uv run pytest tests/test_report.py -q
```

---

### Task 9: Update trends tracking with failure categories

**Objective:** Track failure category breakdown in trends.json for historical analysis.
**Dependencies:** Task 1, Task 8

**Files:**
- Modify: `src/scanner/report/trends.py`
- Test: `tests/test_trends.py`

**Key Decisions / Notes:**
- Add `by_failure_category` dict to trend entries: `{"LOCALSTACK_BUG": 5, "DEPLOYER_ERROR": 10, ...}`
- Update `_build_entry()` to count failure categories from results
- Update `get_chart_data()` to include a second dataset for category trends (optional — can be added to Chart.js later)
- Backward compatible: old entries without `by_failure_category` are handled gracefully

**Definition of Done:**
- [ ] trends.json entries include by_failure_category breakdown
- [ ] Old trends entries load without errors
- [ ] Category counts match actual result counts

**Verify:**
```bash
uv run pytest tests/test_trends.py -q
```

## Testing Strategy

- **Unit tests:** Each task has dedicated test file. Mock subprocess calls in deployer tests. Mock HTTP requests for classifier tests. Mock filesystem for report tests.
- **Integration check:** After all tasks, run `uv run pytest -q --cov=src --cov-fail-under=80`
- **Manual verification:** Trigger a CI run with reduced scope (`--limit 10`) to verify end-to-end: error capture, classification, and report generation.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LocalStack `/diagnose` endpoint not available in external mode | Medium | Classifier can't fetch logs | Fall back to error message pattern matching when log fetch fails |
| CDK bootstrap still fails after env fix | Medium | 487 samples remain unscanned | Mark as DEPLOYER_ERROR instead of SKIPPED so it's visible; log detailed error for debugging |
| SAM S3 bucket creation fails | Low | SAM deploys still fail at upload | Create bucket in prepare() with error handling; if creation fails, proceed without --s3-bucket — deploy will fail with a clear S3 error (more actionable than silent --resolve-s3 conflict) |
| CFN subdirectory search finds wrong template | Low | Deploys wrong template | Limit search to 1 level deep; prefer root dir templates |
| New failure_category field breaks old result parsing | Low | Crashes on old data | Default to None in from_dict(); handle gracefully in templates |

## Goal Verification

### Truths
1. Terraform failures include actual error text from stdout (not just "Non-zero exit code")
2. CDK samples attempt deployment with proper AWS env vars instead of being 100% skipped
3. SAM deployer passes --region and handles S3 bucket setup
4. CFN deployer finds templates in immediate subdirectories
5. Every non-SUCCESS result has a failure_category classification
6. The HTML report shows failure category breakdown (LOCALSTACK_BUG vs DEPLOYER_ERROR vs SAMPLE_ERROR)
7. The index page shows skipped count in the summary line

### Artifacts
1. `src/scanner/models.py` — FailureCategory enum + updated DeployResult
2. `src/scanner/classifier.py` — FailureClassifier with log analysis
3. `src/scanner/deployer/terraform.py` — stdout error capture
4. `src/scanner/deployer/cdk.py` — env vars + better bootstrap
5. `src/scanner/deployer/sam.py` — region + S3 bucket fixes
6. `src/scanner/deployer/cloudformation.py` — subdirectory template search
7. `src/scanner/runner/orchestrator.py` — classifier integration
8. `src/scanner/report/templates/report.html` — category column + breakdown
9. `src/scanner/report/templates/index.html` — skipped count

### Key Links
1. `FailureCategory` enum (models.py) → `FailureClassifier` (classifier.py) → `ScanOrchestrator` (orchestrator.py) — classification pipeline
2. `DeployResult.failure_category` (models.py) → `report.html` template — display pipeline
3. `_build_entry()` (trends.py) → `by_failure_category` → `index.html` — trend tracking pipeline
4. `LocalStackManager` endpoint (localstack.py) → `FailureClassifier` log fetch — log analysis dependency

## Open Questions

None — all decisions made.
