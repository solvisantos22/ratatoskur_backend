# app/config.py
import os

JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-me")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
ACCESS_TOKEN_TTL_MIN = int(os.getenv("ACCESS_TOKEN_TTL_MIN", "15"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30"))

# Cookie settings
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token")

# For local dev: usually False; for production on HTTPS: True
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# "lax" is usually good; if frontend/backend are truly cross-site you may need "none"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" | "strict" | "none"
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")

# Query upload safety limits (bytes)
QUERY_MAX_SINGLE_FILE_BYTES = int(os.getenv("QUERY_MAX_SINGLE_FILE_BYTES", str(7 * 1024 * 1024)))
QUERY_MAX_TOTAL_BYTES = int(os.getenv("QUERY_MAX_TOTAL_BYTES", str(15 * 1024 * 1024)))
QUERY_MAX_PAGE_COUNT = int(os.getenv("QUERY_MAX_PAGE_COUNT", "12"))
