from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from configs import setting

# Database URL
DATABASE_URL = setting.DATABASE_URL

# Create Database engine
database_engine = create_engine(DATABASE_URL)

# Create Session Factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=database_engine
)

# Base Class for SQlAlchemy models
Base = declarative_base()

# FastAPI database dependency
def get_db():
    db = SessionLocal()

    try: 
        yield db

    finally:
        db.close()