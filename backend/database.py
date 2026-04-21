import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
try:
    from .models import Base
except ImportError:
    from models import Base

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_schema_verified = False


def ensure_db_schema():
    global _schema_verified
    if _schema_verified:
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "proposals" in tables:
        proposal_columns = {column["name"] for column in inspector.get_columns("proposals")}
        if "evaluation_payload" not in proposal_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE proposals ADD COLUMN evaluation_payload TEXT"))
    _schema_verified = True

def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_db_schema()
