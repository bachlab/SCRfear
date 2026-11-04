import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pandas as pd
from scipy.io import savemat

from converter.lib.tsv_configs import DATASETS
from converter.lib.corpus import combine_datasets
from converter.lib.corpus_participants import (
    scr_opt_participants,
    select_scr_opt_participants,
)
from converter.lib.ecg_catalog import (
    CatalogEntry,
    DatasetDownload,
    ZenodoFile,
    plan_batches,
)
from converter.lib.ecg_inspection import inspect_downloads
from converter.lib.ecg_inventory import _safe_remove_dataset_cache
from converter.lib.events import build_events, selected_blocks, split_runs
from converter.lib.participants import load_pupilfear_links
from converter.lib.source_data import load_cogent, load_recording, source_ids
from converter.scrf_bids_conversion import (
    _parser,
    _requested_datasets,
    main,
)


class ConverterTests(unittest.TestCase):
    def test_cogent_keys_with_vector_indexes_keep_source_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cogent.mat"
            column_names = ["block_number", "cs_type", "us_presence"]
            key = np.empty(len(column_names), dtype=object)
            for index, name in enumerate(column_names):
                key[index] = {
                    "column_type": name,
                    "column_index": np.arange(1, len(column_names) + 1),
                }
            values = np.array([[1, 2, 0], [2, 1, 1]], dtype=float)
            savemat(path, {"data": values, "dataKey": key})

            frame = load_cogent(path)

        self.assertEqual(frame.columns.tolist(), column_names)
        np.testing.assert_array_equal(frame.to_numpy(), values)

    def test_cogent_keys_with_scalar_indexes_are_sorted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cogent.mat"
            key = np.empty(3, dtype=object)
            key[0] = {"column_type": "us_presence", "column_index": 3}
            key[1] = {"column_type": "cs_type", "column_index": 2}
            key[2] = {"column_type": "block_number", "column_index": 1}
            values = np.array([[1, 2, 0], [2, 1, 1]], dtype=float)
            savemat(path, {"data": values, "dataKey": key})

            frame = load_cogent(path)

        self.assertEqual(
            frame.columns.tolist(),
            ["block_number", "cs_type", "us_presence"],
        )
        np.testing.assert_array_equal(frame.to_numpy(), values)

    def test_ecg_downloads_are_grouped_by_count_and_size(self):
        def download(name, size):
            entry = CatalogEntry(name, str(size))
            remote = ZenodoFile("Data.zip", size, "https://example.org")
            return DatasetDownload(entry, (remote,))

        downloads = [
            download("A", 4),
            download("B", 4),
            download("C", 4),
            download("D", 20),
        ]
        batches = plan_batches(
            downloads,
            batch_size=3,
            max_batch_bytes=10,
        )
        self.assertEqual(
            [[item.entry.dataset for item in batch] for batch in batches],
            [["A", "B"], ["C"], ["D"]],
        )

    def test_ecg_inspection_reads_channel_headers_without_full_extraction(self):
        def recording(path, channel_type, sampling_rate):
            channels = np.empty(2, dtype=object)
            channels[0] = {
                "header": {
                    "chantype": channel_type,
                    "sr": sampling_rate,
                },
                "data": np.array([1.0, 2.0]),
            }
            channels[1] = {
                "header": {"chantype": "scr", "sr": sampling_rate},
                "data": np.array([3.0, 4.0]),
            }
            savemat(path, {"data": channels})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ecg = root / "ecg.mat"
            scr = root / "scr.mat"
            archive = root / "Data.zip"
            recording(ecg, "ecg", 1000)
            recording(scr, "marker", 1000)
            metadata = root / "metadata.mat"
            savemat(metadata, {"data": 1.0})
            with zipfile.ZipFile(archive, "w") as destination:
                destination.write(ecg, "Data/subject-01.mat")
                destination.write(scr, "Data/subject-02.mat")
                destination.write(metadata, "Data/cogent-01.mat")
                destination.writestr(
                    "__MACOSX/Data/._subject-01.mat",
                    b"not a MATLAB file",
                )

            result = inspect_downloads([archive])

        self.assertEqual(result.ecg_recorded, "yes")
        self.assertEqual(result.sampling_rate, "1000")
        self.assertEqual(result.files_checked, 2)
        self.assertEqual(result.status, "verified")

    def test_ecg_inspection_marks_unrecognized_headers_for_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "Data.zip"
            with zipfile.ZipFile(archive, "w") as destination:
                destination.writestr("Data/notes.txt", "No channel data")

            result = inspect_downloads([archive])

        self.assertEqual(result.ecg_recorded, "n/a")
        self.assertEqual(result.files_checked, 0)
        self.assertEqual(result.status, "needs_review")

    def test_ecg_cleanup_is_limited_to_a_marked_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            dataset = cache / "example"
            dataset.mkdir(parents=True)
            (dataset / "Data.zip").write_bytes(b"data")

            with self.assertRaises(ValueError):
                _safe_remove_dataset_cache(cache, dataset)
            self.assertTrue(dataset.is_dir())

            (cache / ".scrfear_ecg_cache").write_text(
                "managed cache\n",
                encoding="utf-8",
            )
            _safe_remove_dataset_cache(cache, dataset)
            self.assertFalse(dataset.exists())

    def test_ecg_inventory_command_uses_low_disk_defaults(self):
        summary = {
            "catalogue": 61,
            "processed": 5,
            "verified": 5,
            "needs_review": 0,
            "failed": 0,
        }
        with (
            patch(
                "converter.scrf_bids_conversion.update_ecg_inventory",
                return_value=summary,
            ) as update,
            patch("builtins.print"),
        ):
            result = main(["ecg-inventory", "--max-batches", "1"])

        self.assertEqual(result, 0)
        self.assertEqual(update.call_args.kwargs["batch_size"], 5)
        self.assertEqual(update.call_args.kwargs["max_batch_gb"], 10.0)
        self.assertEqual(update.call_args.kwargs["max_batches"], 1)
        self.assertFalse(update.call_args.kwargs["keep_downloads"])

    def test_all_selector_expands_to_every_configured_dataset(self):
        for command in ("download", "convert", "combine"):
            args = _parser().parse_args([command, "all"])
            self.assertEqual(_requested_datasets(args.datasets), list(DATASETS))

        combine = _parser().parse_args(["combine"])
        self.assertEqual(
            _requested_datasets(getattr(combine, "datasets", None)),
            list(DATASETS),
        )

        with self.assertRaises(ValueError):
            _requested_datasets(["all", "CFG1"])
        with self.assertRaises(ValueError):
            _requested_datasets(["unknown"])
        with self.assertRaises(ValueError):
            _requested_datasets(["CFG1", "CFG1"])

    def test_all_selector_runs_each_download_and_conversion(self):
        with (
            patch(
                "converter.scrf_bids_conversion.download_dataset"
            ) as download,
            patch("builtins.print"),
        ):
            self.assertEqual(main(["download", "all"]), 0)

        self.assertEqual(
            [item.args[0] for item in download.call_args_list],
            list(DATASETS),
        )

        summary = {"failed_recordings": []}
        with patch(
            "converter.scrf_bids_conversion.convert_dataset",
            return_value=summary,
        ) as convert:
            self.assertEqual(main(["convert", "all"]), 0)

        self.assertEqual(
            [item.args[0] for item in convert.call_args_list],
            list(DATASETS),
        )

        corpus_summary = {
            "participants": 10,
            "datasets": len(DATASETS),
            "output": "Corpus",
        }
        with (
            patch(
                "converter.scrf_bids_conversion.combine_datasets",
                return_value=corpus_summary,
            ) as combine,
            patch("builtins.print"),
        ):
            self.assertEqual(main(["combine"]), 0)

        self.assertEqual(combine.call_args.kwargs["datasets"], list(DATASETS))

    def test_combined_corpus_assigns_ids_and_preserves_source_mapping(self):
        def add_dataset(root, dataset, subject, age, treatment=None):
            dataset_dir = root / dataset
            physio = dataset_dir / subject / "physio"
            physio.mkdir(parents=True)
            source_file = (
                physio
                / f"{subject}_task-fearconditioning_run-01_events.tsv"
            )
            source_file.write_text("onset\tduration\n0\t1\n", encoding="utf-8")

            participant = {
                "participant_id": subject,
                "PupilFearSubjectID": "n/a",
                "age": age,
                "sex": "F",
            }
            if treatment is not None:
                participant["treatment"] = treatment
            pd.DataFrame([participant]).to_csv(
                dataset_dir / "participants.tsv",
                sep="\t",
                index=False,
            )

            metadata = {
                "participant_id": {"Description": "Participant ID."},
                "age": {"Description": "Age.", "Units": "years"},
                "sex": {"Description": "Sex."},
            }
            if treatment is not None:
                metadata["treatment"] = {
                    "Description": "Treatment.",
                    "Levels": {treatment: "Source treatment."},
                }
            (dataset_dir / "participants.json").write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
            (dataset_dir / "dataset_description.json").write_text(
                json.dumps(
                    {
                        "Name": dataset,
                        "Authors": [f"{dataset} Author"],
                        "SourceDatasets": [
                            {"URL": f"https://example.org/{dataset}"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            converted = workspace / "Converted_Datasets"
            corpus = workspace / "Corpus"
            add_dataset(converted, "CFG1", "sub-02", "24")
            add_dataset(
                converted,
                "DoxAv2",
                "sub-001",
                "23",
                "placebo",
            )

            drug_dir = converted / "DoxAv2" / "sub-002" / "physio"
            drug_dir.mkdir(parents=True)
            (drug_dir / "sub-002_task-fearconditioning_run-01_events.tsv").write_text(
                "onset\tduration\n0\t1\n",
                encoding="utf-8",
            )
            doxav2_participants = converted / "DoxAv2" / "participants.tsv"
            participant_rows = pd.read_csv(
                doxav2_participants,
                sep="\t",
                dtype=str,
                keep_default_na=False,
            )
            participant_rows = pd.concat(
                [
                    participant_rows,
                    pd.DataFrame(
                        [
                            {
                                "participant_id": "sub-002",
                                "PupilFearSubjectID": "n/a",
                                "age": "25",
                                "sex": "M",
                                "treatment": "doxycycline",
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
            participant_rows.to_csv(
                doxav2_participants,
                sep="\t",
                index=False,
            )

            summary = combine_datasets(
                converted,
                corpus,
                ["DoxAv2", "CFG1"],
            )
            overview = pd.read_csv(
                corpus / "scrfear_corpus_overview.csv",
                dtype=str,
            )
            participants = pd.read_csv(
                corpus / "participants.tsv",
                sep="\t",
                dtype=str,
                keep_default_na=False,
            )
            participant_metadata = json.loads(
                (corpus / "participants.json").read_text(encoding="utf-8")
            )

            self.assertEqual(summary["datasets"], 2)
            self.assertEqual(summary["participants"], 2)
            self.assertEqual(summary["excluded_participants"], 1)
            self.assertEqual(
                overview.to_dict(orient="records"),
                [
                    {
                        "Corpus_ID": "sub-001",
                        "Dataset": "CFG1",
                        "Orig_ID": "sub-02",
                    },
                    {
                        "Corpus_ID": "sub-002",
                        "Dataset": "DoxAv2",
                        "Orig_ID": "sub-001",
                    },
                ],
            )
            self.assertEqual(
                participants["source_dataset"].tolist(),
                ["CFG1", "DoxAv2"],
            )
            self.assertEqual(
                participants["source_participant_id"].tolist(),
                ["sub-02", "sub-001"],
            )
            self.assertEqual(
                participants["treatment"].tolist(),
                ["n/a", "placebo"],
            )
            self.assertIn("source_dataset", participant_metadata)
            self.assertTrue(
                (
                    corpus
                    / "sub-001"
                    / "physio"
                    / "sub-001_task-fearconditioning_run-01_events.tsv"
                ).is_file()
            )
            self.assertFalse((corpus / "sub-003").exists())
            self.assertFalse((workspace / "Corpus-building").exists())
            self.assertTrue(
                (
                    corpus
                    / "sub-002"
                    / "physio"
                    / "sub-002_task-fearconditioning_run-01_events.tsv"
                ).is_file()
            )

            with self.assertRaises(FileExistsError):
                combine_datasets(converted, corpus, ["CFG1", "DoxAv2"])
            rebuilt = combine_datasets(
                converted,
                corpus,
                ["CFG1", "DoxAv2"],
                force=True,
            )
            self.assertEqual(rebuilt["participants"], 2)

    def test_all_current_datasets_use_shared_configuration(self):
        self.assertEqual(
            set(DATASETS),
            {
                "CFG1",
                "CFG2",
                "DoxMemP",
                "DoxMem1",
                "DoxMem2",
                "DoxAv2",
                "FER01",
                "FER02",
                "FR",
                "FSS6B",
                "LI",
                "LSOA",
                "MinAv",
                "PubFe",
                "SC4B",
                "TC",
                "VC7B",
            },
        )

    def test_source_ids_come_from_named_filename_groups(self):
        subject, recording = source_ids(
            Path("FER02_wdq_7_sn1.mat"),
            DATASETS["FER02"],
        )
        self.assertEqual(subject, "07")
        self.assertEqual(recording, "1")

    def test_cfg1_uses_only_the_acquisition_session(self):
        subject, recording = source_ids(
            Path("CFG1_acq_2_sn1.mat"),
            DATASETS["CFG1"],
        )

        self.assertEqual(subject, "02")
        self.assertEqual(recording, "1")
        self.assertEqual(DATASETS["CFG1"]["acquisition_blocks"], [1, 2, 3, 4])
        self.assertEqual(DATASETS["CFG1"]["exclusions"], [])

    def test_cfg2_uses_the_shared_context_acquisition_settings(self):
        subject, recording = source_ids(
            Path("CFG2_acq_7_sn1.mat"),
            DATASETS["CFG2"],
        )

        self.assertEqual(subject, "07")
        self.assertEqual(recording, "1")
        self.assertEqual(DATASETS["CFG2"]["acquisition_blocks"], [1, 2, 3, 4])
        self.assertEqual(DATASETS["CFG2"]["exclusions"], [])
        self.assertEqual(DATASETS["CFG2"]["cs_duration"], 7.5)
        self.assertEqual(DATASETS["CFG2"]["soa"], 7.0)

    def test_minav_uses_only_session_one(self):
        config = DATASETS["MinAv"]
        subject, recording = source_ids(
            Path("MinAv_acq_7_sn1.mat"),
            config,
        )

        self.assertEqual(subject, "007")
        self.assertEqual(recording, "1")
        self.assertEqual(config["acquisition_blocks"], [1, 2, 3, 4])
        self.assertEqual(config["exclusions"], [])
        self.assertEqual(config["cs_duration"], 7.5)
        self.assertEqual(config["soa"], 7.0)
        self.assertEqual(config["participant_columns"], {"treatment": "group"})
        with self.assertRaises(ValueError):
            source_ids(Path("MinAv_acq_7_sn3.mat"), config)

    def test_doxav2_skips_the_incomplete_acquisition_recording(self):
        config = DATASETS["DoxAv2"]
        subject, recording = source_ids(
            Path("DoxAv2_acq_7_sn1.mat"),
            config,
        )

        self.assertEqual(subject, "007")
        self.assertEqual(recording, "1")
        self.assertEqual(config["acquisition_blocks"], [1, 2, 3, 4])
        self.assertEqual(config["exclusions"], [10])
        self.assertEqual(config["cs_duration"], 7.5)
        self.assertEqual(config["soa"], 7.0)
        self.assertEqual(config["participant_columns"], {"treatment": "group"})
        with self.assertRaises(ValueError):
            source_ids(Path("DoxAv2_acq_7_sn2.mat"), config)

    def test_fss6b_excludes_recording_with_missing_markers(self):
        self.assertEqual(DATASETS["FSS6B"]["exclusions"], [2])

    def test_only_unusable_source_recordings_are_skipped_during_conversion(self):
        exclusions = {
            dataset: config["exclusions"]
            for dataset, config in DATASETS.items()
            if config["exclusions"]
        }

        self.assertEqual(exclusions, {"DoxAv2": [10], "FSS6B": [2]})
        self.assertEqual(DATASETS["DoxMem1"]["zenodo_record"], "3361660")

    def test_hdf5_recordings_use_the_shared_source_loader(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.mat"
            with h5py.File(path, "w") as target:
                references = target.create_group("#refs#")

                def add_char(group, name, value):
                    data = np.array(
                        [ord(character) for character in value],
                        dtype=np.uint16,
                    ).reshape(-1, 1)
                    dataset = group.create_dataset(name, data=data)
                    dataset.attrs["MATLAB_class"] = np.bytes_("char")

                channels = []
                for name, channel_type, values, units in (
                    ("scr", "scr", [0.1, 0.2, 0.3], "uS"),
                    ("marker", "marker", [1.0, 2.0], "events"),
                ):
                    channel = references.create_group(name)
                    channel.attrs["MATLAB_class"] = np.bytes_("struct")
                    data = channel.create_dataset(
                        "data",
                        data=np.asarray(values).reshape(1, -1),
                    )
                    data.attrs["MATLAB_class"] = np.bytes_("double")
                    header = channel.create_group("header")
                    header.attrs["MATLAB_class"] = np.bytes_("struct")
                    add_char(header, "chantype", channel_type)
                    add_char(header, "units", units)
                    rate = header.create_dataset("sr", data=[[1000.0]])
                    rate.attrs["MATLAB_class"] = np.bytes_("double")
                    channels.append(channel.ref)

                cell = target.create_dataset(
                    "data",
                    shape=(1, len(channels)),
                    dtype=h5py.ref_dtype,
                )
                cell.attrs["MATLAB_class"] = np.bytes_("cell")
                for index, reference in enumerate(channels):
                    cell[0, index] = reference

            marker, samples, sampling_rate, units = load_recording(path)

        self.assertEqual(marker.tolist(), [1.0, 2.0])
        self.assertEqual(samples.tolist(), [0.1, 0.2, 0.3])
        self.assertEqual(sampling_rate, 1000.0)
        self.assertEqual(units, "uS")

    def test_pubfe_recordings_map_to_separate_acquisition_blocks(self):
        cogent = pd.DataFrame({"block_number": [1, 1, 2, 2]})
        config = DATASETS["PubFe"]

        self.assertEqual(selected_blocks(cogent, config, "1"), [1])
        self.assertEqual(selected_blocks(cogent, config, "2"), [2])

    def test_tc_uses_trace_conditioning_timing(self):
        config = DATASETS["TC"]
        cogent = pd.DataFrame(
            {
                "block_number": [1],
                "cs_type": [1],
                "us_presence": [1],
            }
        )

        events = build_events(np.array([10.0]), cogent, config, "1")
        cs_event = events[events["event_type"] == "CSpr"].iloc[0]
        us_event = events[events["event_type"] == "USp"].iloc[0]

        self.assertEqual(cs_event["duration"], 3.0)
        self.assertEqual(us_event["onset"], 14.0)

    def test_tc_and_pubfe_keep_source_participants_for_corpus_selection(self):
        self.assertEqual(DATASETS["TC"]["exclusions"], [])
        self.assertEqual(DATASETS["PubFe"]["exclusions"], [])

    def test_vc7b_noncontiguous_blocks_keep_their_own_markers(self):
        config = dict(DATASETS["VC7B"])
        config["acquisition_blocks"] = [1, 3]
        cogent = pd.DataFrame(
            {
                "block_numer": [1, 2, 3, 4],
                "cs_type": [1, 2, 1, 2],
                "us_presence": [1, 0, 0, 0],
            }
        )

        events = build_events(
            np.array([10.0, 20.0, 30.0, 40.0]),
            cogent,
            config,
            "1",
        )
        cs_events = events[
            events["event_type"].isin(["CSpr", "CSpu", "CSm"])
        ]

        self.assertEqual(cs_events["onset"].tolist(), [10.0, 30.0])
        self.assertEqual(set(events["block_number"]), {1, 3})

    def test_vc7b_and_sc4b_keep_source_participants_for_corpus_selection(self):
        self.assertEqual(DATASETS["VC7B"]["exclusions"], [])
        self.assertEqual(DATASETS["SC4B"]["exclusions"], [])

    def test_scr_opt_participant_list_contains_543_people(self):
        selections = scr_opt_participants()

        self.assertEqual(set(selections), set(DATASETS))
        self.assertEqual(sum(map(len, selections.values())), 543)
        self.assertEqual(len(selections["DoxMem1"]), 38)
        self.assertEqual(len(selections["DoxAv2"]), 45)
        self.assertEqual(len(selections["MinAv"]), 48)

    def test_scr_opt_selection_uses_source_ids_for_standard_datasets(self):
        participants = pd.DataFrame({
            "participant_id": [f"sub-{number:02d}" for number in range(1, 80)]
        })

        selected = select_scr_opt_participants(
            "DoxMem2",
            participants,
            require_complete=True,
        )

        self.assertEqual(len(selected), 78)
        self.assertNotIn("sub-40", set(selected["participant_id"]))

    def test_scr_opt_selection_uses_placebo_order_for_drug_studies(self):
        participants = pd.DataFrame({
            "participant_id": [
                f"sub-{number:03d}" for number in range(1, 53)
            ]
        })

        selected = select_scr_opt_participants(
            "DoxAv2",
            participants,
            require_complete=True,
        )

        self.assertEqual(len(selected), 45)
        self.assertNotIn("sub-010", set(selected["participant_id"]))
        self.assertNotIn("sub-021", set(selected["participant_id"]))

    def test_complete_drug_selection_requires_every_placebo_participant(self):
        participants = pd.DataFrame({
            "participant_id": [
                f"sub-{number:03d}" for number in range(1, 52)
            ]
        })

        with self.assertRaisesRegex(ValueError, "52"):
            select_scr_opt_participants(
                "DoxAv2",
                participants,
                require_complete=True,
            )

    def test_events_are_standardised_and_limited_to_acquisition(self):
        config = dict(DATASETS["FER02"])
        cogent = pd.DataFrame(
            {
                "block_number": [1, 1, 2, 2, 3],
                "cs_type": [2, 1, 3, 1, 2],
                "us_presence": [1, 0, 0, 0, 1],
            }
        )
        marker = np.array([10.0, 20.0, 30.0, 40.0])

        events = build_events(marker, cogent, config, "1")

        self.assertEqual(len(events), 8)
        self.assertEqual(set(events["block_number"]), {1, 2})
        self.assertEqual(
            set(events["event_type"]),
            {"CSpr", "CSpu", "CSm", "USp", "USo", "USm"},
        )

    def test_events_allow_configured_trailing_markers(self):
        config = dict(DATASETS["FER02"])
        config["acquisition_blocks"] = [1]
        cogent = pd.DataFrame(
            {
                "block_number": [1],
                "cs_type": [2],
                "us_presence": [1],
            }
        )
        events = build_events(
            np.array([10.0, 99.0, 100.0]),
            cogent,
            config,
            "1",
        )
        self.assertEqual(len(events), 2)

    def test_runs_retime_events_and_crop_scr(self):
        config = dict(DATASETS["FER02"])
        events = pd.DataFrame(
            {
                "onset": [10.0, 13.5, 20.0, 23.5],
                "duration": [4.0, 0.5, 4.0, 0.0],
                "event_type": ["CSpr", "USp", "CSm", "USm"],
                "stimulus_name": ["a", "b", "c", "d"],
                "task_name": ["fearconditioning"] * 4,
                "block_number": [1, 1, 1, 1],
            }
        )
        samples = np.arange(50_000)

        [(run_number, run_events, run_samples)] = list(
            split_runs(events, samples, 1000, config, 1)
        )

        self.assertEqual(run_number, 1)
        self.assertEqual(run_events["onset"].iloc[0], 5.0)
        self.assertEqual(len(run_samples), 43_500)

    def test_pupilfear_lookup_uses_corpus_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overview.csv"
            path.write_text(
                "Corpus_ID,Dataset,Orig_ID\n"
                "sub-102,FER02,sub-01\n",
                encoding="utf-8",
            )
            links = load_pupilfear_links(path)

        self.assertEqual(links[("FER02", "sub-01")], "sub-102")


if __name__ == "__main__":
    unittest.main()
