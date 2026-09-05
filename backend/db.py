import os
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session

load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Recommended for Neon & hosted Postgres: keep pool small and recycle
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

def get_session():
    with Session(engine) as session:
        yield session
