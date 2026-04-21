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

def init_db():
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    proposal_columns = {column["name"] for column in inspector.get_columns("proposals")}
    if "evaluation_payload" not in proposal_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE proposals ADD COLUMN evaluation_payload TEXT"))
