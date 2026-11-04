"""Update the PsPM ECG inventory with a low-disk batch workflow."""

from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path

import requests

from .ecg_catalog import (
    OPEN_DATA_URL,
    DatasetDownload,
    fetch_catalog,
    fetch_dataset_download,
    plan_batches,
)
from .ecg_inspection import inspect_downloads


INVENTORY_COLUMNS = [
    "dataset",
    "zenodo_record",
    "ecg_recorded",
    "ecg_sampling_rate_hz",
    "physiological_files_checked",
    "evidence",
    "status",
]


def _load_inventory(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = [
            column
            for column in INVENTORY_COLUMNS
            if column not in reader.fieldnames
        ]
        if missing:
            raise ValueError(
                f"{path} is missing columns: {', '.join(missing)}"
            )
        return [
            {column: row.get(column, "") for column in INVENTORY_COLUMNS}
            for row in reader
        ]


def _write_inventory(path: Path, rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _merge_catalog(rows, catalog):
    by_dataset = {row["dataset"]: row for row in rows}
    merged = []
    for entry in catalog:
        row = by_dataset.pop(entry.dataset, None)
        if row is None:
            row = {
                "dataset": entry.dataset,
                "zenodo_record": entry.record_url,
                "ecg_recorded": "n/a",
                "ecg_sampling_rate_hz": "n/a",
                "physiological_files_checked": "0",
                "evidence": "",
                "status": "pending",
            }
        elif not row["zenodo_record"]:
            row["zenodo_record"] = entry.record_url
        merged.append(row)
    merged.extend(by_dataset.values())
    return merged


def _checksum(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(
    remote,
    dataset_dir: Path,
    session: requests.Session,
) -> Path:
    destination = dataset_dir / Path(remote.name).name
    partial = destination.with_suffix(destination.suffix + ".part")

    def valid_download(path):
        if not path.is_file() or path.stat().st_size != remote.size:
            return False
        if not remote.checksum or ":" not in remote.checksum:
            return True
        algorithm, expected = remote.checksum.split(":", 1)
        algorithm = algorithm.casefold()
        if algorithm not in hashlib.algorithms_available:
            return True
        return _checksum(path, algorithm).casefold() == expected.casefold()

    if valid_download(destination):
        return destination
    if valid_download(partial):
        partial.replace(destination)
        return destination
    if partial.is_file() and partial.stat().st_size >= remote.size:
        partial.unlink()

    existing = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    with session.get(
        remote.url,
        headers=headers,
        stream=True,
        timeout=(30, 180),
    ) as response:
        response.raise_for_status()
        append = existing > 0 and response.status_code == 206
        mode = "ab" if append else "wb"
        with partial.open(mode) as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)

    actual_size = partial.stat().st_size
    if actual_size != remote.size:
        raise OSError(
            f"{remote.name} is incomplete: expected {remote.size} bytes, "
            f"downloaded {actual_size}"
        )
    partial.replace(destination)

    if not valid_download(destination):
        raise OSError(f"Checksum mismatch for {remote.name}")
    return destination


def _safe_remove_dataset_cache(cache_root: Path, dataset_dir: Path):
    root = cache_root.resolve()
    target = dataset_dir.resolve()
    if not (cache_root / ".scrfear_ecg_cache").is_file():
        raise ValueError("ECG cache marker is missing; refusing deletion")
    if target.parent != root:
        raise ValueError(f"Refusing to delete unsafe cache path: {target}")
    if target.is_dir():
        shutil.rmtree(target)


def _available_bytes(path: Path) -> int:
    existing = path
    while not existing.exists():
        existing = existing.parent
    return shutil.disk_usage(existing).free


def _remaining_download_bytes(
    download: DatasetDownload,
    dataset_dir: Path,
) -> int:
    remaining = 0
    for remote in download.files:
        destination = dataset_dir / Path(remote.name).name
        partial = destination.with_suffix(destination.suffix + ".part")
        if destination.is_file() and destination.stat().st_size == remote.size:
            continue
        downloaded = partial.stat().st_size if partial.is_file() else 0
        remaining += max(0, remote.size - downloaded)
    return remaining


def _human_size(size: int) -> str:
    return f"{size / 1024**3:.2f} GiB"


def _selected_entries(catalog, datasets):
    if not datasets:
        return catalog
    requested = set(datasets)
    available = {entry.dataset for entry in catalog}
    unknown = sorted(requested - available)
    if unknown:
        raise ValueError(
            "Datasets not found on the PsPM Open Data page: "
            + ", ".join(unknown)
        )
    return [entry for entry in catalog if entry.dataset in requested]


def update_ecg_inventory(
    inventory_path: str | Path = "metadata/pspm_ecg_inventory.csv",
    cache_root: str | Path = "ECG_Download_Cache",
    batch_size: int = 5,
    max_batch_gb: float = 10,
    reserve_gb: float = 2,
    max_batches: int | None = None,
    datasets: list[str] | None = None,
    keep_downloads: bool = False,
    catalog_url: str = OPEN_DATA_URL,
    session: requests.Session | None = None,
) -> dict:
    """Inspect pending PsPM datasets and save progress after each dataset."""
    if max_batch_gb <= 0:
        raise ValueError("Maximum batch size must be positive")
    if reserve_gb < 0:
        raise ValueError("Disk reserve cannot be negative")
    if max_batches is not None and max_batches < 1:
        raise ValueError("Maximum batches must be at least 1")

    inventory_path = Path(inventory_path)
    cache_root = Path(cache_root)
    protected = {
        Path.cwd().resolve(),
        Path("Datasets").resolve(),
        Path("Converted_Datasets").resolve(),
        Path("Corpus").resolve(),
    }
    if cache_root.resolve() in protected:
        raise ValueError("ECG cache must be a dedicated directory")
    marker = cache_root / ".scrfear_ecg_cache"
    if cache_root.exists() and any(cache_root.iterdir()) and not marker.is_file():
        raise ValueError(
            f"{cache_root} is not an SCRFear ECG cache; choose an empty directory"
        )
    cache_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "Temporary downloads managed by scrfear ecg-inventory.\n",
        encoding="utf-8",
    )

    client = session or requests.Session()
    catalog = fetch_catalog(client, catalog_url)
    rows = _merge_catalog(_load_inventory(inventory_path), catalog)
    _write_inventory(inventory_path, rows)
    row_lookup = {row["dataset"]: row for row in rows}

    candidates = [
        entry
        for entry in _selected_entries(catalog, datasets)
        if row_lookup[entry.dataset]["status"] != "verified"
    ]
    if not candidates:
        print("[ECG] No pending datasets.")
        return {
            "catalogue": len(catalog),
            "processed": 0,
            "verified": 0,
            "needs_review": 0,
            "failed": 0,
        }

    downloads: list[DatasetDownload] = []
    manifest_failures = 0
    for entry in candidates:
        try:
            downloads.append(fetch_dataset_download(entry, client))
        except Exception as error:
            row = row_lookup[entry.dataset]
            row["evidence"] = f"Could not read Zenodo manifest: {error}"
            row["status"] = "download_error"
            manifest_failures += 1
            _write_inventory(inventory_path, rows)

    batches = plan_batches(
        downloads,
        batch_size=batch_size,
        max_batch_bytes=int(max_batch_gb * 1024**3),
    )
    if max_batches is not None:
        batches = batches[:max_batches]

    processed = 0
    verified = 0
    needs_review = 0
    failed = manifest_failures
    reserve_bytes = int(reserve_gb * 1024**3)

    for batch_number, batch in enumerate(batches, start=1):
        total_size = sum(item.size for item in batch)
        names = ", ".join(item.entry.dataset for item in batch)
        print(
            f"[ECG] Batch {batch_number}: {names} "
            f"({_human_size(total_size)} download)"
        )

        for download in batch:
            dataset = download.entry.dataset
            dataset_dir = cache_root / dataset
            if dataset_dir.resolve().parent != cache_root.resolve():
                raise ValueError(f"Unsafe dataset name in catalogue: {dataset}")
            required = (
                _remaining_download_bytes(download, dataset_dir)
                + reserve_bytes
            )
            if _available_bytes(cache_root) < required:
                row = row_lookup[dataset]
                row["evidence"] = (
                    f"Not enough free space for {_human_size(download.size)} "
                    f"plus the {_human_size(reserve_bytes)} reserve."
                )
                row["status"] = "download_error"
                _write_inventory(inventory_path, rows)
                failed += 1
                print(f"[{dataset}] Skipped: not enough free disk space")
                continue

            dataset_dir.mkdir(parents=True, exist_ok=True)
            try:
                paths = []
                for remote in download.files:
                    print(
                        f"[{dataset}] Downloading {remote.name} "
                        f"({_human_size(remote.size)})"
                    )
                    paths.append(
                        _download_file(remote, dataset_dir, client)
                    )
                result = inspect_downloads(paths)
                row = row_lookup[dataset]
                row.update(
                    {
                        "zenodo_record": download.entry.record_url,
                        "ecg_recorded": result.ecg_recorded,
                        "ecg_sampling_rate_hz": result.sampling_rate,
                        "physiological_files_checked": str(
                            result.files_checked
                        ),
                        "evidence": result.evidence,
                        "status": result.status,
                    }
                )
                _write_inventory(inventory_path, rows)
                processed += 1
                if result.status == "verified":
                    verified += 1
                else:
                    needs_review += 1
                print(
                    f"[{dataset}] ECG: {result.ecg_recorded}; "
                    f"rate: {result.sampling_rate} Hz; "
                    f"status: {result.status}"
                )
                if not keep_downloads:
                    _safe_remove_dataset_cache(cache_root, dataset_dir)
                    print(f"[{dataset}] Removed temporary download")
            except KeyboardInterrupt:
                print(
                    f"[{dataset}] Interrupted. Partial download retained "
                    "for the next run."
                )
                raise
            except Exception as error:
                row = row_lookup[dataset]
                row["evidence"] = f"Processing failed: {error}"
                row["status"] = "download_error"
                _write_inventory(inventory_path, rows)
                failed += 1
                print(f"[{dataset}] Failed: {error}")

    return {
        "catalogue": len(catalog),
        "processed": processed,
        "verified": verified,
        "needs_review": needs_review,
        "failed": failed,
    }
