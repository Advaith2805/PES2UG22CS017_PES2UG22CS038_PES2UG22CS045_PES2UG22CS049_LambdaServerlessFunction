from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./functions.db"  # For production, consider using PostgreSQL or another DB

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}  # This is for SQLite only
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
