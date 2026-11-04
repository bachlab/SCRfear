"""Create participant metadata and link SCRFear IDs to PupilFear."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .bids_writer import write_json
from .source_data import load_cogent


PARTICIPANTS_METADATA = {
    "participant_id": {
        "Description": "Participant identifier in the converted dataset.",
    },
    "PupilFearSubjectID": {
        "Description": (
            "Matching participant identifier in the PupilFear corpus. "
            "The value is n/a when no matching pupil recording exists."
        ),
    },
    "age": {
        "Description": "Participant age.",
        "Units": "years",
    },
    "sex": {
        "Description": "Participant sex reported in the source data.",
        "Levels": {
            "M": "Male",
            "F": "Female",
            "O": "Other",
            "n/a": "Not available",
        },
    },
}


def load_pupilfear_links(path: Path | None) -> dict[tuple[str, str], str]:
    """Read dataset/original-ID to PupilFear corpus-ID mappings."""
    if path is None or not path.exists():
        return {}
    table = pd.read_csv(path, dtype=str)
    required = {"Corpus_ID", "Dataset", "Orig_ID"}
    if not required.issubset(table.columns):
        raise ValueError(
            f"{path} must contain the columns {sorted(required)}"
        )
    return {
        (row.Dataset, row.Orig_ID): row.Corpus_ID
        for row in table.itertuples(index=False)
    }


def _normalise_sex(value, config: dict):
    if pd.isna(value):
        return "n/a"
    if isinstance(value, str):
        normal = value.strip().lower()
        if normal in config.get("sex_map", {}):
            return config["sex_map"][normal]
        if normal in {"m", "male", "1"}:
            return "M"
        if normal in {"f", "female", "2"}:
            return "F"
        if normal in {"o", "other"}:
            return "O"
        return value
    if value == 1:
        return "M"
    if value == 2:
        return "F"
    return str(value)


def _subject_from_metadata(filename: str, config: dict) -> str | None:
    match = re.fullmatch(
        config["metadata_pattern"],
        filename,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group("subject").zfill(config["subject_width"])


def write_participants(
    data_dir: Path,
    output_dir: Path,
    config: dict,
    pupilfear_links: dict[tuple[str, str], str],
    included_subjects: set[str],
) -> int:
    """Write participants.tsv and its JSON sidecar."""
    participants = []

    for path in sorted(data_dir.glob("*.mat")):
        subject = _subject_from_metadata(path.name, config)
        if subject is None or subject not in included_subjects:
            continue

        try:
            source = load_cogent(path, data_type="subject")
        except Exception:
            source = pd.DataFrame()

        age = source["age"].iloc[0] if "age" in source.columns else "n/a"
        sex = "n/a"
        for column in ("sex", "gender", "gender_"):
            if column in source.columns:
                sex = _normalise_sex(source[column].iloc[0], config)
                break

        participant = {
            "participant_id": f"sub-{subject}",
            "PupilFearSubjectID": pupilfear_links.get(
                (config["name"], f"sub-{subject}"),
                "n/a",
            ),
            "age": age,
            "sex": sex,
        }
        maps = config.get("participant_value_maps", {})
        for output_column, source_column in config.get(
            "participant_columns",
            {},
        ).items():
            value = (
                source[source_column].iloc[0]
                if source_column in source.columns
                else "n/a"
            )
            participant[output_column] = maps.get(
                output_column,
                {},
            ).get(value, value)
        participants.append(participant)

    frame = pd.DataFrame(participants)
    if frame.empty:
        raise ValueError("No participant metadata matched converted subjects")
    frame.drop_duplicates("participant_id", inplace=True)
    frame.sort_values("participant_id", inplace=True)
    frame.to_csv(
        output_dir / "participants.tsv",
        sep="\t",
        index=False,
        na_rep="n/a",
    )

    metadata = dict(PARTICIPANTS_METADATA)
    metadata.update(config.get("participant_metadata", {}))
    write_json(output_dir / "participants.json", metadata)
    return len(frame)
