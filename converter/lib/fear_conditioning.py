"""Compatibility imports for the original shared-converter module.

New code should import from the focused modules in this package. These aliases
keep existing imports working while the project transitions to the clearer
module structure.
"""

from .bids_writer import (
    _normalise_units,
    write_dataset_files,
    write_json,
    write_physio,
    write_run,
)
from .conversion import convert_dataset
from .events import (
    EVENT_COLUMNS,
    EVENTS_METADATA,
    build_events,
    selected_blocks,
    split_runs,
)
from .participants import (
    PARTICIPANTS_METADATA,
    _normalise_sex,
    _subject_from_metadata,
    load_pupilfear_links,
    write_participants,
)
from .source_data import (
    _channels,
    cogent_filename,
    find_data_dir,
    load_cogent,
    load_recording,
    source_ids,
)


_runs = split_runs
_write_json = write_json
_write_physio = write_physio
_write_run = write_run
_write_dataset_files = write_dataset_files


__all__ = [
    "EVENT_COLUMNS",
    "EVENTS_METADATA",
    "PARTICIPANTS_METADATA",
    "build_events",
    "cogent_filename",
    "convert_dataset",
    "find_data_dir",
    "load_cogent",
    "load_pupilfear_links",
    "load_recording",
    "selected_blocks",
    "source_ids",
    "split_runs",
    "write_dataset_files",
    "write_json",
    "write_participants",
    "write_physio",
    "write_run",
]
