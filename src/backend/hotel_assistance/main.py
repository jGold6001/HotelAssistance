import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

load_dotenv()

from hotel_assistance.api.chat import router as chat_router  # noqa: E402
from hotel_assistance.api.health import router as health_router  # noqa: E402
from hotel_assistance.config.settings import get_settings  # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Hotel Assistance", version="0.1.0")

app.include_router(health_router)
app.include_router(chat_router)

if FRONTEND_DIR.is_dir():
    # Mounted last so it never shadows an API route.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
