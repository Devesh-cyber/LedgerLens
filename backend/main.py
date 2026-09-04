from fastapi import FastAPI
import os
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel
from src.core.database import engine
from src.api.routes import router as invoice_router

app = FastAPI(title="LedgerLens AI Engine")

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    os.makedirs("data/raw_invoices", exist_ok=True)

app.mount("/static", StaticFiles(directory="data/raw_invoices"), name="static")

app.include_router(invoice_router)

@app.get("/")
def read_root():
    return {"status": "online", "message": "LedgerLens API is running"}