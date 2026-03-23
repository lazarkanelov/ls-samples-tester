# Scanner Improvements for LocalStack Engineers

Created: 2026-03-23
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Make the scanner significantly more useful for LocalStack core engineers by fixing broken deployers, extracting AWS service usage from IaC files, improving failure classification, capturing LocalStack logs, broadening resource verification, adding retry logic, and building richer trend reports with regression detection.

**Architecture:** Static IaC file parsing extracts AWS service names pre-deploy. Post-deploy log snapshots from LocalStack container aid debugging. Expanded failure classifier patterns reduce NOT_CLASSIFIED rate. Regression detection compares consecutive trend entries on the index page.

**Tech Stack:** Python 3.12, Click CLI, Jinja2 templates, Chart.js, Docker API, subprocess (awslocal)

## Scope

### In Scope
- Fix CDK deployer (100% failure rate due to bootstrap issue)
- AWS service extraction from Terraform/CDK/CFN files (populate `services_used`)
- Expanded failure classification patterns + LocalStack log analysis
- LocalStack container log capture per sample
- Broader resource verification (SQS, SNS, DynamoDB, Step Functions, EventBridge)
- Retry logic for transient failures + adaptive timeouts
- Richer trend charts (partial, per-IaC, failure categories, regressions)
- Service-level dashboard in reports

### Out of Scope
- Azure Bicep/ARM deployer improvements (378 UNSUPPORTED — separate initiative)
- JSON/CSV machine-readable export (deferred)
- Slack/Jira integration
- Pulumi/Serverless deployer fixes (only 14 samples total)
- UI redesign (keep current HTML template approach)

## Context for Implementer

> Write for an implementer who has never seen the codebase.

- **Patterns to follow:**
  - Deployers: subclass `Deployer` ABC from `src/scanner/deployer/base.py:10` — implement `prepare()`, `deploy()`, `cleanup()`
  - Tests: see `tests/test_deployer_tf.py` for mock subprocess patterns
  - CLI: Click commands in `src/scanner/cli.py`, config in `src/scanner/config.py`
  - Templates: Jinja2 HTML in `src/scanner/report/templates/`
  - Trend data: `TrendTracker` in `src/scanner/report/trends.py` manages `data/trends.json`

- **Conventions:**
  - `DeployResult` carries all per-sample data (`src/scanner/models.py:90`)
  - Failure classification happens post-deploy in `_classify_result()` (`src/scanner/runner/orchestrator.py:60`)
  - Verification happens post-deploy for SUCCESS samples in `_verify_sample()` (`src/scanner/runner/orchestrator.py:74`)
  - All subprocess calls should use `timeout` parameter
  - ANSI codes appear in deployer output — strip when classifying

- **Key files:**
  - `src/scanner/runner/orchestrator.py` — main scan loop, classification, verification
  - `src/scanner/models.py` — `DeployResult`, `ScanReport`, `DeployStatus`, `FailureCategory`
  - `src/scanner/config.py` — `Config` dataclass, `IaCType` enum
  - `src/scanner/classifier.py` — `FailureClassifier` with pattern lists
  - `src/scanner/verifier.py` — `ResourceVerifier` (Lambda, API GW, S3)
  - `src/scanner/deployer/cdk.py` — CDK deployer (currently broken)
  - `src/scanner/report/trends.py` — `TrendTracker`, Chart.js data, index generation
  - `src/scanner/report/templates/` — `report.html`, `sample_detail.html`, `index.html`

- **Gotchas:**
  - CDK bootstrap fails with "LEGACY EXPORTS" warning that has non-zero exit code — need to handle or suppress
  - `services_used` field exists on `DeployResult` but is always `[]` — no deployer populates it
  - ANSI escape codes in deployer stderr pollute error messages — strip before pattern matching
  - `_LOCALSTACK_BUG_PATTERNS` in classifier is conservative — many LS issues not caught
  - `get_chart_data()` only returns pass/fail/timeout — no partial, no by-IaC breakdown

- **Domain context:**
  - 1,725 samples in registry: 354 Terraform, 489 CDK, 382 Azure Bicep, 340 CFN, 79 SAM, 67 Azure ARM, 13 Serverless, 1 Pulumi
  - Latest full scan: 269 passed, 516 failed, 378 unsupported, 9 partial out of 1,172 scanned
  - 436 CDK samples ALL fail at bootstrap (37% of scanned samples producing zero useful data)
  - 442 failures are NOT_CLASSIFIED — main patterns: missing required variables, provider not found, resource not supported

## Progress Tracking

- [x] Task 1: Fix CDK deployer
- [x] Task 2: AWS service extraction from IaC files
- [x] Task 3: Expand failure classifier
- [x] Task 4: LocalStack log capture
- [x] Task 5: Broaden resource verification
- [x] Task 6: Retry logic and smart timeouts
- [x] Task 7: Richer trend charts and regression detection
- [x] Task 8: Service-level dashboard in reports
- [x] Task 9: Wire everything together in orchestrator

**Total Tasks:** 9 | **Completed:** 9 | **Remaining:** 0

## Implementation Tasks

### Task 1: Fix CDK Deployer

**Objective:** Fix the CDK bootstrap failure that causes 100% failure rate for all 436+ CDK samples. The error is a non-zero exit from `cdklocal bootstrap` due to a "LEGACY EXPORTS" warning.

**Dependencies:** None

**Files:**
- Modify: `src/scanner/deployer/cdk.py`
- Modify: `src/scanner/runner/orchestrator.py` (CDK bootstrap early-exit path at lines 156-179)
- Test: `tests/test_deployer_cdk.py`
- Test: `tests/test_orchestrator.py` (CDK bootstrap fallback tests)

**Key Decisions / Notes:**
- The bootstrap error is actually a WARNING that causes non-zero exit. The fix has two parts:
  1. **In `cdk.py` `bootstrap()`:** When exit code is non-zero and stderr contains "LEGACY EXPORTS", run `awslocal cloudformation describe-stacks --stack-name CDKToolkit` to confirm the stack exists. If it does, return `True` (bootstrap succeeded despite the warning).
  2. **In `orchestrator.py` (lines 156-179):** The orchestrator calls `cdk_deployer.bootstrap()` BEFORE cloning — if it returns `False`, all CDK samples are skipped. Ensure the fixed bootstrap() propagates success correctly so the orchestrator no longer early-exits.
- Alternative: use `--force` flag or set `CDK_NEW_BOOTSTRAP=1` env var to suppress legacy warnings.
- Fix `prepare()`: replace bare `pip install -r requirements.txt` with `uv pip install --system -r requirements.txt` (installs into active Python environment, matching bare pip behavior). The project mandates uv for all Python operations.
- Add `--app` flag support for repos that specify app in `cdk.json` but don't have a default entry point.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] `bootstrap()` returns `True` when subprocess exits non-zero but stderr contains LEGACY EXPORTS warning AND `awslocal cloudformation describe-stacks --stack-name CDKToolkit` confirms stack exists (mocked in tests)
- [ ] `prepare()` uses `uv pip install --system` for Python CDK samples
- [ ] Orchestrator no longer early-exits all CDK samples when bootstrap warning is present

**Verify:**
- `uv run pytest tests/test_deployer_cdk.py -q`

---

### Task 2: AWS Service Extraction from IaC Files

**Objective:** Create a `ServiceExtractor` that parses IaC files (Terraform `.tf`, CDK imports, CloudFormation templates) to identify which AWS services a sample uses. Populate `DeployResult.services_used`.

**Dependencies:** None

**Files:**
- Create: `src/scanner/service_extractor.py`
- Test: `tests/test_service_extractor.py`

**Key Decisions / Notes:**
- **Terraform:** Parse `resource "aws_*"` blocks — extract service from resource type prefix (e.g., `aws_lambda_function` → `Lambda`, `aws_s3_bucket` → `S3`, `aws_dynamodb_table` → `DynamoDB`). Build a mapping dict of ~50 common prefixes.
- **CDK:** Parse Python/TypeScript imports for `aws-cdk-lib/aws-*` or `@aws-cdk/aws-*` patterns.
- **CloudFormation/SAM:** Parse `template.yaml`/`template.json` for `AWS::Service::Resource` type strings.
- Return a deduplicated, sorted `list[str]` of service names (e.g., `["DynamoDB", "Lambda", "S3"]`).
- Call from orchestrator after cloning, before deploy, so service info is available even for failed deploys.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] `ServiceExtractor.extract(sample_dir, iac_type)` returns correct services for Terraform, CDK, and CFN samples
- [ ] At least 10 test cases covering different IaC types and edge cases (no files, mixed resources)

**Verify:**
- `uv run pytest tests/test_service_extractor.py -q`

---

### Task 3: Expand Failure Classifier

**Objective:** Reduce the NOT_CLASSIFIED rate (currently 442/516 failures = 86%) by adding more patterns, stripping ANSI codes, and categorizing common failure modes.

**Dependencies:** None

**Files:**
- Modify: `src/scanner/classifier.py`
- Modify: `src/scanner/models.py` (add new `FailureCategory` values)
- Test: `tests/test_classifier.py`

**Key Decisions / Notes:**
- **New categories:**
  - `MISSING_VARIABLE` — Terraform "No value for required variable" (22 samples in latest scan)
  - `PROVIDER_ERROR` — Terraform provider initialization failures
  - `RESOURCE_NOT_SUPPORTED` — AWS/LS resource type not available
  - `AUTH_ERROR` — credential/permission issues
  - `NETWORK_ERROR` — connection refused, DNS resolution failures
- **ANSI stripping:** Add `_strip_ansi(text)` helper used before all pattern matching.
- **LocalStack /diagnose analysis:** After initial text classification, if NOT_CLASSIFIED, check the existing `/diagnose` HTTP endpoint response for additional error signals. The classifier reads from `result.error_message`/`stdout`/`stderr` and the `/diagnose` endpoint only — NOT from `localstack_logs` (that field is handled separately in Task 9 integration).
- Add more `_LOCALSTACK_BUG_PATTERNS`: "InternalError", "500 Internal Server Error", common LS exception names.
- Add more `_SAMPLE_ERROR_PATTERNS`: "variable.*required", "missing required argument", "provider.*not available".

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] NOT_CLASSIFIED rate drops to < 30% when tested against real failure messages from `data/results/2026-03-23.json` (if unavailable, use most recent file in `data/results/`). Include a test fixture with 20+ representative real failure messages to make this criterion testable without the full data file
- [ ] ANSI codes are stripped before classification
- [ ] New failure categories render correctly in report HTML

**Verify:**
- `uv run pytest tests/test_classifier.py -q`

---

### Task 4: LocalStack Log Capture

**Objective:** After each sample's deploy+verify cycle, capture recent LocalStack container logs and store them in the results. Display on the sample detail page.

**Dependencies:** None

**Files:**
- Modify: `src/scanner/runner/localstack.py` (add `get_recent_logs()` method)
- Modify: `src/scanner/models.py` (add `localstack_logs` field to `DeployResult`)
- Modify: `src/scanner/runner/orchestrator.py` (capture logs after each sample)
- Modify: `src/scanner/report/templates/sample_detail.html` (display logs section)
- Test: `tests/test_orchestrator.py`

**Key Decisions / Notes:**
- `get_recent_logs(since_reset: float) -> str`: Two modes depending on container availability:
  1. **Self-managed mode** (`self._container is not None`): Use Docker API `self._container.logs(since=...)`.
  2. **External mode** (`self._container is None`, i.e., `--external-localstack` / CI): Docker API is UNAVAILABLE. Fetch logs via HTTP: `GET http://localhost:4566/_localstack/diagnose` (already used by classifier — returns service-level logs). Parse the response for relevant log sections. If `/_localstack/diagnose` is insufficient, fall back to subprocess: `docker logs localstack --since <timestamp>` (the container name `localstack` is the default for the setup-localstack action).
- Store in `DeployResult.localstack_logs: str | None = None` (dataclass default `None`). In `from_dict()`, use `data.get("localstack_logs")` with `None` default to maintain backward compatibility with existing results JSON files that lack this key.
- Truncate to 50KB max per sample. Strip ANSI codes before storing.
- In the sample detail template, add a collapsible "LocalStack Logs" section with `<pre>` block.
- The `reset()` call already happens before each sample — record `time.monotonic()` at reset time, use as `since` for log capture.
- Add a test that specifically covers the `external=True` code path returning non-empty logs via HTTP mock.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] `DeployResult` includes `localstack_logs` field with default `None`; `from_dict()` loads correctly from dicts without the key (backward compat test)
- [ ] Sample detail page shows "LocalStack Logs" section when logs are present
- [ ] Logs are captured via HTTP in external mode (not Docker API)
- [ ] Logs are truncated to prevent results JSON from growing too large

**Verify:**
- `uv run pytest tests/test_orchestrator.py -q`
- `uv run pytest tests/test_report.py -q`

---

### Task 5: Broaden Resource Verification

**Objective:** Extend `ResourceVerifier` to discover and smoke-test SQS queues, SNS topics, DynamoDB tables, Step Functions state machines, and EventBridge rules — beyond the current Lambda/API GW/S3.

**Dependencies:** None

**Files:**
- Modify: `src/scanner/verifier.py`
- Test: `tests/test_verifier.py`

**Key Decisions / Notes:**
- **SQS:** `awslocal sqs list-queues` → for each, `get-queue-attributes` to verify it exists and is accessible.
- **SNS:** `awslocal sns list-topics` → count topics found.
- **DynamoDB:** `awslocal dynamodb list-tables` → for each, `describe-table` to verify ACTIVE status.
- **Step Functions:** `awslocal stepfunctions list-state-machines` → count, optionally start a test execution.
- **EventBridge:** `awslocal events list-rules` → count rules found.
- Follow the same pattern as existing `_verify_lambdas()`: return `(details, any_failed, any_found)` tuple.
- S3 currently only counts buckets — no failure possible. Keep as-is.
- Add all new services to the `verify()` method's flow.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] `ResourceVerifier.verify()` checks SQS, SNS, DynamoDB, Step Functions, EventBridge
- [ ] Each new service has at least 2 test cases (resources found, no resources)
- [ ] Verification correctly reports found resources in details

**Verify:**
- `uv run pytest tests/test_verifier.py -q`

---

### Task 6: Retry Logic and Smart Timeouts

**Objective:** Add configurable retry for transient failures (network errors, rate limits, transient LS errors) and track per-sample historical duration to set adaptive timeouts.

**Dependencies:** None

**Files:**
- Modify: `src/scanner/config.py` (add `max_retries`, `retry_delay` settings)
- Modify: `src/scanner/runner/orchestrator.py` (retry loop, duration tracking)
- Create: `src/scanner/duration_tracker.py` (tracks historical deploy durations per sample)
- Test: `tests/test_duration_tracker.py`
- Test: `tests/test_orchestrator.py` (retry tests)

**Key Decisions / Notes:**
- **Retry:** Wrap deploy in a retry loop (max 2 retries). Only retry on transient signals: `ConnectionError`, `TimeoutError`, "connection refused", "rate limit". Don't retry on clean deploy failures.
- **Retry budget guard:** Before each retry, check `time.monotonic() + retry_delay + per_sample_timeout < deadline` (the `overall_scan_timeout` deadline already tracked at `orchestrator.py` line 131). If insufficient time remains, skip the retry and use the last attempt's result. This prevents retries from pushing CI past the 6-hour GitHub Actions limit.
- **Duration tracking:** Store `{sample_full_name: [duration1, duration2, ...]}` in `data/durations.json`. On next run, use median * 2 as timeout (with min/max bounds from config). New samples use the default `per_sample_timeout`. Note: `durations.json` is stored in `data/` and will be auto-committed by the CI data commit step (which uses `git add data/`).
- `Config.max_retries: int = 2`, `Config.retry_delay: int = 10`
- After retries exhausted, use the last attempt's result.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] Transient failures are retried up to `max_retries` times
- [ ] Duration history is persisted and loaded across runs
- [ ] Adaptive timeout uses historical median * 2 with config bounds

**Verify:**
- `uv run pytest tests/test_duration_tracker.py -q`
- `uv run pytest tests/test_orchestrator.py -q`

---

### Task 7: Richer Trend Charts and Regression Detection

**Objective:** Enhance the index page with per-IaC-type breakdown chart, failure category trend chart, partial count in main chart, and a prominent regression section showing samples that went from PASS to FAIL between consecutive weeks.

**Dependencies:** Task 3 (new failure categories)

**Files:**
- Modify: `src/scanner/report/trends.py` (add regression detection, richer chart data)
- Modify: `src/scanner/report/templates/index.html` (new charts, regression section)
- Test: `tests/test_trends.py`

**Key Decisions / Notes:**
- **Main chart:** Add `partial` dataset (orange line) alongside existing pass/fail/timeout.
- **Per-IaC chart:** New stacked bar chart showing success/failure counts by IaC type (data already in `by_iac_type` in trends.json).
- **Failure category chart:** Line/bar chart of category counts over time (data already in `by_failure_category`).
- **Regression detection:** Compare current results file against the previous results file to find samples that went SUCCESS → FAILURE/PARTIAL.
  - **Finding previous file:** Sort `data/results/*.json` lexicographically by filename (YYYY-MM-DD format sorts correctly), take second-to-last.
  - **First run guard:** If no previous file exists, skip regression detection — no "Regressions" section rendered.
  - **Partial scan guard:** Only compare if the previous file has ≥ 80% of the current scan's sample count (prevents false positives when previous run used `--limit`).
  - **Match logic:** Only flag as regression when `sample.full_name` appears in BOTH files AND status changed from SUCCESS → FAILURE/PARTIAL. Samples present in only one file are ignored.
  - Store regression list in the trend entry via a new `"regressions"` key in `_build_entry()`: `{"regressions": [{"name": "...", "from": "SUCCESS", "to": "FAILURE"}]}`.
- **Index page:** Add a red "Regressions" card above charts when regressions exist, listing sample names with links to detail pages.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] Index page shows partial count in main trend chart
- [ ] Per-IaC breakdown chart renders correctly
- [ ] Failure category trend chart renders
- [ ] Regression section highlights samples that went pass→fail

**Verify:**
- `uv run pytest tests/test_trends.py -q`

---

### Task 8: Service-Level Dashboard in Reports

**Objective:** Add a "Service Coverage" section to the main report page showing which AWS services were tested, their pass/fail rates, and a heatmap of service × IaC type compatibility.

**Dependencies:** Task 2 (service extraction), Task 3 (failure categories)

**Files:**
- Modify: `src/scanner/report/generator.py` (compute service stats)
- Modify: `src/scanner/report/templates/report.html` (service dashboard section)
- Test: `tests/test_report.py`

**Key Decisions / Notes:**
- Aggregate `services_used` across all results to build: `{service_name: {"total": N, "success": N, "failure": N, "partial": N}}`.
- Render as a table sorted by total count (most-used services first).
- Add a simple heatmap grid: rows = services, columns = IaC types, cells = success rate (green/yellow/red).
- This section only appears when `services_used` is populated (non-empty for at least one result).

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] Report shows "Service Coverage" table when services_used data exists
- [ ] Service heatmap renders with correct color coding
- [ ] Report still renders correctly when no services_used data exists

**Verify:**
- `uv run pytest tests/test_report.py -q`

---

### Task 9: Wire Everything Together in Orchestrator

**Objective:** Integrate all new components into the scan pipeline: service extraction → deploy → log capture → classify → verify → retry. Update CLI output and ensure data flows through to reports.

**Dependencies:** Tasks 1–8

**Files:**
- Modify: `src/scanner/runner/orchestrator.py`
- Modify: `src/scanner/cli.py` (update summary output)
- Modify: `src/scanner/report/trends.py` (include service and regression data in trend entries)
- Test: `tests/test_orchestrator.py`

**Key Decisions / Notes:**
- **Pipeline order per sample:**
  1. Clone sample
  2. Extract services (Task 2) — populate `result.services_used` even before deploy
  3. Deploy with retry (Task 6)
  4. Capture LocalStack logs (Task 4)
  5. Classify failure (Task 3, with ANSI stripping)
  6. Verify resources (Task 5, broader) + scripts
  7. Cleanup
- **Implement incrementally:** Integrate one component at a time with a test run after each, rather than all at once. Suggested order: (a) service extraction + log capture (data-flow), (b) retry + duration tracking (deploy loop), (c) regression + CLI output (reporting).
- **CLI output:** Update scan complete message to include new category counts.
- **Duration tracker:** Save durations after each sample.
- **Regression:** After scan completes, compute regressions before generating report.
- Update `ScanReport.to_dict()` to include any new summary fields.

**Definition of Done:**
- [ ] All tests pass
- [ ] No diagnostics errors
- [ ] Full pipeline runs end-to-end with all new features integrated
- [ ] `uv run scanner scan --limit 5 --external-localstack` produces results with services_used, localstack_logs, and new failure categories
- [ ] Coverage ≥ 80%

**Verify:**
- `uv run pytest -q --cov=src --cov-fail-under=80`

## Testing Strategy

- **Unit tests:** Each new module (`service_extractor.py`, `duration_tracker.py`) gets dedicated test files with mocked file I/O and subprocess calls.
- **Integration within existing tests:** Orchestrator tests (`test_orchestrator.py`) extended with new mock verification for service extraction, log capture, retry.
- **Report tests:** `test_report.py` extended to verify new dashboard sections render.
- **Trend tests:** `test_trends.py` extended for regression detection and new chart data.
- **Manual verification:** Run `scanner scan --limit 5 --external-localstack` after integration to validate real-world behavior.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| CDK bootstrap fix doesn't resolve all CDK failures | Medium | Medium | Bootstrap fix handles the warning; remaining failures classified normally rather than all failing at bootstrap |
| Service extraction regex misses IaC patterns | Medium | Low | Start with common Terraform `aws_*` prefixes (~50 types). Unrecognized resource prefixes are logged at DEBUG level. `ServiceExtractor.extract()` always returns a list — empty if nothing recognized. Add a test verifying unrecognized resource types don't raise |
| Log capture bloats results JSON | Medium | Medium | Truncate to 50KB per sample, strip ANSI codes. ~50KB × 500 samples = ~25MB max per run (acceptable) |
| Retry delays extend scan time significantly | Low | Medium | Cap at 2 retries with 10s delay. Retry budget guard checks remaining time against CI deadline before each retry — skips retry if insufficient time. Only retries transient failures (not clean deploy failures) |
| Regression detection noisy with sample churn | Low | Low | Only flag regressions for samples present in both runs. New samples can't regress |

## Goal Verification

### Truths
1. CDK samples no longer all fail at bootstrap — at least some produce SUCCESS or meaningful FAILURE results
2. `services_used` is populated for Terraform/CDK/CFN samples, visible in report detail pages
3. NOT_CLASSIFIED failure rate drops from 86% to < 30%
4. LocalStack logs appear on sample detail pages for debugging
5. Trend index page shows partial counts, per-IaC breakdown, failure category trends, and regressions
6. Resource verification covers SQS, SNS, DynamoDB, Step Functions, EventBridge in addition to Lambda/API GW/S3
7. Transient failures are retried, and deploy durations are tracked historically

### Artifacts
1. `src/scanner/deployer/cdk.py` — fixed bootstrap handling
2. `src/scanner/service_extractor.py` — new module for IaC service extraction
3. `src/scanner/classifier.py` — expanded patterns, ANSI stripping, new categories
4. `src/scanner/verifier.py` — broader resource verification
5. `src/scanner/duration_tracker.py` — new module for duration history
6. `src/scanner/report/templates/index.html` — richer charts, regression section
7. `src/scanner/report/templates/report.html` — service dashboard

### Key Links
- `ServiceExtractor` → called from `ScanOrchestrator._run_sample()` → populates `DeployResult.services_used` → rendered in `report.html` service dashboard
- `FailureClassifier` (expanded) → called from `ScanOrchestrator._classify_result()` → new categories rendered in `report.html` breakdown table
- `LocalStackManager.get_recent_logs()` → captured in orchestrator → stored in `DeployResult.localstack_logs` → rendered in `sample_detail.html`
- `TrendTracker.detect_regressions()` → computed from consecutive results files → rendered in `index.html` regression card
- `DurationTracker` → loaded/saved in orchestrator → adaptive timeouts per sample

## Deferred Ideas

- Azure Bicep/ARM deployer improvements (378 UNSUPPORTED samples)
- JSON/CSV export for downstream tooling (Jira, Slack)
- Pulumi/Serverless deployer fixes
- GitHub issue auto-creation for LOCALSTACK_BUG failures
- Email/webhook notifications on regression detection
