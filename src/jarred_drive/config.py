"""System configuration loading and thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DetectionConfig:
    motor_power_w: float
    attempt_min_seconds: float
    foil_speed_mps: float
    foil_erpm: float
    foil_vibration_g: float
    touchdown_vibration_g: float
    fall_gyro_dps: float
    recovery_window_seconds: float


@dataclass(frozen=True)
class SafetyConfig:
    pack_warning_c: float
    pack_critical_c: float
    pack_delta_warning_c: float
    mosfet_warning_c: float
    enclosure_warning_c: float
    minimum_voltage_v: float


@dataclass(frozen=True)
class AppConfig:
    detection: DetectionConfig
    safety: SafetyConfig


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "system.yaml"


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    data: dict[str, Any]
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return AppConfig(
        detection=DetectionConfig(**data["detection"]),
        safety=SafetyConfig(**data["safety"]),
    )
