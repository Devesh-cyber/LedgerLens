# init_db.py
from sqlmodel import SQLModel
from src.core.database import engine
# Import all models so SQLModel registers them before creating tables
from src.models.model import Vendor, Invoice, LineItem

def setup_database():
    print("Connecting to Supabase PostgreSQL...")
    SQLModel.metadata.create_all(engine)
    print("All tables (Vendor, Invoice, LineItem) created successfully!")

if __name__ == "__main__":
    setup_database()