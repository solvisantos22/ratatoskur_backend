import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.llm import is_langfuse_enabled
from backend.routes.auth import router as auth_router
from backend.routes.classroom import router as classroom_router
from backend.storage.local import router as local_storage_router
from backend.routes.exam import router as exam_router
from backend.routes.problem import router as problem_router
from backend.routes.query import router as query_router

app = FastAPI()

# Browser origins allowed to call this API directly, comma-separated.
# Empty by default: the iPad app is native (CORS does not apply) and the
# teacher portal reaches the backend through its own server-side proxy,
# so no browser makes a cross-origin call here. Set this only if that changes.
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip()
]

if CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(problem_router)
app.include_router(query_router)
app.include_router(exam_router)
app.include_router(classroom_router)
app.include_router(local_storage_router)

@app.get("/health")
def health():
    return {"ok": True, "langfuse_enabled": is_langfuse_enabled()}
