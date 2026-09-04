from fastapi import FastAPI

from hotel_assistance.api.health import router as health_router

app = FastAPI(title="Hotel Assistance")

app.include_router(health_router)
