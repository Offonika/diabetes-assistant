from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from services import find_protocol_by_diagnosis

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

class DiagnoseRequest(BaseModel):
    diagnosis: str

class DiagnoseResponse(BaseModel):
    protocol: str

@app.post("/v1/ai/diagnose", response_model=DiagnoseResponse)
async def ai_diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
    protocol = find_protocol_by_diagnosis(req.diagnosis)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return DiagnoseResponse(protocol=protocol)


# Serve the Telegram WebApp static files from the built directory when available.
# Fall back to the source directory in development environments.
dist_dir = BASE_DIR / "dist"
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="webapp")
else:
    app.mount("/", StaticFiles(directory=BASE_DIR / "webapp", html=True), name="webapp")

