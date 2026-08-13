from pathlib import Path

import pytest

from xrd.pattern import analyze_pattern, read_cpi, read_json_pattern, read_pattern, read_xrdml


def test_read_opxrd_json():
    pattern = read_json_pattern(
        {
            "two_theta_values": [10 + 0.1 * index for index in range(9)],
            "intensity_values": [1, 1, 1, 1, 20, 1, 1, 1, 1],
            "label": '{"xray_info":"{\\"primary_wavelength\\":1.5406}"}',
        }
    )
    assert pattern.wavelength == 1.5406
    assert analyze_pattern(pattern).detected_peak_count == 1


def test_read_xrdml(tmp_path: Path):
    path = tmp_path / "sample.xrdml"
    path.write_text(
        """<?xml version="1.0"?>
<xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/2.3">
  <usedWavelength><kAlpha1>1.5406</kAlpha1></usedWavelength>
  <xRayTube><anodeMaterial>Cu</anodeMaterial></xRayTube>
  <dataPoints><positions axis="2Theta"><startPosition>10</startPosition>
  <endPosition>10.4</endPosition></positions><counts>1 2 20 2 1</counts></dataPoints>
</xrdMeasurements>""",
        encoding="utf-8",
    )
    pattern = read_xrdml(path)
    assert pattern.two_theta == [10.0, 10.1, 10.2, 10.3, 10.4]
    assert pattern.radiation == "Cu"


def test_read_sietronics_cpi(tmp_path: Path):
    path = tmp_path / "sample.cpi"
    path.write_text(
        "SIETRONICS XRD SCAN\n10.0\n10.04\n0.02\nCu\n1.54056\n"
        "13-8-2026\n1\nReference sample\nSCANDATA\n100\n250\n120\n",
        encoding="ascii",
    )
    pattern = read_pattern(path)
    assert pattern.two_theta == pytest.approx([10.0, 10.02, 10.04])
    assert pattern.intensity == [100.0, 250.0, 120.0]
    assert pattern.wavelength == 1.54056
    assert pattern.metadata["format"] == "sietronics_cpi"


def test_cpi_rejects_scan_length_mismatch(tmp_path: Path):
    path = tmp_path / "broken.cpi"
    path.write_text(
        "SIETRONICS XRD SCAN\n10.0\n10.04\n0.02\nCu\n1.54056\n"
        "13-8-2026\n1\nReference sample\nSCANDATA\n100\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="scan length mismatch"):
        read_cpi(path)
