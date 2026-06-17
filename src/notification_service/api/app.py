from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..domain import InvalidVariables, NotificationError, TemplateNotFound
from ..service import NotificationService
from .dependencies import get_service, get_session
from .schemas import CreateNotificationRequest, NotificationResponse


def create_app() -> FastAPI:
    app = FastAPI(title="notification-service")

    @app.exception_handler(TemplateNotFound)
    @app.exception_handler(InvalidVariables)
    async def _domain_422(request, exc: NotificationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> JSONResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    @app.post("/notifications", response_model=NotificationResponse, status_code=201)
    def create_notification(
        payload: CreateNotificationRequest,
        service: NotificationService = Depends(get_service),
    ) -> NotificationResponse:
        notification = service.send(
            payload.channel, payload.template_key, payload.recipient, payload.variables
        )
        return NotificationResponse.from_domain(notification)

    @app.get("/notifications/{notification_id}", response_model=NotificationResponse)
    def get_notification(
        notification_id: UUID,
        service: NotificationService = Depends(get_service),
    ) -> NotificationResponse:
        notification = service.get(notification_id)
        if notification is None:
            raise HTTPException(status_code=404, detail="notification not found")
        return NotificationResponse.from_domain(notification)

    return app


app = create_app()
