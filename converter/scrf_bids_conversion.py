"""Main command-line interface for SCRFear."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from requests import RequestException

from .lib.corpus import combine_datasets
from .lib.conversion import convert_dataset
from .lib.ecg_inventory import update_ecg_inventory
from .lib.tsv_configs import DATASETS
from .zenodo_autodownload import download_dataset


def _parser():
    parser = argparse.ArgumentParser(
        prog="scrfear",
        description=(
            "Download and convert public SCR fear-conditioning datasets, "
            "build a combined BIDS corpus, and maintain the PsPM ECG inventory."
        ),
        epilog=(
            "Run 'scrfear <command> --help' for command-specific options."
        ),
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
    )

    convert = commands.add_parser(
        "convert",
        help="convert downloaded datasets to BIDS",
        description=(
            "Convert one or more downloaded source datasets into separate "
            "BIDS datasets."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    convert.add_argument(
        "datasets",
        nargs="+",
        choices=["all", *sorted(DATASETS)],
        help="dataset names to convert; use 'all' for every configured dataset",
    )
    convert.add_argument(
        "--raw-dir",
        default="Datasets",
        type=Path,
        help="directory containing downloaded source dataset folders",
    )
    convert.add_argument(
        "--output-dir",
        default="Converted_Datasets",
        type=Path,
        help="directory in which separate converted datasets are written",
    )
    convert.add_argument(
        "--pupilfear-overview",
        default=Path("metadata/pupilbench_corpus_overview.csv"),
        type=Path,
        help="CSV mapping source IDs to PupilFear corpus IDs",
    )
    convert.add_argument(
        "--subjects",
        nargs="+",
        metavar="ID",
        help="convert only the specified source participant IDs",
    )

    download = commands.add_parser(
        "download",
        help="download source datasets from Zenodo",
        description=(
            "Download and extract Data.zip for one or more configured datasets."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    download.add_argument(
        "datasets",
        nargs="+",
        choices=["all", *sorted(DATASETS)],
        help="dataset names to download; use 'all' for every configured dataset",
    )
    download.add_argument(
        "--raw-dir",
        default="Datasets",
        type=Path,
        help="directory in which downloaded dataset folders are written",
    )
    download.add_argument(
        "--force",
        action="store_true",
        help="download and extract Data.zip again when it already exists",
    )

    combine = commands.add_parser(
        "combine",
        help="combine converted datasets into one corpus",
        description=(
            "Copy converted datasets into one corpus with unique participant "
            "IDs and a source-ID overview."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    combine.add_argument(
        "datasets",
        nargs="*",
        default=argparse.SUPPRESS,
        metavar="DATASET",
        help=(
            "converted datasets to include; omit this argument or use 'all' "
            "for every configured dataset (see 'scrfear list')"
        ),
    )
    combine.add_argument(
        "--input-dir",
        default="Converted_Datasets",
        type=Path,
        help="directory containing separate converted dataset folders",
    )
    combine.add_argument(
        "--output-dir",
        default="Corpus",
        type=Path,
        help="directory in which the combined corpus is written",
    )
    combine.add_argument(
        "--force",
        action="store_true",
        help="replace an existing corpus after a successful rebuild",
    )

    ecg_inventory = commands.add_parser(
        "ecg-inventory",
        help="complete the PsPM ECG spreadsheet in low-disk batches",
        description=(
            "Inspect pending datasets from the PsPM Open Data catalogue for "
            "ECG channels and sampling rates. Progress is saved after every "
            "dataset, and temporary downloads are then removed."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ecg_inventory.add_argument(
        "datasets",
        nargs="*",
        default=argparse.SUPPRESS,
        metavar="DATASET",
        help=(
            "specific PsPM catalogue datasets to inspect; omit to process "
            "every row not already verified"
        ),
    )
    ecg_inventory.add_argument(
        "--inventory",
        default=Path("metadata/pspm_ecg_inventory.csv"),
        type=Path,
        help="CSV file updated after each inspected dataset",
    )
    ecg_inventory.add_argument(
        "--cache-dir",
        default=Path("ECG_Download_Cache"),
        type=Path,
        help="dedicated directory used only for temporary downloads",
    )
    ecg_inventory.add_argument(
        "--batch-size",
        default=5,
        type=int,
        help="maximum number of datasets grouped into one batch",
    )
    ecg_inventory.add_argument(
        "--max-batch-gb",
        default=10.0,
        type=float,
        help="approximate maximum compressed download size per batch in GiB",
    )
    ecg_inventory.add_argument(
        "--reserve-gb",
        default=2.0,
        type=float,
        help="free disk space kept in reserve before each download",
    )
    ecg_inventory.add_argument(
        "--max-batches",
        type=int,
        help="stop after this many batches; omit to process all pending rows",
    )
    ecg_inventory.add_argument(
        "--keep-downloads",
        action="store_true",
        help="retain downloaded files after recording the inspection result",
    )

    commands.add_parser(
        "list",
        help="list configured dataset names",
        description="List every dataset supported by this converter.",
    )
    return parser


def _requested_datasets(values):
    """Expand the all selector or return the requested dataset names."""
    if not values:
        return list(DATASETS)
    if "all" in values:
        if len(values) != 1:
            raise ValueError("'all' cannot be combined with dataset names")
        return list(DATASETS)
    unknown = sorted(set(values) - set(DATASETS))
    if unknown:
        raise ValueError("Unknown dataset(s): " + ", ".join(unknown))
    if len(set(values)) != len(values):
        raise ValueError("Dataset names must not be repeated")
    return list(values)


def main(argv=None):
    args = _parser().parse_args(argv)

    if args.command == "list":
        for dataset in DATASETS:
            print(dataset)
        return 0

    try:
        if args.command == "ecg-inventory":
            summary = update_ecg_inventory(
                inventory_path=args.inventory,
                cache_root=args.cache_dir,
                batch_size=args.batch_size,
                max_batch_gb=args.max_batch_gb,
                reserve_gb=args.reserve_gb,
                max_batches=args.max_batches,
                datasets=getattr(args, "datasets", None),
                keep_downloads=args.keep_downloads,
            )
            print(
                f"[ECG] Catalogue: {summary['catalogue']}; "
                f"processed: {summary['processed']}; "
                f"verified: {summary['verified']}; "
                f"needs review: {summary['needs_review']}; "
                f"failed: {summary['failed']}"
            )
            return 1 if summary["failed"] else 0

        datasets = _requested_datasets(getattr(args, "datasets", None))
        if args.command == "combine":
            summary = combine_datasets(
                converted_root=args.input_dir,
                corpus_root=args.output_dir,
                datasets=datasets,
                force=args.force,
            )
            print(
                f"[Corpus] Complete: {summary['participants']} participants "
                f"from {summary['datasets']} datasets"
            )
            if summary.get("excluded_participants"):
                print(
                    "[Corpus] Excluded by study selection rules: "
                    f"{summary['excluded_participants']} participants"
                )
                for dataset, counts in summary["dataset_participants"].items():
                    if counts["excluded"]:
                        print(
                            f"[{dataset}] Corpus selection: "
                            f"{counts['included']} included, "
                            f"{counts['excluded']} excluded"
                        )
            print(f"[Corpus] Output: {summary['output']}")
            return 0

        failed = []

        if args.command == "download":
            if args.datasets == ["all"]:
                print(
                    f"[all] Downloading and extracting all {len(datasets)} "
                    "datasets may require substantial disk space. Archives "
                    "and extracted files are both retained."
                )
            for dataset in datasets:
                try:
                    download_dataset(dataset, args.raw_dir, args.force)
                except Exception as error:
                    failed.append(dataset)
                    print(f"[{dataset}] Failed: {error}", file=sys.stderr)
        else:
            for dataset in datasets:
                try:
                    summary = convert_dataset(
                        dataset,
                        raw_root=args.raw_dir,
                        output_root=args.output_dir,
                        pupilfear_overview=args.pupilfear_overview,
                        subjects=args.subjects,
                    )
                    if summary["failed_recordings"]:
                        failed.append(dataset)
                except Exception as error:
                    failed.append(dataset)
                    print(f"[{dataset}] Failed: {error}", file=sys.stderr)

        if failed:
            print(
                "Datasets requiring attention: " + ", ".join(failed),
                file=sys.stderr,
            )
            return 1
    except (OSError, RequestException, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
