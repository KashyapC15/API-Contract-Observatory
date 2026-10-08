"""FastAPI endpoint for comparing uploaded OpenAPI specifications."""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from app.analyzer import AnalysisError, analyze_changes
from app.config import MAX_SPEC_BYTES
from app.db_migration import (
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_TOTAL_BYTES,
    SUPPORTED_SOURCE_SUFFIXES,
    MigrationReport,
    analyze_migration,
)
from app.differ import SpecDiffError, compare_specs
from app.models import Change, RiskAnalysis
from app.parser import SpecParseError, parse_spec_text

SUPPORTED_SUFFIXES = {".json", ".yaml", ".yml"}
CONTENT_TYPE_SUFFIXES = {
    "application/json": ".json",
    "application/yaml": ".yaml",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "text/x-yaml": ".yaml",
}


class CompareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Change]
    analysis: RiskAnalysis | None = None


app = FastAPI(
    title="Contract Observatory",
    description=(
        "Deterministic API contract and database migration risk analysis, "
        "with optional local AI reasoning for API changes."
    ),
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/compare", response_model=CompareResponse)
async def compare_openapi_specs(
    old_spec: UploadFile = File(...),
    new_spec: UploadFile = File(...),
    analyze_ai: bool = Form(False),
    model: str | None = Form(None),
) -> CompareResponse:
    try:
        old_document = await _read_spec_upload(old_spec)
        new_document = await _read_spec_upload(new_spec)
        diff = compare_specs(old_document, new_document)
    except SpecParseError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SpecDiffError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    analysis = None
    if analyze_ai:
        try:
            analysis = analyze_changes(diff, model=model)
        except AnalysisError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    return CompareResponse(changes=diff.changes, analysis=analysis)


@app.post("/analyze-migration", response_model=MigrationReport)
async def analyze_sql_migration(
    migration: UploadFile = File(...),
    source_files: list[UploadFile] | None = File(None),
) -> MigrationReport:
    migration_name = migration.filename or "migration.sql"
    migration_suffix = PurePosixPath(
        migration_name.replace("\\", "/")
    ).suffix.lower()
    if migration_suffix != ".sql":
        raise HTTPException(status_code=415, detail="Upload a .sql migration file.")

    sql_bytes = await migration.read(MAX_SPEC_BYTES + 1)
    if len(sql_bytes) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=413, detail="SQL migration exceeds the 5 MiB limit.")
    try:
        sql_text = sql_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422, detail="SQL migration must be UTF-8 encoded."
        ) from error

    decoded_sources: list[tuple[str, str]] = []
    source_total_bytes = 0
    for source in source_files or []:
        source_name = source.filename or ""
        suffix = PurePosixPath(source_name.replace("\\", "/")).suffix.lower()
        if suffix not in SUPPORTED_SOURCE_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported application source file type: '{source_name}'.",
            )
        contents = await source.read(MAX_SOURCE_FILE_BYTES + 1)
        if len(contents) > MAX_SOURCE_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Source file '{source_name}' exceeds the 2 MiB limit.",
            )
        source_total_bytes += len(contents)
        if source_total_bytes > MAX_SOURCE_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Uploaded application source files exceed the 10 MiB total limit.",
            )
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(
                status_code=422,
                detail=f"Application source file '{source_name}' must be UTF-8 encoded.",
            ) from error
        safe_name = PurePosixPath(source_name.replace("\\", "/")).name
        decoded_sources.append((safe_name, text))

    try:
        return analyze_migration(sql_text, decoded_sources)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _read_spec_upload(upload: UploadFile) -> dict[str, Any]:
    contents = await upload.read(MAX_SPEC_BYTES + 1)
    file_name = upload.filename or ""
    suffix = _filename_suffix(file_name)

    if len(contents) > MAX_SPEC_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"'{file_name or 'Uploaded specification'}' exceeds the 5 MiB limit.",
        )
    if suffix not in SUPPORTED_SUFFIXES:
        media_type = (upload.content_type or "").split(";", maxsplit=1)[0].lower()
        suffix = CONTENT_TYPE_SUFFIXES.get(media_type, "")
        file_name = f"uploaded-spec{suffix}"
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Upload a JSON, YAML, or YML OpenAPI specification.",
        )
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=422, detail="OpenAPI specifications must be UTF-8 encoded."
        ) from error
    return parse_spec_text(text, file_name=file_name)


def _filename_suffix(file_name: str) -> str:
    posix_suffix = PurePosixPath(file_name.replace("\\", "/")).suffix.lower()
    windows_suffix = PureWindowsPath(file_name).suffix.lower()
    if posix_suffix in SUPPORTED_SUFFIXES:
        return posix_suffix
    return windows_suffix
