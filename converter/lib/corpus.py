"""Combine converted SCRFear datasets into one corpus."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pandas as pd

from .bids_writer import write_json
from .corpus_participants import (
    scr_opt_participants,
    select_scr_opt_participants,
)
from .tsv_configs import DATASETS


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_participant_metadata(target: dict, source: dict):
    for column, details in source.items():
        if column not in target:
            target[column] = copy.deepcopy(details)
            continue

        source_levels = details.get("Levels", {})
        if source_levels:
            target[column].setdefault("Levels", {}).update(source_levels)


def _rename_subject_files(subject_dir: Path, old_id: str, new_id: str):
    if old_id == new_id:
        return

    for path in sorted(subject_dir.rglob("*")):
        if not path.is_file() or old_id not in path.name:
            continue
        destination = path.with_name(path.name.replace(old_id, new_id))
        if destination.exists():
            raise FileExistsError(destination)
        path.rename(destination)


def _source_dataset_entry(dataset: str, description: dict) -> dict:
    entries = description.get("SourceDatasets", [])
    if not entries or "URL" not in entries[0]:
        raise ValueError(f"{dataset} has no source URL in dataset_description.json")
    return {"Name": dataset, "URL": entries[0]["URL"]}


def _filter_corpus_participants(
    dataset: str,
    participants: pd.DataFrame,
    participants_path: Path,
) -> pd.DataFrame:
    config = DATASETS.get(dataset, {})
    filters = config.get("corpus_participant_filters", {})
    selected = participants
    for column, allowed_values in filters.items():
        if column not in selected:
            raise ValueError(
                f"{participants_path} has no {column} column required by "
                f"the {dataset} corpus selection rule"
            )
        values = selected[column].astype(str).str.strip().str.casefold()
        known_values = (
            config.get("participant_metadata", {})
            .get(column, {})
            .get("Levels", {})
        )
        known = {str(value).strip().casefold() for value in known_values}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                f"{participants_path} contains unrecognized {column} "
                f"value(s): {', '.join(unknown)}"
            )
        allowed = {str(value).strip().casefold() for value in allowed_values}
        selected = selected[values.isin(allowed)]
    return selected


def _build_corpus(
    converted_root: Path,
    corpus_root: Path,
    datasets: list[str],
) -> dict:
    mapping_rows = []
    participant_rows = []
    participant_metadata = {}
    authors = []
    source_datasets = []
    dataset_participants = {}
    subject_number = 1
    excluded_participants = 0
    require_complete_selection = set(datasets) == set(DATASETS)

    for dataset in sorted(datasets):
        dataset_dir = converted_root / dataset
        participants_path = dataset_dir / "participants.tsv"
        participants_json_path = dataset_dir / "participants.json"
        description_path = dataset_dir / "dataset_description.json"

        required = [
            participants_path,
            participants_json_path,
            description_path,
        ]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{dataset} is missing required files: {', '.join(missing)}"
            )

        participants = pd.read_csv(
            participants_path,
            sep="\t",
            dtype=str,
            keep_default_na=False,
        )
        if "participant_id" not in participants:
            raise ValueError(f"{participants_path} has no participant_id column")
        if participants["participant_id"].duplicated().any():
            raise ValueError(f"{participants_path} contains duplicate IDs")
        selected_participants = _filter_corpus_participants(
            dataset,
            participants,
            participants_path,
        )
        selected_participants = select_scr_opt_participants(
            dataset,
            selected_participants,
            require_complete=require_complete_selection,
        )
        participant_lookup = selected_participants.set_index("participant_id")

        source_metadata = _read_json(participants_json_path)
        _merge_participant_metadata(participant_metadata, source_metadata)

        description = _read_json(description_path)
        for author in description.get("Authors", []):
            if author not in authors:
                authors.append(author)
        source_datasets.append(_source_dataset_entry(dataset, description))

        subject_dirs = sorted(
            path
            for path in dataset_dir.iterdir()
            if path.is_dir() and path.name.startswith("sub-")
        )
        if not subject_dirs:
            raise ValueError(f"{dataset} contains no participant directories")

        participant_ids = set(participants["participant_id"])
        missing_rows = [
            path.name for path in subject_dirs if path.name not in participant_ids
        ]
        if missing_rows:
            raise ValueError(
                f"{dataset} participant directories have no participants.tsv "
                f"row: {', '.join(missing_rows)}"
            )

        selected_ids = set(participant_lookup.index)
        selected_subject_dirs = [
            path for path in subject_dirs if path.name in selected_ids
        ]
        excluded_count = len(subject_dirs) - len(selected_subject_dirs)
        excluded_participants += excluded_count
        dataset_participants[dataset] = {
            "included": len(selected_subject_dirs),
            "excluded": excluded_count,
        }
        if not selected_subject_dirs:
            raise ValueError(
                f"{dataset} has no participant directories matching its "
                "corpus selection rules"
            )

        for source_dir in selected_subject_dirs:
            source_id = source_dir.name
            if source_id not in participant_lookup.index:
                raise ValueError(
                    f"{dataset} {source_id} has no participants.tsv row"
                )

            corpus_id = f"sub-{subject_number:03d}"
            destination = corpus_root / corpus_id
            shutil.copytree(source_dir, destination)
            _rename_subject_files(destination, source_id, corpus_id)

            source_row = participant_lookup.loc[source_id].to_dict()
            combined_row = {
                "participant_id": corpus_id,
                "source_dataset": dataset,
                "source_participant_id": source_id,
                **source_row,
            }
            participant_rows.append(combined_row)
            mapping_rows.append(
                {
                    "Corpus_ID": corpus_id,
                    "Dataset": dataset,
                    "Orig_ID": source_id,
                }
            )
            subject_number += 1

    overview = pd.DataFrame(
        mapping_rows,
        columns=["Corpus_ID", "Dataset", "Orig_ID"],
    )
    overview.to_csv(
        corpus_root / "scrfear_corpus_overview.csv",
        index=False,
    )

    participants = pd.DataFrame(participant_rows)
    participants.fillna("n/a", inplace=True)
    participants.to_csv(
        corpus_root / "participants.tsv",
        sep="\t",
        index=False,
        na_rep="n/a",
    )

    corpus_participant_metadata = copy.deepcopy(participant_metadata)
    corpus_participant_metadata.update({
        "participant_id": {
            "Description": "Participant identifier in the SCRFear corpus.",
        },
        "source_dataset": {
            "Description": "Converted source dataset.",
        },
        "source_participant_id": {
            "Description": "Participant identifier in the source dataset.",
        },
    })
    write_json(
        corpus_root / "participants.json",
        corpus_participant_metadata,
    )

    write_json(
        corpus_root / "dataset_description.json",
        {
            "Name": "SCRFear Corpus",
            "BIDSVersion": "1.10.0",
            "DatasetType": "raw",
            "License": "CC-BY-4.0",
            "Authors": authors,
            "Description": (
                "Combined fear-acquisition physiology datasets converted "
                "by SCRFear."
            ),
            "SourceDatasets": source_datasets,
        },
    )

    dataset_lines = "\n".join(f"- {dataset}" for dataset in sorted(datasets))
    readme = (
        "# SCRFear Corpus\n\n"
        "This corpus combines the converted fear-acquisition datasets listed "
        "below. Each source participant is assigned a unique corpus ID. "
        "The original dataset and participant ID are recorded in "
        "`scrfear_corpus_overview.csv` and `participants.tsv`.\n\n"
        "Source recordings remain separate participants; recordings from "
        "different studies are not joined within a participant. Participant "
        "selection follows the 543-person list from the original SCRopt "
        "analysis. For DoxMem1, DoxAv2, and MinAv, only placebo participants "
        "are considered; DoxMem2 treatment occurred after initial learning.\n\n"
        "## Included datasets\n\n"
        f"{dataset_lines}\n"
    )
    (corpus_root / "README.md").write_text(readme, encoding="utf-8")

    summary = {
        "datasets": len(datasets),
        "participants": len(mapping_rows),
        "excluded_participants": excluded_participants,
        "dataset_participants": dataset_participants,
        "output": str(corpus_root.resolve()),
    }
    if require_complete_selection:
        expected = sum(
            len(numbers) for numbers in scr_opt_participants().values()
        )
        if summary["participants"] != expected:
            raise ValueError(
                f"Corpus contains {summary['participants']} participants; "
                f"the SCRopt selection requires {expected}"
            )
    return summary


def combine_datasets(
    converted_root: str | Path = "Converted_Datasets",
    corpus_root: str | Path = "Corpus",
    datasets: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Build a combined corpus from converted dataset directories."""
    converted_root = Path(converted_root)
    corpus_root = Path(corpus_root)
    datasets = list(datasets or [])

    if not datasets:
        raise ValueError("No datasets were selected for the corpus")
    missing_datasets = [
        dataset
        for dataset in datasets
        if not (converted_root / dataset).is_dir()
    ]
    if missing_datasets:
        raise FileNotFoundError(
            "Converted datasets not found: " + ", ".join(missing_datasets)
        )

    converted_resolved = converted_root.resolve()
    corpus_resolved = corpus_root.resolve()
    working_directory = Path.cwd().resolve()
    if corpus_resolved == working_directory:
        raise ValueError("Corpus output must be a dedicated directory")
    if (
        corpus_resolved == converted_resolved
        or corpus_resolved.is_relative_to(converted_resolved)
        or converted_resolved.is_relative_to(corpus_resolved)
    ):
        raise ValueError(
            "Corpus output and converted dataset directories must be separate"
        )
    if corpus_root.exists() and not force:
        raise FileExistsError(
            f"{corpus_root} already exists; use --force to rebuild it"
        )

    corpus_root.parent.mkdir(parents=True, exist_ok=True)
    if not corpus_root.exists():
        corpus_root.mkdir()
        return _build_corpus(converted_root, corpus_root, datasets)
        # try:
        # except Exception:
        #     if corpus_root.exists():
        #         shutil.rmtree(corpus_root)
        #     raise

    temporary = corpus_root.with_name(f"{corpus_root.name}-building")
    if temporary.exists():
        raise FileExistsError(
            f"{temporary} already exists from an earlier build; remove it "
            "before trying again"
        )
    temporary.mkdir()
    try:
        summary = _build_corpus(
            converted_root,
            temporary,
            datasets,
        )
        if corpus_root.exists():
            if not corpus_root.is_dir():
                raise NotADirectoryError(corpus_root)
            shutil.rmtree(corpus_root)
        shutil.move(str(temporary), str(corpus_root))
        summary["output"] = str(corpus_root.resolve())
        return summary
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
