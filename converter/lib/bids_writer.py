"""Write BIDS dataset, event, and physiology files."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .events import EVENTS_METADATA


def write_json(path: Path, value: dict):
    """Write consistently formatted UTF-8 JSON."""
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _normalise_units(units: str) -> str:
    return {"volt": "V"}.get(units.casefold(), units)


def write_physio(
    path: Path,
    samples: np.ndarray,
    sampling_rate: float,
    units: str,
    config: dict,
):
    """Write one compressed SCR time series and its JSON sidecar."""
    timestamps = np.arange(len(samples), dtype=float) / sampling_rate
    frame = pd.DataFrame({"timestamp": timestamps, "scr": samples})
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            frame.to_csv(
                compressed,
                sep="\t",
                index=False,
                header=False,
                na_rep="n/a",
            )

    metadata = {
        "Columns": ["timestamp", "scr"],
        "SamplingFrequency": sampling_rate,
        "StartTime": 0,
        "TaskName": config["task_name"],
        "TaskDescription": config["task_description"],
        "timestamp": {
            "LongName": "Time",
            "Description": "Time relative to the start of this recording.",
            "Units": "s",
        },
        "scr": {
            "Description": config.get(
                "scr_description",
                "Skin conductance recording.",
            ),
            "Units": config.get("scr_units", _normalise_units(units)),
        },
        "SOA": config["soa"],
        "StimulusPresentation": {
            "SoftwareName": config.get(
                "stimulus_software",
                "Cogent 2000",
            )
        },
    }
    write_json(
        path.with_name(path.name.replace(".tsv.gz", ".json")),
        metadata,
    )


def write_run(
    subject_dir: Path,
    subject: str,
    run_number: int,
    events: pd.DataFrame,
    samples: np.ndarray,
    sampling_rate: float,
    units: str,
    config: dict,
):
    """Write events and SCR data for one BIDS run."""
    stem = (
        f"sub-{subject}_task-{config['task_name']}_run-{run_number:02d}"
    )
    events_path = subject_dir / f"{stem}_events.tsv"
    events.to_csv(events_path, sep="\t", index=False, na_rep="n/a")
    write_json(events_path.with_suffix(".json"), EVENTS_METADATA)

    physio_path = subject_dir / f"{stem}_recording-scr_physio.tsv.gz"
    write_physio(
        physio_path,
        samples,
        sampling_rate,
        units,
        config,
    )


def write_dataset_files(output_dir: Path, config: dict):
    """Write root-level BIDS description and README files."""
    description = {
        "Name": config["name"],
        "BIDSVersion": "1.10.0",
        "DatasetType": "raw",
        "License": "CC-BY-4.0",
        "Authors": config["authors"],
        "Description": config["description"],
        "SourceDatasets": [
            {
                "URL": (
                    "https://zenodo.org/records/"
                    f"{config['zenodo_record']}"
                )
            }
        ],
    }
    write_json(output_dir / "dataset_description.json", description)

    blocks = ", ".join(str(value) for value in config["acquisition_blocks"])
    readme = (
        f"# {config['name']}\n\n"
        f"{config['description']}\n\n"
        "This converted dataset contains skin-conductance recordings and "
        "events from the fear-acquisition phase. Source experimental blocks "
        f"{blocks} are represented by BIDS `run-*` identifiers. Events and "
        "SCR data are stored together in each participant's `physio` "
        "directory.\n\n"
        "Source: "
        f"https://zenodo.org/records/{config['zenodo_record']}\n"
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
