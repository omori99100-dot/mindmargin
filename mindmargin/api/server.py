from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mindmargin.api.routes.pipelines import router as pipelines_router
from mindmargin.api.routes.health import router as health_router
from mindmargin.api.routes.jobs import router as jobs_router
from mindmargin.api.routes.analytics import router as analytics_router
from mindmargin.api.routes.intelligence import router as intelligence_router
from mindmargin.api.routes.decisions import router as decisions_router
from mindmargin.api.routes.operations import router as operations_router
from mindmargin.api.routes.channel import router as channel_router
from mindmargin.api.routes.executive import router as executive_router
from mindmargin.api.routes.github import router as github_router
from mindmargin.api.routes.content import router as content_router
from mindmargin.api.routes.business import router as business_router
from mindmargin.api.routes.youtube_intelligence import router as youtube_intelligence_router
from mindmargin.config import settings

app = FastAPI(
    title="MindMargin API",
    description="Content intelligence platform — research, analytics, experiments, planning, and autonomous decisions",
    version="1.0.0",
)

_cors_origins = settings.production.allowed_origins if hasattr(settings.production, "allowed_origins") and settings.production.allowed_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Top-level health (no prefix)
app.include_router(health_router)

# All domain routes under /api/v1
app.include_router(pipelines_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(intelligence_router, prefix="/api/v1")
app.include_router(decisions_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(channel_router)
app.include_router(executive_router)
app.include_router(github_router)
app.include_router(content_router)
app.include_router(business_router)
app.include_router(youtube_intelligence_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "name": "MindMargin API",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
