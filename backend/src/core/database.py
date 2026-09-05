import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

database_url = os.environ.get("DATABASE_URL")

# Add pool_pre_ping=True to prevent random disconnects from the Supabase pooler
engine = create_engine(database_url, echo=False, pool_pre_ping=True)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session