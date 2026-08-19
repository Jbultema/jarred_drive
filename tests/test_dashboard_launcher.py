from __future__ import annotations

import pytest

from jarred_drive.dashboard import launcher


def test_port_search_skips_occupied_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "is_port_available", lambda _host, port: port == 8503)

    assert launcher.find_available_port(start_port=8501, attempts=3) == 8503


def test_port_search_reports_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "is_port_available", lambda _host, _port: False)

    with pytest.raises(RuntimeError, match="8501 through 8502"):
        launcher.find_available_port(start_port=8501, attempts=2)


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_start_port_is_rejected(port: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        launcher.find_available_port(start_port=port)
