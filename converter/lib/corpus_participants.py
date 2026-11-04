"""Participant list used for the SCRFear corpus."""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from importlib.resources import files

import pandas as pd


# SCRopt renumbered placebo participants after filtering these studies.
FILTERED_PARTICIPANT_NUMBERS = {"DoxAv2", "DoxMem1", "MinAv"}


def _participant_number(participant_id: str) -> int:
    match = re.fullmatch(r"sub-(\d+)", str(participant_id))
    if match is None:
        raise ValueError(f"Invalid participant ID: {participant_id}")
    return int(match.group(1))


@lru_cache(maxsize=1)
def scr_opt_participants() -> dict[str, frozenset[int]]:
    """Read the participant numbers exported by the original SCRopt code."""
    path = files("converter").joinpath("data", "SCRopt_ppids.csv")
    selected: dict[str, set[int]] = {}
    seen = set()

    with path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            dataset = row["database"].strip()
            ppid = row["ppid"].strip()
            prefix = f"{dataset}_"
            if not ppid.startswith(prefix):
                raise ValueError(f"Invalid SCRopt participant ID: {ppid}")
            try:
                number = int(ppid.removeprefix(prefix))
            except ValueError as error:
                raise ValueError(
                    f"Invalid SCRopt participant ID: {ppid}"
                ) from error
            key = dataset, number
            if key in seen:
                raise ValueError(f"Duplicate SCRopt participant ID: {ppid}")
            seen.add(key)
            selected.setdefault(dataset, set()).add(number)

    return {
        dataset: frozenset(numbers)
        for dataset, numbers in selected.items()
    }


def select_scr_opt_participants(
    dataset: str,
    participants: pd.DataFrame,
    require_complete: bool,
) -> pd.DataFrame:
    """Apply the participant selection from the original SCRopt analysis."""
    selections = scr_opt_participants()
    if dataset not in selections:
        raise ValueError(f"No SCRopt participant list is available for {dataset}")

    wanted = selections[dataset]
    participant_numbers = participants["participant_id"].map(
        _participant_number
    )

    if dataset in FILTERED_PARTICIPANT_NUMBERS:
        ordered_ids = sorted(
            participants["participant_id"],
            key=_participant_number,
        )
        expected_candidates = max(wanted)
        if require_complete and len(ordered_ids) != expected_candidates:
            raise ValueError(
                f"{dataset} has {len(ordered_ids)} placebo participants, "
                f"but the SCRopt selection expects {expected_candidates}. "
                "Reconvert this dataset with the current converter."
            )
        selected_ids = {
            ordered_ids[number - 1]
            for number in wanted
            if number <= len(ordered_ids)
        }
    else:
        selected_ids = set(
            participants.loc[
                participant_numbers.isin(wanted), "participant_id"
            ]
        )

    if require_complete and len(selected_ids) != len(wanted):
        raise ValueError(
            f"{dataset} contains {len(selected_ids)} of the "
            f"{len(wanted)} participants required by the SCRopt selection. "
            "Reconvert this dataset with the current converter."
        )

    return participants[participants["participant_id"].isin(selected_ids)]
