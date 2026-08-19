"""Jarred Drive Streamlit dashboard.

Run with: poetry run streamlit run src/jarred_drive/dashboard/app.py
"""

from __future__ import annotations

import base64
import io
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
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
BRAND_ROOT = ROOT / "assets" / "branding"
BRAND_MARK = BRAND_ROOT / "jarred-drive-mark.png"
BRAND_ICON = BRAND_ROOT / "jarred-drive-icon.png"
BRAND_HERO = BRAND_ROOT / "jarred-drive-hero.png"
CONFIG = load_config(ROOT / "configs" / "system.yaml")


def _asset_uri(path: Path) -> str:
    """Return a local PNG as an offline-safe data URI."""
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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
NAV_ICONS = {
    "Devices / Sync": "⇄",
    "Flight Deck": "⌁",
    "Launch Lab": "↗",
    "Ride Dynamics": "∿",
    "Thermal Lab": "◫",
    "System Health": "✦",
    "Tuning": "⌘",
    "Progress": "▥",
    "Annotate": "✎",
    "Raw Data": "≡",
}
PAGE_DESCRIPTIONS = {
    "Devices / Sync": "Secure home-base transfer, verification, and device readiness.",
    "Flight Deck": "The whole session at a glance—from launch to last ride.",
    "Launch Lab": "Power delivery, takeoff efficiency, and failed-start forensics.",
    "Ride Dynamics": "Flight segments, recoveries, turns, and crash signatures.",
    "Thermal Lab": "Heat accumulation across packs, propulsion, and ride phases.",
    "System Health": "Electrical envelope, logger integrity, and sensor confidence.",
    "Tuning": "Configuration provenance and controlled experiment comparison.",
    "Progress": "Session-over-session development and rider progression.",
    "Annotate": "Human-reviewed event labels for better future classifiers.",
    "Raw Data": "Immutable observations, validation findings, and exports.",
}
STATE_COLORS = {
    str(RideState.IDLE): "#64748b",
    str(RideState.ACCELERATING): "#f59e0b",
    str(RideState.FOILING): "#22d3ee",
    str(RideState.TOUCHDOWN): "#fb7185",
    str(RideState.FALL): "#ef4444",
}

JD_COLORS = ["#4DE4FF", "#FFB547", "#FF667D", "#6EE7B7", "#9B8AFB", "#60A5FA"]
pio.templates["jarred_drive"] = go.layout.Template(
    layout={
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(7,17,31,0.12)",
        "font": {"family": "Inter, Avenir Next, system-ui, sans-serif", "color": "#B8CBDA"},
        "title": {"font": {"size": 17, "color": "#F3FBFF"}, "x": 0.02, "xanchor": "left"},
        "colorway": JD_COLORS,
        "hoverlabel": {
            "bgcolor": "#102337",
            "bordercolor": "#28465E",
            "font": {"color": "#F3FBFF"},
        },
        "legend": {"font": {"color": "#A9BDCC"}, "title": {"font": {"color": "#EAF9FF"}}},
        "xaxis": {
            "gridcolor": "rgba(101,141,166,.14)",
            "linecolor": "rgba(101,141,166,.22)",
            "zerolinecolor": "rgba(101,141,166,.22)",
            "title": {"font": {"color": "#8EA7B8"}},
        },
        "yaxis": {
            "gridcolor": "rgba(101,141,166,.14)",
            "linecolor": "rgba(101,141,166,.22)",
            "zerolinecolor": "rgba(101,141,166,.22)",
            "title": {"font": {"color": "#8EA7B8"}},
        },
        "margin": {"l": 52, "r": 30, "t": 62, "b": 48},
    }
)
pio.templates.default = "jarred_drive"
px.defaults.template = "jarred_drive"
px.defaults.color_discrete_sequence = JD_COLORS


st.set_page_config(
    page_title="Jarred Drive",
    page_icon=str(BRAND_ICON),
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    :root {
        --jd-cyan: #4de4ff; --jd-cyan-soft: rgba(77,228,255,.14);
        --jd-navy: #050c15; --jd-panel: rgba(11,25,39,.86);
        --jd-panel-hi: rgba(16,36,54,.92); --jd-line: rgba(106,157,187,.20);
        --jd-text: #f3fbff; --jd-muted: #8fa8b9; --jd-green: #5ee5ae;
        --jd-amber: #ffb547; --jd-red: #ff667d;
    }
    html, body, [class*="css"] { font-family: Inter, "Avenir Next", -apple-system, BlinkMacSystemFont, sans-serif; }
    .stApp {
        background:
            radial-gradient(circle at 76% -8%, rgba(0,176,214,.13), transparent 28rem),
            radial-gradient(circle at 18% 82%, rgba(27,88,126,.12), transparent 32rem),
            linear-gradient(148deg, #050c15 0%, #071321 48%, #081827 100%);
        color: var(--jd-text);
    }
    .stApp::before {
        content: ""; position: fixed; inset: 0; pointer-events: none; opacity: .22;
        background-image: linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px),
                          linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px);
        background-size: 42px 42px;
        mask-image: linear-gradient(to bottom, black, transparent 68%);
    }
    header[data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbar"] { visibility: hidden; }
    #MainMenu, footer { visibility: hidden; }
    .block-container { padding: 2.2rem 2.6rem 5rem; max-width: 1540px; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(5,13,22,.98), rgba(7,20,32,.98));
        border-right: 1px solid var(--jd-line); box-shadow: 18px 0 60px rgba(0,0,0,.18);
    }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 1.7rem; }
    [data-testid="stSidebar"] hr { border-color: var(--jd-line); }
    .jd-brand-wrap { display: flex; align-items: center; gap: .7rem; margin: -.25rem 0 .1rem; }
    .jd-brand-mark { width: 54px; height: 54px; padding:3px; object-fit: contain; border-radius:13px;
        background:#fff; border:1px solid rgba(77,228,255,.22); box-shadow:0 0 18px rgba(77,228,255,.12); }
    .jd-brand { letter-spacing: .13em; font-weight: 850; font-size: 1.06rem; color: var(--jd-text); }
    .jd-brand-copy { min-width: 0; }
    .jd-subtitle { color: #5fb9c8; font-size: .58rem; letter-spacing: .14em; margin-top: .16rem; }
    .jd-nav-label { color: #547386; font-size: .62rem; font-weight: 750; letter-spacing: .18em; margin: 1.2rem 0 .45rem; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .26rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        border: 1px solid transparent; border-radius: 10px; padding: .48rem .62rem;
        transition: all .16s ease; color: #9fb4c2;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(77,228,255,.06); border-color: rgba(77,228,255,.12); color: #effcff;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(90deg, rgba(77,228,255,.16), rgba(77,228,255,.04));
        border-color: rgba(77,228,255,.22); color: #f4fdff;
        box-shadow: inset 3px 0 0 var(--jd-cyan);
    }
    [data-testid="stSidebar"] [role="radiogroup"] [data-testid="stMarkdownContainer"] p {
        font-size: .83rem; font-weight: 620;
    }
    [data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div > div:first-child {
        display: none;
    }
    [data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p {
        color: #668397; font-size: .64rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase;
    }
    .jd-sidebar-foot {
        margin-top: 1.25rem; padding: .75rem .85rem; border: 1px solid var(--jd-line);
        border-radius: 11px; background: rgba(14,31,45,.55); color: #7894a7; font-size: .67rem;
    }
    .jd-live-dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:.45rem;
        background:var(--jd-green); box-shadow:0 0 10px rgba(94,229,174,.7); }
    h1 { font-size: 2.32rem !important; line-height: 1.04 !important; letter-spacing: -.035em !important;
         font-weight: 780 !important; margin: .05rem 0 .25rem !important; color: var(--jd-text) !important; }
    h2 { font-size: 1.42rem !important; letter-spacing: -.02em; color: var(--jd-text) !important;
         margin-top: 1.9rem !important; }
    h3 { font-size: 1.05rem !important; color: #dff8ff !important; letter-spacing: -.01em; }
    .jd-eyebrow { color: var(--jd-cyan); font-size: .64rem; font-weight: 800; letter-spacing: .2em;
                  text-transform: uppercase; margin-bottom: .45rem; }
    .jd-page-description { color: #91aaba; font-size: .94rem; max-width: 760px; margin-bottom: .82rem; }
    .jd-meta-row { display:flex; flex-wrap:wrap; gap:.45rem; margin-bottom:1.45rem; }
    .jd-chip { padding:.28rem .58rem; border-radius:999px; background:rgba(105,149,174,.08);
               border:1px solid rgba(105,149,174,.17); color:#91adbf; font-size:.67rem; letter-spacing:.03em; }
    .jd-chip strong { color:#dff8ff; font-weight:650; }
    .jd-divider { height:1px; margin:.2rem 0 1.15rem; background:linear-gradient(90deg,var(--jd-line),transparent 78%); }
    .jd-hero {
        position:relative; overflow:hidden; min-height:255px; margin:.15rem 0 1.3rem;
        border:1px solid rgba(102,184,211,.24); border-radius:20px;
        background-size:cover; background-position:center 53%;
        box-shadow:0 24px 70px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.04);
    }
    .jd-hero::before { content:""; position:absolute; inset:0;
        background:linear-gradient(90deg,rgba(3,11,20,.96) 0%,rgba(4,15,25,.78) 39%,rgba(5,15,24,.18) 72%),
                   linear-gradient(0deg,rgba(4,13,22,.8),transparent 55%); }
    .jd-hero-copy { position:relative; z-index:1; max-width:520px; padding:2.25rem 2.2rem; }
    .jd-hero-kicker { color:var(--jd-cyan); font-size:.61rem; font-weight:850; letter-spacing:.2em; text-transform:uppercase; }
    .jd-hero-title { color:#f3fbff; font-size:1.55rem; line-height:1.08; font-weight:780; letter-spacing:-.025em; margin:.45rem 0 .55rem; }
    .jd-hero-text { color:#a9c1d0; font-size:.81rem; line-height:1.55; max-width:430px; }
    .jd-hero-system { display:inline-flex; gap:.42rem; align-items:center; margin-top:1.05rem; padding:.34rem .62rem;
        border:1px solid rgba(77,228,255,.22); border-radius:999px; background:rgba(5,20,31,.56);
        color:#dffaff; font-size:.64rem; letter-spacing:.06em; }
    .jd-hero-system::before { content:""; width:6px; height:6px; border-radius:50%; background:var(--jd-green);
        box-shadow:0 0 10px rgba(94,229,174,.75); }
    [data-testid="stMetric"] {
        position: relative; overflow: hidden; min-height: 108px;
        background: linear-gradient(145deg, rgba(16,36,54,.91), rgba(9,23,36,.76));
        border: 1px solid var(--jd-line); border-radius: 14px; padding: .92rem 1rem;
        box-shadow: 0 12px 30px rgba(0,0,0,.11), inset 0 1px 0 rgba(255,255,255,.025);
        transition: transform .16s ease, border-color .16s ease;
    }
    [data-testid="stMetric"]::before { content:""; position:absolute; inset:0 auto 0 0; width:2px;
        background:linear-gradient(to bottom,var(--jd-cyan),transparent 80%); opacity:.72; }
    [data-testid="stMetric"]:hover { transform: translateY(-2px); border-color: rgba(77,228,255,.32); }
    [data-testid="stMetricLabel"] { color: #7895a9; }
    [data-testid="stMetricLabel"] p { font-size: .68rem; font-weight: 720; text-transform: uppercase;
                                      letter-spacing: .075em; }
    [data-testid="stMetricValue"] { color: var(--jd-text); font-variant-numeric: tabular-nums; }
    [data-testid="stMetricValue"] > div { font-size: 1.58rem; font-weight: 720; letter-spacing: -.035em; }
    [data-testid="stPlotlyChart"] {
        background: linear-gradient(145deg, rgba(12,29,44,.76), rgba(7,20,32,.52));
        border: 1px solid var(--jd-line); border-radius: 16px; padding: .45rem;
        box-shadow: 0 14px 38px rgba(0,0,0,.10); overflow: hidden;
    }
    [data-testid="stDataFrame"] { border: 1px solid var(--jd-line); border-radius: 13px; overflow: hidden; }
    [data-testid="stAlert"] { border-radius: 12px; border: 1px solid var(--jd-line); }
    .stButton > button, .stDownloadButton > button {
        border-radius: 10px; border: 1px solid rgba(77,228,255,.28); min-height: 2.65rem;
        background: linear-gradient(135deg, rgba(77,228,255,.16), rgba(31,112,144,.10));
        color: #eaffff; font-weight: 680; letter-spacing: .015em; transition: all .16s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: rgba(77,228,255,.65); background: rgba(77,228,255,.18);
        box-shadow: 0 0 24px rgba(77,228,255,.10); transform: translateY(-1px);
    }
    [data-testid="stSelectbox"] > div > div, [data-baseweb="input"] {
        background-color: rgba(10,25,39,.8); border-color: var(--jd-line); border-radius: 10px;
    }
    [data-testid="stExpander"] { border: 1px solid var(--jd-line); border-radius: 12px;
                                 background: rgba(9,23,36,.52); }
    .stTabs [data-baseweb="tab-list"] { gap: .32rem; border-bottom: 1px solid var(--jd-line); }
    .stTabs [data-baseweb="tab"] { background: transparent; border-radius: 8px 8px 0 0; color:#7894a7; }
    .stTabs [aria-selected="true"] { color: var(--jd-cyan); background: rgba(77,228,255,.07); }
    .jd-status { position:relative; overflow:hidden; border-radius: 16px; padding: 1.15rem 1.3rem;
                 margin: .2rem 0 1.15rem; background: linear-gradient(120deg,rgba(14,33,49,.94),rgba(8,22,34,.8));
                 border: 1px solid var(--jd-line); box-shadow: 0 16px 38px rgba(0,0,0,.13); }
    .jd-status::after { content:""; position:absolute; width:190px; height:190px; right:-65px; top:-95px;
                        border-radius:50%; background:currentColor; opacity:.055; }
    .jd-ready { color: var(--jd-green); border-left: 4px solid var(--jd-green); }
    .jd-warning { color: var(--jd-amber); border-left: 4px solid var(--jd-amber); }
    .jd-stop { color: var(--jd-red); border-left: 4px solid var(--jd-red); background:linear-gradient(120deg,rgba(54,18,30,.78),rgba(22,15,26,.78)); }
    .jd-status-label { font-size: .62rem; font-weight:800; letter-spacing: .2em; color: currentColor; }
    .jd-status-value { color: var(--jd-text); font-size: 1.45rem; font-weight: 760; margin: .2rem 0 .18rem; }
    .jd-note { color: #8fa7b7; font-size: .78rem; }
    .jd-device-card { display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:1rem;
        padding:1.05rem 1.2rem; margin:.3rem 0 1.1rem; border-radius:15px; border:1px solid var(--jd-line);
        background:linear-gradient(120deg,rgba(15,37,54,.9),rgba(8,23,35,.78)); }
    .jd-device-icon { width:42px;height:42px;display:grid;place-items:center;border-radius:12px;
        background:var(--jd-cyan-soft);border:1px solid rgba(77,228,255,.24);color:var(--jd-cyan);font-size:1.2rem; }
    .jd-device-name { color:var(--jd-text);font-weight:720;font-size:1rem; }
    .jd-device-meta { color:#7895a8;font-size:.72rem;margin-top:.18rem; }
    .jd-online { color:var(--jd-green);font-size:.66rem;font-weight:800;letter-spacing:.13em; }
    @media (max-width: 900px) { .block-container { padding: 1.4rem 1rem 4rem; } h1 { font-size:1.85rem!important; }
        .jd-hero { min-height:225px; background-position:64% center; } .jd-hero-copy { padding:1.55rem 1.35rem; max-width:78%; } }
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
    st.markdown(
        f'<div class="jd-device-card"><div class="jd-device-icon">⇄</div>'
        f'<div><div class="jd-device-name">{escape(device.name)}</div>'
        f'<div class="jd-device-meta">{escape(device.device_id)} · {escape(device.hardware_revision)}</div></div>'
        f'<div class="jd-online"><span class="jd-live-dot"></span>{escape(status_color)}</div></div>',
        unsafe_allow_html=True,
    )
    columns = st.columns(6)
    columns[0].metric("Mode", device.mode)
    columns[1].metric("Battery", f"{device.battery_percent:.0f}%")
    columns[2].metric("Firmware", device.firmware_version.removesuffix("-simulated"))
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
        height=122,
        margin={"l": 8, "r": 8, "t": 14, "b": 34},
        xaxis_title="Session seconds",
        yaxis={"showticklabels": False, "title": None},
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
                render_mode="svg",
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
            render_mode="svg",
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
            render_mode="svg",
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
                render_mode="svg",
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
            render_mode="svg",
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
            render_mode="svg",
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
    brand_mark_uri = _asset_uri(BRAND_MARK)
    hero_uri = _asset_uri(BRAND_HERO)
    st.sidebar.markdown(
        f'<div class="jd-brand-wrap"><img class="jd-brand-mark" src="{brand_mark_uri}" alt="Jarred Drive rider with lumbar pack, coiled lead, mast motor and propeller, and foil">'
        '<div class="jd-brand-copy"><div class="jd-brand">JARRED DRIVE</div>'
        '<div class="jd-subtitle">FOIL INTELLIGENCE SYSTEM</div></div></div>',
        unsafe_allow_html=True,
    )
    _import_panel()
    sessions = _available_sessions()
    if not sessions:
        st.error("No sessions found. Run `make demo` from the repository root.")
        st.stop()
    st.sidebar.markdown('<div class="jd-nav-label">ACTIVE SESSION</div>', unsafe_allow_html=True)
    session_id = st.sidebar.selectbox(
        "Session", sorted(sessions, reverse=True), label_visibility="collapsed"
    )
    st.sidebar.markdown('<div class="jd-nav-label">WORKSPACES</div>', unsafe_allow_html=True)
    page = st.sidebar.radio(
        "Mode",
        NAV_ITEMS,
        format_func=lambda item: f"{NAV_ICONS[item]}  {item}",
        label_visibility="collapsed",
    )
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

    source_label = "SYNTHETIC DATA" if use_truth else "FIELD IMPORT"
    st.sidebar.markdown(
        f'<div class="jd-sidebar-foot"><div><span class="jd-live-dot"></span>{escape(source_label)}</div>'
        f'<div style="margin-top:.42rem">Schema {escape(str(raw["schema_version"].iloc[0]))} · VESC read only</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="jd-eyebrow">FOIL SESSION INTELLIGENCE</div>', unsafe_allow_html=True)
    st.title(page)
    st.markdown(
        f'<div class="jd-page-description">{PAGE_DESCRIPTIONS[page]}</div>',
        unsafe_allow_html=True,
    )
    if page == "Devices / Sync":
        chips = (
            '<span class="jd-chip"><strong>LOCAL</strong> home network</span>'
            '<span class="jd-chip"><strong>SHA-256</strong> verified</span>'
            '<span class="jd-chip"><strong>RAW</strong> never auto-deleted</span>'
        )
    else:
        chips = (
            f'<span class="jd-chip"><strong>SESSION</strong> {escape(session_id)}</span>'
            f'<span class="jd-chip"><strong>SCENARIO</strong> {escape(str(summary["scenario"]))}</span>'
            f'<span class="jd-chip"><strong>CONFIG</strong> {escape(str(summary["config_id"]))}</span>'
        )
    st.markdown(
        f'<div class="jd-meta-row">{chips}</div><div class="jd-divider"></div>',
        unsafe_allow_html=True,
    )
    if page == "Flight Deck":
        st.markdown(
            f'<section class="jd-hero" style="background-image:url(\'{hero_uri}\')">'
            '<div class="jd-hero-copy"><div class="jd-hero-kicker">Lumbar-powered · rider-developed</div>'
            '<div class="jd-hero-title">Turn every launch, foil run, and fall into design evidence.</div>'
            '<div class="jd-hero-text">Jarred Drive connects propulsion, thermal, motion, and GPS telemetry into one local-first session record—built to improve both the machine and the rider.</div>'
            '<div class="jd-hero-system">SESSION TELEMETRY READY</div></div></section>',
            unsafe_allow_html=True,
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
