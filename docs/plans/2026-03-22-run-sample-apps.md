# Run Sample Apps End-to-End Implementation Plan

Created: 2026-03-22
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** Add post-deploy verification to the scanner so it tests whether deployed resources actually work on LocalStack — not just whether IaC provisioning succeeds. After a successful deploy, discover what was created (Lambda functions, API Gateways, S3 buckets) via `awslocal`, invoke/test each resource, and optionally run sample test scripts found in the repo. If deploy succeeds but verification fails, mark the result as `PARTIAL`.

**Architecture:** Add a `ResourceVerifier` class that uses `awslocal` CLI to discover and smoke-test deployed AWS resources. Add a `ScriptDetector` that finds and runs test scripts (Makefile targets, shell scripts) in cloned repos. Insert a verification phase in the orchestrator between `deploy()` and `cleanup()`. Extend `DeployResult` with `verification_status` and `verification_details` fields. Add `DeployStatus.PARTIAL` for deploy-success-but-verify-fail cases.

**Tech Stack:** Python 3.12, subprocess (awslocal CLI calls), existing deployer infrastructure.

## Scope

### In Scope
- Add `DeployStatus.PARTIAL` enum value
- Add `verification_status` and `verification_details` fields to `DeployResult`
- Create `ResourceVerifier` — discovers Lambda, API Gateway, S3 via awslocal; invokes/tests each
- Create `ScriptDetector` — finds test scripts (Makefile, scripts/*.sh, test_*.py) in sample repos
- Integrate verification into orchestrator between deploy and cleanup
- Update report templates: PARTIAL badge, verification status column, verification details on detail page
- Update `ScanReport.partial_count` property

### Out of Scope
- Testing non-AWS resources (Azure, etc.) — future enhancement
- Per-sample verification config files — too complex for phase 1
- Running sample application UIs or web servers
- Modifying the existing deployer ABC interface (verification is orchestrator-level, not deployer-level)
- Testing DynamoDB data, SQS messages, or other data-plane operations beyond basic resource existence

## Context for Implementer

> The scanner discovers AWS IaC sample repos, clones each, deploys against LocalStack, and records results. Currently the flow is: `reset LS → bootstrap (CDK) → clone → prepare → deploy → cleanup`. There is NO verification step — deploy success means "IaC command exited 0", not "the app works."

- **Patterns to follow:** The orchestrator loop in `src/scanner/runner/orchestrator.py:88-192` is where verification inserts — between `deploy()` (line 156) and `cleanup()` (line 168). Follow the same try/except pattern used for deploy.
- **Conventions:** Use `subprocess.run()` with `capture_output=True, text=True` for CLI calls. Use `awslocal` (not `aws --endpoint-url`) for LocalStack API calls — it's already installed in CI.
- **Key files:**
  - `src/scanner/models.py` — DeployResult, DeployStatus, ScanReport
  - `src/scanner/runner/orchestrator.py` — ScanOrchestrator (main scan loop)
  - `src/scanner/deployer/base.py` — Deployer ABC (NOT modified — verification is separate)
  - `src/scanner/config.py` — Config dataclass
  - `src/scanner/report/templates/report.html` — main report template
  - `src/scanner/report/templates/sample_detail.html` — per-sample detail page
- **Gotchas:**
  - `awslocal` commands need `--region us-east-1` or `AWS_DEFAULT_REGION=us-east-1` env var
  - Lambda invocation output goes to a file, not stdout: `awslocal lambda invoke --function-name X <tempfile>` — use `tempfile.NamedTemporaryFile` for unique paths
  - API Gateway REST APIs need stage + resource path to form a callable URL
  - The verification timeout must be separate from the deploy timeout — a 5-minute deploy should not eat into verification time
  - Test scripts in sample repos are untrusted — run with timeout and capture output
  - Cleanup must still happen even if verification fails or crashes

## Progress Tracking

- [x] Task 1: Add PARTIAL status and verification fields to DeployResult
- [x] Task 2: Create ResourceVerifier for AWS resource smoke tests
- [x] Task 3: Create ScriptDetector for sample test script discovery and execution
- [x] Task 4: Integrate verification into orchestrator
- [x] Task 5: Update report templates with verification info

**Total Tasks:** 5 | **Completed:** 5 | **Remaining:** 0

## Implementation Tasks

### Task 1: Add PARTIAL status and verification fields to DeployResult

**Objective:** Extend the data model to support verification results alongside deploy results.
**Dependencies:** None

**Files:**
- Modify: `src/scanner/models.py`
- Test: `tests/test_models.py`

**Key Decisions / Notes:**
- Add `DeployStatus.PARTIAL = "PARTIAL"` — means deploy succeeded but verification found issues
- Add to `DeployResult`:
  - `verification_status: str | None = None` — one of "PASSED", "FAILED", "SKIPPED", or None (not yet verified)
  - `verification_details: str | None = None` — human-readable summary (e.g., "2/3 Lambda functions invoked successfully; API Gateway returned 500")
- Update `to_dict()` to serialize both new fields
- Update `from_dict()` to handle missing fields (backward compat with old JSON)
- Add `ScanReport.partial_count` property (same pattern as `success_count`, `failure_count`)
- Update `ScanReport.to_dict()` summary block to include `"partial": self.partial_count` (currently only has success/failure/timeout/unsupported/skipped at `models.py:190-196`)
- Follow existing patterns in `models.py:109-142` for serialization

**Definition of Done:**
- [ ] `DeployStatus.PARTIAL` enum value exists
- [ ] `DeployResult` has `verification_status` and `verification_details` fields
- [ ] Serialization round-trips correctly (to_dict/from_dict)
- [ ] Old JSON without verification fields loads without error
- [ ] `ScanReport.partial_count` returns count of PARTIAL results
- [ ] `ScanReport.to_dict()` includes `"partial"` key in the summary dict

**Verify:**
```bash
uv run pytest tests/test_models.py -q
```

---

### Task 2: Create ResourceVerifier for AWS resource smoke tests

**Objective:** Create a class that uses `awslocal` to discover deployed AWS resources and smoke-test them (invoke Lambda, hit API GW, check S3 buckets).
**Dependencies:** None (standalone module)

**Files:**
- Create: `src/scanner/verifier.py`
- Test: `tests/test_verifier.py`

**Key Decisions / Notes:**
- Class `ResourceVerifier` with method `verify(ls_endpoint: str, timeout: int = 120) -> VerifyOutcome`
- `VerifyOutcome` is a simple dataclass: `passed: bool`, `summary: str`, `details: list[str]`
- **Lambda verification:**
  1. `awslocal lambda list-functions --region us-east-1 --query 'Functions[].FunctionName' --output text`
  2. For each function: `awslocal lambda invoke --function-name <name> --region us-east-1 --payload '{}' <tempfile>` — use `tempfile.NamedTemporaryFile(suffix='.json', delete=False)` for a unique output path per invocation (avoids stale/colliding files)
  3. Check exit code + read output file for `"FunctionError"` key; delete temp file after reading
  4. Record: "Lambda <name>: OK" or "Lambda <name>: FAILED (error details)"
- **API Gateway verification:**
  1. `awslocal apigateway get-rest-apis --region us-east-1 --query 'items[].id' --output text`
  2. For each API: `awslocal apigateway get-stages --rest-api-id <id> --region us-east-1`
  3. Build URL: `http://localhost:4566/restapis/<id>/<stage>/_user_request_/`
  4. Send GET request, check for non-5xx response
  5. Record result
- **S3 verification:**
  1. `awslocal s3 ls --region us-east-1`
  2. Just verify buckets exist (listing confirms creation was real)
  3. Record count of buckets
- Use `subprocess.run()` with timeout for all awslocal calls
- ENV: `{"AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}`
- If awslocal is not available (command not found), return a SKIPPED outcome
- Each resource check is independent — one Lambda failure shouldn't prevent checking others
- If no verifiable resources are found (0 Lambda, 0 API GW, 0 S3), set `passed=True` with `summary="No verifiable resources found (Lambda/API GW/S3)"` — this is accurate rather than masking empty deploys. The orchestrator will set `verification_status="SKIPPED"` (not "PASSED") when ResourceVerifier finds nothing to test.
- If any resource was found AND all passed, `passed=True`. If any resource fails, `passed=False`.
- Lambda invocation output uses a unique temp file path per invocation (no hardcoded `/tmp/lambda_out.json`)

**Definition of Done:**
- [ ] ResourceVerifier.verify() discovers Lambda functions via awslocal
- [ ] ResourceVerifier.verify() invokes each Lambda and records pass/fail
- [ ] ResourceVerifier.verify() discovers API GW endpoints and makes test requests
- [ ] ResourceVerifier.verify() checks S3 bucket existence
- [ ] Handles awslocal not being available gracefully (returns SKIPPED)
- [ ] Each resource check is independent (one failure doesn't skip others)
- [ ] All subprocess calls have timeouts
- [ ] All awslocal calls are mocked in unit tests
- [ ] Lambda invocation output uses a unique temp file path per invocation

**Verify:**
```bash
uv run pytest tests/test_verifier.py -q
```

---

### Task 3: Create ScriptDetector for sample test script discovery and execution

**Objective:** Detect and run test scripts found in cloned sample repos (Makefile targets, shell scripts, Python test files).
**Dependencies:** None (standalone module)

**Files:**
- Create: `src/scanner/script_detector.py`
- Test: `tests/test_script_detector.py`

**Key Decisions / Notes:**
- Class `ScriptDetector` with methods:
  - `detect(sample_dir: Path) -> list[DetectedScript]` — find runnable test artifacts
  - `run(sample_dir: Path, scripts: list[DetectedScript], timeout: int = 60) -> ScriptOutcome`
- `DetectedScript` dataclass: `path: str`, `script_type: str` (makefile/shell/python), `command: list[str]`
- `ScriptOutcome` dataclass: `passed: bool`, `summary: str`, `details: list[str]`
- **Detection rules (priority order):**
  1. `Makefile` with a `test` target → `["make", "test"]`
  2. `scripts/test*.sh` or `test*.sh` in root → `["bash", "<script>"]`
  3. `test_*.py` or `tests/test_*.py` (not part of IaC) → `[sys.executable, "<script>"]` — use `sys.executable` instead of bare `python` to ensure the correct interpreter (avoids ModuleNotFoundError when system python lacks deps)
- **Execution:** Run the first detected script only (to avoid runaway test suites). Use `subprocess.run()` with `cwd=sample_dir`, `timeout=timeout`, `capture_output=True`.
- ENV: Same AWS env vars as ResourceVerifier + `LOCALSTACK_HOSTNAME=localhost`, `EDGE_PORT=4566`
- `passed` based on exit code (0 = passed, non-zero = failed)
- If no scripts detected, return outcome with `passed=True, summary="No test scripts found"`

**Definition of Done:**
- [ ] Detects Makefile with test target
- [ ] Detects shell scripts matching test*.sh pattern
- [ ] Detects Python test files
- [ ] Runs detected script with timeout and captures output
- [ ] Handles missing scripts gracefully (returns "no scripts found")
- [ ] All subprocess calls mocked in unit tests

**Verify:**
```bash
uv run pytest tests/test_script_detector.py -q
```

---

### Task 4: Integrate verification into orchestrator

**Objective:** Insert a verification phase in the scan loop between deploy and cleanup. Use ResourceVerifier and ScriptDetector on successful deploys. Set status to PARTIAL if verification fails.
**Dependencies:** Task 1, Task 2, Task 3

**Files:**
- Modify: `src/scanner/runner/orchestrator.py`
- Modify: `src/scanner/config.py` (add `verification_timeout` config)
- Test: `tests/test_orchestrator.py`

**Key Decisions / Notes:**
- Add `Config.verification_timeout: int = 120` — separate from `per_sample_timeout`
- Add `Config.enable_verification: bool = True` — allow disabling verification via config
- **Insertion ordering (critical):** The current orchestrator flow at `orchestrator.py:155-166` is: `deploy() → _classify_result(result) → _results.append(result) → cleanup()`. Insert `_verify_sample` AFTER `_classify_result(result)` and BEFORE `self._results.append(result)`. This ensures status mutation from PARTIAL is reflected in the stored result. The full order after changes: `deploy() → classify → verify → append → cleanup`.
  ```python
  # After line 163 (result field assignments), before line 165 (_classify_result):
  self._classify_result(result)
  if result.status == DeployStatus.SUCCESS and self._config.enable_verification:
      self._verify_sample(sample_dir, result)
  self._results.append(result)
  ```
- **Update `_classify_result` guard** (at `orchestrator.py:60`): The current guard is `if result.status == DeployStatus.SUCCESS or result.failure_category is not None: return`. Add PARTIAL to the short-circuit: `if result.status in (DeployStatus.SUCCESS, DeployStatus.PARTIAL) or result.failure_category is not None: return`. This prevents future refactors from accidentally classifying PARTIAL results.
- New method `_verify_sample(self, sample_dir: Path, result: DeployResult) -> None`:
  1. Run `ResourceVerifier.verify(self._config.localstack_endpoint, timeout)`
  2. Run `ScriptDetector.detect(sample_dir)` then `ScriptDetector.run(...)`
  3. Combine outcomes into `verification_status` and `verification_details`
  4. If ResourceVerifier found no resources AND ScriptDetector found no scripts: set `verification_status="SKIPPED"` (not "PASSED")
  5. If any verification failed: set `result.status = DeployStatus.PARTIAL`, `verification_status="FAILED"`
  6. If all passed: `verification_status="PASSED"`
  7. Wrap in try/except — verification failure should never crash the scan
- Verification only runs for `SUCCESS` deploys — failed deploys have nothing to verify
- The cleanup step must still execute regardless of verification outcome (it's in a finally block already)
- **Mock audit:** All existing SUCCESS-path tests in `test_orchestrator.py` must add `@patch("scanner.runner.orchestrator.ResourceVerifier")` and `@patch("scanner.runner.orchestrator.ScriptDetector")` (or patch the module-level imports). Without this, tests will attempt real `awslocal` subprocess calls and fail in CI.

**Definition of Done:**
- [ ] Verification runs after successful deploy, before cleanup
- [ ] ResourceVerifier and ScriptDetector are called
- [ ] Deploy SUCCESS + verify FAIL sets status to PARTIAL
- [ ] Deploy SUCCESS + verify PASS keeps status as SUCCESS
- [ ] Verification failure/exception does not crash the scan
- [ ] Verification is skippable via `Config.enable_verification = False`
- [ ] Verification has its own timeout separate from deploy timeout
- [ ] `_classify_result` does not assign failure_category to PARTIAL results
- [ ] `result.status` is PARTIAL in `self._results` after verification fails (not just in local variable)
- [ ] All existing test_orchestrator.py tests pass with ResourceVerifier and ScriptDetector mocked
- [ ] Test `test_run_does_not_set_category_for_partial` verifies PARTIAL results have `failure_category=None`

**Verify:**
```bash
uv run pytest tests/test_orchestrator.py -q
```

---

### Task 5: Update report templates with verification info

**Objective:** Add PARTIAL badge, verification status column, and verification details to HTML reports.
**Dependencies:** Task 1, Task 4

**Files:**
- Modify: `src/scanner/report/templates/report.html`
- Modify: `src/scanner/report/templates/sample_detail.html`
- Test: `tests/test_report.py`

**Key Decisions / Notes:**
- Add `.badge-partial { background: #f57c00; }` CSS class (orange — between success green and failure red) to **BOTH** `report.html` AND `sample_detail.html` — both templates have their own `<style>` blocks
- Add stat card for PARTIAL count in the stats section (like existing passed/failed/timeout cards)
- Add "Verification" column to the results table showing verification_status with a badge
- On detail page (`sample_detail.html`): add a "Verification" section with `<pre>` block showing verification_details
- Follow existing badge pattern: `badge-{{ result.verification_status | lower }}` with CSS classes for passed/failed/skipped
- Add CSS to both templates: `.badge-passed { background: #2e7d32; }`, `.badge-failed { background: #c62828; }`, `.badge-skipped { background: #9e9e9e; }`, `.badge-partial { background: #f57c00; }`
- Handle `verification_status=None` gracefully — no badge rendered when verification wasn't attempted

**Definition of Done:**
- [ ] PARTIAL badge style exists in BOTH `report.html` and `sample_detail.html`
- [ ] Verification status column shows in results table
- [ ] Detail page shows verification_details in a pre block when set
- [ ] Detail page shows no verification badge when verification_status is None
- [ ] Stats section includes PARTIAL count
- [ ] `test_report.py` includes a test rendering report.html with a PARTIAL result and asserts HTML contains `badge-partial`
- [ ] `test_report.py` includes a test rendering with verification_status=None and asserts no verification badge shown
- [ ] `test_report.py` includes a test rendering sample_detail.html with verification_details and asserts the pre block contains the details text

**Verify:**
```bash
uv run pytest tests/test_report.py -q
```

---

## Testing Strategy

- **Unit tests:** All ResourceVerifier and ScriptDetector methods tested with mocked subprocess calls. No real awslocal or LocalStack needed.
- **Integration points:** Orchestrator tests mock ResourceVerifier and ScriptDetector to verify the integration flow (deploy → classify → verify → append → cleanup order, PARTIAL status assignment).
- **Mock audit (critical):** When Task 4 adds ResourceVerifier/ScriptDetector imports to orchestrator.py, ALL existing SUCCESS-path tests in `test_orchestrator.py` must add mocks for both classes. Without mocks, tests will attempt real `awslocal` subprocess calls.
- **Backward compatibility:** Old DeployResult JSON without verification fields loads correctly.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| awslocal not available in some environments | Low | Medium | ResourceVerifier returns SKIPPED if awslocal command not found |
| Lambda invocation with empty payload crashes function | Medium | Low | Record as verification failure, not scanner crash; catch all exceptions |
| API Gateway URL construction fails (no stages, custom domains) | Medium | Low | Try best-effort URL; log and skip if cannot determine endpoint |
| Test scripts in repos have external dependencies or are broken | High | Low | Run with strict timeout (60s); capture output; one script failure doesn't affect others |
| Verification doubles scan time | Medium | Medium | Separate verification_timeout (120s default); only verify SUCCESS deploys; can disable via config |
| Some samples deploy resources that can't be verified generically | Medium | Low | Record as SKIPPED verification, not failure; "No verifiable resources found" is acceptable |
| HTTP APIs (API Gateway v2) not detected by REST API query | Medium | Low | Phase 1 only queries `apigateway get-rest-apis` (v1); HTTP APIs use `apigatewayv2 get-apis` — defer to phase 2 |
| Python test scripts may fail with wrong interpreter | Medium | Low | Use `sys.executable` instead of bare `python` to avoid system python mismatch |

## Goal Verification

### Truths
1. After a successful IaC deploy, the system discovers Lambda functions via awslocal and invokes them
2. After a successful IaC deploy, the system discovers API Gateway endpoints and makes test HTTP requests
3. If a Lambda invocation fails, the sample status becomes PARTIAL (not SUCCESS)
4. Sample repos with test scripts (Makefile test target, test*.sh) have those scripts detected and executed
5. The HTML report shows verification status alongside deploy status
6. Verification failures do not crash the scanner or prevent cleanup

### Artifacts
- `src/scanner/verifier.py` — ResourceVerifier (Lambda, API GW, S3 smoke tests)
- `src/scanner/script_detector.py` — ScriptDetector (find and run test scripts)
- `src/scanner/runner/orchestrator.py` — verification phase integration
- `src/scanner/models.py` — PARTIAL status, verification fields

### Key Links
- `ScanOrchestrator._verify_sample()` → `ResourceVerifier.verify()` + `ScriptDetector.detect()/run()`
- `DeployResult.verification_status` → `report.html` verification column
- `DeployStatus.PARTIAL` → `report.html` badge-partial CSS

## Deferred Ideas
- Per-service verification (DynamoDB put/get, SQS send/receive, SNS publish) — phase 2
- Per-sample verification config file (e.g., `.localstack-test.yml`) specifying custom test commands
- Azure resource verification (only AWS supported in phase 1)
- Verification trend tracking in trends.json (track verification pass rate over time)
- API Gateway v2 (HTTP APIs) verification via `apigatewayv2 get-apis` — phase 1 only covers REST APIs (v1)
