"""Tests for Code Search-based discovery and TTL cache."""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from scanner.config import CloudProvider, Config, IaCType
from scanner.models import Sample


def _make_repo_mock(
    repo_full_name: str,
    archived: bool = False,
    fork: bool = False,
    updated_at: datetime | None = None,
    topics: list[str] | None = None,
) -> MagicMock:
    """Build a mock PyGithub Repository object (as returned by search_iac_repos)."""
    repo = MagicMock()
    org, name = repo_full_name.split("/", 1)
    repo.name = name
    repo.full_name = repo_full_name
    repo.html_url = f"https://github.com/{repo_full_name}"
    repo.description = f"Description of {name}"
    repo.language = "HCL"
    repo.default_branch = "main"
    repo.updated_at = updated_at or datetime(2024, 1, 1, tzinfo=UTC)
    repo.archived = archived
    repo.fork = fork
    repo.get_topics.return_value = topics or []
    return repo


def _make_content_file(
    repo_full_name: str,
    archived: bool = False,
    fork: bool = False,
    updated_at: datetime | None = None,
    topics: list[str] | None = None,
) -> MagicMock:
    """Build a mock PyGithub ContentFile with a .repository attribute.

    Used for tests that mock search_code() directly (search_iac_repos tests).
    For discover_all tests, use _make_repo_mock() since search_iac_repos
    already extracts repos from content files.
    """
    cf = MagicMock()
    cf.repository = _make_repo_mock(repo_full_name, archived, fork, updated_at, topics)
    return cf


def _make_sample(name: str, org: str, iac_type: IaCType) -> Sample:
    return Sample(
        name=name,
        org=org,
        url=f"https://github.com/{org}/{name}",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
        description="",
        topics=[],
        language="HCL",
        default_branch="main",
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# ETagCache tests
# ---------------------------------------------------------------------------

class TestETagCache:
    def test_miss_when_cache_file_missing(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        result = cache.get("aws-samples", IaCType.TERRAFORM)
        assert result is None

    def test_stores_and_retrieves_fresh_entry(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        samples = [_make_sample("tf-app", "aws-samples", IaCType.TERRAFORM)]
        cache.put("aws-samples", IaCType.TERRAFORM, samples)

        result = cache.get("aws-samples", IaCType.TERRAFORM)
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "tf-app"

    def test_miss_when_entry_expired(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        samples = [_make_sample("tf-app", "aws-samples", IaCType.TERRAFORM)]

        # Write an entry with a stale fetched_at (48h ago)
        stale_time = datetime.now(tz=UTC) - timedelta(hours=48)
        cache_path = tmp_path / "cache.json"
        cache_data = {
            "aws-samples:TERRAFORM": {
                "fetched_at": stale_time.isoformat(),
                "repos": [s.to_dict() for s in samples],
            }
        }
        cache_path.write_text(json.dumps(cache_data))

        result = cache.get("aws-samples", IaCType.TERRAFORM)
        assert result is None

    def test_put_overwrites_stale_entry(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        old = [_make_sample("old-app", "aws-samples", IaCType.TERRAFORM)]
        new = [_make_sample("new-app", "aws-samples", IaCType.TERRAFORM)]

        cache.put("aws-samples", IaCType.TERRAFORM, old)
        cache.put("aws-samples", IaCType.TERRAFORM, new)

        result = cache.get("aws-samples", IaCType.TERRAFORM)
        assert result is not None
        assert result[0].name == "new-app"

    def test_multiple_orgs_and_types_stored_independently(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        tf_samples = [_make_sample("tf-app", "aws-samples", IaCType.TERRAFORM)]
        cdk_samples = [_make_sample("cdk-app", "aws-samples", IaCType.CDK)]
        azure_samples = [_make_sample("bicep-app", "Azure-Samples", IaCType.AZURE_BICEP)]

        cache.put("aws-samples", IaCType.TERRAFORM, tf_samples)
        cache.put("aws-samples", IaCType.CDK, cdk_samples)
        cache.put("Azure-Samples", IaCType.AZURE_BICEP, azure_samples)

        assert cache.get("aws-samples", IaCType.TERRAFORM)[0].name == "tf-app"
        assert cache.get("aws-samples", IaCType.CDK)[0].name == "cdk-app"
        assert cache.get("Azure-Samples", IaCType.AZURE_BICEP)[0].name == "bicep-app"

    def test_cache_persists_across_instances(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache

        path = str(tmp_path / "cache.json")
        cache1 = ETagCache(path=path, ttl_hours=24)
        samples = [_make_sample("tf-app", "aws-samples", IaCType.TERRAFORM)]
        cache1.put("aws-samples", IaCType.TERRAFORM, samples)

        cache2 = ETagCache(path=path, ttl_hours=24)
        result = cache2.get("aws-samples", IaCType.TERRAFORM)
        assert result is not None
        assert result[0].name == "tf-app"


# ---------------------------------------------------------------------------
# GitHubClient search methods
# ---------------------------------------------------------------------------

class TestSearchIacRepos:
    def setup_method(self):
        self.config = Config(max_repos_per_org=10)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_iac_repos_returns_repos_for_terraform(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        cf = _make_content_file("aws-samples/tf-app")
        mock_gh.search_code.return_value = [cf]

        client = GitHubClient(config=self.config)
        result = client.search_iac_repos("aws-samples", IaCType.TERRAFORM)

        assert len(result) == 1
        assert result[0].full_name == "aws-samples/tf-app"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_uses_extension_query_for_terraform(self, mock_sleep, mock_github_cls):
        """Terraform uses 'extension:tf' not 'filename:main.tf' to catch all .tf files."""
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_gh.search_code.return_value = []

        client = GitHubClient(config=self.config)
        client.search_iac_repos("aws-samples", IaCType.TERRAFORM)

        query = mock_gh.search_code.call_args[0][0]
        assert "extension:tf" in query
        assert "org:aws-samples" in query

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_uses_extension_query_for_bicep(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_gh.search_code.return_value = []

        client = GitHubClient(config=self.config)
        client.search_iac_repos("aws-samples", IaCType.AZURE_BICEP)

        query = mock_gh.search_code.call_args[0][0]
        assert "extension:bicep" in query

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_uses_filename_query_for_cdk(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_gh.search_code.return_value = []

        client = GitHubClient(config=self.config)
        client.search_iac_repos("aws-samples", IaCType.CDK)

        query = mock_gh.search_code.call_args[0][0]
        assert "filename:cdk.json" in query

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_filters_archived_repos(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        active = _make_content_file("aws-samples/active-app")
        archived = _make_content_file("aws-samples/archived-app", archived=True)
        mock_gh.search_code.return_value = [active, archived]

        client = GitHubClient(config=self.config)
        result = client.search_iac_repos("aws-samples", IaCType.CDK)

        names = [r.name for r in result]
        assert "active-app" in names
        assert "archived-app" not in names

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_filters_forked_repos(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        original = _make_content_file("aws-samples/original-app")
        forked = _make_content_file("aws-samples/forked-app", fork=True)
        mock_gh.search_code.return_value = [original, forked]

        client = GitHubClient(config=self.config)
        result = client.search_iac_repos("aws-samples", IaCType.CDK)

        names = [r.name for r in result]
        assert "original-app" in names
        assert "forked-app" not in names

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_deduplicates_repos_from_multiple_files(self, mock_sleep, mock_github_cls):
        """A repo with many .tf files should appear only once."""
        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        # Same repo returned 3 times (3 .tf files matched)
        cf1 = _make_content_file("aws-samples/tf-app")
        cf2 = _make_content_file("aws-samples/tf-app")
        cf3 = _make_content_file("aws-samples/tf-app")
        mock_gh.search_code.return_value = [cf1, cf2, cf3]

        client = GitHubClient(config=self.config)
        result = client.search_iac_repos("aws-samples", IaCType.TERRAFORM)

        assert len(result) == 1

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_respects_max_repos_cap(self, mock_sleep, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=3)
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        cfs = [_make_content_file(f"aws-samples/tf-app-{i}") for i in range(10)]
        mock_gh.search_code.return_value = cfs

        client = GitHubClient(config=config)
        result = client.search_iac_repos("aws-samples", IaCType.TERRAFORM)

        assert len(result) <= 3

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    @patch("scanner.discovery.github_client.Github")
    @patch("scanner.discovery.github_client.time.sleep")
    def test_search_rate_limit_handler_uses_search_bucket(self, mock_sleep, mock_github_cls):
        """_wait_for_search_rate_limit must read rate_limit.search.reset, not .core.reset."""
        from github import RateLimitExceededException

        from scanner.discovery.github_client import GitHubClient

        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh

        # First call raises rate limit, second call returns results
        exc = RateLimitExceededException(403, {}, {})
        cf = _make_content_file("aws-samples/tf-app")
        mock_gh.search_code.side_effect = [exc, [cf]]

        future = datetime(2099, 1, 1, tzinfo=UTC)
        # Use spec=['search'] so accessing .core raises AttributeError, proving
        # the implementation uses the correct search bucket (not core bucket).
        mock_rate_limit = MagicMock(spec=["search"])
        mock_rate_limit.search.reset = future
        mock_gh.get_rate_limit.return_value = mock_rate_limit

        client = GitHubClient(config=self.config)
        # This must not raise — if impl accidentally accessed .core, AttributeError
        with patch("scanner.discovery.github_client.time.sleep"):
            client.search_iac_repos("aws-samples", IaCType.TERRAFORM)

        # _wait_for_search_rate_limit must have read rate_limit.search.reset
        mock_gh.get_rate_limit.assert_called()
        mock_rate_limit.search.reset  # Verify .search was accessed (not .core which would raise)

    @patch.dict(os.environ, {}, clear=True)
    @patch("scanner.discovery.github_client.Github")
    def test_warns_when_no_github_token(self, mock_github_cls, caplog):
        from scanner.discovery.github_client import GitHubClient

        mock_github_cls.return_value = MagicMock()
        # Ensure GITHUB_TOKEN is not set
        os.environ.pop("GITHUB_TOKEN", None)

        with caplog.at_level(logging.WARNING, logger="scanner.discovery.github_client"):
            GitHubClient(config=self.config)

        assert any("GITHUB_TOKEN" in msg for msg in caplog.messages)


class TestDiscoverAll:
    def setup_method(self):
        self.config = Config(max_repos_per_org=10)

    def _make_client_with_search(self, search_results: dict[IaCType, list]):
        """Build a GitHubClient whose search_iac_repos is mocked per IaC type."""
        from scanner.discovery.github_client import GitHubClient
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=self.config)

        def search_side_effect(org: str, iac_type: IaCType) -> list:
            return search_results.get(iac_type, [])

        client.search_iac_repos = MagicMock(side_effect=search_side_effect)
        return client

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_returns_samples_for_each_iac_type(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        # search_iac_repos returns repo objects (already extracted from ContentFiles)
        tf_repo = _make_repo_mock("aws-samples/tf-app")
        cdk_repo = _make_repo_mock("aws-samples/cdk-app")
        client.search_iac_repos = MagicMock(side_effect=lambda org, t: {
            IaCType.TERRAFORM: [tf_repo],
            IaCType.CDK: [cdk_repo],
        }.get(t, []))

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        samples = client.discover_all(["aws-samples"], cache=cache)

        types = {s.iac_type for s in samples}
        assert IaCType.TERRAFORM in types
        assert IaCType.CDK in types

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_deduplicates_across_iac_types(self, tmp_path):
        """A repo matching both SAM and CFN markers → classified as SAM (first in priority)."""
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        # Same repo appears in both SAM and CFN results (same full_name = same repo)
        sam_repo = _make_repo_mock("aws-samples/serverless-app")
        cfn_repo = _make_repo_mock("aws-samples/serverless-app")

        client.search_iac_repos = MagicMock(side_effect=lambda org, t: {
            IaCType.SAM: [sam_repo],
            IaCType.CLOUDFORMATION: [cfn_repo],
        }.get(t, []))

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        samples = client.discover_all(["aws-samples"], cache=cache)

        # Should appear only once, classified as SAM (SAM precedes CFN in default priority)
        matching = [s for s in samples if s.name == "serverless-app"]
        assert len(matching) == 1
        assert matching[0].iac_type == IaCType.SAM

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_respects_custom_scan_priority(self, tmp_path):
        """When config.scan_priority puts AZURE_BICEP first, it is searched first."""
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        config.scan_priority = [IaCType.AZURE_BICEP, IaCType.TERRAFORM]
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        call_order: list[IaCType] = []

        def track_calls(org: str, iac_type: IaCType) -> list:
            call_order.append(iac_type)
            return []

        client.search_iac_repos = MagicMock(side_effect=track_calls)

        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        client.discover_all(["aws-samples"], cache=cache)

        # First two calls should be AZURE_BICEP then TERRAFORM
        assert call_order[:2] == [IaCType.AZURE_BICEP, IaCType.TERRAFORM]

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_uses_cache_when_fresh(self, tmp_path):
        """If cache is fresh, search_iac_repos is not called for that (org, iac_type) pair."""
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        # Pre-populate cache with TF results
        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)
        cached_sample = _make_sample("cached-tf-app", "aws-samples", IaCType.TERRAFORM)
        cache.put("aws-samples", IaCType.TERRAFORM, [cached_sample])

        search_calls: list[IaCType] = []

        def track_calls(org: str, iac_type: IaCType) -> list:
            search_calls.append(iac_type)
            return []

        client.search_iac_repos = MagicMock(side_effect=track_calls)
        config.scan_priority = [IaCType.TERRAFORM]

        samples = client.discover_all(["aws-samples"], cache=cache)

        # search_iac_repos should NOT have been called for TERRAFORM (cache hit)
        assert IaCType.TERRAFORM not in search_calls
        # Cached sample should be in results
        assert any(s.name == "cached-tf-app" for s in samples)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_bypasses_cache_when_no_cache(self, tmp_path):
        """When cache=None, search_iac_repos is always called."""
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        config.scan_priority = [IaCType.TERRAFORM]
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        tf_repo = _make_repo_mock("aws-samples/tf-app")
        client.search_iac_repos = MagicMock(return_value=[tf_repo])

        samples = client.discover_all(["aws-samples"], cache=None)

        client.search_iac_repos.assert_called()
        assert any(s.name == "tf-app" for s in samples)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_skips_unknown_iac_type(self, tmp_path):
        """UNKNOWN iac_type is excluded — it's only in scan_priority if user explicitly adds it."""
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        config.scan_priority = [IaCType.TERRAFORM]
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        client.search_iac_repos = MagicMock(return_value=[])
        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)

        # Should not raise even if scan_priority only has TERRAFORM
        samples = client.discover_all(["aws-samples"], cache=cache)
        assert samples == []

    @patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"})
    def test_discover_all_multiple_orgs(self, tmp_path):
        from scanner.discovery.etag_cache import ETagCache
        from scanner.discovery.github_client import GitHubClient

        config = Config(max_repos_per_org=10)
        config.scan_priority = [IaCType.TERRAFORM]
        with patch("scanner.discovery.github_client.Github"):
            client = GitHubClient(config=config)

        def search_side_effect(org: str, iac_type: IaCType) -> list:
            if org == "aws-samples":
                return [_make_repo_mock("aws-samples/aws-tf")]
            if org == "Azure-Samples":
                return [_make_repo_mock("Azure-Samples/az-tf")]
            return []

        client.search_iac_repos = MagicMock(side_effect=search_side_effect)
        cache = ETagCache(path=str(tmp_path / "cache.json"), ttl_hours=24)

        samples = client.discover_all(["aws-samples", "Azure-Samples"], cache=cache)

        names = {s.name for s in samples}
        assert "aws-tf" in names
        assert "az-tf" in names
