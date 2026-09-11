from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hotel_assistance.api.dependencies import get_registry
from hotel_assistance.config.settings import Settings, get_settings
from hotel_assistance.domain.services.filter_registry import FilterRegistry

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = "ok"
    filters: int = 0
    retrieval_mode: str = "semantic"
    llm_configured: bool = False
    hotel_backend_configured: bool = False


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Settings = Depends(get_settings),
    registry: FilterRegistry = Depends(get_registry),
) -> HealthResponse:
    """Liveness plus the configuration facts the UI needs, never any secret."""

    return HealthResponse(
        filters=len(registry),
        retrieval_mode=settings.retrieval_mode.value,
        llm_configured=settings.has_openai_credentials(),
        hotel_backend_configured=bool(settings.hotel_backend_url),
    )
