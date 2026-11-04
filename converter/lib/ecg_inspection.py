"""Inspect downloaded physiology archives for ECG channel metadata."""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .source_data import load_channel_headers


SUPPORTED_RECORDINGS = {".mat", ".edf", ".bdf", ".vhdr"}


@dataclass
class InspectionResult:
    ecg_recorded: str
    sampling_rate: str
    files_checked: int
    evidence: str
    status: str


@dataclass
class _InspectionSummary:
    files_checked: int = 0
    ecg_files: int = 0
    rates: set[float] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def _normalise_channel(value) -> str:
    return "".join(
        character
        for character in str(value).strip().casefold()
        if character.isalnum()
    )


def _is_ecg(value) -> bool:
    channel = _normalise_channel(value)
    return channel in {"ecg", "ekg", "electrocardiogram"} or channel.startswith(
        ("ecg", "ekg")
    )


def _sampling_rate(header: dict) -> float | None:
    for key in ("sr", "sampling_rate", "samplingrate", "fs"):
        if key not in header:
            continue
        try:
            value = float(header[key])
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _inspect_mat(path: Path, summary: _InspectionSummary) -> bool:
    headers = load_channel_headers(path)
    if not headers:
        return False

    summary.files_checked += 1
    ecg_headers = [
        header
        for header in headers
        if _is_ecg(
            header.get(
                "chantype",
                header.get("channel_type", header.get("label", "")),
            )
        )
    ]
    if ecg_headers:
        summary.ecg_files += 1
        for header in ecg_headers:
            rate = _sampling_rate(header)
            if rate is not None:
                summary.rates.add(rate)
    return True


def _edf_text(header: bytes, start: int, length: int) -> str:
    return header[start : start + length].decode("latin-1").strip()


def _inspect_edf(path: Path, summary: _InspectionSummary) -> bool:
    with path.open("rb") as source:
        fixed = source.read(256)
        if len(fixed) != 256:
            return False
        header_bytes = int(_edf_text(fixed, 184, 8))
        duration = float(_edf_text(fixed, 244, 8))
        signals = int(_edf_text(fixed, 252, 4))
        signal_header = source.read(header_bytes - 256)
    if signals < 1 or duration <= 0 or len(signal_header) < 216 * signals:
        return False

    labels = [
        _edf_text(signal_header, index * 16, 16)
        for index in range(signals)
    ]
    samples_offset = 216 * signals
    samples = [
        int(
            _edf_text(
                signal_header,
                samples_offset + index * 8,
                8,
            )
        )
        for index in range(signals)
    ]
    summary.files_checked += 1
    ecg_indexes = [
        index for index, label in enumerate(labels) if _is_ecg(label)
    ]
    if ecg_indexes:
        summary.ecg_files += 1
        for index in ecg_indexes:
            summary.rates.add(samples[index] / duration)
    return True


def _inspect_vhdr(path: Path, summary: _InspectionSummary) -> bool:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sampling_interval = None
    labels = []
    in_channels = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_channels = line.casefold() == "[channel infos]"
            continue
        if line.casefold().startswith("samplinginterval="):
            sampling_interval = float(line.split("=", 1)[1].strip())
        elif in_channels and line.casefold().startswith("ch") and "=" in line:
            labels.append(line.split("=", 1)[1].split(",", 1)[0].strip())

    if sampling_interval is None or not labels:
        return False
    summary.files_checked += 1
    if any(_is_ecg(label) for label in labels):
        summary.ecg_files += 1
        summary.rates.add(1_000_000 / sampling_interval)
    return True


def _inspect_recording(path: Path, summary: _InspectionSummary):
    try:
        suffix = path.suffix.casefold()
        if suffix == ".mat":
            _inspect_mat(path, summary)
        elif suffix in {".edf", ".bdf"}:
            _inspect_edf(path, summary)
        elif suffix == ".vhdr":
            _inspect_vhdr(path, summary)
    except Exception as error:
        summary.errors.append(f"{path.name}: {error}")


def _temporary_recording(
    source,
    name: str,
    temporary_dir: Path,
    number: int,
) -> Path:
    suffix = Path(PurePosixPath(name).name).suffix.casefold()
    destination = temporary_dir / f"recording-{number:06d}{suffix}"
    with destination.open("wb") as output:
        shutil.copyfileobj(source, output)
    return destination


def _archive_noise(name: str) -> bool:
    path = PurePosixPath(name)
    return "__MACOSX" in path.parts or path.name.startswith("._")


def _inspect_zip(
    archive: Path,
    temporary_dir: Path,
    summary: _InspectionSummary,
):
    with zipfile.ZipFile(archive) as source:
        candidates = [
            member
            for member in source.infolist()
            if not member.is_dir()
            and not _archive_noise(member.filename)
            and Path(PurePosixPath(member.filename).name).suffix.casefold()
            in SUPPORTED_RECORDINGS
        ]
        for number, member in enumerate(candidates, start=1):
            with source.open(member) as item:
                recording = _temporary_recording(
                    item,
                    member.filename,
                    temporary_dir,
                    number,
                )
            try:
                _inspect_recording(recording, summary)
            finally:
                recording.unlink(missing_ok=True)


def _inspect_tar(
    archive: Path,
    temporary_dir: Path,
    summary: _InspectionSummary,
):
    with tarfile.open(archive) as source:
        candidates = [
            member
            for member in source.getmembers()
            if member.isfile()
            and not _archive_noise(member.name)
            and Path(PurePosixPath(member.name).name).suffix.casefold()
            in SUPPORTED_RECORDINGS
        ]
        for number, member in enumerate(candidates, start=1):
            item = source.extractfile(member)
            if item is None:
                continue
            with item:
                recording = _temporary_recording(
                    item,
                    member.name,
                    temporary_dir,
                    number,
                )
            try:
                _inspect_recording(recording, summary)
            finally:
                recording.unlink(missing_ok=True)


def _format_rate(rate: float) -> str:
    return str(int(rate)) if rate.is_integer() else f"{rate:g}"


def _result(summary: _InspectionSummary) -> InspectionResult:
    if summary.files_checked == 0:
        detail = (
            f" First inspection error: {summary.errors[0]}"
            if summary.errors
            else ""
        )
        return InspectionResult(
            "n/a",
            "n/a",
            0,
            "No supported physiological channel headers were found." + detail,
            "needs_review",
        )

    if summary.ecg_files:
        rates = ";".join(_format_rate(rate) for rate in sorted(summary.rates))
        evidence = (
            f"ECG channel header found in {summary.ecg_files} of "
            f"{summary.files_checked} physiological files."
        )
        status = "verified"
        if not summary.rates:
            rates = "n/a"
            status = "needs_review"
            evidence += " ECG sampling rate was not present in the header."
        elif len(summary.rates) > 1:
            status = "needs_review"
            evidence += " Multiple ECG sampling rates were found."
        if summary.errors:
            status = "needs_review"
            evidence += (
                f" {len(summary.errors)} candidate files could not be checked."
            )
        return InspectionResult(
            "yes",
            rates,
            summary.files_checked,
            evidence,
            status,
        )

    evidence = (
        f"No ECG channel in any of {summary.files_checked} "
        "physiological files."
    )
    status = "verified"
    if summary.errors:
        status = "needs_review"
        evidence += f" {len(summary.errors)} candidate files could not be checked."
    return InspectionResult(
        "no",
        "n/a",
        summary.files_checked,
        evidence,
        status,
    )


def inspect_downloads(paths: list[Path]) -> InspectionResult:
    """Inspect archives or direct recordings and summarize ECG metadata."""
    summary = _InspectionSummary()
    with tempfile.TemporaryDirectory(prefix="scrfear-ecg-") as directory:
        temporary_dir = Path(directory)
        for path in paths:
            lower_name = path.name.casefold()
            try:
                if zipfile.is_zipfile(path):
                    _inspect_zip(path, temporary_dir, summary)
                elif lower_name.endswith((".tar", ".tar.gz", ".tgz")):
                    _inspect_tar(path, temporary_dir, summary)
                elif path.suffix.casefold() in SUPPORTED_RECORDINGS:
                    _inspect_recording(path, summary)
            except Exception as error:
                summary.errors.append(f"{path.name}: {error}")
    return _result(summary)
