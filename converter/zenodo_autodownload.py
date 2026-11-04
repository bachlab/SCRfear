"""Download and extract SCRFear source datasets from Zenodo."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import requests

from .lib.tsv_configs import DATASETS


def download_dataset(
    dataset: str,
    raw_root: str | Path = "Datasets",
    force: bool = False,
):
    """Download and extract one configured dataset."""
    config = DATASETS[dataset]
    dataset_dir = Path(raw_root) / dataset
    archive = dataset_dir / "Data.zip"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    if archive.exists() and not force:
        print(f"[{dataset}] Using existing {archive}")
    else:
        url = (
            f"https://zenodo.org/records/{config['zenodo_record']}/files/"
            "Data.zip?download=1"
        )
        partial = archive.with_suffix(".zip.part")
        print(f"[{dataset}] Downloading Data.zip from Zenodo")
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with partial.open("wb") as destination:
                shutil.copyfileobj(response.raw, destination)
        partial.replace(archive)

    print(f"[{dataset}] Extracting {archive.name}")
    root = dataset_dir.resolve()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            destination = (dataset_dir / member.filename).resolve()
            if root != destination and root not in destination.parents:
                raise ValueError(
                    f"Unsafe path in {archive.name}: {member.filename}"
                )
        source.extractall(dataset_dir)
    print(f"[{dataset}] Raw data ready in {dataset_dir.resolve()}")
