from fastapi import FastAPI

app = FastAPI(title="Payment Processing")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


