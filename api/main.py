from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.analyzer import analyze_changes
from api.differ import compare_specs
from api.models import AnalyzeResponse
from api.parser import parse_openapi

app = FastAPI(title="API Change Guard", version="0.1.0")


class AnalyzeRequest(BaseModel):
    api_v1: str = Field(min_length=1)
    api_v2: str = Field(min_length=1)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_api_changes(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        old_spec = parse_openapi(request.api_v1)
        new_spec = parse_openapi(request.api_v2)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    changes = compare_specs(old_spec, new_spec)
    try:
        risk_report = analyze_changes(changes)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AnalyzeResponse(changes=changes, risk_report=risk_report)
