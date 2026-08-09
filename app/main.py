import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_context
from app.services.exceptions import AppError

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "B2B-сервис приёма заказов от клиентских систем и надёжной передачи внешнему поставщику."
    ),
    openapi_tags=[
        {"name": "Система", "description": "Проверка состояния приложения и базы данных."},
        {"name": "Заказы", "description": "Создание, просмотр и отмена заказов клиента."},
        {
            "name": "Webhook поставщика",
            "description": "Приём подписанных событий о смене статуса заказа.",
        },
        {
            "name": "Администрирование",
            "description": "Диагностика попыток передачи заказов поставщику.",
        },
    ],
)
app.include_router(router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(token)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id_context.get(),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_failed",
                "message": "Запрос не прошёл проверку",
                "details": {"errors": jsonable_encoder(exc.errors())},
                "request_id": request_id_context.get(),
            }
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка приложения")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Произошла непредвиденная ошибка",
                "details": {},
                "request_id": request_id_context.get(),
            }
        },
    )
