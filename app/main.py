from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routers import auth, bookings, catalog, payments


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="EVE Healthcare Diagnostic Booking API",
    description="Diagnostic centre discovery, test bookings, and simulated payments.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(bookings.router)
app.include_router(payments.router)


@app.get("/health", tags=["Operations"])
def health() -> dict[str, str]:
    return {"status": "ok"}