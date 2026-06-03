from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.llm import is_langfuse_enabled
from backend.routes.auth import router as auth_router
from backend.routes.exam import router as exam_router
from backend.routes.problem import router as problem_router
from backend.routes.query import router as query_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],#["http://localhost:3000"],  # adjust
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(problem_router)
app.include_router(query_router)
app.include_router(exam_router)

@app.get("/health")
def health():
    return {"ok": True, "langfuse_enabled": is_langfuse_enabled()}
