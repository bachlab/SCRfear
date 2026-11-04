"""Dataset-specific settings for the SCRFear converter."""


def _dataset(
    *,
    name,
    zenodo,
    authors,
    description,
    data_pattern,
    metadata_pattern,
    cogent_name,
    blocks,
    cs_plus,
    cs_minus,
    stimuli,
    soa,
    cs_duration,
    task_description,
    **overrides,
):
    config = {
        "name": name,
        "zenodo_record": str(zenodo),
        "authors": authors,
        "description": description,
        "data_pattern": data_pattern,
        "metadata_pattern": metadata_pattern,
        "cogent_name": cogent_name,
        "acquisition_blocks": blocks,
        "cs_plus": cs_plus,
        "cs_minus": cs_minus,
        "stimuli": stimuli,
        "soa": soa,
        "cs_duration": cs_duration,
        "task_description": task_description,
        "task_name": "fearconditioning",
        "block_column": "block_number",
        "cs_column": "cs_type",
        "us_column": "us_presence",
        "us_duration": 0.5,
        "left_offset": 5.0,
        "right_offset": 25.0,
        "subject_width": 2,
        "exclusions": [],
    }
    config.update(overrides)
    return config


def _context_dataset(*, name, zenodo, exclusions):
    return _dataset(
        name=name,
        zenodo=zenodo,
        authors=[
            "Xia, Y.",
            "Wehrli, J.",
            "Gerster, S.",
            "Kroes, M.",
            "Houtekamer, M.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from the acquisition session of "
            "a differential contextual fear-conditioning study."
        ),
        data_pattern=(
            rf"^{name}_acq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$"
        ),
        metadata_pattern=rf"^{name}_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name=f"{name}_cogent_{{subject}}_sn{{recording}}.mat",
        blocks=[1, 2, 3, 4],
        cs_plus=[1],
        cs_minus=[2, 3, 4, 5],
        stimuli={
            1: "CS+ room image",
            2: "CS- room image 2",
            3: "CS- room image 3",
            4: "CS- room image 4",
            5: "CS- room image 5",
        },
        soa=7.0,
        cs_duration=7.5,
        task_description=(
            "Differential contextual fear acquisition with five static room "
            "images and a partially reinforced electrical stimulus."
        ),
        scr_units="µS",
        exclusions=exclusions,
    )


def _medication_context_dataset(
    *,
    name,
    zenodo,
    authors,
    medication,
    exclusions,
    treatment_values,
):
    return _dataset(
        name=name,
        zenodo=zenodo,
        authors=authors,
        description=(
            "Skin conductance measurements from the acquisition session of "
            f"a placebo-controlled {medication} study using differential "
            "configural fear conditioning."
        ),
        data_pattern=(
            rf"^{name}_acq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$"
        ),
        metadata_pattern=rf"^{name}_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name=f"{name}_cogent_{{subject}}_sn{{recording}}.mat",
        blocks=[1, 2, 3, 4],
        cs_plus=[1],
        cs_minus=[2, 3, 4, 5],
        stimuli={
            1: "CS+ room image",
            2: "CS- room image 2",
            3: "CS- room image 3",
            4: "CS- room image 4",
            5: "CS- room image 5",
        },
        soa=7.0,
        cs_duration=7.5,
        task_description=(
            "Differential configural fear acquisition with five static room "
            "images and a partially reinforced electrical stimulus."
        ),
        scr_units="µS",
        subject_width=3,
        exclusions=exclusions,
        participant_columns={"treatment": "group"},
        participant_value_maps={"treatment": treatment_values},
        participant_metadata={
            "treatment": {
                "Description": "Treatment administered before fear acquisition.",
                "Levels": {
                    medication: f"200 mg {medication} treatment.",
                    "placebo": "Placebo treatment.",
                },
            },
        },
        corpus_participant_filters={"treatment": ["placebo"]},
    )


DATASETS = {
    "DoxMemP": _dataset(
        name="DoxMemP",
        zenodo="1887738",
        authors=[
            "Khemka, S.",
            "Tzovara, A.",
            "Gerster, S.",
            "Quednow, B.B.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from the acquisition phase of a "
            "discriminant delay fear-conditioning study."
        ),
        data_pattern=r"^DoxMemP_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^DoxMemP_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name="DoxMemP_cogent_{subject}_sn{recording}.mat",
        blocks=[1, 2],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ coloured rectangle",
            2: "CS- coloured rectangle",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with red and blue rectangles "
            "and a partially reinforced electrical stimulus."
        ),
    ),
    "DoxMem1": _dataset(
        name="DoxMem1",
        zenodo="3361660",
        authors=["Bach, D.R.", "Tzovara, A.", "Vunder, J."],
        description=(
            "Skin conductance measurements from the acquisition phase of a "
            "placebo-controlled doxycycline fear-memory study."
        ),
        data_pattern=r"^DoxMem1_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^DoxMem1_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name="DoxMem1_cogent_{subject}_sn{recording}.mat",
        blocks=[1, 2],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ coloured screen",
            2: "CS- coloured screen",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with red and blue screens "
            "and a partially reinforced electrical stimulus."
        ),
        participant_columns={"treatment": "drug"},
        participant_value_maps={
            "treatment": {0: "placebo", 1: "doxycycline"},
        },
        participant_metadata={
            "treatment": {
                "Description": "Treatment administered before fear acquisition.",
                "Levels": {
                    "placebo": "Placebo treatment.",
                    "doxycycline": "200 mg doxycycline treatment.",
                },
            },
        },
        corpus_participant_filters={"treatment": ["placebo"]},
    ),
    "DoxMem2": _dataset(
        name="DoxMem2",
        zenodo="3460921",
        authors=[
            "Bach, D.R.",
            "Naef, M.",
            "Deutschmann, M.",
            "Tyagarajan, S.K.",
            "Quednow, B.B.",
        ],
        description=(
            "Skin conductance measurements from the initial acquisition phase "
            "of a discriminant delay fear-conditioning and memory study."
        ),
        data_pattern=r"^DoxMem2_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^DoxMem2_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name="DoxMem2_cogent_{subject}_sn{recording}.mat",
        blocks=[1],
        cs_plus=[2, 3],
        cs_minus=[1],
        stimuli={
            1: "CS- coloured triangle",
            2: "reminded CS+ coloured triangle",
            3: "non-reminded CS+ coloured triangle",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Initial discriminant delay fear acquisition with one CS- and two "
            "partially reinforced CS+ coloured triangles."
        ),
        exclusions=[],
    ),
    "FER01": _dataset(
        name="FER01",
        zenodo="5650832",
        authors=["Zimmermann, J.", "Sporrer, J.K.", "Bach, D.R."],
        description=(
            "Skin conductance measurements from a discriminant delay "
            "fear-conditioning study with three visual stimuli."
        ),
        data_pattern=r"^FER01_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^FER01_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="FER01_cogent_{subject}.mat",
        blocks=[1, 2],
        cs_plus=[2, 3],
        cs_minus=[1],
        stimuli={
            1: "CS- coloured triangle",
            2: "CS+ coloured triangle A",
            3: "CS+ coloured triangle B",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with one CS- and two "
            "partially reinforced CS+ coloured triangles."
        ),
    ),
    "FER02": _dataset(
        name="FER02",
        zenodo="10491934",
        authors=["Zimmermann, J.", "Sporrer, J.K.", "Bach, D.R."],
        description=(
            "Skin conductance measurements from the acquisition phase of a "
            "three-session return-of-fear study."
        ),
        data_pattern=r"^FER02_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^FER02_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name="FER02_cogent_{subject}_sn{recording}.mat",
        blocks=[1, 2],
        cs_plus=[2, 3],
        cs_minus=[1],
        stimuli={
            1: "CS- coloured triangle",
            2: "CSa+ coloured triangle",
            3: "CSb+ coloured triangle",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with one CS- and two "
            "partially reinforced CS+ coloured triangles."
        ),
        sex_map={"w": "F"},
        scr_units="V",
        scr_description="Skin conductance channel recorded as device output voltage.",
        trailing_markers=2,
        exclusions=[],
    ),
    "FR": _dataset(
        name="FR",
        zenodo="1405394",
        authors=[
            "Castegnetti, G.",
            "Tzovara, A.",
            "Staib, M.",
            "Paulus, P.C.",
            "Hofer, N.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from the acquisition phase of a "
            "discriminant delay fear-conditioning study."
        ),
        data_pattern=r"^FR_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^FR_cogent_(?P<subject>\d+)_sn1\.mat$",
        cogent_name="FR_cogent_{subject}_sn{recording}.mat",
        blocks=[1, 2],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ coloured rectangle",
            2: "CS- coloured rectangle",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with red and blue rectangles "
            "and a partially reinforced electrical stimulus."
        ),
    ),
    "LI": _dataset(
        name="LI",
        zenodo="1288494",
        authors=[
            "Korn, C.W.",
            "Staib, M.",
            "Tzovara, A.",
            "Castegnetti, G.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from a discriminant delay "
            "fear-conditioning study with auditory stimuli."
        ),
        data_pattern=r"^LI_wdq_(?P<subject>\d+)_sn(?P<recording>[12])\.mat$",
        metadata_pattern=r"^LI_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="LI_cogent_{subject}.mat",
        blocks=[1, 2],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={1: "CS+ sine tone", 2: "CS- sine tone"},
        soa=6.0,
        cs_duration=6.5,
        task_description=(
            "Discriminant delay fear acquisition with 220 Hz and 440 Hz sine "
            "tones and a partially reinforced electrical stimulus."
        ),
        recording_blocks={"1": [1], "2": [2]},
    ),
    "LSOA": _dataset(
        name="LSOA",
        zenodo="3835557",
        authors=["Tzovara, A.", "Sporrer, J.", "Bach, D.R."],
        description=(
            "Skin conductance measurements in a delay fear-conditioning task "
            "with auditory conditioned stimuli and an electrical "
            "unconditioned stimulus."
        ),
        data_pattern=r"^LSOA_windaq_n_(?P<subject>\d+)_sn(?P<recording>\d+)\.mat$",
        metadata_pattern=r"^LSOA_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="LSOA_cogent_{subject}.mat",
        blocks=[1, 2, 3, 4],
        cs_plus=[2],
        cs_minus=[1],
        stimuli={1: "300 Hz tone", 2: "135 Hz tone"},
        soa=7.5,
        cs_duration=8.0,
        task_description=(
            "Classical discriminant delay fear conditioning with 135 Hz and "
            "300 Hz auditory conditioned stimuli and an electrical "
            "unconditioned stimulus."
        ),
    ),
    "PubFe": _dataset(
        name="PubFe",
        zenodo="5573788",
        authors=[
            "Korn, C.W.",
            "Castegnetti, G.",
            "Sporrer, J.",
            "Staib, M.",
            "Tzovara, A.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from a discriminant delay "
            "fear-conditioning study with auditory stimuli."
        ),
        data_pattern=(
            r"^PubFe_wdq_(?P<subject>\d+)_sn(?P<recording>[12])\.mat$"
        ),
        metadata_pattern=r"^PubFe_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="PubFe_cogent_{subject}.mat",
        blocks=[1, 2],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={1: "CS+ sine tone", 2: "CS- sine tone"},
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with 220 Hz and 440 Hz sine "
            "tones and a partially reinforced electrical stimulus."
        ),
        recording_blocks={"1": [1], "2": [2]},
        scr_units="µS",
        exclusions=[],
    ),
    "TC": _dataset(
        name="TC",
        zenodo="1404810",
        authors=[
            "Tzovara, A.",
            "Hofer, N.",
            "Bach, D.R.",
            "Castegnetti, G.",
            "Gerster, S.",
            "Korn, C.W.",
            "Paulus, P.C.",
            "Staib, M.",
        ],
        description=(
            "Skin conductance measurements from a discriminant trace "
            "fear-conditioning study with visual stimuli."
        ),
        data_pattern=r"^TC_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^TC_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="TC_cogent_{subject}.mat",
        blocks=[1],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ coloured rectangle",
            2: "CS- coloured rectangle",
        },
        soa=4.0,
        cs_duration=3.0,
        task_description=(
            "Discriminant trace fear acquisition with red and blue rectangles, "
            "a one-second trace interval and a partially reinforced electrical "
            "stimulus."
        ),
        exclusions=[],
    ),
    "SC4B": _dataset(
        name="SC4B",
        zenodo="5573810",
        authors=[
            "Staib, M.",
            "Castegnetti, G.",
            "Hofer, N.",
            "Paulus, P.C.",
            "Sporrer, J.",
            "Tzovara, A.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from a discriminant delay "
            "fear-conditioning study with auditory stimuli."
        ),
        data_pattern=r"^SC4B_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^SC4B_cogent_(?P<subject>\d+)\.mat$",
        cogent_name="SC4B_cogent_{subject}.mat",
        blocks=[1, 2, 3, 4, 5, 6, 7, 8],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ auditory tone or frequency sweep",
            2: "CS- auditory tone or frequency sweep",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with simple tones and "
            "complex frequency sweeps and a partially reinforced electrical "
            "stimulus."
        ),
        scr_units="µS",
        exclusions=[],
    ),
    "VC7B": _dataset(
        name="VC7B",
        zenodo="5573833",
        authors=[
            "Staib, M.",
            "Castegnetti, G.",
            "Korn, C.W.",
            "Sporrer, J.",
            "Tzovara, A.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from the acquisition blocks of a "
            "discriminant delay fear-conditioning study with visual stimuli."
        ),
        data_pattern=r"^VC7B_wdq_(?P<subject>\d+)_sn(?P<recording>1)\.mat$",
        metadata_pattern=r"^VC7B_psych_(?P<subject>\d+)\.mat$",
        cogent_name="VC7B_psych_{subject}.mat",
        blocks=[1, 3, 5, 7],
        block_column="block_numer",
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ Gabor patch or plaid",
            2: "CS- Gabor patch or plaid",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with simple Gabor patches "
            "and complex plaid stimuli and a partially reinforced electrical "
            "stimulus."
        ),
        stimulus_software="Psychtoolbox",
        scr_units="µS",
        exclusions=[],
    ),
    "CFG1": _context_dataset(
        name="CFG1",
        zenodo="6419011",
        exclusions=[],
    ),
    "CFG2": _context_dataset(
        name="CFG2",
        zenodo="6419020",
        exclusions=[],
    ),
    "MinAv": _medication_context_dataset(
        name="MinAv",
        zenodo="7601792",
        authors=[
            "Xia, Y.",
            "Wehrli, J.",
            "Abivardi, A.",
            "Hostiuc, M.",
            "Kleim, B.",
            "Bach, D.R.",
        ],
        medication="minocycline",
        exclusions=[],
        treatment_values={
            "Minocycline": "minocycline",
            "Placebo": "placebo",
        },
    ),
    "DoxAv2": _medication_context_dataset(
        name="DoxAv2",
        zenodo="7601734",
        authors=[
            "Wehrli, J.",
            "Xia, Y.",
            "Abivardi, A.",
            "Kleim, B.",
            "Bach, D.R.",
        ],
        medication="doxycycline",
        exclusions=[10],
        treatment_values={
            "doxycycline": "doxycycline",
            "placebo": "placebo",
        },
    ),
    "FSS6B": _dataset(
        name="FSS6B",
        zenodo="7334479",
        authors=[
            "Staib, M.",
            "Castegnetti, G.",
            "Korn, C.W.",
            "Sporrer, J.",
            "Tzovara, A.",
            "Bach, D.R.",
        ],
        description=(
            "Skin conductance measurements from a discriminant delay "
            "fear-conditioning study with somatosensory stimuli."
        ),
        data_pattern=r"^FSS6B_wdq_(?P<subject>\d+)\.mat$",
        metadata_pattern=r"^FSS6B_psych_(?P<subject>\d+)\.mat$",
        cogent_name="FSS6B_psych_{subject}.mat",
        blocks=[1, 2, 3, 4, 5, 6, 7, 8],
        cs_plus=[1],
        cs_minus=[2],
        stimuli={
            1: "CS+ somatosensory stimulus",
            2: "CS- somatosensory stimulus",
        },
        soa=3.5,
        cs_duration=4.0,
        task_description=(
            "Discriminant delay fear acquisition with simple and complex "
            "somatosensory stimuli and a partially reinforced electrical "
            "stimulus."
        ),
        stimulus_software="Psychtoolbox",
        scr_units="µS",
        exclusions=[2],
    ),
}
