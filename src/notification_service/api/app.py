from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .dependencies import get_session


def create_app() -> FastAPI:
    app = FastAPI(title="notification-service")

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> JSONResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    return app


app = create_app()
