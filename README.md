# LocalStack Sample Tester

Automated weekly compatibility scanner that discovers AWS and Azure IaC sample repositories from GitHub organizations, deploys them against [LocalStack](https://localstack.cloud/), and publishes HTML trend reports via GitHub Pages.

## Overview

The scanner runs on a Monday 6 AM UTC schedule (or on demand). It:

1. **Discovers** IaC sample apps from configured GitHub orgs using Code Search
2. **Deploys** each sample against a LocalStack Pro instance using the appropriate IaC tool
3. **Records** pass/fail/timeout results with logs
4. **Publishes** an HTML report to GitHub Pages with trend history

Supported IaC types: Terraform, Azure Bicep, CDK, SAM, CloudFormation, Pulumi, Serverless Framework, Azure ARM.

## Prerequisites

| Tool | Purpose |
|------|---------|
| Python 3.12+ | Runtime |
| [uv](https://docs.astral.sh/uv/) | Package management |
| Docker | LocalStack container |
| `cdklocal` / `samlocal` / `tflocal` / `pulumilocal` | IaC wrapper tools |
| Node.js 20+ | CDK and Serverless Framework |
| Terraform CLI | Terraform deployments |
| Pulumi CLI | Pulumi deployments |

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your tokens

# 3. Discover sample repos
uv run scanner discover

# 4. Run a quick test scan (first 5 samples, using an already-running LocalStack)
uv run scanner scan --limit 5 --external-localstack

# 5. Generate a report from results
uv run scanner report --input data/results/$(ls data/results | tail -1) --output /tmp/report
```

## CLI Commands

```
scanner [--verbose] COMMAND
```

| Command | Description |
|---------|-------------|
| `discover` | Discover IaC samples from GitHub orgs and build the registry |
| `scan` | Deploy samples against LocalStack and record results |
| `report` | Generate HTML report from a results JSON file |
| `run` | Run the full pipeline: discover → scan → report |

### `discover`

```bash
uv run scanner discover [--org <org>]... [--max-repos-per-org N] [--no-cache]
```

- `--org` — override configured orgs (repeatable)
- `--max-repos-per-org` — cap repos per org (default: 500)
- `--no-cache` — bypass the local 24h ETag cache

### `scan`

```bash
uv run scanner scan [--limit N] [--external-localstack] [--localstack-image IMAGE]
```

- `--limit` — scan only the first N samples (sorted by IaC priority)
- `--external-localstack` — skip container start/stop (use running LocalStack)
- `--localstack-image` — override the Docker image (default: `localstack/localstack-pro:latest`)

### `run`

```bash
uv run scanner run [--max-repos-per-org N] [--limit N] [--external-localstack] [--localstack-image IMAGE]
```

Combines `discover` and `scan` in one step.

## Environment Variables

Copy `.env.example` to `.env` and fill in values for local development. In CI, configure these as GitHub Actions secrets.

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Strongly recommended | GitHub personal access token. Without it: 10 results/query, 10 req/min. With it: full Code Search (30 req/min). Scopes: `public_repo`, `read:org`. |
| `LOCALSTACK_AUTH_TOKEN` | For Pro features | LocalStack Pro auth token. Get at [app.localstack.cloud](https://app.localstack.cloud/workspace/auth-token). |
| `PULUMI_CONFIG_PASSPHRASE` | For Pulumi samples | Passphrase for Pulumi state encryption. Set to `localstack-scanner` in CI. |

## CI/CD

The scanner runs automatically every Monday at 6 AM UTC via `.github/workflows/weekly-scan.yml`. It can also be triggered manually from the **Actions** tab.

**What the workflow does:**

1. Sets up Python 3.12, Node.js 20, Terraform, and Pulumi CLI
2. Installs uv and project dependencies
3. Installs IaC wrapper tools (`aws-cdk-local`, `aws-sam-cli-local`, `awscli-local`, `terraform-local`, `pulumi-local`)
4. Starts LocalStack Pro via the `LocalStack/setup-localstack` action
5. Runs `scanner run --max-repos-per-org 500 --external-localstack`
6. Commits updated `data/` (registry, results, trends) back to the repo
7. Deploys `reports/` to GitHub Pages

**Data persistence:** Scan results, the sample registry, and trend history are committed back to the `data/` directory after each run. The `data/.gitkeep` file tracks the directory structure; actual data files are populated by the first CI run.

## GitHub Production Setup

After pushing the repository, complete the following configuration in GitHub Settings:

### 1. Secrets

Go to **Settings → Secrets and variables → Actions → Repository secrets** and add:

| Secret | Value |
|--------|-------|
| `LOCALSTACK_AUTH_TOKEN` | Your LocalStack Pro token |

`GITHUB_TOKEN` is automatically provided by GitHub Actions — no configuration needed.

### 2. GitHub Pages

1. Go to **Settings → Pages**
2. Set **Source** to **GitHub Actions**
3. The first CI run will deploy the reports. The URL will be `https://<username>.github.io/localstack-sample-tester/`

### 3. Branch Protection (Recommended)

Go to **Settings → Branches → Add branch protection rule** for `main`:

- **Require a pull request before merging** — prevents direct pushes
- **Require status checks to pass before merging** — add `scan` once the first workflow run completes
- **Do not allow bypassing the above settings**
- **Allow force pushes** — leave unchecked (never force-push to main)

> Note: The weekly scan workflow commits `data/` changes directly to `main` using the `github-actions[bot]` user. This is an automated commit, not a human push. Branch protection still applies to human pushes.

## Architecture

```
src/scanner/
├── cli.py              # Click CLI (discover / scan / report / run)
├── config.py           # Config dataclass, IaCType, CloudProvider enums
├── models.py           # Sample, DeployResult, ScanReport dataclasses
├── priority.py         # sort_samples_by_priority()
├── discovery/          # GitHub repo discovery
│   ├── github_client.py    # Code Search API client (rate-limit aware)
│   ├── iac_detector.py     # IaC type detection from file trees
│   ├── registry.py         # Local JSON registry of discovered samples
│   └── etag_cache.py       # 24h TTL cache for Code Search results
├── deployer/           # IaC deployers
│   ├── base.py             # Abstract Deployer (prepare / deploy / cleanup)
│   ├── terraform.py        # tflocal
│   ├── cdk.py              # cdklocal
│   ├── sam.py              # samlocal
│   ├── cloudformation.py   # awslocal cloudformation
│   ├── pulumi.py           # pulumilocal
│   ├── serverless.py       # serverless
│   └── azure.py            # Azure ARM/Bicep deployer
├── runner/
│   ├── orchestrator.py     # ScanOrchestrator — main scan loop
│   ├── localstack.py       # LocalStackManager — Docker container lifecycle
│   └── sandbox.py          # Sandbox — git clone into temp dirs
└── report/
    ├── generator.py        # Jinja2 HTML report generator
    ├── trends.py           # TrendTracker — update/read trends.json
    └── templates/          # HTML templates (index, report, sample_detail)
```

**Discovery flow:** GitHub Code Search per IaC type → deduplicate by repo (first IaC match wins) → cache results for 24h → write registry JSON.

**Scan loop:** For each sample: reset LocalStack state → clone repo to temp dir → `prepare()` (install deps) → `deploy()` → `cleanup()` → record result.

**IaC priority:** `TERRAFORM → AZURE_BICEP → CDK → SAM → CLOUDFORMATION → PULUMI → SERVERLESS → AZURE_ARM`. SAM comes before CloudFormation because SAM repos contain both `samconfig.toml` and `template.yaml` — without this ordering, they would be misclassified as CloudFormation.

## Development

```bash
# Run tests
uv run pytest -q

# Run tests with coverage
uv run pytest -q --cov=src --cov-fail-under=80

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run `ruff format` and `ruff check --fix` on every commit.

## Contributing

1. Fork the repo and create a feature branch
2. Install pre-commit hooks: `pip install pre-commit && pre-commit install`
3. Make your changes with tests
4. Ensure `uv run pytest -q` and `uv run ruff check .` pass
5. Open a pull request against `main`
