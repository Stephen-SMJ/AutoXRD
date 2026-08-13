from pathlib import Path

import pytest

from benchmarks.run_agent_benchmark import (
    DockerBashTool,
    ScopedFileReadTool,
    _atomic_json,
    _extract_json,
    _load_records,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"valid":true,"violations":[]}', {"valid": True, "violations": []}),
        ('```json\n{"diagnosis":"zero_shift","action":"refine_zero"}\n```',
         {"diagnosis": "zero_shift", "action": "refine_zero"}),
        ('Result: {"phases":["corundum"]}', {"phases": ["corundum"]}),
    ],
)
def test_extract_json(text, expected):
    assert _extract_json(text) == expected


def test_extract_json_rejects_plain_text():
    with pytest.raises(ValueError, match="no JSON object"):
        _extract_json("I cannot answer")


def test_scoped_read_rejects_outside_workspace(tmp_path: Path):
    result = ScopedFileReadTool(tmp_path).execute("/etc/passwd")
    assert result.is_error
    assert "boundary violation" in result.content


def test_docker_bash_has_no_host_repo_or_network(tmp_path: Path):
    (tmp_path / "visible.txt").write_text("case data", encoding="utf-8")
    tool = DockerBashTool(tmp_path, "lambda-sandbox:preload-safe")
    visible = tool.execute("test -r visible.txt")
    hidden = tool.execute("test ! -r /home/ubuntu/autoxrd/.git/HEAD")
    assert not visible.is_error
    assert not hidden.is_error


def test_resume_preserves_error_records_until_explicit_recovery(tmp_path: Path):
    records = tmp_path / "records"
    _atomic_json(records / "case-1.json", {
        "id": "case-1", "status": "error", "answer": {}, "attempt": 1,
    })
    assert _load_records(records)["case-1"]["status"] == "error"
    assert not (records / "case-1.json.tmp").exists()
