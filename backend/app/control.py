"""Internal control API for the collector process (never exposed to browsers).

Receives one-time codes / 2FA passwords / disconnect requests from the API
process over the private docker network. Codes and passwords live in memory only.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import settings
from .models import TelegramStatus
from .services import collector_state

CONTROL_TOKEN_HEADER = "X-Control-Token"


class InitializeBody(BaseModel):
    api_id: str
    api_hash: str


class PhoneBody(BaseModel):
    phone: str


class CodeBody(BaseModel):
    code: str


class PasswordBody(BaseModel):
    password: str


class SimMessageBody(BaseModel):
    chat_id: int
    text: str | None = None


def _check_token(x_control_token: str | None = Header(default=None)) -> None:
    if not x_control_token or x_control_token != settings.collector_control_token:
        raise HTTPException(status_code=401, detail="invalid control token")


def create_control_app() -> FastAPI:
    app = FastAPI(title="Telemonitor collector control", docs_url=None, redoc_url=None, openapi_url=None)

    def service():
        svc = collector_state.get_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="collector service not ready")
        return svc

    @app.post("/control/initialize", dependencies=[Depends(_check_token)])
    async def control_initialize(body: InitializeBody, svc=Depends(service)):
        return await svc.initialize(body.api_id, body.api_hash)

    @app.post("/control/phone", dependencies=[Depends(_check_token)])
    async def control_phone(body: PhoneBody, svc=Depends(service)):
        return await svc.submit_phone(body.phone)

    @app.post("/control/code", dependencies=[Depends(_check_token)])
    async def control_code(body: CodeBody, svc=Depends(service)):
        return await svc.submit_code(body.code)

    @app.post("/control/password", dependencies=[Depends(_check_token)])
    async def control_password(body: PasswordBody, svc=Depends(service)):
        return await svc.submit_password(body.password)

    @app.post("/control/disconnect", dependencies=[Depends(_check_token)])
    async def control_disconnect(svc=Depends(service)):
        return await svc.disconnect()

    @app.get("/control/status", dependencies=[Depends(_check_token)])
    async def control_status(svc=Depends(service)):
        return svc.status()

    @app.get("/control/dialogs", dependencies=[Depends(_check_token)])
    async def control_dialogs(svc=Depends(service)):
        st = svc.status()
        if st.get("state") != TelegramStatus.AUTHORIZED:
            raise HTTPException(status_code=409, detail="Telegram account is not authorized")
        return await svc.get_dialogs()

    @app.post("/control/sim/message", dependencies=[Depends(_check_token)])
    async def control_sim_message(body: SimMessageBody, svc=Depends(service)):
        if not settings.simulate_telegram:
            raise HTTPException(status_code=404, detail="simulation disabled")
        if not hasattr(svc, "inject_message"):
            raise HTTPException(status_code=404, detail="simulation disabled")
        try:
            return await svc.inject_message(body.chat_id, body.text)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/control/connect", dependencies=[Depends(_check_token)])
    async def control_connect(svc=Depends(service)):
        await svc.start()
        return svc.status()

    return app
