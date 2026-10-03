# Database setup using SQLAlchemy.
# SQLAlchemy lets me write Python classes instead of CREATE TABLE statements,
# and the same code works with PostgreSQL (Docker) and SQLite (tests).

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app import config

# SQLite needs one extra option when used from many threads; Postgres does not.
connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def now_utc():
    return datetime.now(timezone.utc)


# Table: users
# Same as: CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE, ...)
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin / user / readonly


# Table: chat_logs  (one row for every /chat request)
class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    model = Column(String(50))
    cached = Column(Integer, default=0)  # 1 if the answer came from Redis cache
    prompt_tokens = Column(Integer, default=0)
    answer_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=now_utc)


def create_tables():
    Base.metadata.create_all(bind=engine)


# FastAPI "dependency": gives each request its own DB session and closes it after.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
