import pytest

from benchmarks.run_agent_benchmark import _extract_json


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
