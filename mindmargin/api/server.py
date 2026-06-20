from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mindmargin.api.routes import router
from mindmargin.config import settings

app = FastAPI(
    title="MindMargin API",
    description="MVP pipeline — research → script → voice → video",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}
