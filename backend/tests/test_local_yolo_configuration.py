"""Regression checks for the local, non-cloud inference configuration."""

from datetime import datetime, timezone

from config import settings
from modules.violation_recorder import _build_storage_key
from modules.vision_analyzer import REQUIRED_PPE


def test_required_ppe_matches_dataset_classes() -> None:
    assert REQUIRED_PPE == {"helmet", "vest"}


def test_configuration_uses_local_model_and_snapshot_paths() -> None:
    assert "model_path" in settings.model_fields
    assert "snapshot_dir" in settings.model_fields
    assert settings.model_path.endswith("best.pt")


def test_snapshot_path_is_local_and_deterministic() -> None:
    timestamp = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert _build_storage_key("cam_01", timestamp).startswith("violations/cam_01/2026-07-22/")
