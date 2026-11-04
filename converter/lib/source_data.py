"""Read identifiers, trial metadata, and recordings from source files."""

from __future__ import annotations

import re
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy.io import loadmat


def _matlab_class(item) -> str:
    value = item.attrs.get("MATLAB_class", b"")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _matlab_order(values: np.ndarray) -> np.ndarray:
    if values.ndim < 2:
        return values
    return values.transpose(tuple(reversed(range(values.ndim))))


def _decode_hdf5(item, source: h5py.File):
    if isinstance(item, h5py.Group):
        reference_fields = [
            child
            for child in item.values()
            if isinstance(child, h5py.Dataset) and child.dtype.kind == "O"
        ]
        if _matlab_class(item) == "struct" and reference_fields:
            count = reference_fields[0].size
            records = [dict() for _ in range(count)]
            for name, child in item.items():
                if isinstance(child, h5py.Dataset) and child.dtype.kind == "O":
                    references = _matlab_order(child[()]).reshape(-1)
                    values = [
                        _decode_hdf5(source[reference], source)
                        if reference
                        else None
                        for reference in references
                    ]
                else:
                    value = _decode_hdf5(child, source)
                    values = [value] * count
                for record, value in zip(records, values):
                    record[name] = value
            return records[0] if count == 1 else records
        return {
            name: _decode_hdf5(child, source)
            for name, child in item.items()
        }

    values = _matlab_order(item[()])
    if item.dtype.kind == "O":
        decoded = [
            _decode_hdf5(source[reference], source)
            if reference
            else None
            for reference in values.reshape(-1)
        ]
        return decoded

    if _matlab_class(item) == "char":
        return "".join(chr(int(value)) for value in values.reshape(-1))
    if _matlab_class(item) == "canonical empty":
        return np.array([])
    if values.size == 1:
        return values.reshape(-1)[0].item()
    return values


def _load_source(path: Path, names: list[str]) -> dict:
    try:
        return loadmat(
            path,
            simplify_cells=True,
            variable_names=names,
        )
    except (NotImplementedError, ValueError):
        if not h5py.is_hdf5(path):
            raise
        with h5py.File(path, "r") as source:
            return {
                name: _decode_hdf5(source[name], source)
                for name in names
                if name in source
            }


def _load_hdf5_recording_channels(path: Path) -> list[dict]:
    channels = []
    with h5py.File(path, "r") as source:
        references = _matlab_order(source["data"][()]).reshape(-1)
        for reference in references:
            channel = source[reference]
            header = _decode_hdf5(channel["header"], source)
            channel_type = str(header["chantype"]).strip().lower()
            if channel_type not in {"scr", "marker"}:
                continue
            channels.append(
                {
                    "header": header,
                    "data": _decode_hdf5(channel["data"], source),
                }
            )
    return channels


def _load_hdf5_channel_headers(path: Path) -> list[dict]:
    headers = []
    with h5py.File(path, "r") as source:
        if "data" not in source or not isinstance(source["data"], h5py.Dataset):
            return headers
        data = source["data"]
        if data.dtype.kind != "O":
            return headers
        references = _matlab_order(data[()]).reshape(-1)
        for reference in references:
            if not reference:
                continue
            channel = source[reference]
            if not isinstance(channel, h5py.Group) or "header" not in channel:
                continue
            header = _decode_hdf5(channel["header"], source)
            if isinstance(header, dict) and "chantype" in header:
                headers.append(header)
    return headers


def load_channel_headers(path: Path) -> list[dict]:
    """Read channel headers without retaining physiological sample arrays."""
    if h5py.is_hdf5(path):
        return _load_hdf5_channel_headers(path)

    source = _load_source(path, ["data"])
    data = source.get("data")
    if data is None:
        return []

    headers = []
    for channel in _channels(data):
        if not isinstance(channel, dict):
            continue
        header = channel.get("header")
        if isinstance(header, dict) and "chantype" in header:
            headers.append(header)
    return headers


def find_data_dir(dataset_dir: Path) -> Path:
    """Find the directory that directly contains the source MAT files."""
    candidates = [
        dataset_dir,
        dataset_dir / "Data",
        dataset_dir / "Data" / "Data",
    ]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.mat")):
            return candidate
    raise FileNotFoundError(
        f"No MAT files found in {dataset_dir}, Data, or Data/Data"
    )


def _channels(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, np.ndarray):
        return list(value.flat)
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _scalar_column_index(item: dict) -> float | None:
    values = np.asarray(item.get("column_index")).reshape(-1)
    if values.size != 1:
        return None
    try:
        return float(values[0])
    except (TypeError, ValueError):
        return None


def load_recording(path: Path):
    """Load marker and SCR channels from one WinDaq MAT file."""
    source = (
        {"data": _load_hdf5_recording_channels(path)}
        if h5py.is_hdf5(path)
        else _load_source(path, ["data"])
    )
    marker = None
    scr = None

    for channel in _channels(source["data"]):
        channel_type = str(channel["header"]["chantype"]).strip().lower()
        if channel_type == "marker":
            marker = np.asarray(channel["data"]).reshape(-1)
        elif channel_type == "scr":
            scr = channel

    if marker is None:
        raise ValueError(f"No marker channel found in {path.name}")
    if scr is None:
        raise ValueError(f"No SCR channel found in {path.name}")

    header = scr["header"]
    sampling_rate = float(header["sr"])
    units = str(header.get("units", "n/a")).strip() or "n/a"
    samples = np.asarray(scr["data"]).reshape(-1)
    return marker, samples, sampling_rate, units


def load_cogent(path: Path, data_type: str = "data") -> pd.DataFrame:
    """Read trial or participant information from a Cogent MAT file."""
    names = (
        ["subject"]
        if data_type == "subject"
        else [data_type, "dataKey", f"{data_type}Key"]
    )
    source = _load_source(path, names)

    if data_type == "subject":
        subject = source.get("subject", {})
        if not isinstance(subject, dict):
            return pd.DataFrame(subject)
        flattened = {}
        for key, value in subject.items():
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    flattened[f"{key}_{nested_key}"] = nested_value
            else:
                flattened[key] = value
        return pd.DataFrame([flattened])

    data = source[data_type]
    key = source.get("dataKey", source.get(f"{data_type}Key"))
    if key is None:
        raise ValueError(f"No dataKey found in {path.name}")

    if isinstance(key, dict):
        key = [key]
    if (
        isinstance(key, (list, np.ndarray))
        and len(key)
        and isinstance(key[0], dict)
    ):
        indexes = [_scalar_column_index(item) for item in key]
        if all(index is not None for index in indexes):
            key = [
                item
                for _, item in sorted(
                    zip(indexes, key),
                    key=lambda pair: pair[0],
                )
            ]
        columns = [item["column_type"] for item in key]
    else:
        columns = list(np.asarray(key).reshape(-1))

    values = np.asarray(data)
    if values.ndim == 1:
        values = values.reshape(1, -1)

    columns = [str(column).strip() for column in columns]
    if len(columns) < values.shape[1]:
        columns.extend(
            f"unlabelled_source_column_{index}"
            for index in range(len(columns) + 1, values.shape[1] + 1)
        )
    elif len(columns) > values.shape[1]:
        raise ValueError(
            f"{path.name} documents {len(columns)} columns but contains "
            f"{values.shape[1]}"
        )

    return pd.DataFrame(values, columns=columns)


def source_ids(path: Path, config: dict) -> tuple[str, str | None]:
    """Extract normalized subject and recording IDs from a source filename."""
    match = re.fullmatch(
        config["data_pattern"],
        path.name,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"Unexpected source filename: {path.name}")
    subject = match.group("subject").zfill(config["subject_width"])
    recording = match.groupdict().get("recording")
    return subject, recording


def cogent_filename(config: dict, subject: str, recording: str | None) -> str:
    """Build the trial-metadata filename for one source recording."""
    return config["cogent_name"].format(
        subject=subject,
        subject_int=int(subject),
        recording=recording,
    )
