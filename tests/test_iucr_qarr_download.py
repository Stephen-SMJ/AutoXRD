import zipfile
from pathlib import Path

from benchmarks.download_iucr_qarr import REQUIRED_STEMS, extract_required


def test_extract_required_normalizes_historical_uppercase_names(tmp_path: Path) -> None:
    archive = tmp_path / "cpi.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for stem in REQUIRED_STEMS:
            bundle.writestr(f"{stem.upper()}.CPI", "5.0 100\n5.02 110\n")
    destination = tmp_path / "patterns"
    checksums = extract_required(archive, destination)
    assert len(checksums) == 20
    assert all((destination / f"{stem}.cpi").is_file() for stem in REQUIRED_STEMS)
