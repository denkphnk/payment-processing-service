from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers.payments import router as payments_router
from src.messaging.broker import broker, payments_dlq, payments_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.connect()
    await broker.declare_queue(payments_queue)
    await broker.declare_queue(payments_dlq)

    yield

    await broker.close()


app = FastAPI(
    title="Payment Processing",
    lifespan=lifespan,
)

app.include_router(payments_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
