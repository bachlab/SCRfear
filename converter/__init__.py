"""SCRFear dataset download and conversion tools."""

from .lib.corpus import combine_datasets
from .lib.conversion import convert_dataset
from .lib.tsv_configs import DATASETS

__all__ = ["DATASETS", "combine_datasets", "convert_dataset"]
__version__ = "0.1.0"
