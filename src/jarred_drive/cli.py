"""Command-line workflows for data generation, validation, and analysis."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from jarred_drive.analytics import (
    build_crash_dynamics,
    build_electrical_phase_summary,
    build_launch_attempts,
    build_rides,
    build_thermal_analysis,
    summarize_session,
    system_monitoring_summary,
)
from jarred_drive.config import DEFAULT_CONFIG_PATH, load_config
from jarred_drive.demo_server import create_demo_server
from jarred_drive.events import detect_events
from jarred_drive.io import read_telemetry
from jarred_drive.schema import validate_telemetry
from jarred_drive.sync import (
    DEFAULT_DEVICE_URL,
    FilesystemLoggerClient,
    HttpLoggerClient,
    SessionStore,
    SyncError,
    sync_logger,
)
from jarred_drive.synthetic import write_demo_package

app = typer.Typer(no_args_is_help=True, help="Jarred Drive telemetry and analytics tools.")


@app.command("generate-demo")
def generate_demo(
    output: Annotated[Path, typer.Option(help="Demo package directory")] = Path("data/demo"),
    config_path: Annotated[
        Path, typer.Option(help="System threshold configuration")
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Create deterministic synthetic sessions covering normal and fault scenarios."""
    written = write_demo_package(output, load_config(config_path))
    typer.echo(f"Generated {len(written)} artifacts under {output}")


@app.command("validate-log")
def validate_log(path: Annotated[Path, typer.Argument(help="Telemetry CSV")]) -> None:
    """Validate a logger CSV against the versioned raw-data contract."""
    report = validate_telemetry(read_telemetry(path))
    for issue in report.issues:
        typer.echo(f"{issue.severity.upper():7} {issue.code}: {issue.message} ({issue.row_count})")
    if not report.valid:
        raise typer.Exit(code=1)
    typer.echo("VALID")


@app.command("summarize")
def summarize(
    path: Annotated[Path, typer.Argument(help="Telemetry CSV")],
    output: Annotated[Path | None, typer.Option(help="Optional JSON output")] = None,
    synthetic_truth: Annotated[
        bool, typer.Option(help="Use sim_state when present instead of baseline detection")
    ] = False,
) -> None:
    """Derive events, rides, and a session summary from raw telemetry."""
    frame = read_telemetry(path)
    report = validate_telemetry(frame)
    if not report.valid:
        typer.echo("Log validation failed; run validate-log for details")
        raise typer.Exit(code=1)
    config = load_config()
    telemetry, events = detect_events(frame, config.detection, use_synthetic_truth=synthetic_truth)
    rides = build_rides(telemetry, events)
    launches = build_launch_attempts(telemetry, events)
    crashes = build_crash_dynamics(telemetry, events, config.detection.motor_power_w)
    _, thermal_sensors, thermal_phases = build_thermal_analysis(telemetry)
    electrical_phases = build_electrical_phase_summary(telemetry)
    monitoring = system_monitoring_summary(telemetry)
    summary = summarize_session(telemetry, events, rides)
    rendered = json.dumps(summary, indent=2, default=float)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n")
        events.to_csv(output.with_name(output.stem + "_events.csv"), index=False)
        rides.to_csv(output.with_name(output.stem + "_rides.csv"), index=False)
        launches.to_csv(output.with_name(output.stem + "_launches.csv"), index=False)
        crashes.to_csv(output.with_name(output.stem + "_crashes.csv"), index=False)
        thermal_sensors.to_csv(output.with_name(output.stem + "_thermal_sensors.csv"), index=False)
        thermal_phases.to_csv(output.with_name(output.stem + "_thermal_phases.csv"), index=False)
        electrical_phases.to_csv(
            output.with_name(output.stem + "_electrical_phases.csv"), index=False
        )
        output.with_name(output.stem + "_monitoring.json").write_text(
            json.dumps(monitoring, indent=2, default=float) + "\n"
        )
    typer.echo(rendered)


@app.command("compare-configs")
def compare_configs(
    session_index: Annotated[Path, typer.Option(help="Generated session index CSV")] = Path(
        "data/demo/session_index.csv"
    ),
) -> None:
    """Print an experiment table grouped by immutable VESC configuration snapshot."""
    frame = pd.read_csv(session_index)
    columns = [
        "config_id",
        "launch_success",
        "failed_launch_rate",
        "launch_crashes",
        "ride_falls",
        "median_time_to_takeoff_seconds",
        "foil_utilization",
        "energy_Wh",
        "peak_pack_C",
        "longest_ride_seconds",
    ]
    typer.echo(frame[columns].to_string(index=False))


@app.command("register-config")
def register_config(
    path: Annotated[Path, typer.Argument(help="VESC configuration snapshot JSON")],
    output: Annotated[Path, typer.Option(help="Local snapshot registry")] = Path("data/configs"),
) -> None:
    """Register a read-only VESC snapshot for lookup by session config_id."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    config_id = snapshot.get("config_id")
    if not isinstance(config_id, str) or not config_id.strip():
        typer.echo("Snapshot must contain a non-empty string config_id")
        raise typer.Exit(code=1)
    snapshot["write_policy"] = "read_only_snapshot"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{config_id}.json"
    destination.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Registered {config_id} at {destination}")


@app.command("sync")
def sync_device(
    url: Annotated[str, typer.Option(help="Logger base URL or 'demo'")] = DEFAULT_DEVICE_URL,
    token: Annotated[
        str | None, typer.Option(help="Device token for import acknowledgement")
    ] = None,
    raw_root: Annotated[Path, typer.Option(help="Immutable raw session root")] = Path("data/raw"),
    processed_root: Annotated[Path, typer.Option(help="DuckDB/Parquet analytical root")] = Path(
        "data/processed"
    ),
) -> None:
    """Synchronize new sessions from a logger in explicit SYNC mode."""
    client = FilesystemLoggerClient(Path("data/demo")) if url == "demo" else HttpLoggerClient(url)
    try:
        results = sync_logger(client, SessionStore(raw_root, processed_root), token=token)
    except SyncError as error:
        typer.echo(f"SYNC FAILED: {error}")
        raise typer.Exit(code=1) from error
    for result in results:
        typer.echo(
            f"{result.session_id}: {result.status} "
            f"({result.verified_files} files, {result.downloaded_bytes} bytes downloaded)"
        )
    typer.echo("Raw logger data was not deleted.")


@app.command("serve-demo")
def serve_demo(
    source: Annotated[Path, typer.Option(help="Synthetic logger package")] = Path("data/demo"),
    host: Annotated[
        str, typer.Option(help="Listen address; use 0.0.0.0 for a physical phone")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="HTTP port")] = 8765,
    token: Annotated[str | None, typer.Option(help="Optional acknowledgement token")] = None,
) -> None:
    """Serve synthetic fixtures using the same REST contract as the ESP logger."""
    try:
        server = create_demo_server(source, host=host, port=port, token=token)
    except OSError as error:
        typer.echo(f"DEMO SERVER FAILED: {error}")
        raise typer.Exit(code=1) from error
    shown_host = host
    if host == "0.0.0.0":
        try:
            shown_host = socket.gethostbyname(socket.gethostname())
        except OSError:
            shown_host = "YOUR_MAC_IP"
    typer.echo(f"Synthetic development logger: http://{shown_host}:{server.server_port}")
    typer.echo("Synthetic fixtures are software test data, not hardware observations.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nDemo server stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
