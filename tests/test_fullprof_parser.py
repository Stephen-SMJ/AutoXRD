from pathlib import Path

from xrd.fullprof import parse_fullprof_output


def test_parse_fullprof_metrics(tmp_path: Path):
    (tmp_path / "sample.out").write_text(
        """
 => Conventional Rietveld Rp,Rwp,Re and Chi2:  13.8  17.8  5.80  9.423
 => Global user-weigthed Chi2 (Bragg contrib.):  11.7
 => Convergence reached at this CYCLE !!!!
 => Bragg R-factor: 3.58 Vol: 158.5 Fract(%): 100.00(14.54)
""",
        encoding="utf-8",
    )

    result = parse_fullprof_output("sample", tmp_path, 0, 1.25)

    assert result.success
    assert result.converged
    assert result.patterns[0].rwp == 17.8
    assert result.final_pattern.rwp == 17.8
    assert result.global_chi2 == 11.7
    assert result.phases[0].bragg_r == 3.58
