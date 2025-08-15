from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from services import find_protocol_by_diagnosis

app = FastAPI()

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


# Serve the Telegram WebApp static files from the built directory
app.mount("/", StaticFiles(directory="dist", html=True), name="webapp")

