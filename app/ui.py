"""Streamlit interface for Contract Observatory."""

import html
import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

from app.analyzer import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AnalysisError,
    analyze_changes,
    analyze_migration_changes,
    ensure_ollama_model_available,
)
from app.config import MAX_SPEC_BYTES
from app.db_migration import (
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_TOTAL_BYTES,
    SUPPORTED_SOURCE_SUFFIXES,
    MigrationReport,
    analyze_migration,
)
from app.differ import SpecDiffError, compare_specs
from app.models import Change, ChangeAssessment, DiffResult, RiskAnalysis, RiskSeverity
from app.parser import SpecParseError, parse_spec_text

SEVERITY_ICONS = {
    RiskSeverity.CRITICAL: "🔴",
    RiskSeverity.HIGH: "🟠",
    RiskSeverity.MEDIUM: "🟡",
    RiskSeverity.LOW: "⚪",
}
PRODUCT_NAME = "Contract Observatory"
ANALYSIS_LANES = (
    "API contract",
    "Database migration",
    "Unified review",
)

CUSTOM_CSS = """
<style>
:root {
  --ink: #e7f0ee;
  --muted: #8da5a0;
  --panel: #101a1b;
  --panel-raised: #142122;
  --line: rgba(176, 211, 201, .12);
  --mint: #9cf4d4;
  --orange: #ffb36b;
}
html, body, [class*="css"] {
  font-family: Inter, "Segoe UI", sans-serif;
}
.stApp {
  color: var(--ink);
  background:
    radial-gradient(ellipse at 72% -12%, rgba(77, 161, 135, .15), transparent 39%),
    linear-gradient(160deg, #0b1113 0%, #0b1214 52%, #101718 100%);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #111b1c 0%, #0d1517 100%);
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
[data-testid="stMainBlockContainer"] {
  max-width: 1440px;
  padding-top: 2.2rem;
  padding-bottom: 4rem;
}
h1, h2, h3 { letter-spacing: -.045em; }
.brand-lockup { display:flex; gap:12px; align-items:center; margin: 0 0 6px; }
.brand-mark {
  width:38px;height:38px;display:grid;place-items:center;border-radius:12px;
  color:#081511;background:linear-gradient(140deg,#a5f4d7,#62c6a3);
  font-size:17px;font-weight:900;box-shadow:0 0 24px rgba(120,229,190,.18);
}
.brand-name { font-size:15px;font-weight:800;letter-spacing:-.04em;color:#eef8f4; }
.brand-sub { color:#829a94;font:10px Consolas,monospace;letter-spacing:.12em;text-transform:uppercase; }
.eyebrow { color:var(--mint);font:11px Consolas,monospace;letter-spacing:.16em;text-transform:uppercase; }
.hero-title { font-size:clamp(36px,5vw,64px);line-height:1.03;font-weight:800;letter-spacing:-.07em;margin:.55rem 0 .8rem; }
.hero-title span { color:var(--mint); }
.hero-copy { color:#9db1ac;font-size:15px;line-height:1.7;max-width:720px; }
.topline { display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:1.3rem; }
.status-pill { border:1px solid rgba(156,244,212,.23);background:rgba(156,244,212,.06);color:#b4f4da;border-radius:999px;padding:7px 11px;font:10px Consolas,monospace;letter-spacing:.08em;white-space:nowrap; }
.status-dot { color:#72e7b9;margin-right:6px; }
.section-kicker { margin:1.3rem 0 .65rem;color:#91aaa3;font:10px Consolas,monospace;letter-spacing:.15em;text-transform:uppercase; }
.stat-card {
  background:linear-gradient(145deg,rgba(23,37,37,.96),rgba(15,24,25,.92));
  border:1px solid var(--line);border-radius:15px;padding:16px 18px;min-height:108px;
}
.stat-label { color:#92a8a2;font:10px Consolas,monospace;letter-spacing:.12em;text-transform:uppercase; }
.stat-value { color:#edf7f3;font-size:29px;font-weight:800;letter-spacing:-.06em;margin:8px 0 2px; }
.stat-note { color:#78908a;font-size:11px; }
.gate-card {
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  border:1px solid var(--line);border-radius:15px;padding:15px 18px;margin:14px 0;
  background:linear-gradient(100deg,rgba(17,29,29,.96),rgba(13,21,22,.9));
}
.gate-card.hold { border-color:rgba(255,135,111,.25); }
.gate-title { color:#91aaa3;font:10px Consolas,monospace;letter-spacing:.14em;text-transform:uppercase; }
.gate-state { font-size:18px;font-weight:800;letter-spacing:-.04em;margin-top:5px; }
.gate-note { color:#829a94;font-size:11px;margin-top:3px; }
.fingerprint { min-width:180px;max-width:330px;width:36%; }
.fingerprint-bar { display:flex;height:7px;overflow:hidden;border-radius:99px;background:#263435; }
.fingerprint-removed { background:#ff876f; }
.fingerprint-required { background:#ffc16e; }
.fingerprint-type { background:#bd9cff; }
.fingerprint-added { background:#70d7ad; }
.fingerprint-label { display:flex;justify-content:space-between;color:#78918a;font:9px Consolas,monospace;margin-top:7px; }
.flow-wrap { display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:13px 15px;border:1px solid var(--line);border-radius:14px;background:rgba(14,23,24,.64);margin:18px 0 24px; }
.flow-step { color:#a9bbb6;font:10px Consolas,monospace;letter-spacing:.04em; }
.flow-step strong { color:#e2efeb;font-weight:500; }
.flow-arrow { color:#52766c;font-size:12px; }
.change-card {
  background:linear-gradient(135deg,rgba(19,31,32,.98),rgba(14,23,25,.98));
  border:1px solid var(--line);border-left:3px solid #78948d;border-radius:14px;
  padding:17px 19px;margin:10px 0 12px;box-shadow:0 9px 24px rgba(0,0,0,.12);
}
.change-card.breaking { border-left-color:#ff876f; }
.change-card.safe { border-left-color:#70d7ad; }
.change-top { display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:11px; }
.change-kind { color:#dbe9e5;font-size:14px;font-weight:700; }
.change-badge { border-radius:999px;padding:5px 8px;font:9px Consolas,monospace;letter-spacing:.09em;text-transform:uppercase;white-space:nowrap; }
.badge-break { color:#ffb1a3;background:rgba(255,110,93,.1);border:1px solid rgba(255,110,93,.2); }
.badge-safe { color:#a8f0d2;background:rgba(105,215,170,.08);border:1px solid rgba(105,215,170,.19); }
.change-route { color:#95aea7;font:11px Consolas,monospace;overflow-wrap:anywhere; }
.change-field { color:#e7f4ef;font:12px Consolas,monospace;margin:8px 0; }
.change-message { color:#a5b7b1;font-size:12px;line-height:1.6; }
.change-detail { display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:13px; }
.detail-cell { border:1px solid rgba(176,211,201,.09);background:rgba(6,13,14,.25);border-radius:10px;padding:10px 12px; }
.detail-label { color:#78918a;font:9px Consolas,monospace;letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px; }
.detail-value { color:#d5e2dd;font-size:11px;line-height:1.55; }
.empty-stage { border:1px dashed rgba(156,244,212,.24);border-radius:20px;padding:26px;background:linear-gradient(140deg,rgba(23,43,39,.42),rgba(16,25,27,.55)); }
.empty-title { color:#e8f3ef;font-size:20px;font-weight:700;letter-spacing:-.04em;margin:5px 0 7px; }
.empty-copy { color:#91a7a1;font-size:12px;line-height:1.7; }
.mini-step { height:100%;border:1px solid var(--line);border-radius:13px;padding:13px;background:rgba(14,23,24,.7); }
.mini-num { color:var(--mint);font:10px Consolas,monospace; }
.mini-title { color:#e3efeb;font-size:12px;font-weight:700;margin:7px 0 4px; }
.mini-copy { color:#829a94;font-size:10px;line-height:1.5; }
.footnote { color:#708781;font:10px Consolas,monospace;letter-spacing:.03em;margin-top:28px;padding-top:13px;border-top:1px solid var(--line); }
div[data-testid="stFileUploader"] { border:1px dashed rgba(156,244,212,.2);border-radius:12px;padding:7px;background:rgba(9,16,17,.38); }
div[data-testid="stFileUploader"] section { background:transparent; }
div[data-testid="stFileUploader"] small { color:#78918a; }
div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {
  border:0;color:#081511;background:linear-gradient(110deg,#a7f3d7,#76d9b5);
  font-weight:800;box-shadow:0 8px 28px rgba(87,205,159,.14);
}
div.stButton > button, div.stDownloadButton > button { border-radius:10px; }
[data-testid="stMetric"] { background:transparent; }
[data-testid="stTabs"] button { color:#8da59e; }
[data-testid="stTabs"] button[aria-selected="true"] { color:#a5f2d5; }
@media (max-width: 700px) {
  .change-detail { grid-template-columns:1fr; }
  .topline { align-items:flex-start;flex-direction:column; }
}
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title=f"{PRODUCT_NAME} · Contract Observatory",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    _render_sidebar()
    _render_header()

    report = st.session_state.get("report")
    request_error = st.session_state.get("request_error")
    if request_error:
        st.error(request_error)

    if report is None:
        _render_empty_state()
    else:
        _render_report(report)

    st.markdown(
        '<div class="footnote">LOCAL-FIRST · SPECIFICATION CONTENT STAYS ON THIS MACHINE · '
        'AI IS OPTIONAL</div>',
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand-lockup"><div class="brand-mark">◈</div><div>'
            f'<div class="brand-name">{PRODUCT_NAME}</div>'
            '<div class="brand-sub">Contract Observatory</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown('<div class="section-kicker">01 / Intelligence lane</div>', unsafe_allow_html=True)
        analysis_lane = st.radio(
            "Choose what to review",
            ANALYSIS_LANES,
            key="analysis_lane",
            label_visibility="collapsed",
        )
        old_upload = None
        new_upload = None
        migration_upload = None
        source_uploads = []
        if analysis_lane in {"API contract", "Unified review"}:
            st.markdown('<div class="section-kicker">API contract pair</div>', unsafe_allow_html=True)
            old_upload = st.file_uploader(
                "BASELINE · older spec",
                type=["json", "yaml", "yml"],
                key="old_spec",
                help="The currently deployed OpenAPI contract.",
            )
            new_upload = st.file_uploader(
                "CANDIDATE · newer spec",
                type=["json", "yaml", "yml"],
                key="new_spec",
                help="The proposed OpenAPI contract to review.",
            )
        if analysis_lane in {"Database migration", "Unified review"}:
            st.markdown('<div class="section-kicker">Database migration</div>', unsafe_allow_html=True)
            migration_upload = st.file_uploader(
                "SQL migration script",
                type=["sql"],
                key="migration_sql",
                help="The migration whose schema and data effects you want to review.",
            )
            source_uploads = st.file_uploader(
                "Application source references · optional",
                type=sorted(suffix.removeprefix(".") for suffix in SUPPORTED_SOURCE_SUFFIXES),
                accept_multiple_files=True,
                key="migration_sources",
                help=(
                    "Upload relevant source files. The scanner reports exact token "
                    "matches as evidence; it does not infer a complete call graph."
                ),
            )

        st.markdown('<div class="section-kicker">02 / Reasoning mode</div>', unsafe_allow_html=True)
        analyze_ai = st.toggle(
            "Ask local Ollama for explanations",
            value=False,
            help=(
                "Ollama explains API or recognized migration events. "
                "It cannot change deterministic compatibility flags or migration scores."
            ),
        )
        model = st.text_input(
            "Model",
            value=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
            disabled=not analyze_ai,
            help="Only change events are sent to this local model.",
        )
        base_url = st.text_input(
            "Ollama endpoint",
            value=os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
            disabled=not analyze_ai,
        )
        if analyze_ai:
            with st.expander("Ollama not connecting?"):
                st.markdown(
                    "1. Start the Ollama desktop app, or run `ollama serve` in a "
                    "separate terminal.\n"
                    "2. In a terminal, run `ollama list` to check installed models.\n"
                    "3. If needed, run `ollama pull " + model.strip() + "`.\n"
                    "4. Keep the endpoint at `http://localhost:11434` unless you "
                    "changed Ollama's host or port."
                )
            if st.button("Test Ollama connection", use_container_width=True):
                try:
                    available_models = ensure_ollama_model_available(
                        model=model,
                        base_url=base_url,
                    )
                except AnalysisError as error:
                    st.session_state["ollama_check"] = {
                        "ok": False,
                        "message": str(error),
                        "model": model,
                        "base_url": base_url,
                    }
                else:
                    st.session_state["ollama_check"] = {
                        "ok": True,
                        "message": (
                            f"Connected. Model '{model}' is available. "
                            f"{len(available_models)} model(s) installed."
                        ),
                        "model": model,
                        "base_url": base_url,
                    }
            ollama_check = st.session_state.get("ollama_check")
            if ollama_check and (
                ollama_check.get("model") != model
                or ollama_check.get("base_url") != base_url
            ):
                st.session_state.pop("ollama_check", None)
                ollama_check = None
            if ollama_check:
                if ollama_check["ok"]:
                    st.success(ollama_check["message"])
                else:
                    st.error(ollama_check["message"])

        if st.button("Run change review", type="primary", use_container_width=True):
            spinner_message = (
                "Checking Ollama and reviewing changes. First model load may take a while…"
                if analyze_ai
                else "Reviewing schema and consumer evidence…"
            )
            with st.spinner(spinner_message):
                _run_scan(
                    analysis_lane,
                    old_upload,
                    new_upload,
                    migration_upload,
                    source_uploads,
                    analyze_ai,
                    model,
                    base_url,
                )

        st.markdown("---")
        st.markdown('<div class="section-kicker">Sandbox</div>', unsafe_allow_html=True)
        st.caption("Try the included API + database change scenario.")
        if st.button("Load unified demo", use_container_width=True):
            with st.spinner("Loading the included change-intelligence scenario…"):
                _run_demo(analysis_lane, analyze_ai, model, base_url)
        st.caption("Loads both example lanes; choose API, database, or unified review.")

        if st.session_state.get("report") is not None:
            if st.button("Clear current report", use_container_width=True):
                st.session_state.pop("report", None)
                st.session_state.pop("request_error", None)


def _render_header() -> None:
    st.markdown(
        '<div class="topline"><div class="eyebrow">CONTRACT OBSERVATORY / CHANGE INTELLIGENCE</div>'
        '<div class="status-pill"><span class="status-dot">●</span>'
        'DETERMINISTIC CORE · READY</div></div>'
        '<div class="hero-title">API Change<br><span>Risk Analyzer</span></div>'
        '<div class="hero-copy"><strong>Contract Observatory</strong> — one review surface for '
        'API contracts and database migrations. Deterministic analyzers find change evidence; '
        'optional local AI adds API impact explanations.</div>',
        unsafe_allow_html=True,
    )


def _render_empty_state() -> None:
    st.markdown('<div class="section-kicker">Your review workspace</div>', unsafe_allow_html=True)
    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown(
            '<div class="empty-stage"><div class="eyebrow">READY WHEN YOU ARE</div>'
            '<div class="empty-title">Review application and schema change together.</div>'
            '<div class="empty-copy">Choose API contract, database migration, or unified review in '
            'the left rail. Compare OpenAPI versions, scan SQL DDL, and optionally match changed '
            'identifiers against source files. Every score stays attached to its evidence.</div><br>'
            '<div class="flow-wrap"><span class="flow-step"><strong>API SPEC / SQL</strong> · change</span>'
            '<span class="flow-arrow">⟶</span><span class="flow-step"><strong>RULE ENGINE</strong> · evidence</span>'
            '<span class="flow-arrow">⟶</span><span class="flow-step"><strong>BLAST RADIUS</strong> · references</span>'
            '<span class="flow-arrow">⟶</span><span class="flow-step"><strong>REVIEW</strong> · decision</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    with right:
        steps = [
            ("01", "Choose a lane", "API contracts · SQL migrations · unified review"),
            ("02", "Trace evidence", "DDL rules and exact source identifier references"),
            ("03", "Plan rollout", "Risk score, affected files and staged guidance"),
        ]
        for number, title, copy in steps:
            st.markdown(
                f'<div class="mini-step"><div class="mini-num">{number} / STEP</div>'
                f'<div class="mini-title">{title}</div><div class="mini-copy">{copy}</div></div>',
                unsafe_allow_html=True,
            )
            st.write("")


def _run_scan(
    analysis_lane: str,
    old_upload: Any,
    new_upload: Any,
    migration_upload: Any,
    source_uploads: list[Any],
    analyze_ai: bool,
    model: str,
    base_url: str,
) -> None:
    st.session_state.pop("report", None)
    st.session_state.pop("request_error", None)
    diff: DiffResult | None = None
    migration: MigrationReport | None = None
    filenames: dict[str, str] = {}

    if analysis_lane in {"API contract", "Unified review"}:
        if old_upload is None or new_upload is None:
            st.session_state["request_error"] = (
                "Choose both a baseline and candidate OpenAPI specification."
            )
            return
        try:
            old_document = _parse_upload(old_upload)
            new_document = _parse_upload(new_upload)
            diff = compare_specs(old_document, new_document)
        except (SpecParseError, SpecDiffError) as error:
            st.session_state["request_error"] = str(error)
            return
        filenames["baseline"] = old_upload.name
        filenames["candidate"] = new_upload.name

    if analysis_lane in {"Database migration", "Unified review"}:
        if migration_upload is None:
            st.session_state["request_error"] = "Choose a SQL migration script to review."
            return
        try:
            migration_sql = _decode_upload(
                migration_upload,
                max_bytes=MAX_SPEC_BYTES,
                description="SQL migration",
            )
            source_files = _decode_source_uploads(source_uploads)
            migration = analyze_migration(migration_sql, source_files)
        except (UnicodeDecodeError, ValueError) as error:
            st.session_state["request_error"] = str(error)
            return
        filenames["migration"] = migration_upload.name
        filenames["source_files"] = [upload.name for upload in source_uploads]

    _save_report(
        analysis_lane,
        diff,
        migration,
        analyze_ai,
        model,
        base_url,
        filenames,
    )


def _run_demo(
    analysis_lane: str,
    analyze_ai: bool,
    model: str,
    base_url: str,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    st.session_state.pop("request_error", None)
    diff: DiffResult | None = None
    migration: MigrationReport | None = None
    filenames: dict[str, str] = {}
    try:
        if analysis_lane in {"API contract", "Unified review"}:
            old_path = project_root / "examples" / "api-v1.yaml"
            new_path = project_root / "examples" / "api-v2.yaml"
            old_document = parse_spec_text(
                old_path.read_text(encoding="utf-8"),
                file_name=old_path.name,
                source=str(old_path),
            )
            new_document = parse_spec_text(
                new_path.read_text(encoding="utf-8"),
                file_name=new_path.name,
                source=str(new_path),
            )
            diff = compare_specs(old_document, new_document)
            filenames.update(
                {"baseline": old_path.name, "candidate": new_path.name}
            )

        if analysis_lane in {"Database migration", "Unified review"}:
            migration_path = project_root / "examples" / "customer-migration.sql"
            source_paths = sorted(
                (project_root / "examples" / "source-snapshot").glob("*")
            )
            migration_sql = migration_path.read_text(encoding="utf-8")
            source_files = [
                (path.name, path.read_text(encoding="utf-8"))
                for path in source_paths
                if path.is_file()
            ]
            migration = analyze_migration(migration_sql, source_files)
            filenames["migration"] = migration_path.name
            filenames["source_files"] = [name for name, _ in source_files]
    except (OSError, SpecParseError, SpecDiffError, ValueError) as error:
        st.session_state.pop("report", None)
        st.session_state["request_error"] = (
            f"Could not load the included change-intelligence demo: {error}"
        )
        return
    _save_report(
        analysis_lane,
        diff,
        migration,
        analyze_ai,
        model,
        base_url,
        filenames,
    )


def _save_report(
    analysis_lane: str,
    diff: DiffResult | None,
    migration: MigrationReport | None,
    analyze_ai: bool,
    model: str,
    base_url: str,
    filenames: dict[str, Any],
) -> None:
    report: dict[str, Any] = {
        "analysis_lane": analysis_lane,
        "changes": diff.model_dump(mode="json")["changes"] if diff else [],
        "analysis": None,
        "migration": migration.model_dump(mode="json") if migration else None,
        "files": filenames,
    }
    ollama_error: str | None = None
    has_ai_events = bool(
        (diff and diff.changes) or (migration and migration.findings)
    )
    if analyze_ai and has_ai_events:
        try:
            ensure_ollama_model_available(model=model, base_url=base_url)
        except AnalysisError as error:
            ollama_error = str(error)

    if analyze_ai and ollama_error:
        report["ollama_error"] = ollama_error
    elif analyze_ai and diff is not None and diff.changes:
        try:
            analysis = analyze_changes(diff, model=model, base_url=base_url)
        except AnalysisError as error:
            report["ollama_error"] = str(error)
        else:
            report["analysis"] = analysis.model_dump(mode="json")

    if (
        analyze_ai
        and "ollama_error" not in report
        and migration is not None
        and migration.findings
    ):
        try:
            migration_analysis = analyze_migration_changes(
                migration,
                model=model,
                base_url=base_url,
            )
        except AnalysisError as error:
            report["ollama_error"] = str(error)
        else:
            report["migration_analysis"] = migration_analysis.model_dump(mode="json")
    st.session_state["report"] = report


def _decode_upload(upload: Any, max_bytes: int, description: str) -> str:
    content = upload.getvalue()
    if len(content) > max_bytes:
        raise ValueError(
            f"'{upload.name}' exceeds the {max_bytes // (1024 * 1024)} MiB limit."
        )
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"{description} '{upload.name}' must be UTF-8 encoded."
        ) from error


def _decode_source_uploads(source_uploads: list[Any]) -> list[tuple[str, str]]:
    decoded: list[tuple[str, str]] = []
    total_size = 0
    for upload in source_uploads:
        suffix = Path(upload.name).suffix.lower()
        if suffix not in SUPPORTED_SOURCE_SUFFIXES:
            raise ValueError(f"Unsupported source file type: '{upload.name}'.")
        content = upload.getvalue()
        if len(content) > MAX_SOURCE_FILE_BYTES:
            raise ValueError(
                f"Source file '{upload.name}' exceeds the "
                f"{MAX_SOURCE_FILE_BYTES // (1024 * 1024)} MiB per-file limit."
            )
        total_size += len(content)
        if total_size > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError(
                f"Source files exceed the "
                f"{MAX_SOURCE_TOTAL_BYTES // (1024 * 1024)} MiB total limit."
            )
        try:
            decoded.append((Path(upload.name).name, content.decode("utf-8-sig")))
        except UnicodeDecodeError as error:
            raise ValueError(
                f"Source file '{upload.name}' must be UTF-8 encoded."
            ) from error
    return decoded


def _parse_upload(upload: Any) -> dict[str, Any]:
    if upload.size > MAX_SPEC_BYTES:
        raise SpecParseError(
            f"'{upload.name}' exceeds the {MAX_SPEC_BYTES // (1024 * 1024)} MiB limit."
        )
    try:
        text = upload.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SpecParseError(
            f"OpenAPI document '{upload.name}' must be UTF-8 encoded."
        ) from error
    return parse_spec_text(text, file_name=upload.name)


def _render_report(report: dict[str, Any]) -> None:
    changes = [Change.model_validate(change) for change in report["changes"]]
    analysis_payload = report.get("analysis")
    analysis = (
        RiskAnalysis.model_validate(analysis_payload)
        if analysis_payload is not None
        else None
    )
    assessments = (
        {assessment.change_index: assessment for assessment in analysis.assessments}
        if analysis is not None
        else {}
    )
    migration_payload = report.get("migration")
    migration = (
        MigrationReport.model_validate(migration_payload)
        if migration_payload is not None
        else None
    )
    migration_analysis_payload = report.get("migration_analysis")
    migration_analysis = (
        RiskAnalysis.model_validate(migration_analysis_payload)
        if migration_analysis_payload is not None
        else None
    )
    migration_assessments = (
        {
            assessment.change_index: assessment
            for assessment in migration_analysis.assessments
        }
        if migration_analysis is not None
        else {}
    )

    if report.get("ollama_error"):
        st.warning(
            f"Local Ollama analysis unavailable: {report['ollama_error']} "
            "The deterministic results below are still complete."
        )
    if report.get("analysis_error"):
        st.warning(
            f"Local AI analysis unavailable: {report['analysis_error']} "
            "The deterministic scan remains available."
        )
    if report.get("migration_analysis_error"):
        st.warning(
            f"Local migration explanation unavailable: "
            f"{report['migration_analysis_error']} "
            "The deterministic SQL findings and score remain available."
        )
    if changes:
        _render_scan_summary(changes, assessments, report.get("files", {}), analysis)
    if migration is not None:
        _render_migration_summary(
            migration,
            report.get("files", {}),
            migration_analysis,
        )

    tab_names = []
    tab_keys = []
    if report.get("analysis_lane") in {"API contract", "Unified review"}:
        tab_names.append("◈  API contract evidence")
        tab_keys.append("api")
    if migration is not None:
        tab_names.append("▤  Migration blast radius")
        tab_keys.append("migration")
    if report.get("analysis_lane") in {"API contract", "Unified review"}:
        tab_names.append("✳  API reasoning")
        tab_keys.append("reasoning")
    tab_names.append("{ }  JSON evidence")
    tab_keys.append("json")

    for key, tab in zip(tab_keys, st.tabs(tab_names)):
        with tab:
            if key == "api":
                _render_change_ledger(changes, assessments)
            elif key == "migration" and migration is not None:
                _render_migration_evidence(migration, migration_assessments)
            elif key == "reasoning":
                _render_reasoning(analysis, assessments)
            elif key == "json":
                _render_evidence(report)


def _render_migration_summary(
    migration: MigrationReport,
    files: dict[str, Any],
    analysis: RiskAnalysis | None = None,
) -> None:
    score_color = {
        RiskSeverity.LOW: "#a5f2d5",
        RiskSeverity.MEDIUM: "#ffd37d",
        RiskSeverity.HIGH: "#ffad72",
        RiskSeverity.CRITICAL: "#ff827d",
    }[RiskSeverity(migration.severity.value)]
    hold = migration.breaking or migration.human_review_required
    gate_class = "hold" if hold else ""
    gate_state = "HOLD FOR REVIEW" if hold else "CLEAR TO REVIEW"
    gate_note = (
        f"{len(migration.findings)} recognized DDL event(s); "
        f"{len(migration.references)} matching source file(s); "
        f"{len(migration.unsupported_statements)} statement(s) need manual attention."
    )
    st.markdown(
        '<div class="section-kicker">Database migration / deterministic risk model</div>'
        f'<div class="gate-card {gate_class}"><div>'
        '<div class="gate-title">Migration risk score</div>'
        f'<div class="gate-state" style="color:{score_color}">'
        f'{migration.risk_score} / 100 · {migration.severity.value}</div>'
        f'<div class="gate-note">{html.escape(gate_note)}</div></div>'
        f'<div class="fingerprint">MIGRATION · '
        f'{html.escape(str(files.get("migration", "SQL script")))}</div></div>',
        unsafe_allow_html=True,
    )
    st.progress(migration.risk_score, text=f"{migration.risk_score}% modeled risk")
    st.markdown(f"**Compatibility gate:** {gate_state}")
    columns = st.columns(4)
    components = [
        ("Schema risk", migration.breakdown.schema_risk, 35),
        ("Dependency risk", migration.breakdown.dependency_risk, 30),
        ("API exposure", migration.breakdown.api_risk, 20),
        ("Data-loss risk", migration.breakdown.data_loss_risk, 15),
    ]
    for column, (label, score, maximum) in zip(columns, components):
        with column:
            st.metric(label, f"{score} / {maximum}")
            st.progress(score / maximum if maximum else 0)
    st.caption(
        "Score is a deterministic heuristic from recognized DDL, exact token matches "
        "in uploaded source files, and destructive operations. It is not a production-safety guarantee."
    )
    if files.get("source_files") == []:
        st.info("No source files were supplied; dependency and API exposure scores are zero.")
    if analysis is not None:
        review_required = sum(
            assessment.human_review_required
            for assessment in analysis.assessments
        )
        st.caption(
            f"Local explanation model: {analysis.model} · "
            f"{review_required} finding(s) marked for human review."
        )


def _render_migration_evidence(
    migration: MigrationReport,
    assessments: dict[int, ChangeAssessment],
) -> None:
    if migration.findings:
        st.markdown("#### Deterministic SQL findings")
        for index, finding in enumerate(migration.findings):
            assessment = assessments.get(index)
            severity = "BREAKING" if finding.breaking else "REVIEW"
            title = finding.operation.replace("_", " ").upper()
            target = ".".join(
                part for part in (finding.table, finding.column) if part
            ) or finding.table or "schema"
            st.markdown(
                f'<article class="change-card {"breaking" if finding.breaking else "safe"}">'
                f'<div class="change-top"><div class="change-kind">'
                f'{html.escape(title)} · line {finding.line}</div>'
                f'<span class="change-badge {"badge-break" if finding.breaking else "badge-safe"}">'
                f'{severity} · {finding.risk_points} BASE POINTS</span></div>'
                f'<div class="change-route">{html.escape(target)}</div>'
                f'<div class="change-message">{html.escape(finding.reason)}</div>'
                f'<div class="detail-cell"><div class="detail-label">SAFER NEXT STEP</div>'
                f'<div class="detail-value">{html.escape(finding.recommendation)}</div></div>'
                f'{_assessment_detail_html(assessment)}</article>',
                unsafe_allow_html=True,
            )
    else:
        st.success("No supported schema DDL changes were recognized.")

    st.markdown("#### Source blast-radius evidence")
    st.caption(
        "These are exact identifier matches in uploaded files, classified from filename "
        "and common framework markers—not a semantic call graph."
    )
    if migration.references:
        for reference in migration.references:
            categories = " · ".join(reference.categories)
            st.markdown(
                f'<div class="flow-wrap"><span class="flow-step"><strong>'
                f'{html.escape(categories)}</strong></span><span class="flow-arrow">→</span>'
                f'<span class="flow-step"><strong>{html.escape(reference.file)}</strong>'
                f' : {reference.line}</span><span class="flow-arrow">→</span>'
                f'<span class="flow-step">identifier match: '
                f'{html.escape(", ".join(reference.identifiers))}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No matching source references were supplied or detected.")

    st.markdown("#### Expand → migrate → contract playbook")
    st.warning(
        "Guidance only—not executable SQL. Confirm database dialect, data volume, "
        "locks, backups and production usage with your team."
    )
    playbook = _migration_playbook(migration)
    for index, step in enumerate(playbook, start=1):
        st.markdown(f"**{index}. {step[0]}**  \n{step[1]}")

    if migration.recommendations:
        with st.expander("All deterministic recommendations"):
            for recommendation in migration.recommendations:
                st.markdown(f"- {recommendation}")
    if migration.unsupported_statements:
        with st.expander(
            f"Unsupported / unmodeled statements ({len(migration.unsupported_statements)})"
        ):
            for statement in migration.unsupported_statements:
                st.code(
                    f"Line {statement.line}: {statement.statement}\n"
                    f"Review: {statement.reason}",
                    language="sql",
                )


def _assessment_detail_html(
    assessment: ChangeAssessment | None,
) -> str:
    if assessment is None:
        return ""
    details = [
        ("LOCAL AI · WHY", assessment.reason),
        (
            "POTENTIAL CONSUMERS",
            ", ".join(assessment.affected_consumers) or "Not specified",
        ),
        (
            "AI CONFIDENCE",
            f"{assessment.confidence:.0%} · "
            f"{_certainty_label(assessment.confidence)} certainty",
        ),
    ]
    rendered = "".join(
        '<div class="detail-cell"><div class="detail-label">'
        f"{html.escape(label)}</div><div class=\"detail-value\">"
        f"{html.escape(value)}</div></div>"
        for label, value in details
    )
    return f'<div class="change-detail">{rendered}</div>'


def _migration_playbook(
    migration: MigrationReport,
) -> list[tuple[str, str]]:
    operations = {finding.operation for finding in migration.findings}
    if operations & {
        "column_dropped",
        "column_renamed",
        "column_type_changed",
        "table_dropped",
        "table_renamed",
        "not_null_added",
    }:
        return [
            (
                "Inventory consumers",
                "Use the reference list as a starting point; confirm runtime queries, scheduled jobs, reports, and external consumers too.",
            ),
            (
                "Expand compatibly",
                "Add the replacement schema without removing the old contract. Deploy code that can tolerate both versions.",
            ),
            (
                "Backfill and migrate traffic",
                "Backfill in bounded batches, validate values, then move reads and writes while monitoring errors and query performance.",
            ),
            (
                "Contract later",
                "Only after production usage confirms the old contract is unused, remove or tighten it in a separate reviewed migration.",
            ),
        ]
    if "unique_added" in operations or "foreign_key_added" in operations:
        return [
            (
                "Preflight existing rows",
                "Find duplicates or orphaned references before the constraint migration.",
            ),
            (
                "Repair and validate",
                "Resolve invalid rows, deploy compatible application checks, then add the constraint.",
            ),
            (
                "Monitor enforcement",
                "Observe rejected writes and constraint validation time after deployment.",
            ),
        ]
    return [
        (
            "Review the change",
            "Confirm the SQL dialect, migration lock behavior, backups, and affected query plans.",
        ),
        (
            "Deploy and observe",
            "Apply in staging first, then monitor application errors and database performance.",
        ),
    ]


def _render_scan_summary(
    changes: list[Change],
    assessments: dict[int, ChangeAssessment],
    files: dict[str, str],
    analysis: RiskAnalysis | None,
) -> None:
    st.markdown('<div class="section-kicker">Scan result / evidence first</div>', unsafe_allow_html=True)
    breaking_count = sum(change.breaking for change in changes)
    safe_count = len(changes) - breaking_count
    review_count = sum(
        assessment.human_review_required for assessment in assessments.values()
    )
    elevated_risk_count = sum(
        assessment.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL}
        for assessment in assessments.values()
    )
    _render_release_gate(changes, breaking_count)
    cards = [
        ("EVENTS FOUND", str(len(changes)), "Deterministic contract deltas"),
        ("BREAKING", str(breaking_count), "Compatibility review required"),
        ("ADDITIVE", str(safe_count), "Not marked breaking by the detector"),
        (
            "REVIEW QUEUE",
            str(review_count if analysis is not None else "—"),
            "Low confidence or model-requested review",
        ),
    ]
    columns = st.columns(4)
    for column, (label, value, note) in zip(columns, cards):
        with column:
            st.markdown(
                f'<div class="stat-card"><div class="stat-label">{label}</div>'
                f'<div class="stat-value">{value}</div><div class="stat-note">{note}</div></div>',
                unsafe_allow_html=True,
            )

    baseline = html.escape(files.get("baseline", "baseline"))
    candidate = html.escape(files.get("candidate", "candidate"))
    ai_stage = (
        f"LOCAL REASONING · {html.escape(analysis.model)}"
        if analysis is not None
        else "REASONING · optional"
    )
    st.markdown(
        '<div class="flow-wrap">'
        f'<span class="flow-step"><strong>{baseline}</strong></span>'
        '<span class="flow-arrow">⟶</span><span class="flow-step">compare</span>'
        '<span class="flow-arrow">⟶</span><span class="flow-step"><strong>'
        f'{candidate}</strong></span><span class="flow-arrow">⟶</span>'
        '<span class="flow-step"><strong>'
        f'{len(changes)} EVIDENCE EVENTS</strong></span><span class="flow-arrow">⟶</span>'
        f'<span class="flow-step"><strong>{ai_stage}</strong></span></div>',
        unsafe_allow_html=True,
    )
    if analysis is not None and elevated_risk_count:
        st.info(
            f"AI marked {elevated_risk_count} change(s) as high or critical risk. "
            "Severity is advisory; the deterministic `breaking` flag remains the compatibility signal."
        )
    if not changes:
        st.success("The detector found no supported contract changes in this pair.")


def _render_release_gate(changes: list[Change], breaking_count: int) -> None:
    gate_class = "hold" if breaking_count else ""
    state = "HOLD FOR REVIEW" if breaking_count else "CLEAR TO REVIEW"
    color = "#ffad9d" if breaking_count else "#a5f2d5"
    note = (
        f"{breaking_count} deterministic breaking signal(s) need a compatibility decision."
        if breaking_count
        else "No detected breaking signals. Confirm supported scope before release."
    )
    st.markdown(
        f'<div class="gate-card {gate_class}"><div>'
        '<div class="gate-title">Deterministic compatibility gate</div>'
        f'<div class="gate-state" style="color:{color}">{state}</div>'
        f'<div class="gate-note">{note}</div></div>'
        f'<div class="fingerprint">{_fingerprint_bar(changes)}</div></div>',
        unsafe_allow_html=True,
    )


def _fingerprint_bar(changes: list[Change]) -> str:
    groups = [
        (
            "REMOVED",
            "fingerprint-removed",
            sum(
                change.change_type.value in {"endpoint_removed", "field_removed"}
                for change in changes
            ),
        ),
        (
            "REQUIRED",
            "fingerprint-required",
            sum(
                change.change_type.value
                in {"required_field_added", "parameter_required"}
                for change in changes
            ),
        ),
        (
            "RE-TYPED",
            "fingerprint-type",
            sum(change.change_type.value == "field_type_changed" for change in changes),
        ),
        (
            "ADDED",
            "fingerprint-added",
            sum(
                change.change_type.value in {"endpoint_added", "field_added"}
                for change in changes
            ),
        ),
    ]
    event_count = len(changes)
    segments = "".join(
        f'<span class="{css_class}" style="width:{count / event_count * 100:.2f}%"></span>'
        for _, css_class, count in groups
        if count
    ) if event_count else ""
    if not event_count:
        segments = '<span class="fingerprint-added" style="width:100%;opacity:.28"></span>'
    labels = " · ".join(f"{label} {count}" for label, _, count in groups if count)
    return (
        f'<div class="fingerprint-bar">{segments}</div>'
        f'<div class="fingerprint-label"><span>CHANGE FINGERPRINT</span>'
        f'<span>{html.escape(labels or "NO DELTAS")}</span></div>'
    )


def _render_change_ledger(
    changes: list[Change],
    assessments: dict[int, ChangeAssessment],
) -> None:
    if not changes:
        st.markdown(
            '<div class="empty-stage"><div class="empty-title">No events in the ledger.</div>'
            '<div class="empty-copy">No supported endpoint or schema changes were detected.</div></div>',
            unsafe_allow_html=True,
        )
        return

    filter_choice = st.radio(
        "Filter the change ledger",
        ["All events", "Breaking only", "Additive only"],
        horizontal=True,
        label_visibility="collapsed",
        key="change_filter",
    )
    st.caption("Each card links the compatibility signal back to the exact operation and field.")
    visible_count = 0
    for index, change in enumerate(changes):
        if filter_choice == "Breaking only" and not change.breaking:
            continue
        if filter_choice == "Additive only" and change.breaking:
            continue
        visible_count += 1
        _render_change(change, assessments.get(index))
    if visible_count == 0:
        st.caption("No changes match this filter.")


def _render_change(change: Change, assessment: ChangeAssessment | None) -> None:
    breaking = change.breaking
    variant = "breaking" if breaking else "safe"
    badge_class = "badge-break" if breaking else "badge-safe"
    label = "BREAKING CONTRACT CHANGE" if breaking else "ADDITIVE / NOT MARKED BREAKING"
    title = change.change_type.value.replace("_", " ").upper()
    method = change.method.upper() if change.method else "SCHEMA"
    route = f"{method}  {change.path}"
    if assessment is not None:
        severity = assessment.severity
        label = (
            "REVIEW REQUIRED"
            if assessment.human_review_required
            else f"{severity.value} RISK · {label}"
        )
        icon = SEVERITY_ICONS[severity]
    else:
        icon = "⛔" if breaking else "＋"

    field_html = (
        f'<div class="change-field">FIELD&nbsp;&nbsp; {html.escape(change.field)}</div>'
        if change.field
        else ""
    )
    content = (
        f'<article class="change-card {variant}"><div class="change-top">'
        f'<div class="change-kind">{icon}&nbsp; {html.escape(title)}</div>'
        f'<span class="change-badge {badge_class}">{html.escape(label)}</span></div>'
        f'<div class="change-route">{html.escape(route)}</div>{field_html}'
        f'<div class="change-message">{html.escape(change.message)}</div>'
    )
    if assessment is not None:
        consumers = ", ".join(assessment.affected_consumers) or "Not specified"
        details = [
            ("WHY IT MATTERS", assessment.reason),
            ("POTENTIAL CONSUMERS", consumers),
            ("RECOMMENDED ACTION", assessment.recommended_action),
            (
                "MODEL CONFIDENCE",
                f"{assessment.confidence:.0%} · "
                f"{_certainty_label(assessment.confidence)} certainty",
            ),
        ]
        details_html = "".join(
            '<div class="detail-cell"><div class="detail-label">'
            f"{html.escape(label)}</div><div class=\"detail-value\">"
            f"{html.escape(value)}</div></div>"
            for label, value in details
        )
        content += f'<div class="change-detail">{details_html}</div>'
    elif change.old_value is not None or change.new_value is not None:
        before = html.escape(str(change.old_value))
        after = html.escape(str(change.new_value))
        content += (
            '<div class="change-detail"><div class="detail-cell"><div class="detail-label">'
            'BEFORE</div><div class="detail-value">'
            f"{before}</div></div><div class=\"detail-cell\"><div class=\"detail-label\">"
            f"AFTER</div><div class=\"detail-value\">{after}</div></div></div>"
        )
    content += "</article>"
    st.markdown(content, unsafe_allow_html=True)


def _render_reasoning(
    analysis: RiskAnalysis | None,
    assessments: dict[int, ChangeAssessment],
) -> None:
    if analysis is None:
        st.markdown(
            '<div class="empty-stage"><div class="eyebrow">NO MODEL REQUIRED</div>'
            '<div class="empty-title">The evidence is still useful without AI.</div>'
            '<div class="empty-copy">Enable “Ask local Ollama” before scanning to add '
            'impact explanations, recommendations, confidence scores and human-review flags. '
            'The deterministic change ledger remains the source of truth.</div></div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"Assessments generated by **`{html.escape(analysis.model)}`**. "
        "Compare every explanation with its deterministic event before acting."
    )
    if not assessments:
        st.caption("No change events required AI assessment.")
    for index in sorted(assessments):
        assessment = assessments[index]
        icon = SEVERITY_ICONS[assessment.severity]
        st.markdown(
            f"{icon} **{assessment.severity.value}** · change #{index + 1} · "
            f"confidence {assessment.confidence:.0%} · "
            f"{'human review required' if assessment.human_review_required else 'no review flag'}"
        )
        st.write(assessment.reason)


def _render_evidence(report: dict[str, Any]) -> None:
    st.caption(
        "This is the auditable payload produced by the comparison pipeline. "
        "AI descriptions are kept separate from the deterministic change events."
    )
    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    st.code(report_json, language="json", line_numbers=True)
    st.download_button(
        "Download scan evidence",
        data=report_json,
        file_name="api-change-risk-report.json",
        mime="application/json",
        use_container_width=True,
    )


def _certainty_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "HIGH"
    if confidence >= 0.6:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    main()
