"""Supporting modules for the SCRFear converter."""

from .corpus import combine_datasets
from .conversion import convert_dataset
from .tsv_configs import DATASETS

__all__ = ["DATASETS", "combine_datasets", "convert_dataset"]
