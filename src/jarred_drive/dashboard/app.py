"""Jarred Drive Streamlit dashboard.

Run with: poetry run streamlit run src/jarred_drive/dashboard/app.py
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from jarred_drive.analytics import (
    build_crash_dynamics,
    build_electrical_phase_summary,
    build_launch_attempts,
    build_launch_curves,
    build_rides,
    build_thermal_analysis,
    health_status,
    summarize_session,
    system_monitoring_summary,
)
from jarred_drive.annotations import (
    ANNOTATION_COLUMNS,
    annotation_template,
    merge_annotations,
    save_annotations,
    validate_annotations,
)
from jarred_drive.config import load_config
from jarred_drive.events import detect_events
from jarred_drive.io import discover_sessions, read_json, read_telemetry
from jarred_drive.schema import PACK_TEMP_COLUMNS, EventType, RideState, validate_telemetry
from jarred_drive.sync import (
    DEFAULT_DEVICE_URL,
    FilesystemLoggerClient,
    HttpLoggerClient,
    LoggerClient,
    SessionStore,
    SyncError,
    sync_logger,
)

ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = ROOT / "data" / "demo"
IMPORT_ROOT = ROOT / "data" / "imports"
RAW_ROOT = ROOT / "data" / "raw"
PROCESSED_ROOT = ROOT / "data" / "processed"
ANNOTATION_ROOT = ROOT / "data" / "annotations"
CONFIG_SNAPSHOT_ROOT = ROOT / "data" / "configs"
CONFIG = load_config(ROOT / "configs" / "system.yaml")

NAV_ITEMS = (
    "Devices / Sync",
    "Flight Deck",
    "Launch Lab",
    "Ride Dynamics",
    "Thermal Lab",
    "System Health",
    "Tuning",
    "Progress",
    "Annotate",
    "Raw Data",
)
STATE_COLORS = {
    str(RideState.IDLE): "#64748b",
    str(RideState.ACCELERATING): "#f59e0b",
    str(RideState.FOILING): "#22d3ee",
    str(RideState.TOUCHDOWN): "#fb7185",
    str(RideState.FALL): "#ef4444",
}


st.set_page_config(
    page_title="Jarred Drive",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    :root { --jd-cyan: #22d3ee; --jd-navy: #07111f; --jd-panel: #0d1b2a; }
    .stApp { background: linear-gradient(145deg, #07111f 0%, #0b1626 55%, #0e2230 100%); }
    [data-testid="stSidebar"] { background: #07111f; border-right: 1px solid #1e3a4f; }
    .jd-brand { letter-spacing: .16em; font-weight: 800; font-size: 1.35rem; color: #e6fbff; }
    .jd-subtitle { color: #75d9e8; font-size: .72rem; letter-spacing: .13em; margin-bottom: 1.2rem; }
    .jd-status { border-radius: 12px; padding: 1.1rem 1.25rem; margin: .3rem 0 1rem 0;
                 background: #0d1b2a; border: 1px solid #1e3a4f; }
    .jd-ready { border-left: 6px solid #2dd4bf; }
    .jd-warning { border-left: 6px solid #f59e0b; }
    .jd-stop { border-left: 6px solid #ef4444; background: #2a1118; }
    .jd-status-label { font-size: .72rem; letter-spacing: .18em; color: #94a3b8; }
    .jd-status-value { color: #e6fbff; font-size: 1.6rem; font-weight: 800; margin-top: .15rem; }
    .jd-note { color: #94a3b8; font-size: .82rem; }
    [data-testid="stMetric"] { background: rgba(13,27,42,.78); border: 1px solid #1e3a4f;
                               border-radius: 10px; padding: .75rem 1rem; }
    [data-testid="stMetricLabel"] { color: #94a3b8; }
    [data-testid="stMetricValue"] { color: #e6fbff; }
    h1, h2, h3 { color: #e6fbff; }
    .stTabs [data-baseweb="tab-list"] { gap: .25rem; }
    .stTabs [data-baseweb="tab"] { background: #0d1b2a; border-radius: 7px; }
</style>
""",
    unsafe_allow_html=True,
)


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _seconds(frame: pd.DataFrame) -> pd.Series:
    return (frame["timestamp_ms"] - int(frame["timestamp_ms"].iloc[0])) / 1000.0


def _local_track(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert valid WGS84 points to a local meter-scale plot without map tiles."""
    track = frame.dropna(subset=["gps_lat", "gps_lon"]).copy()
    if track.empty:
        return track
    lat0 = float(track["gps_lat"].iloc[0])
    lon0 = float(track["gps_lon"].iloc[0])
    track["north_m"] = (track["gps_lat"] - lat0) * 111_111.0
    track["east_m"] = (track["gps_lon"] - lon0) * 111_111.0 * np.cos(np.deg2rad(lat0))
    return track


def _event_track_points(
    telemetry: pd.DataFrame,
    events: pd.DataFrame,
    event_type: EventType,
    lat0: float,
    lon0: float,
) -> pd.DataFrame:
    rows: list[pd.Series] = []
    for timestamp_ms in events.loc[events["event_type"] == event_type, "timestamp_ms"]:
        position = (telemetry["timestamp_ms"] - int(timestamp_ms)).abs().idxmin()
        row = telemetry.loc[position]
        if pd.notna(row.get("gps_lat")) and pd.notna(row.get("gps_lon")):
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    points = pd.DataFrame(rows)
    points["east_m"] = (points["gps_lon"] - lon0) * 111_111.0 * np.cos(np.deg2rad(lat0))
    points["north_m"] = (points["gps_lat"] - lat0) * 111_111.0
    return points


def _number(summary: dict[str, object], key: str) -> float:
    value = summary[key]
    if not isinstance(value, (int, float)):
        raise TypeError(f"Summary field {key} is not numeric: {value!r}")
    return float(value)


@st.cache_data(show_spinner=False)
def _load_session(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns
    return read_telemetry(path)


def _available_sessions() -> dict[str, Path]:
    sessions = (
        discover_sessions(DEMO_ROOT)
        + discover_sessions(IMPORT_ROOT)
        + discover_sessions(RAW_ROOT, recursive=True)
    )
    return {session.session_id: session.telemetry for session in sessions}


def _import_panel() -> None:
    with st.sidebar.expander("Manual microSD fallback"):
        uploaded = st.file_uploader("Telemetry CSV", type=["csv"], label_visibility="collapsed")
        if uploaded is None:
            st.caption(
                "Normal transfer is Wi-Fi sync. This offline fallback preserves the raw CSV."
            )
            return
        try:
            frame = pd.read_csv(io.BytesIO(uploaded.getvalue()), low_memory=False)
        except Exception as error:
            st.error(f"CSV could not be read: {error}")
            return
        report = validate_telemetry(frame)
        if not report.valid:
            st.error("Log does not satisfy schema 1.0.0")
            for issue in report.issues:
                st.caption(issue.message)
            return
        session_ids = frame["session_id"].dropna().astype(str).unique()
        if len(session_ids) != 1:
            st.error("One CSV must contain exactly one session.")
            return
        session_id = session_ids[0]
        st.success(f"Valid session: {session_id}")
        if st.button("Import session", type="primary", width="stretch"):
            destination = RAW_ROOT / "manual-import" / session_id / "telemetry.csv"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                st.info("This session already exists; the raw file was not overwritten.")
                return
            destination.write_bytes(uploaded.getvalue())
            _load_session.clear()
            st.rerun()


def _sync_page() -> None:
    st.header("Devices / Sync")
    st.markdown(
        "Bring the logger home, connect USB-C, and explicitly enable **SYNC** mode. "
        "microSD remains the source of truth; imports are copied, hash-verified, and never deleted remotely."
    )
    source = st.radio(
        "Logger source",
        ("Development logger (synthetic)", "Home LAN logger"),
        horizontal=True,
    )
    token: str | None = None
    if source == "Home LAN logger":
        address = st.text_input("Logger address", value=DEFAULT_DEVICE_URL)
        token = st.text_input("Device token (needed for acknowledgement)", type="password") or None
        client: LoggerClient = HttpLoggerClient(address)
        st.caption(
            "The app first tries the logger's mDNS name. You can enter its LAN IP if mDNS is unavailable."
        )
    else:
        client = FilesystemLoggerClient(DEMO_ROOT)
        st.info(
            "Synthetic device transport: exercises the same manifests, hashes, deduplication, QA, and catalog flow."
        )

    try:
        device = client.device()
        manifests = [client.manifest(session_id) for session_id in client.session_ids()]
    except (SyncError, OSError, ValueError) as error:
        st.error(f"Logger unavailable: {error}")
        return

    store = SessionStore(RAW_ROOT, PROCESSED_ROOT)
    known = store.known_sessions(device.device_id)
    pending = [manifest for manifest in manifests if manifest.session_id not in known]
    pending_bytes = sum(item.size for manifest in pending for item in manifest.files)
    status_color = "ONLINE" if device.mode.upper() == "SYNC" else device.mode.upper()
    st.subheader(f"{device.name} — {status_color}")
    columns = st.columns(6)
    columns[0].metric("Mode", device.mode)
    columns[1].metric("Battery", f"{device.battery_percent:.0f}%")
    columns[2].metric("Firmware", device.firmware_version)
    columns[3].metric("SD free", f"{device.sd_free_percent:.0f}%")
    columns[4].metric("New sessions", len(pending))
    columns[5].metric("Pending data", f"{pending_bytes / (1024 * 1024):.1f} MB")

    session_rows = []
    for manifest in manifests:
        session_rows.append(
            {
                "session_id": manifest.session_id,
                "duration_min": manifest.duration_s / 60.0,
                "config_id": manifest.vesc_config_id,
                "schema": manifest.telemetry_schema_version,
                "files": len(manifest.files),
                "size_MB": sum(item.size for item in manifest.files) / (1024 * 1024),
                "local_status": "IMPORTED" if manifest.session_id in known else "NEW",
            }
        )
    st.dataframe(pd.DataFrame(session_rows).round(2), width="stretch", hide_index=True)

    if st.button("SYNC NOW", type="primary", disabled=not pending):
        bar = st.progress(0.0, text="Preparing transfer...")
        total = max(1, pending_bytes)
        completed_by_file: dict[tuple[str, str], int] = {}

        def update_progress(session_id: str, filename: str, completed: int, size: int) -> None:
            completed_by_file[(session_id, filename)] = completed
            transferred = sum(completed_by_file.values())
            bar.progress(
                min(1.0, transferred / total),
                text=f"{session_id} • {filename} • {completed / max(1, size):.0%}",
            )

        try:
            results = sync_logger(
                client,
                store,
                token=token,
                progress=update_progress,
                session_ids=[manifest.session_id for manifest in pending],
            )
        except SyncError as error:
            st.error(str(error))
            st.warning(
                "Any verified raw files remain local. Restarting sync resumes .part downloads and does not duplicate sessions."
            )
            return
        bar.progress(1.0, text="Transfer, checksum, validation, and import complete")
        imported = sum(result.status.startswith("imported") for result in results)
        verified = sum(result.verified_files for result in results)
        ack_pending = sum("ack_pending" in result.status for result in results)
        st.success(f"{imported} sessions imported • {verified} files verified")
        if ack_pending:
            st.warning(
                f"{ack_pending} logger acknowledgement(s) pending. Check the device token and sync again; "
                "the app will not duplicate local sessions."
            )
        _load_session.clear()
        st.rerun()

    st.caption(
        "Downloads are read-only. Configuration writes and firmware updates require authentication; "
        "VESC writes are not exposed. Logger raw data is retained until you explicitly manage it on-device."
    )


def _status_card(level: str, headline: str, reasons: tuple[str, ...]) -> None:
    css = {"READY": "jd-ready", "WARNING": "jd-warning", "STOP": "jd-stop"}[level]
    details = " • ".join(reasons)
    st.markdown(
        f'<div class="jd-status {css}"><div class="jd-status-label">SYSTEM STATUS</div>'
        f'<div class="jd-status-value">{headline}</div><div class="jd-note">{details}</div></div>',
        unsafe_allow_html=True,
    )


def _timeline_chart(frame: pd.DataFrame) -> go.Figure:
    time = _seconds(frame)
    mapping = {state: index for index, state in enumerate(STATE_COLORS)}
    values = frame["state_inferred"].map(mapping)
    colorscale: list[list[object]] = []
    count = len(mapping)
    for index, state in enumerate(mapping):
        low = index / max(1, count - 1)
        colorscale.extend(
            [[low, STATE_COLORS[state]], [min(1.0, low + 0.001), STATE_COLORS[state]]]
        )
    figure = go.Figure(
        go.Heatmap(
            x=time,
            y=["Ride state"],
            z=[values],
            colorscale=colorscale,
            showscale=False,
            hovertemplate="%{x:.1f}s<extra></extra>",
        )
    )
    figure.update_layout(
        height=105, margin={"l": 0, "r": 0, "t": 10, "b": 20}, xaxis_title="Session seconds"
    )
    return figure


def _flight_deck(
    telemetry: pd.DataFrame,
    events: pd.DataFrame,
    rides: pd.DataFrame,
    summary: dict[str, object],
) -> None:
    status = health_status(telemetry, CONFIG.safety)
    _status_card(status.level, status.headline, status.reasons)
    columns = st.columns(7)
    columns[0].metric("Water time", _format_duration(_number(summary, "duration_seconds")))
    columns[1].metric("Foil time", _format_duration(_number(summary, "foil_seconds")))
    columns[2].metric("Launch success", f"{_number(summary, 'launch_success'):.0%}")
    columns[3].metric("Failed launches", int(_number(summary, "failed_launches")))
    columns[4].metric("Ride falls", int(_number(summary, "ride_falls")))
    columns[5].metric("Longest ride", _format_duration(_number(summary, "longest_ride_seconds")))
    columns[6].metric("Energy used", f"{_number(summary, 'energy_Wh'):.1f} Wh")

    st.plotly_chart(_timeline_chart(telemetry), width="stretch", config={"displayModeBar": False})
    left, right = st.columns([1.55, 1])
    with left:
        plot = telemetry.assign(session_seconds=_seconds(telemetry))
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=plot["session_seconds"],
                y=plot["battery_power_W"] / 1000,
                name="Power",
                line={"color": "#22d3ee", "width": 1.8},
            )
        )
        if "gps_speed_mps" in plot:
            figure.add_trace(
                go.Scatter(
                    x=plot["session_seconds"],
                    y=plot["gps_speed_mps"] * 2.23694,
                    name="Speed",
                    yaxis="y2",
                    line={"color": "#f59e0b", "width": 1.4},
                )
            )
        figure.update_layout(
            title="Propulsion and speed",
            xaxis_title="Session seconds",
            yaxis={"title": "Power (kW)"},
            yaxis2={"title": "Speed (mph)", "overlaying": "y", "side": "right"},
            height=380,
            legend={"orientation": "h", "y": 1.12},
        )
        st.plotly_chart(figure, width="stretch")
    with right:
        if {"gps_lat", "gps_lon"}.issubset(telemetry.columns):
            route = _local_track(telemetry.iloc[:: max(1, len(telemetry) // 1400)])
            route["state"] = route["state_inferred"]
            figure = px.scatter(
                route,
                x="east_m",
                y="north_m",
                color="state",
                color_discrete_map=STATE_COLORS,
                height=380,
                title="Offline local track by ride state",
                labels={"east_m": "East (m)", "north_m": "North (m)"},
            )
            figure.update_traces(marker={"size": 4})
            figure.update_yaxes(scaleanchor="x", scaleratio=1)
            st.plotly_chart(figure, width="stretch")
        else:
            st.info("This session has no GPS fields. All non-spatial analytics remain available.")

    st.subheader("Event log")
    event_view = events.copy()
    session_start_ms = int(telemetry["timestamp_ms"].iloc[0])
    event_view["time"] = event_view["timestamp_ms"].map(
        lambda value: _format_duration((float(value) - session_start_ms) / 1000)
    )
    st.dataframe(
        event_view[["time", "event_type", "confidence", "source", "notes"]],
        width="stretch",
        hide_index=True,
    )


def _launch_lab(telemetry: pd.DataFrame, events: pd.DataFrame) -> None:
    st.header("Launch performance lab")
    attempts = build_launch_attempts(telemetry, events)
    if attempts.empty:
        st.warning("No launch attempts were detected in this session.")
        return
    curves = build_launch_curves(telemetry, attempts)
    successes = attempts[attempts["outcome"] == "SUCCESS"]
    columns = st.columns(7)
    columns[0].metric("Attempts", len(attempts))
    columns[1].metric("Success rate", f"{len(successes) / len(attempts):.0%}")
    columns[2].metric("Failed / aborted", int((attempts["outcome"] == "FAILED").sum()))
    columns[3].metric("Launch crashes", int((attempts["outcome"] == "LAUNCH_CRASH").sum()))
    columns[4].metric(
        "Median takeoff",
        f"{successes['time_to_takeoff_s'].median():.1f} s" if not successes.empty else "—",
    )
    columns[5].metric("Median launch energy", f"{attempts['launch_energy_Wh'].median():.2f} Wh")
    columns[6].metric("Worst sag", f"{attempts['voltage_sag_V'].max():.2f} V")

    left, right = st.columns([1.55, 1])
    with left:
        figure = px.line(
            curves,
            x="attempt_seconds",
            y="power_kW",
            color="outcome",
            line_group="attempt_id",
            hover_data=["attempt_id", "vesc_battery_A", "vesc_vin_V", "speed_mph"],
            title="All launch power curves aligned at motor start",
            labels={"attempt_seconds": "Seconds from attempt start", "power_kW": "Power (kW)"},
            color_discrete_map={
                "SUCCESS": "#22d3ee",
                "FAILED": "#f59e0b",
                "LAUNCH_CRASH": "#ef4444",
            },
        )
        figure.update_traces(opacity=0.78)
        st.plotly_chart(figure, width="stretch")
    with right:
        outcome_counts = (
            attempts["outcome"].value_counts().rename_axis("outcome").reset_index(name="attempts")
        )
        figure = px.bar(
            outcome_counts,
            x="outcome",
            y="attempts",
            color="outcome",
            title="Attempt outcomes",
            color_discrete_map={
                "SUCCESS": "#22d3ee",
                "FAILED": "#f59e0b",
                "LAUNCH_CRASH": "#ef4444",
            },
        )
        figure.update_layout(showlegend=False)
        st.plotly_chart(figure, width="stretch")

    selected_id = st.selectbox("Inspect attempt", attempts["attempt_id"].astype(int).tolist())
    selected = attempts[attempts["attempt_id"] == selected_id].iloc[0]
    selected_curve = curves[curves["attempt_id"] == selected_id]
    detail_columns = st.columns(6)
    detail_columns[0].metric("Outcome", str(selected["outcome"]))
    detail_columns[1].metric("Peak power", f"{selected['peak_power_W'] / 1000:.2f} kW")
    detail_columns[2].metric("10–90% power rise", f"{selected['power_10_90_s']:.2f} s")
    detail_columns[3].metric("Peak motor current", f"{selected['peak_motor_A']:.1f} A")
    detail_columns[4].metric("Peak speed", f"{selected['peak_speed_mps'] * 2.23694:.1f} mph")
    detail_columns[5].metric("Pack rise", f"{selected['pack_rise_C']:.2f}°C")

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=selected_curve["attempt_seconds"], y=selected_curve["power_kW"], name="Power kW"
        )
    )
    figure.add_trace(
        go.Scatter(
            x=selected_curve["attempt_seconds"],
            y=selected_curve["speed_mph"],
            name="Speed mph",
            yaxis="y2",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=selected_curve["attempt_seconds"],
            y=selected_curve["vesc_vin_V"],
            name="Voltage",
            yaxis="y3",
        )
    )
    figure.update_layout(
        title=f"Attempt {selected_id}: coupled power, speed, and voltage",
        xaxis_title="Seconds from attempt start",
        yaxis={"title": "Power (kW)"},
        yaxis2={"title": "Speed (mph)", "overlaying": "y", "side": "right"},
        yaxis3={
            "title": "Voltage",
            "overlaying": "y",
            "side": "right",
            "anchor": "free",
            "position": 0.94,
        },
        legend={"orientation": "h", "y": 1.12},
    )
    st.plotly_chart(figure, width="stretch")

    display = attempts.copy()
    display["peak_power_kW"] = display["peak_power_W"] / 1000.0
    display["peak_speed_mph"] = display["peak_speed_mps"] * 2.23694
    st.dataframe(
        display[
            [
                "attempt_id",
                "outcome",
                "duration_s",
                "time_to_takeoff_s",
                "power_10_90_s",
                "peak_power_kW",
                "launch_energy_Wh",
                "peak_battery_A",
                "peak_motor_A",
                "peak_speed_mph",
                "voltage_sag_V",
                "sag_per_kW_V",
                "peak_accel_delta_g",
                "peak_gyro_dps",
                "pack_rise_C",
                "vesc_rise_C",
            ]
        ].round(3),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Attempt outcomes are inferred from START_ATTEMPT → TAKEOFF/FALL/MOTOR_STOP transitions. "
        "Review and correct events on the Annotate page before treating field rates as ground truth."
    )


def _ride_dynamics_page(
    telemetry: pd.DataFrame, events: pd.DataFrame, rides: pd.DataFrame, summary: dict[str, object]
) -> None:
    st.header("Ride & crash dynamics")
    crashes = build_crash_dynamics(telemetry, events, CONFIG.detection.motor_power_w)
    if rides.empty:
        st.warning("No rides were detected in this session.")
        return
    columns = st.columns(7)
    columns[0].metric("Foil rides", len(rides))
    columns[1].metric("Median ride", _format_duration(float(rides["ride_seconds"].median())))
    columns[2].metric("Ride falls", int((crashes["crash_type"] == "RIDE_FALL").sum()))
    columns[3].metric("Launch crashes", int((crashes["crash_type"] == "LAUNCH_CRASH").sum()))
    columns[4].metric(
        "Recovery rate", f"{rides['recoveries'].sum() / max(1, rides['touchdowns'].sum()):.0%}"
    )
    columns[5].metric("Median vibration p95", f"{rides['p95_vibration_g'].median():.2f} g")
    columns[6].metric("Wh / foil min", f"{rides['energy_per_foil_min_Wh'].median():.1f}")

    left, right = st.columns(2)
    with left:
        duration = rides.melt(
            id_vars=["ride_id"],
            value_vars=["ride_seconds", "foil_seconds"],
            var_name="metric",
            value_name="seconds",
        )
        figure = px.bar(
            duration,
            x="ride_id",
            y="seconds",
            color="metric",
            barmode="group",
            color_discrete_map={"ride_seconds": "#64748b", "foil_seconds": "#22d3ee"},
            title="Ride and flight duration",
        )
        st.plotly_chart(figure, width="stretch")
    with right:
        figure = px.scatter(
            rides,
            x="mean_power_W",
            y="ride_seconds",
            size="energy_Wh",
            color="p95_vibration_g",
            hover_data=["ride_id", "touchdowns", "recoveries", "peak_gyro_dps"],
            color_continuous_scale="Turbo",
            title="Duration vs cruise load and vibration",
            labels={"mean_power_W": "Mean ride power (W)", "ride_seconds": "Ride seconds"},
        )
        st.plotly_chart(figure, width="stretch")

    if {"gps_lat", "gps_lon", "gps_speed_mps", "gps_course_deg"}.issubset(telemetry.columns):
        gps = _local_track(telemetry[telemetry["gps_fix_quality"].fillna(0) > 0].iloc[::5])
        gps["session_seconds"] = _seconds(gps)
        gps["speed_mph"] = gps["gps_speed_mps"] * 2.23694
        left, right = st.columns([1.15, 1])
        with left:
            figure = px.scatter(
                gps,
                x="east_m",
                y="north_m",
                color="speed_mph",
                hover_data=["session_seconds", "gps_course_deg", "gyro_z_dps", "state_inferred"],
                color_continuous_scale="Turbo",
                height=430,
                title="Offline GPS trajectory colored by speed",
                labels={"east_m": "East (m)", "north_m": "North (m)"},
            )
            figure.update_traces(marker={"size": 5})
            lat0 = float(gps["gps_lat"].iloc[0])
            lon0 = float(gps["gps_lon"].iloc[0])
            for event_type, name, symbol, color in (
                (EventType.TAKEOFF, "Takeoff", "triangle-up", "#2dd4bf"),
                (EventType.FALL, "Fall", "x", "#ef4444"),
            ):
                points = _event_track_points(telemetry, events, event_type, lat0, lon0)
                if not points.empty:
                    figure.add_trace(
                        go.Scatter(
                            x=points["east_m"],
                            y=points["north_m"],
                            mode="markers",
                            name=name,
                            marker={"symbol": symbol, "size": 11, "color": color},
                            hovertemplate=f"{name}<extra></extra>",
                        )
                    )
            figure.update_yaxes(scaleanchor="x", scaleratio=1)
            st.plotly_chart(figure, width="stretch")
        with right:
            figure = go.Figure()
            figure.add_trace(
                go.Scatter(
                    x=gps["session_seconds"],
                    y=gps["gps_course_deg"],
                    name="GPS course",
                    mode="markers",
                    marker={"size": 3, "color": "#22d3ee"},
                )
            )
            figure.add_trace(
                go.Scatter(
                    x=gps["session_seconds"],
                    y=gps["gyro_z_dps"],
                    name="Yaw rate",
                    yaxis="y2",
                    line={"color": "#f59e0b", "width": 1.2},
                )
            )
            figure.update_layout(
                title="Course and turn dynamics",
                xaxis_title="Session seconds",
                yaxis={"title": "Course (degrees)", "range": [0, 360]},
                yaxis2={"title": "Yaw rate (°/s)", "overlaying": "y", "side": "right"},
                height=430,
                legend={"orientation": "h", "y": 1.12},
            )
            st.plotly_chart(figure, width="stretch")

    if not crashes.empty:
        st.subheader("Crash signatures")
        crash_columns = st.columns(5)
        crash_columns[0].metric("Crash events", len(crashes))
        crash_columns[1].metric(
            "Worst accel transient", f"{crashes['peak_accel_delta_g'].max():.2f} g"
        )
        crash_columns[2].metric("Worst angular rate", f"{crashes['peak_gyro_dps'].max():.0f}°/s")
        crash_columns[3].metric(
            "Median pre-fall speed", f"{crashes['pre_speed_mps'].median() * 2.23694:.1f} mph"
        )
        crash_columns[4].metric(
            "Median motor cut", f"{crashes['motor_cut_latency_ms'].median():.0f} ms"
        )
        selected_crash = st.selectbox("Inspect crash", crashes["crash_id"].astype(int).tolist())
        crash = crashes[crashes["crash_id"] == selected_crash].iloc[0]
        center = int(crash["timestamp_ms"])
        window = telemetry[telemetry["timestamp_ms"].between(center - 3000, center + 2000)].copy()
        window["crash_seconds"] = (window["timestamp_ms"] - center) / 1000.0
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=window["crash_seconds"], y=window["accel_magnitude_g"], name="Accel magnitude g"
            )
        )
        figure.add_trace(
            go.Scatter(
                x=window["crash_seconds"],
                y=window["gyro_magnitude_dps"],
                name="Gyro magnitude °/s",
                yaxis="y2",
            )
        )
        figure.add_vline(x=0, line_dash="dash", line_color="#ef4444")
        figure.update_layout(
            title=f"Crash {selected_crash} impact window — {crash['crash_type']}",
            xaxis_title="Seconds relative to detected fall",
            yaxis={"title": "Acceleration magnitude (g)"},
            yaxis2={"title": "Angular rate (°/s)", "overlaying": "y", "side": "right"},
            legend={"orientation": "h", "y": 1.12},
        )
        st.plotly_chart(figure, width="stretch")
        st.dataframe(crashes.round(3), width="stretch", hide_index=True)

    display = rides.copy()
    display["max_speed_mph"] = display["max_speed_mps"] * 2.23694
    display["peak_power_kW"] = display["peak_power_W"] / 1000.0
    st.subheader("Ride diagnostic table")
    st.dataframe(display.round(3), width="stretch", hide_index=True)


def _thermal_lab(telemetry: pd.DataFrame, events: pd.DataFrame) -> None:
    st.header("Thermal lab")
    trace, sensors, phases = build_thermal_analysis(telemetry)
    hottest = sensors.sort_values("peak_C", ascending=False).iloc[0]
    sensor_label = str(hottest["sensor"]).removesuffix("_C").replace("_", " ").upper()
    columns = st.columns(5)
    columns[0].metric("Hottest sensor", sensor_label)
    columns[1].metric("Peak temperature", f"{hottest['peak_C']:.1f}°C")
    columns[2].metric("Largest session rise", f"{sensors['rise_C'].max():.1f}°C")
    columns[3].metric("Peak pack spread", f"{trace['pack_spread_C'].max():.1f}°C")
    columns[4].metric("Peak heating rate", f"{sensors['peak_heat_rate_C_min'].max():.2f} °C/min")

    temperature_columns = list(PACK_TEMP_COLUMNS) + [
        "vesc_mosfet_C",
        "vesc_motor_or_safety_ntc_C",
        "enclosure_C",
    ]
    thermal_plot = trace.iloc[::5].copy()
    melted = thermal_plot.melt(
        id_vars="session_seconds",
        value_vars=temperature_columns,
        var_name="sensor",
        value_name="temperature_C",
    )
    figure = px.line(
        melted,
        x="session_seconds",
        y="temperature_C",
        color="sensor",
        title="All thermal channels across the session",
        labels={"session_seconds": "Session seconds", "temperature_C": "Temperature (°C)"},
        render_mode="svg",
    )
    figure.add_hline(y=CONFIG.safety.pack_warning_c, line_dash="dash", line_color="#f59e0b")
    figure.add_hline(y=CONFIG.safety.pack_critical_c, line_dash="dash", line_color="#ef4444")
    st.plotly_chart(figure, width="stretch")

    attempts = build_launch_attempts(telemetry, events)
    curves = build_launch_curves(telemetry, attempts)
    left, right = st.columns(2)
    with left:
        launch_temps = curves.melt(
            id_vars=["attempt_id", "outcome", "attempt_seconds"],
            value_vars=["pack_max_C", "vesc_mosfet_C"],
            var_name="sensor",
            value_name="temperature_C",
        )
        figure = px.line(
            launch_temps,
            x="attempt_seconds",
            y="temperature_C",
            color="attempt_id",
            line_dash="sensor",
            hover_data=["outcome"],
            title="Temperature during every launch",
            labels={
                "attempt_seconds": "Seconds from attempt start",
                "temperature_C": "Temperature (°C)",
            },
            render_mode="svg",
        )
        st.plotly_chart(figure, width="stretch")
    with right:
        heatmap = phases.pivot(index="sensor", columns="phase", values="mean_heat_rate_C_min")
        figure = px.imshow(
            heatmap,
            color_continuous_scale="RdBu_r",
            color_continuous_midpoint=0,
            aspect="auto",
            title="Mean heating/cooling rate by operating phase",
            labels={"color": "°C/min"},
        )
        st.plotly_chart(figure, width="stretch")

    left, right = st.columns(2)
    with left:
        figure = px.line(
            thermal_plot,
            x="session_seconds",
            y="pack_spread_C",
            title="Pack thermal spread",
            labels={"session_seconds": "Session seconds", "pack_spread_C": "Max − min pack (°C)"},
            render_mode="svg",
        )
        figure.add_hline(
            y=CONFIG.safety.pack_delta_warning_c, line_dash="dash", line_color="#ef4444"
        )
        st.plotly_chart(figure, width="stretch")
    with right:
        rate_columns = [f"{sensor}_rate_C_min" for sensor in PACK_TEMP_COLUMNS]
        rates = thermal_plot.melt(
            id_vars="session_seconds",
            value_vars=rate_columns,
            var_name="sensor",
            value_name="rate_C_min",
        )
        figure = px.line(
            rates,
            x="session_seconds",
            y="rate_C_min",
            color="sensor",
            title="Rolling 10-second pack heating rate",
            labels={"session_seconds": "Session seconds", "rate_C_min": "°C/min"},
            render_mode="svg",
        )
        st.plotly_chart(figure, width="stretch")
    st.subheader("Sensor thermal summary")
    st.dataframe(sensors.round(3), width="stretch", hide_index=True)
    with st.expander("Operating-phase thermal detail"):
        st.dataframe(phases.round(3), width="stretch", hide_index=True)


def _system_health_page(telemetry: pd.DataFrame, summary: dict[str, object]) -> None:
    st.header("System monitoring & electrical envelope")
    monitor = system_monitoring_summary(telemetry)
    phases = build_electrical_phase_summary(telemetry)
    plot = telemetry.assign(session_seconds=_seconds(telemetry))
    columns = st.columns(7)
    columns[0].metric("Sample rate", f"{monitor['sample_rate_hz']:.1f} Hz")
    columns[1].metric("Timestamp gaps", int(monitor["gap_count"]))
    columns[2].metric("Numeric completeness", f"{monitor['numeric_completeness']:.1%}")
    columns[3].metric("GPS fix coverage", f"{monitor['gps_fix_fraction']:.1%}")
    columns[4].metric("SD OK coverage", f"{monitor['sd_ok_fraction']:.1%}")
    columns[5].metric("Minimum voltage", f"{monitor['minimum_voltage_V']:.1f} V")
    columns[6].metric("Fault samples", int(monitor["fault_samples"]))

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(x=plot["session_seconds"], y=plot["battery_power_W"] / 1000.0, name="Power kW")
    )
    figure.add_trace(
        go.Scatter(
            x=plot["session_seconds"], y=plot["vesc_battery_A"], name="Battery A", yaxis="y2"
        )
    )
    figure.add_trace(
        go.Scatter(x=plot["session_seconds"], y=plot["vesc_vin_V"], name="Voltage", yaxis="y3")
    )
    figure.update_layout(
        title="Electrical load, current, and voltage",
        xaxis_title="Session seconds",
        yaxis={"title": "Power (kW)"},
        yaxis2={"title": "Battery current (A)", "overlaying": "y", "side": "right"},
        yaxis3={
            "title": "Voltage",
            "overlaying": "y",
            "side": "right",
            "anchor": "free",
            "position": 0.94,
        },
        legend={"orientation": "h", "y": 1.12},
    )
    st.plotly_chart(figure, width="stretch")

    left, right = st.columns(2)
    with left:
        figure = px.scatter(
            plot.iloc[::5],
            x="vesc_battery_A",
            y="vesc_vin_V",
            color="state_inferred",
            color_discrete_map=STATE_COLORS,
            title="Voltage sag by operating phase",
            labels={"vesc_battery_A": "Battery current (A)", "vesc_vin_V": "Voltage (V)"},
        )
        st.plotly_chart(figure, width="stretch")
    with right:
        load_scatter = plot.iloc[::5].copy()
        load_scatter["pack_spread_C"] = load_scatter[list(PACK_TEMP_COLUMNS)].max(
            axis=1
        ) - load_scatter[list(PACK_TEMP_COLUMNS)].min(axis=1)
        figure = px.scatter(
            load_scatter,
            x="battery_power_W",
            y="pack_spread_C",
            color="vesc_mosfet_C",
            color_continuous_scale="Turbo",
            title="Load vs pack imbalance",
            labels={
                "battery_power_W": "Battery power (W)",
                "pack_spread_C": "Pack spread (°C)",
            },
        )
        st.plotly_chart(figure, width="stretch")

    status_columns = ["water_adc", "water_alarm", "fault_code", "sd_ok"]
    if "gps_fix_quality" in plot:
        status_columns.append("gps_fix_quality")
    status = plot.iloc[::5].melt(
        id_vars="session_seconds",
        value_vars=status_columns,
        var_name="channel",
        value_name="value",
    )
    figure = px.line(
        status,
        x="session_seconds",
        y="value",
        facet_row="channel",
        title="Safety and logger channel timeline",
        labels={"session_seconds": "Session seconds"},
        height=640,
        render_mode="svg",
    )
    figure.update_yaxes(matches=None)
    st.plotly_chart(figure, width="stretch")

    st.subheader("Electrical load by operating phase")
    phase_display = phases.copy()
    phase_display["energy_fraction"] = phase_display["energy_Wh"] / max(
        float(phase_display["energy_Wh"].sum()), 1e-9
    )
    st.dataframe(phase_display.round(3), width="stretch", hide_index=True)
    st.caption(
        f"Session energy: {_number(summary, 'energy_Wh'):.1f} Wh. Mechanical shaft power and propulsive "
        "efficiency are not estimated because torque is not measured."
    )


def _tuning_page(session_id: str, summary: dict[str, object]) -> None:
    st.header("VESC configuration & experiments")
    user_path = CONFIG_SNAPSHOT_ROOT / f"{summary['config_id']}.json"
    demo_path = DEMO_ROOT / "configs" / f"{summary['config_id']}.json"
    config_path = user_path if user_path.exists() else demo_path
    if config_path.exists():
        snapshot = read_json(config_path)
        st.warning("Read-only configuration snapshot. Jarred Drive does not write VESC settings.")
        left, right = st.columns([1, 1.4])
        with left:
            st.json(snapshot)
        with right:
            st.markdown(
                "Every session is linked to an immutable configuration ID. Compare outcomes only after "
                "accounting for session conditions and collecting repeated runs; one synthetic session is "
                "a UI example, not evidence that a profile is better."
            )
    else:
        st.warning(
            "No configuration snapshot matches this session. Register one with "
            "`jarred-drive register-config` before comparing tuning outcomes."
        )
    index_path = DEMO_ROOT / "session_index.csv"
    if index_path.exists():
        index = pd.read_csv(index_path)
        metrics = [
            "launch_success",
            "failed_launch_rate",
            "ride_falls",
            "median_time_to_takeoff_seconds",
            "foil_utilization",
            "energy_Wh",
            "peak_pack_C",
            "max_pack_spread_C",
        ]
        selected = st.selectbox("Comparison metric", metrics)
        figure = px.bar(
            index,
            x="config_id",
            y=selected,
            color="scenario",
            title=f"Configuration comparison — {selected}",
            color_discrete_sequence=["#22d3ee", "#f59e0b", "#fb7185"],
        )
        st.plotly_chart(figure, width="stretch")
        st.dataframe(index, width="stretch", hide_index=True)
    st.caption(f"Selected session: {session_id}")


def _progress_page() -> None:
    st.header("Progress across sessions")
    index_path = DEMO_ROOT / "session_index.csv"
    if not index_path.exists():
        st.info("At least two analyzed sessions are needed for progression views.")
        return
    index = pd.read_csv(index_path)
    index["date"] = pd.to_datetime(index["session_id"].str[:10])
    newest = index.sort_values("date").iloc[-1]
    columns = st.columns(4)
    columns[0].metric("Sessions", len(index))
    columns[1].metric("Latest launch success", f"{newest['launch_success']:.0%}")
    columns[2].metric("Latest foil utilization", f"{newest['foil_utilization']:.0%}")
    columns[3].metric(
        "Latest longest ride", _format_duration(float(newest["longest_ride_seconds"]))
    )
    metric = st.selectbox(
        "Progress metric",
        [
            "launch_success",
            "failed_launch_rate",
            "ride_falls",
            "median_time_to_takeoff_seconds",
            "foil_utilization",
            "longest_ride_seconds",
            "energy_Wh",
            "peak_pack_C",
        ],
    )
    figure = px.line(
        index.sort_values("date"),
        x="date",
        y=metric,
        color="config_id",
        markers=True,
        hover_data=["session_id", "scenario"],
        title=f"{metric} by session",
        color_discrete_sequence=["#22d3ee", "#f59e0b", "#fb7185"],
    )
    st.plotly_chart(figure, width="stretch")
    st.info(
        "These three points are synthetic workflow fixtures, not a performance trend. Field progression "
        "becomes meaningful only after repeated, manually reviewed sessions under comparable conditions."
    )


def _annotation_page(session_id: str, telemetry: pd.DataFrame, events: pd.DataFrame) -> None:
    st.header("Manual event annotation")
    st.markdown(
        "Correct takeoffs, touchdowns, recoveries, and falls here. Manual labels are preserved separately "
        "from detector output and become ground truth for later model development."
    )
    path = ANNOTATION_ROOT / f"{session_id}.csv"
    initial = pd.read_csv(path) if path.exists() else annotation_template(session_id)
    edited = st.data_editor(
        initial,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "session_id": st.column_config.TextColumn(default=session_id),
            "timestamp_ms": st.column_config.NumberColumn(min_value=0, step=100),
            "event_type": st.column_config.SelectboxColumn(
                options=[str(event) for event in EventType]
            ),
            "confidence": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, default=1.0),
            "source": st.column_config.TextColumn(default="manual"),
            "notes": st.column_config.TextColumn(),
        },
        key=f"annotations-{session_id}",
    )
    if st.button("Save annotations", type="primary"):
        normalized = edited.loc[:, ANNOTATION_COLUMNS].copy()
        normalized["session_id"] = normalized["session_id"].fillna(session_id)
        normalized["source"] = "manual"
        normalized["confidence"] = normalized["confidence"].fillna(1.0)
        normalized["notes"] = normalized["notes"].fillna("")
        errors = validate_annotations(normalized, session_id, int(telemetry["timestamp_ms"].max()))
        if errors:
            for error in errors:
                st.error(error)
        else:
            save_annotations(normalized, path)
            st.success(f"Saved {len(normalized)} annotations to {path.relative_to(ROOT)}")
    if not initial.empty:
        merged = merge_annotations(events, initial)
        st.subheader("Merged event preview")
        st.dataframe(merged, width="stretch", hide_index=True)


def _raw_page(telemetry: pd.DataFrame, events: pd.DataFrame) -> None:
    st.header("Raw telemetry")
    report = validate_telemetry(telemetry)
    if report.valid:
        st.success("Telemetry satisfies schema 1.0.0")
    for issue in report.issues:
        getattr(st, "error" if issue.severity == "error" else "warning")(issue.message)
    start, end = st.slider(
        "Session-second window",
        0.0,
        float(_seconds(telemetry).max()),
        (0.0, min(60.0, float(_seconds(telemetry).max()))),
    )
    window = telemetry[_seconds(telemetry).between(start, end)]
    st.dataframe(window, width="stretch", height=420)
    st.download_button(
        "Download raw telemetry CSV",
        telemetry.to_csv(index=False),
        file_name=f"{telemetry['session_id'].iloc[0]}_telemetry.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download derived events CSV",
        events.to_csv(index=False),
        file_name=f"{telemetry['session_id'].iloc[0]}_events.csv",
        mime="text/csv",
    )


def main() -> None:
    st.sidebar.markdown('<div class="jd-brand">JARRED DRIVE</div>', unsafe_allow_html=True)
    st.sidebar.markdown(
        '<div class="jd-subtitle">FOIL-ASSIST FLIGHT RECORDER</div>', unsafe_allow_html=True
    )
    _import_panel()
    sessions = _available_sessions()
    if not sessions:
        st.error("No sessions found. Run `make demo` from the repository root.")
        st.stop()
    session_id = st.sidebar.selectbox("Session", sorted(sessions, reverse=True))
    page = st.sidebar.radio("Mode", NAV_ITEMS)
    telemetry_path = sessions[session_id]
    raw = _load_session(str(telemetry_path), telemetry_path.stat().st_mtime_ns)
    report = validate_telemetry(raw)
    if not report.valid:
        st.error("Selected session does not satisfy the telemetry contract.")
        st.json(report.as_dicts())
        st.stop()
    use_truth = "sim_state" in raw.columns
    telemetry, detected = detect_events(raw, CONFIG.detection, use_synthetic_truth=use_truth)
    annotation_path = ANNOTATION_ROOT / f"{session_id}.csv"
    annotations = pd.read_csv(annotation_path) if annotation_path.exists() else pd.DataFrame()
    events = merge_annotations(detected, annotations)
    rides = build_rides(telemetry, events)
    summary = summarize_session(telemetry, events, rides)

    source_label = "SYNTHETIC" if use_truth else "IMPORTED"
    st.sidebar.caption(f"{source_label} • schema {raw['schema_version'].iloc[0]}")
    st.sidebar.caption("VESC policy: READ ONLY")
    st.title(page)
    st.caption(
        f"Session {session_id} • {summary['scenario']} • Configuration {summary['config_id']}"
    )
    if page == "Devices / Sync":
        _sync_page()
    elif page == "Flight Deck":
        _flight_deck(telemetry, events, rides, summary)
    elif page == "Launch Lab":
        _launch_lab(telemetry, events)
    elif page == "Ride Dynamics":
        _ride_dynamics_page(telemetry, events, rides, summary)
    elif page == "Thermal Lab":
        _thermal_lab(telemetry, events)
    elif page == "System Health":
        _system_health_page(telemetry, summary)
    elif page == "Tuning":
        _tuning_page(session_id, summary)
    elif page == "Progress":
        _progress_page()
    elif page == "Annotate":
        _annotation_page(session_id, telemetry, events)
    else:
        _raw_page(telemetry, events)


if __name__ == "__main__":
    main()
