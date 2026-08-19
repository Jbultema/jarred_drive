"""Jarred Drive Streamlit dashboard.

Run with: poetry run streamlit run src/jarred_drive/dashboard/app.py
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from jarred_drive.analytics import build_rides, health_status, summarize_session
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

ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = ROOT / "data" / "demo"
IMPORT_ROOT = ROOT / "data" / "imports"
ANNOTATION_ROOT = ROOT / "data" / "annotations"
CONFIG_SNAPSHOT_ROOT = ROOT / "data" / "configs"
CONFIG = load_config(ROOT / "configs" / "system.yaml")

NAV_ITEMS = (
    "Flight Deck",
    "Rides",
    "Equipment",
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
    sessions = discover_sessions(DEMO_ROOT) + discover_sessions(IMPORT_ROOT)
    return {session.session_id: session.telemetry for session in sessions}


def _import_panel() -> None:
    with st.sidebar.expander("Import microSD log"):
        uploaded = st.file_uploader("Telemetry CSV", type=["csv"], label_visibility="collapsed")
        if uploaded is None:
            st.caption("Files stay on this machine.")
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
            destination = IMPORT_ROOT / session_id / "telemetry.csv"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(uploaded.getvalue())
            _load_session.clear()
            st.rerun()


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
    columns = st.columns(6)
    columns[0].metric("Water time", _format_duration(_number(summary, "duration_seconds")))
    columns[1].metric("Foil time", _format_duration(_number(summary, "foil_seconds")))
    columns[2].metric("Launch success", f"{_number(summary, 'launch_success'):.0%}")
    columns[3].metric("Longest ride", _format_duration(_number(summary, "longest_ride_seconds")))
    columns[4].metric("Energy used", f"{_number(summary, 'energy_Wh'):.1f} Wh")
    columns[5].metric("Peak power", f"{_number(summary, 'peak_power_W') / 1000:.2f} kW")

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
            route = telemetry.iloc[:: max(1, len(telemetry) // 1400)].copy()
            route["state"] = route["state_inferred"]
            figure = px.scatter_map(
                route,
                lat="gps_lat",
                lon="gps_lon",
                color="state",
                color_discrete_map=STATE_COLORS,
                zoom=13,
                height=380,
                title="Session track by ride state",
            )
            figure.update_traces(marker={"size": 5})
            figure.update_layout(
                map_style="carto-darkmatter", margin={"l": 0, "r": 0, "b": 0, "t": 35}
            )
            st.plotly_chart(figure, width="stretch")
        else:
            st.info("This session has no GPS fields. All non-spatial analytics remain available.")

    st.subheader("Event log")
    event_view = events.copy()
    event_view["time"] = event_view["timestamp_ms"].map(
        lambda value: _format_duration(float(value) / 1000)
    )
    st.dataframe(
        event_view[["time", "event_type", "confidence", "source", "notes"]],
        width="stretch",
        hide_index=True,
    )


def _rides_page(rides: pd.DataFrame, summary: dict[str, object]) -> None:
    st.header("Rides & progression")
    if rides.empty:
        st.warning("No rides were detected in this session.")
        return
    columns = st.columns(4)
    columns[0].metric("Rides", len(rides))
    columns[1].metric("Median ride", _format_duration(float(rides["ride_seconds"].median())))
    columns[2].metric(
        "Recovery rate", f"{rides['recoveries'].sum() / max(1, rides['touchdowns'].sum()):.0%}"
    )
    columns[3].metric("Wh / ride", f"{_number(summary, 'energy_Wh') / max(1, len(rides)):.2f}")
    chart_data = rides.melt(
        id_vars=["ride_id"],
        value_vars=["ride_seconds", "foil_seconds"],
        var_name="metric",
        value_name="seconds",
    )
    figure = px.bar(
        chart_data,
        x="ride_id",
        y="seconds",
        color="metric",
        barmode="group",
        color_discrete_map={"ride_seconds": "#64748b", "foil_seconds": "#22d3ee"},
        title="Ride and flight duration",
    )
    st.plotly_chart(figure, width="stretch")
    display = rides.copy()
    display["max_speed_mph"] = display["max_speed_mps"] * 2.23694
    display["peak_power_kW"] = display["peak_power_W"] / 1000
    st.dataframe(
        display[
            [
                "ride_id",
                "ride_seconds",
                "foil_seconds",
                "touchdowns",
                "recoveries",
                "energy_Wh",
                "max_speed_mph",
                "peak_power_kW",
                "termination",
            ]
        ],
        width="stretch",
        hide_index=True,
    )


def _equipment_page(telemetry: pd.DataFrame, summary: dict[str, object]) -> None:
    st.header("Equipment health")
    columns = st.columns(5)
    columns[0].metric("Peak pack", f"{_number(summary, 'peak_pack_C'):.1f}°C")
    columns[1].metric("Pack spread", f"{_number(summary, 'max_pack_spread_C'):.1f}°C")
    columns[2].metric("Peak VESC", f"{_number(summary, 'peak_vesc_C'):.1f}°C")
    columns[3].metric("Minimum voltage", f"{telemetry['vesc_vin_V'].min():.1f} V")
    columns[4].metric("Water", "DETECTED" if summary["water_detected"] else "DRY")
    plot = telemetry.assign(session_seconds=_seconds(telemetry))
    temp_columns = list(PACK_TEMP_COLUMNS) + ["vesc_mosfet_C", "enclosure_C"]
    melted = plot.melt(
        id_vars="session_seconds",
        value_vars=temp_columns,
        var_name="sensor",
        value_name="temperature_C",
    )
    figure = px.line(
        melted,
        x="session_seconds",
        y="temperature_C",
        color="sensor",
        title="Thermal channels",
        labels={"session_seconds": "Session seconds", "temperature_C": "Temperature (°C)"},
    )
    figure.add_hline(y=CONFIG.safety.pack_warning_c, line_dash="dash", line_color="#f59e0b")
    figure.add_hline(y=CONFIG.safety.pack_critical_c, line_dash="dash", line_color="#ef4444")
    st.plotly_chart(figure, width="stretch")
    left, right = st.columns(2)
    with left:
        figure = px.line(
            plot,
            x="session_seconds",
            y="water_adc",
            title="Water-electrode raw ADC",
            labels={"session_seconds": "Session seconds", "water_adc": "ADC"},
        )
        figure.update_traces(line_color="#38bdf8")
        st.plotly_chart(figure, width="stretch")
    with right:
        figure = px.scatter(
            plot.iloc[::10],
            x="vesc_battery_A",
            y="vesc_vin_V",
            color="vesc_mosfet_C",
            title="Voltage sag under battery load",
            labels={"vesc_battery_A": "Battery current (A)", "vesc_vin_V": "Voltage (V)"},
            color_continuous_scale="Turbo",
        )
        st.plotly_chart(figure, width="stretch")


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
        metrics = ["launch_success", "foil_utilization", "energy_Wh", "peak_pack_C"]
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
    if page == "Flight Deck":
        _flight_deck(telemetry, events, rides, summary)
    elif page == "Rides":
        _rides_page(rides, summary)
    elif page == "Equipment":
        _equipment_page(telemetry, summary)
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
