"""Create standardized events and split continuous recordings into runs."""

from __future__ import annotations

import numpy as np
import pandas as pd


EVENT_COLUMNS = [
    "onset",
    "duration",
    "event_type",
    "stimulus_name",
    "task_name",
    "block_number",
]

EVENTS_METADATA = {
    "onset": {
        "LongName": "Event onset",
        "Description": "Event onset relative to the start of the BIDS run.",
        "Units": "s",
    },
    "duration": {
        "LongName": "Event duration",
        "Description": "Duration of the event.",
        "Units": "s",
    },
    "event_type": {
        "LongName": "Fear-conditioning event type",
        "Description": "Standardized fear-conditioning event label.",
        "Levels": {
            "CSpr": "Reinforced CS+ followed by a delivered US.",
            "CSpu": "Unreinforced CS+.",
            "CSm": "CS-.",
            "USp": "Delivered unconditioned stimulus.",
            "USm": "Expected US time on a CS- trial; no US was delivered.",
            "USo": "Expected US time on an unreinforced CS+ trial.",
        },
    },
    "stimulus_name": {
        "LongName": "Stimulus name",
        "Description": "Human-readable identity of the presented stimulus.",
    },
    "task_name": {
        "LongName": "Task name",
        "Description": "BIDS task label.",
    },
    "block_number": {
        "LongName": "Source block number",
        "Description": "Experimental block number in the source dataset.",
    },
}


def selected_blocks(
    cogent: pd.DataFrame,
    config: dict,
    recording: str | None,
) -> list[int]:
    """Return configured acquisition blocks available in a trial table."""
    column = config["block_column"]
    available = {
        int(value)
        for value in pd.unique(cogent[column])
        if pd.notna(value)
    }
    recording_blocks = config.get("recording_blocks", {})
    requested = recording_blocks.get(str(recording))
    if requested is None:
        requested = config["acquisition_blocks"]

    missing = set(requested) - available
    if missing:
        raise ValueError(
            f"Acquisition blocks {sorted(missing)} are absent; "
            f"available blocks are {sorted(available)}"
        )
    return [block for block in requested if block in available]


def build_events(
    marker: np.ndarray,
    cogent: pd.DataFrame,
    config: dict,
    recording: str | None = None,
) -> pd.DataFrame:
    """Pair source markers with trials and standardize event labels."""
    required = {
        config["block_column"],
        config["cs_column"],
        config["us_column"],
    }
    missing = required - set(cogent.columns)
    if missing:
        raise ValueError(f"Missing Cogent columns: {sorted(missing)}")

    blocks = selected_blocks(cogent, config, recording)
    all_trials = cogent.copy()
    trials = all_trials[
        all_trials[config["block_column"]].isin(blocks)
    ].copy()

    trailing_markers = config.get("trailing_markers", 0)
    if len(marker) in {len(all_trials), len(all_trials) + trailing_markers}:
        all_trials["onset"] = pd.to_numeric(
            marker[: len(all_trials)],
            errors="raise",
        )
        trials = all_trials[
            all_trials[config["block_column"]].isin(blocks)
        ].copy()
    elif len(marker) in {len(trials), len(trials) + trailing_markers}:
        trials["onset"] = pd.to_numeric(
            marker[: len(trials)],
            errors="raise",
        )
    else:
        raise ValueError(
            f"Marker/trial mismatch: {len(marker)} markers for "
            f"{len(trials)} acquisition trials and {len(all_trials)} "
            "total trials"
        )

    trials.reset_index(drop=True, inplace=True)
    rows = []

    for _, trial in trials.iterrows():
        cs_value = trial[config["cs_column"]]
        try:
            stimulus_key = int(cs_value)
        except (TypeError, ValueError):
            stimulus_key = cs_value

        us_present = float(trial[config["us_column"]]) != 0
        if cs_value in config["cs_plus"]:
            cs_event = "CSpr" if us_present else "CSpu"
            us_event = "USp" if us_present else "USo"
        elif cs_value in config["cs_minus"]:
            cs_event = "CSm"
            us_event = "USm"
        else:
            raise ValueError(f"Unknown CS value {cs_value!r}")

        onset = float(trial["onset"])
        common = {
            "task_name": config["task_name"],
            "block_number": int(trial[config["block_column"]]),
        }
        rows.append(
            {
                "onset": onset,
                "duration": float(config["cs_duration"]),
                "event_type": cs_event,
                "stimulus_name": config["stimuli"].get(
                    stimulus_key,
                    f"CS type {stimulus_key}",
                ),
                **common,
            }
        )
        rows.append(
            {
                "onset": onset + float(config["soa"]),
                "duration": (
                    float(config["us_duration"]) if us_event == "USp" else 0.0
                ),
                "event_type": us_event,
                "stimulus_name": (
                    "electrical stimulus"
                    if us_event == "USp"
                    else "no stimulus delivered"
                ),
                **common,
            }
        )

    return (
        pd.DataFrame(rows, columns=EVENT_COLUMNS)
        .sort_values(["onset", "event_type"], kind="mergesort")
        .reset_index(drop=True)
    )


def split_runs(
    events: pd.DataFrame,
    samples: np.ndarray,
    sampling_rate: float,
    config: dict,
    first_run: int,
):
    """Yield cropped samples and retimed events for each source block."""
    left = float(config["left_offset"])
    right = float(config["right_offset"])

    for run_number, block in enumerate(
        sorted(events["block_number"].unique()),
        start=first_run,
    ):
        run_events = events[events["block_number"] == block].copy()
        run_events.reset_index(drop=True, inplace=True)
        source_start = max(0.0, float(run_events["onset"].iloc[0]) - left)
        source_stop = float(run_events["onset"].iloc[-1]) + right
        start_sample = max(0, int(source_start * sampling_rate))
        stop_sample = min(len(samples), int(source_stop * sampling_rate))

        run_events["onset"] -= source_start
        yield run_number, run_events, samples[start_sample:stop_sample]
