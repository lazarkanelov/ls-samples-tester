"""Tests for GitHub discovery, IaC detection, and sample registry."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from scanner.config import CloudProvider, Config, IaCType
from scanner.models import Sample

# ---------------------------------------------------------------------------
# IaCDetector tests
# ---------------------------------------------------------------------------

class TestIaCDetector:
    def setup_method(self):
        from scanner.discovery.iac_detector import IaCDetector
        self.config = Config()
        self.detector = IaCDetector(config=self.config)

    def _make_tree(self, paths: list[str]) -> MagicMock:
        """Build a mock GitHub tree object from a list of file paths."""
        tree = MagicMock()
        elements = []
        for p in paths:
            el = MagicMock()
            el.path = p
            elements.append(el)
        tree.tree = elements
        return tree

    def test_detects_cdk(self):
        tree = self._make_tree(["cdk.json", "lib/my-stack.ts", "package.json"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.CDK

    def test_detects_sam_with_samconfig(self):
        tree = self._make_tree(["template.yaml", "samconfig.toml", "src/handler.py"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.SAM

    def test_detects_cloudformation_without_samconfig(self):
        tree = self._make_tree(["template.yaml", "README.md"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.CLOUDFORMATION

    def test_detects_terraform_by_tf_extension(self):
        tree = self._make_tree(["main.tf", "variables.tf", "outputs.tf"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.TERRAFORM

    def test_detects_pulumi(self):
        tree = self._make_tree(["Pulumi.yaml", "index.ts", "package.json"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.PULUMI

    def test_detects_serverless(self):
        tree = self._make_tree(["serverless.yml", "handler.js"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.SERVERLESS

    def test_detects_azure_arm(self):
        tree = self._make_tree(["azuredeploy.json", "azuredeploy.parameters.json"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.AZURE_ARM

    def test_detects_azure_bicep(self):
        tree = self._make_tree(["main.bicep", "modules/storage.bicep"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.AZURE_BICEP

    def test_returns_unknown_for_no_markers(self):
        tree = self._make_tree(["README.md", "src/main.py", ".gitignore"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.UNKNOWN

    def test_cdk_takes_priority_over_cfn(self):
        # A repo with both cdk.json and template.yaml → CDK wins
        tree = self._make_tree(["cdk.json", "template.yaml", "lib/stack.ts"])
        result = self.detector.detect_from_tree(tree)
        assert result == IaCType.CDK

    def test_cloud_provider_for_azure_arm(self):
        assert self.detector.get_cloud_provider(IaCType.AZURE_ARM) == CloudProvider.AZURE

    def test_cloud_provider_for_azure_bicep(self):
        assert self.detector.get_cloud_provider(IaCType.AZURE_BICEP) == CloudProvider.AZURE

    def test_cloud_provider_for_cdk(self):
        assert self.detector.get_cloud_provider(IaCType.CDK) == CloudProvider.AWS

    def test_detect_batch_returns_samples_for_iac_repos(self):
        """detect_batch converts raw GitHub repos to Sample objects, skipping UNKNOWN."""
        from scanner.discovery.iac_detector import IaCDetector

        config = Config()
        detector = IaCDetector(config=config)

        repo = MagicMock()
        repo.name = "my-cdk-app"
        repo.full_name = "aws-samples/my-cdk-app"
        repo.html_url = "https://github.com/aws-samples/my-cdk-app"
        repo.description = "CDK app"
        repo.language = "TypeScript"
        repo.default_branch = "main"
        repo.updated_at = datetime(2024, 6, 1, tzinfo=__import__("datetime").timezone.utc)
        repo.archived = False
        repo.fork = False
        repo.get_topics.return_value = ["cdk"]

        tree_mock = MagicMock()
        el = MagicMock()
        el.path = "cdk.json"
        tree_mock.tree = [el]
        repo.get_git_tree.return_value = tree_mock

        samples = detector.detect_batch([repo], existing=[])
        assert len(samples) == 1
        assert samples[0].name == "my-cdk-app"
        assert samples[0].iac_type == IaCType.CDK

    def test_detect_batch_skips_unknown_repos(self):
        """detect_batch skips repos with no recognized IaC markers."""
        from scanner.discovery.iac_detector import IaCDetector

        config = Config()
        detector = IaCDetector(config=config)

        repo = MagicMock()
        repo.name = "plain-tutorial"
        repo.full_name = "aws-samples/plain-tutorial"
        repo.html_url = "https://github.com/aws-samples/plain-tutorial"
        repo.description = ""
        repo.language = "Python"
        repo.default_branch = "main"
        repo.updated_at = datetime(2024, 1, 1, tzinfo=__import__("datetime").timezone.utc)
        repo.get_topics.return_value = []

        tree_mock = MagicMock()
        el = MagicMock()
        el.path = "README.md"
        tree_mock.tree = [el]
        repo.get_git_tree.return_value = tree_mock

        samples = detector.detect_batch([repo], existing=[])
        assert samples == []


# ---------------------------------------------------------------------------
# GitHubClient tests
# ---------------------------------------------------------------------------

class TestGitHubClient:
    def setup_method(self):
        self.config = Config(max_repos_per_org=5)

    def _make_mock_repo(self, name: str, updated: datetime | None = None) -> MagicMock:
        repo = MagicMock()
        repo.name = name
        repo.full_name = f"aws-samples/{name}"
        repo.html_url = f"https://github.com/aws-samples/{name}"
        repo.description = f"Description of {name}"
        repo.get_topics.return_value = ["aws", "cdk"]
        repo.language = "TypeScript"
        repo.default_branch = "main"
        repo.updated_at = updated or datetime(2024, 1, 1, tzinfo=UTC)
        repo.archived = False
        repo.fork = False
        return repo

    @patch("scanner.discovery.github_client.Github")
    def test_list_repos_returns_up_to_cap(self, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        repos = [self._make_mock_repo(f"repo-{i}") for i in range(10)]
        mock_org.get_repos.return_value = repos

        client = GitHubClient(config=self.config)
        result = client.list_repos("aws-samples")

        assert len(result) <= 5

    @patch("scanner.discovery.github_client.Github")
    def test_list_repos_skips_archived(self, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        active = self._make_mock_repo("active-repo")
        archived = self._make_mock_repo("archived-repo")
        archived.archived = True
        mock_org.get_repos.return_value = [active, archived]

        client = GitHubClient(config=self.config)
        result = client.list_repos("aws-samples")

        names = [r.name for r in result]
        assert "active-repo" in names
        assert "archived-repo" not in names

    @patch("scanner.discovery.github_client.Github")
    def test_list_repos_skips_forks(self, mock_github_cls):
        from scanner.discovery.github_client import GitHubClient

        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        original = self._make_mock_repo("original-repo")
        fork = self._make_mock_repo("forked-repo")
        fork.fork = True
        mock_org.get_repos.return_value = [original, fork]

        client = GitHubClient(config=self.config)
        result = client.list_repos("aws-samples")

        names = [r.name for r in result]
        assert "original-repo" in names
        assert "forked-repo" not in names

    @patch("scanner.discovery.github_client.Github")
    def test_list_repos_retries_after_rate_limit(self, mock_github_cls):
        """Rate limit during pagination causes wait then resumes — does not drop repos."""
        from github import RateLimitExceededException

        from scanner.discovery.github_client import GitHubClient

        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_org = MagicMock()
        mock_github.get_organization.return_value = mock_org

        repo_a = self._make_mock_repo("repo-a")
        repo_b = self._make_mock_repo("repo-b")

        # Iterator raises RateLimitExceededException on first next(), then yields both repos
        rate_exc = RateLimitExceededException(403, {}, {})
        mock_org.get_repos.return_value = iter([rate_exc, repo_a, repo_b])

        # Patch iter() so the exception is raised on iteration
        def side_effect_iter(seq):
            for item in seq:
                if isinstance(item, RateLimitExceededException):
                    raise item
                yield item

        # Simulate iter behavior where exception occurs mid-pagination
        real_iter = [repo_a, repo_b]
        call_count = [0]

        def patched_next(it):  # noqa: ARG001
            call_count[0] += 1
            if call_count[0] == 1:
                raise RateLimitExceededException(403, {}, {})
            return real_iter.pop(0) if real_iter else (_ for _ in ()).throw(StopIteration)

        mock_org.get_repos.return_value = [repo_a, repo_b]

        # Use a simpler approach: make iter return an object whose __next__ raises once
        class OnceRateLimitIter:
            def __init__(self):
                self._items = [repo_a, repo_b]
                self._hit = False
            def __iter__(self):
                return self
            def __next__(self):
                if not self._hit:
                    self._hit = True
                    raise RateLimitExceededException(403, {}, {})
                if self._items:
                    return self._items.pop(0)
                raise StopIteration

        mock_org.get_repos.return_value = OnceRateLimitIter()
        mock_github.get_rate_limit.return_value = MagicMock(
            core=MagicMock(reset=datetime(2099, 1, 1, tzinfo=UTC))
        )

        with patch("scanner.discovery.github_client.time.sleep"):
            client = GitHubClient(config=Config(max_repos_per_org=10))
            result = client.list_repos("aws-samples")

        # Both repos should be returned (rate limit retry worked)
        names = [r.name for r in result]
        assert "repo-a" in names
        assert "repo-b" in names


# ---------------------------------------------------------------------------
# SampleRegistry tests
# ---------------------------------------------------------------------------

class TestSampleRegistry:
    def _make_sample(self, name: str = "test-repo") -> Sample:
        return Sample(
            name=name,
            org="aws-samples",
            url=f"https://github.com/aws-samples/{name}",
            iac_type=IaCType.CDK,
            cloud_provider=CloudProvider.AWS,
            description="Test",
            topics=[],
            language="TypeScript",
            default_branch="main",
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )

    def test_save_and_load_round_trip(self, tmp_path):
        from scanner.discovery.registry import SampleRegistry

        registry_path = str(tmp_path / "registry.json")
        registry = SampleRegistry(path=registry_path)

        samples = [self._make_sample("app-a"), self._make_sample("app-b")]
        registry.save(samples)

        loaded = registry.load()
        assert len(loaded) == 2
        names = {s.name for s in loaded}
        assert names == {"app-a", "app-b"}

    def test_load_returns_empty_list_when_file_missing(self, tmp_path):
        from scanner.discovery.registry import SampleRegistry

        registry = SampleRegistry(path=str(tmp_path / "missing.json"))
        assert registry.load() == []

    def test_save_partial_merges_by_org(self, tmp_path):
        from scanner.discovery.registry import SampleRegistry

        registry_path = str(tmp_path / "registry.json")
        registry = SampleRegistry(path=registry_path)

        aws_sample = self._make_sample("aws-app")
        registry.save_partial("aws-samples", [aws_sample])

        azure_sample = Sample(
            name="azure-app",
            org="Azure-Samples",
            url="https://github.com/Azure-Samples/azure-app",
            iac_type=IaCType.AZURE_ARM,
            cloud_provider=CloudProvider.AZURE,
            description="Azure test",
            topics=[],
            language="JSON",
            default_branch="main",
            updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        registry.save_partial("Azure-Samples", [azure_sample])

        loaded = registry.load()
        assert len(loaded) == 2
        orgs = {s.org for s in loaded}
        assert "aws-samples" in orgs
        assert "Azure-Samples" in orgs

    def test_incremental_update_skips_unchanged(self, tmp_path):
        from scanner.discovery.registry import SampleRegistry

        registry_path = str(tmp_path / "registry.json")
        registry = SampleRegistry(path=registry_path)

        original = self._make_sample("my-app")
        registry.save([original])

        # Same updated_at → should be considered unchanged
        existing = registry.load()
        same_updated = self._make_sample("my-app")  # same updated_at
        is_new = registry.is_new_or_updated(same_updated, existing)
        assert not is_new

    def test_incremental_update_includes_newer(self, tmp_path):
        from scanner.discovery.registry import SampleRegistry

        registry_path = str(tmp_path / "registry.json")
        registry = SampleRegistry(path=registry_path)

        original = self._make_sample("my-app")
        registry.save([original])

        existing = registry.load()
        newer = Sample(
            name="my-app",
            org="aws-samples",
            url="https://github.com/aws-samples/my-app",
            iac_type=IaCType.CDK,
            cloud_provider=CloudProvider.AWS,
            description="Updated",
            topics=[],
            language="TypeScript",
            default_branch="main",
            updated_at=datetime(2025, 1, 1, tzinfo=UTC),  # newer
        )
        is_new = registry.is_new_or_updated(newer, existing)
        assert is_new
