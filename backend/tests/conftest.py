from __future__ import annotations

import os


os.environ.setdefault("DATABASE_URL", "sqlite:///./test_contract.db")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
