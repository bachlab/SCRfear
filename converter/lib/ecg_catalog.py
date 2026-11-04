"""Read the PsPM Open Data catalogue and Zenodo file manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests


OPEN_DATA_URL = "https://bachlab.github.io/PsPM/opendata/"


@dataclass(frozen=True)
class CatalogEntry:
    dataset: str
    record_id: str

    @property
    def record_url(self) -> str:
        return f"https://zenodo.org/records/{self.record_id}"


@dataclass(frozen=True)
class ZenodoFile:
    name: str
    size: int
    url: str
    checksum: str | None = None


@dataclass(frozen=True)
class DatasetDownload:
    entry: CatalogEntry
    files: tuple[ZenodoFile, ...]

    @property
    def size(self) -> int:
        return sum(item.size for item in self.files)


class _OpenDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries: list[tuple[str, str]] = []
        self._in_row = False
        self._cell = -1
        self._link: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_row = True
            self._cell = -1
            self._link = None
            self._text = []
        elif self._in_row and tag in {"td", "th"}:
            self._cell += 1
        elif self._in_row and self._cell == 0 and tag == "a":
            self._link = dict(attrs).get("href")

    def handle_data(self, data):
        if self._in_row and self._cell == 0 and self._link:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self._in_row:
            text = " ".join("".join(self._text).split())
            if text and self._link:
                self.entries.append((text, self._link))
            self._in_row = False


def _dataset_name(value: str) -> str:
    return re.sub(r"^PsPM-", "", value.strip(), flags=re.IGNORECASE)


def _record_id_from_url(url: str) -> str | None:
    match = re.search(
        r"zenodo(?:\.org)?(?:/records?/|\.)(\d+)",
        url,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def fetch_catalog(
    session: requests.Session | None = None,
    url: str = OPEN_DATA_URL,
) -> list[CatalogEntry]:
    """Return the dataset names and Zenodo records on the Open Data page."""
    client = session or requests.Session()
    response = client.get(url, timeout=60)
    response.raise_for_status()

    parser = _OpenDataParser()
    parser.feed(response.text)

    entries = []
    seen = set()
    for visible_name, href in parser.entries:
        dataset = _dataset_name(visible_name)
        link = urljoin(url, href)
        record_id = _record_id_from_url(link)
        if record_id is None:
            with client.get(
                link,
                allow_redirects=True,
                stream=True,
                timeout=60,
            ) as resolved:
                resolved.raise_for_status()
                record_id = _record_id_from_url(resolved.url)
        if record_id is None:
            raise ValueError(f"Could not find a Zenodo record for {dataset}")
        if dataset in seen:
            raise ValueError(f"Duplicate dataset on Open Data page: {dataset}")
        seen.add(dataset)
        entries.append(CatalogEntry(dataset, record_id))

    if not entries:
        raise ValueError("No datasets were found on the PsPM Open Data page")
    return entries


def fetch_dataset_download(
    entry: CatalogEntry,
    session: requests.Session | None = None,
) -> DatasetDownload:
    """Return the downloadable data files for one Zenodo record."""
    client = session or requests.Session()
    response = client.get(
        f"https://zenodo.org/api/records/{entry.record_id}",
        timeout=60,
    )
    response.raise_for_status()
    manifest = response.json()

    files = manifest.get("files", [])
    data_archives = [
        item
        for item in files
        if item.get("key", "").casefold() == "data.zip"
    ]
    if not data_archives:
        supported = (
            ".zip",
            ".tar",
            ".tar.gz",
            ".tgz",
            ".mat",
            ".edf",
            ".bdf",
            ".vhdr",
        )
        data_archives = [
            item
            for item in files
            if item.get("key", "").casefold().endswith(supported)
        ]
    if not data_archives:
        raise ValueError(
            f"{entry.dataset} has no supported physiological data file"
        )

    downloads = []
    for item in data_archives:
        link = item.get("links", {}).get("self")
        if not link:
            raise ValueError(
                f"{entry.dataset} has no download link for {item.get('key')}"
            )
        downloads.append(
            ZenodoFile(
                name=item["key"],
                size=int(item["size"]),
                url=link,
                checksum=item.get("checksum"),
            )
        )
    return DatasetDownload(entry, tuple(downloads))


def plan_batches(
    downloads: list[DatasetDownload],
    batch_size: int = 5,
    max_batch_bytes: int = 10 * 1024**3,
) -> list[list[DatasetDownload]]:
    """Group downloads without splitting one dataset across batches."""
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1")
    if max_batch_bytes < 1:
        raise ValueError("Maximum batch size must be positive")

    batches: list[list[DatasetDownload]] = []
    current: list[DatasetDownload] = []
    current_size = 0
    for download in downloads:
        would_exceed_count = len(current) >= batch_size
        would_exceed_size = (
            bool(current) and current_size + download.size > max_batch_bytes
        )
        if would_exceed_count or would_exceed_size:
            batches.append(current)
            current = []
            current_size = 0
        current.append(download)
        current_size += download.size
    if current:
        batches.append(current)
    return batches
