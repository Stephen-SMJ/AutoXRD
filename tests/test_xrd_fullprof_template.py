from pathlib import Path

import pytest

from xrd.fullprof import run_fullprof_template
from xrd.le_bail import default_fullprof_executable


def test_fullprof_discovery_honors_benchmark_environment(monkeypatch, tmp_path: Path):
    executable = tmp_path / "fp2k"
    executable.write_text("binary", encoding="utf-8")
    monkeypatch.delenv("AUTOXRD_FULLPROF_BIN", raising=False)
    monkeypatch.setenv("FULLPROF_BIN", str(executable))
    assert default_fullprof_executable() == executable


def test_template_runner_rejects_unsafe_case(tmp_path: Path):
    template = tmp_path / "input.pcr"
    pattern = tmp_path / "input.dat"
    template.write_text("PCR", encoding="utf-8")
    pattern.write_text("10 1", encoding="utf-8")
    with pytest.raises(ValueError, match="safe filename"):
        run_fullprof_template(Path("fp2k"), template, pattern, tmp_path, "../escape")


def test_template_runner_refuses_nonempty_run_directory(tmp_path: Path):
    template = tmp_path / "input.pcr"
    pattern = tmp_path / "input.dat"
    run_dir = tmp_path / "run_001"
    template.write_text("PCR", encoding="utf-8")
    pattern.write_text("10 1", encoding="utf-8")
    run_dir.mkdir()
    (run_dir / "evidence.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        run_fullprof_template(Path("fp2k"), template, pattern, tmp_path, "run_001")
