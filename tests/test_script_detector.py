"""Tests for ScriptDetector."""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

from scanner.script_detector import DetectedScript, ScriptDetector, ScriptOutcome


class TestDataclasses:
    def test_detected_script_fields(self):
        s = DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])
        assert s.path == "Makefile"
        assert s.script_type == "makefile"
        assert s.command == ["make", "test"]

    def test_script_outcome_fields(self):
        o = ScriptOutcome(passed=True, summary="All OK", details=["Exit code 0"])
        assert o.passed is True
        assert o.summary == "All OK"
        assert o.details == ["Exit code 0"]


class TestDetectMakefile:
    def test_detects_makefile_with_test_target(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("test:\n\tpython -m pytest\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "makefile"
        assert scripts[0].command == ["make", "test"]

    def test_ignores_makefile_without_test_target(self, tmp_path):
        makefile = tmp_path / "Makefile"
        makefile.write_text("build:\n\tnpm run build\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 0

    def test_makefile_takes_priority_over_shell_scripts(self, tmp_path):
        (tmp_path / "Makefile").write_text("test:\n\techo test\n")
        (tmp_path / "test.sh").write_text("#!/bin/bash\necho test\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert scripts[0].script_type == "makefile"


class TestDetectShellScripts:
    def test_detects_test_sh_in_root(self, tmp_path):
        script = tmp_path / "test.sh"
        script.write_text("#!/bin/bash\necho test\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "shell"
        assert scripts[0].command == ["bash", str(script)]

    def test_detects_test_star_sh_pattern(self, tmp_path):
        script = tmp_path / "test_integration.sh"
        script.write_text("#!/bin/bash\necho test\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "shell"

    def test_detects_test_sh_in_scripts_subdir(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "test.sh"
        script.write_text("#!/bin/bash\necho test\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "shell"

    def test_shell_takes_priority_over_python_tests(self, tmp_path):
        (tmp_path / "test.sh").write_text("#!/bin/bash\necho test\n")
        (tmp_path / "test_app.py").write_text("def test_foo(): pass\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert scripts[0].script_type == "shell"


class TestDetectPythonTests:
    def test_detects_test_underscore_py(self, tmp_path):
        test_file = tmp_path / "test_app.py"
        test_file.write_text("def test_foo(): pass\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "python"
        assert scripts[0].command == [sys.executable, str(test_file)]

    def test_detects_test_py_in_tests_subdir(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_integration.py"
        test_file.write_text("def test_bar(): pass\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert len(scripts) == 1
        assert scripts[0].script_type == "python"

    def test_uses_sys_executable_not_bare_python(self, tmp_path):
        test_file = tmp_path / "test_app.py"
        test_file.write_text("def test_foo(): pass\n")

        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert scripts[0].command[0] == sys.executable
        assert "python" not in scripts[0].command[0] or sys.executable == scripts[0].command[0]


class TestNoScriptsFound:
    def test_returns_empty_list_when_no_scripts(self, tmp_path):
        detector = ScriptDetector()
        scripts = detector.detect(tmp_path)
        assert scripts == []


class TestRunScripts:
    @patch("scanner.script_detector.subprocess.run")
    def test_run_first_script_only(self, mock_run, tmp_path):
        """run() executes only the first detected script."""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "Tests passed"
        proc.stderr = ""
        mock_run.return_value = proc

        scripts = [
            DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"]),
            DetectedScript(path="test.sh", script_type="shell", command=["bash", "test.sh"]),
        ]
        detector = ScriptDetector()
        outcome = detector.run(tmp_path, scripts)
        assert mock_run.call_count == 1
        assert outcome.passed is True

    @patch("scanner.script_detector.subprocess.run")
    def test_exit_code_zero_means_passed(self, mock_run, tmp_path):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "All tests passed"
        proc.stderr = ""
        mock_run.return_value = proc

        scripts = [DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])]
        detector = ScriptDetector()
        outcome = detector.run(tmp_path, scripts)
        assert outcome.passed is True

    @patch("scanner.script_detector.subprocess.run")
    def test_nonzero_exit_code_means_failed(self, mock_run, tmp_path):
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "FAILED 2 tests"
        mock_run.return_value = proc

        scripts = [DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])]
        detector = ScriptDetector()
        outcome = detector.run(tmp_path, scripts)
        assert outcome.passed is False

    @patch("scanner.script_detector.subprocess.run")
    def test_run_with_correct_cwd(self, mock_run, tmp_path):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock_run.return_value = proc

        scripts = [DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])]
        detector = ScriptDetector()
        detector.run(tmp_path, scripts)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == tmp_path

    @patch("scanner.script_detector.subprocess.run")
    def test_run_with_timeout(self, mock_run, tmp_path):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock_run.return_value = proc

        scripts = [DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])]
        detector = ScriptDetector()
        detector.run(tmp_path, scripts, timeout=30)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 30

    def test_run_empty_scripts_returns_no_scripts_found(self, tmp_path):
        detector = ScriptDetector()
        outcome = detector.run(tmp_path, [])
        assert outcome.passed is True
        assert "No test scripts found" in outcome.summary

    @patch(
        "scanner.script_detector.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["make", "test"], timeout=60),
    )
    def test_run_handles_timeout(self, mock_run, tmp_path):
        scripts = [DetectedScript(path="Makefile", script_type="makefile", command=["make", "test"])]
        detector = ScriptDetector()
        outcome = detector.run(tmp_path, scripts)
        assert outcome.passed is False
        assert "timeout" in outcome.summary.lower()
