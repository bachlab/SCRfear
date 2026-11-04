"""Coordinate conversion of one configured source dataset."""

from __future__ import annotations

import re
from pathlib import Path

from .bids_writer import write_dataset_files, write_run
from .events import build_events, split_runs
from .participants import load_pupilfear_links, write_participants
from .source_data import (
    cogent_filename,
    find_data_dir,
    load_cogent,
    load_recording,
    source_ids,
)
from .tsv_configs import DATASETS


def _source_recordings(
    data_dir: Path,
    config: dict,
    subjects: list[str] | None,
) -> list[Path]:
    requested = (
        {
            str(value).removeprefix("sub-").zfill(config["subject_width"])
            for value in subjects
        }
        if subjects
        else None
    )
    excluded = {
        str(value).zfill(config["subject_width"])
        for value in config["exclusions"]
    }

    files = []
    for path in data_dir.glob("*.mat"):
        match = re.fullmatch(
            config["data_pattern"],
            path.name,
            flags=re.IGNORECASE,
        )
        if match is None:
            continue
        subject = match.group("subject").zfill(config["subject_width"])
        if subject in excluded:
            continue
        if requested is not None and subject not in requested:
            continue
        files.append(path)

    files.sort(key=lambda path: source_ids(path, config))
    return files


def convert_dataset(
    dataset: str,
    raw_root: str | Path = "Datasets",
    output_root: str | Path = "Converted_Datasets",
    pupilfear_overview: str | Path | None = (
        "metadata/pupilbench_corpus_overview.csv"
    ),
    subjects: list[str] | None = None,
) -> dict:
    """Convert one configured dataset and return a conversion summary."""
    if dataset not in DATASETS:
        raise KeyError(
            f"Unknown dataset {dataset!r}; choose from {sorted(DATASETS)}"
        )

    config = DATASETS[dataset]
    data_dir = find_data_dir(Path(raw_root) / dataset)
    output_dir = Path(output_root) / dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    write_dataset_files(output_dir, config)

    files = _source_recordings(data_dir, config, subjects)
    if not files:
        raise FileNotFoundError(f"No matching recordings found in {data_dir}")

    next_run = {}
    included_subjects = set()
    run_count = 0
    failures = []

    print(f"[{dataset}] Converting {len(files)} source recordings")
    for path in files:
        subject, recording = source_ids(path, config)
        try:
            cogent_path = data_dir / cogent_filename(
                config,
                subject,
                recording,
            )
            if not cogent_path.exists():
                raise FileNotFoundError(cogent_path.name)

            marker, samples, sampling_rate, units = load_recording(path)
            cogent = load_cogent(cogent_path)
            events = build_events(marker, cogent, config, recording)
            first_run = next_run.get(subject, 1)
            subject_dir = output_dir / f"sub-{subject}" / "physio"
            subject_dir.mkdir(parents=True, exist_ok=True)

            converted = 0
            for run_number, run_events, run_samples in split_runs(
                events,
                samples,
                sampling_rate,
                config,
                first_run,
            ):
                write_run(
                    subject_dir,
                    subject,
                    run_number,
                    run_events,
                    run_samples,
                    sampling_rate,
                    units,
                    config,
                )
                converted += 1

            next_run[subject] = first_run + converted
            included_subjects.add(subject)
            run_count += converted
            print(f"[{dataset}] sub-{subject}: {converted} runs")
        except Exception as error:
            failures.append((path.name, str(error)))
            print(f"[{dataset}] {path.name}: failed ({error})")

    if not included_subjects:
        raise RuntimeError(f"{dataset} conversion failed for every recording")

    overview = (
        Path(pupilfear_overview)
        if pupilfear_overview is not None
        else None
    )
    links = load_pupilfear_links(overview)
    participant_count = write_participants(
        data_dir,
        output_dir,
        config,
        links,
        included_subjects,
    )

    summary = {
        "dataset": dataset,
        "participants": participant_count,
        "runs": run_count,
        "failed_recordings": failures,
        "output": str(output_dir.resolve()),
    }
    status = "complete" if not failures else "complete with errors"
    print(
        f"[{dataset}] {status}: {participant_count} participants, "
        f"{run_count} runs"
    )
    print(f"[{dataset}] Output: {summary['output']}")
    return summary
