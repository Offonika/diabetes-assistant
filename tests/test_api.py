import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from fastapi.testclient import TestClient

from api import ai_diagnose, DiagnoseRequest, DiagnoseResponse, app

@pytest.mark.asyncio
async def test_ai_diagnose_with_protocol():
    result = await ai_diagnose(DiagnoseRequest(diagnosis="диабет 2 типа"))
    assert isinstance(result.protocol, str)
    assert result.protocol == "standard protocol"

@pytest.mark.asyncio
async def test_ai_diagnose_unknown_diagnosis_returns_404():
    with pytest.raises(HTTPException) as exc_info:
        await ai_diagnose(DiagnoseRequest(diagnosis="unknown"))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Protocol not found"


def test_diagnose_response_requires_protocol():
    with pytest.raises(ValidationError):
        DiagnoseResponse(protocol=None)


def test_webapp_served_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Diabetes Assistant WebApp" in response.text

