from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .logic import CalmSendEngine, load_settings, save_settings, train_and_persist_model
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    IntegrationDescriptor,
    SettingsResponse,
)

app = FastAPI(title="CalmSend API", version="1.0.0")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
engine = CalmSendEngine()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    result = engine.analyze(
        request.message,
        request.recipient,
        request.source_app,
        request.content_type,
        request.delay_mode,
    )
    return AnalyzeResponse(**result.__dict__)


@app.get("/api/integrations", response_model=list[IntegrationDescriptor])
def integrations() -> list[IntegrationDescriptor]:
    return [IntegrationDescriptor(**item) for item in engine.supported_integrations()]


@app.get("/api/settings", response_model=SettingsResponse)
def settings() -> SettingsResponse:
    return SettingsResponse(**load_settings())


@app.put("/api/settings", response_model=SettingsResponse)
def update_settings(settings: SettingsResponse) -> SettingsResponse:
    return SettingsResponse(**save_settings(settings.model_dump()))


@app.post("/api/train")
def train() -> dict:
    metrics = train_and_persist_model()
    global engine
    engine = CalmSendEngine()
    return metrics


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")


    @app.get("/{path:path}")
    def frontend_fallback(path: str) -> FileResponse:
        requested = FRONTEND_DIST / path
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
