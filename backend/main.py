from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router as invoices_router

app = FastAPI(title="LedgerLens AI Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(invoices_router)

@app.get("/")
def read_root():
    return {"status": "online", "message": "LedgerLens API is running"}