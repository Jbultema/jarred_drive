from __future__ import annotations

import pandas as pd

from jarred_drive.annotations import ANNOTATION_COLUMNS, merge_annotations, validate_annotations


def test_manual_annotation_supersedes_nearby_detection() -> None:
    detected = pd.DataFrame(
        [["s1", 1000, "TAKEOFF", 0.72, "baseline", ""]], columns=ANNOTATION_COLUMNS
    )
    manual = pd.DataFrame(
        [["s1", 1200, "TAKEOFF", 1.0, "manual", "video verified"]],
        columns=ANNOTATION_COLUMNS,
    )
    merged = merge_annotations(detected, manual)
    assert len(merged) == 1
    assert merged.iloc[0]["source"] == "manual"


def test_annotation_outside_session_is_rejected() -> None:
    annotation = pd.DataFrame(
        [["s1", 20_000, "FALL", 1.0, "manual", ""]], columns=ANNOTATION_COLUMNS
    )
    assert validate_annotations(annotation, "s1", 10_000)
