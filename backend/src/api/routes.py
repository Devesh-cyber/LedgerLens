import os
import shutil
import io
import csv
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from src.services.extractor import process_invoice
from src.schemas.extraction import ExtractedInvoicePayload, InvoiceUpdate
from src.models.model import Vendor, Invoice, LineItem, InvoiceStatus
from src.core.database import get_session
from typing import Optional
from datetime import date

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])

UPLOAD_DIR = "data/raw_invoices"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload")
async def upload_invoice(file: UploadFile = File(...), session: Session = Depends(get_session)):
    allowed_extensions = (".pdf", ".jpg", ".jpeg", ".png")
    if not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(status_code=400, detail="Only PDF, JPG, JPEG, and PNG files are supported.")
        
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        # 1. Run AI Extraction (Supports text PDFs and vision models)
        extracted_data = process_invoice(file_path)
        
        # --- AUTOMATED TRIAGE GATEKEEPER ---
        math_is_valid = True
        if extracted_data.subtotal is not None and extracted_data.tax_amount is not None and extracted_data.total_amount is not None:
            calculated_total = extracted_data.subtotal + extracted_data.tax_amount
            if abs(calculated_total - extracted_data.total_amount) > 0.05:
                math_is_valid = False
                
        is_high_confidence = extracted_data.overall_confidence >= 0.90
        
        if is_high_confidence and math_is_valid:
            initial_status = InvoiceStatus.VALID
        else:
            initial_status = InvoiceStatus.NEEDS_REVIEW
        # -----------------------------------

        # 2. Find or Create Vendor
        vendor_name = extracted_data.vendor_name
        statement = select(Vendor).where(Vendor.raw_name == vendor_name)
        vendor = session.exec(statement).first()
        
        if not vendor:
            vendor = Vendor(raw_name=vendor_name, tax_id=extracted_data.vendor_tax_id)
            session.add(vendor)
            session.flush()
            
        # 3. Create Invoice Record with dynamic status assignment
        db_invoice = Invoice(
            vendor_id=vendor.id,
            invoice_number=extracted_data.invoice_number,
            invoice_date=extracted_data.invoice_date,
            due_date=extracted_data.due_date,
            subtotal=extracted_data.subtotal,
            tax_amount=extracted_data.tax_amount,
            total_amount=extracted_data.total_amount,
            status=initial_status,
            file_path=file_path,
            confidence_scores=extracted_data.field_confidences
        )
        session.add(db_invoice)
        session.flush()
        
        # 4. Create Line Items
        for item in extracted_data.line_items:
            db_line_item = LineItem(
                invoice_id=db_invoice.id,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total
            )
            session.add(db_line_item)
            
        # 5. Commit everything to the database
        session.commit()
        session.refresh(db_invoice)
        
        return {
            "message": "Invoice processed and triaged successfully", 
            "invoice_id": db_invoice.id,
            "assigned_status": db_invoice.status
        }
        
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Database or Extraction Error: {str(e)}")

@router.get("/")
def get_all_invoices(
    status: Optional[InvoiceStatus] = None, # <--- FastAPI renders this as a selectbox dropdown in Swagger UI
    search: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Populates the Main Dashboard Queue with optional filters."""
    statement = select(Invoice)
    
    if status:
        statement = statement.where(Invoice.status == status)
        
    invoices = session.exec(statement).all()
    
    results = []
    for inv in invoices:
        vendor_name = inv.vendor.raw_name if inv.vendor else ""
        
        if search:
            query = search.lower()
            match_num = query in (inv.invoice_number or "").lower()
            match_vendor = query in vendor_name.lower()
            if not match_num and not match_vendor:
                continue
                
        results.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "vendor_name": vendor_name,
            "status": inv.status,
            "total_amount": inv.total_amount,
            "date": inv.invoice_date
        })
        
    return results

@router.get("/export/csv")
def export_invoices_csv(session: Session = Depends(get_session)):
    """Exports ledger rows as a downloadable CSV file for reporting and data sync."""
    invoices = session.exec(select(Invoice)).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["Invoice ID", "Invoice Number", "Vendor", "Date", "Due Date", "Subtotal", "Tax Amount", "Total Amount", "Status"])
    
    for inv in invoices:
        writer.writerow([
            inv.id,
            inv.invoice_number,
            inv.vendor.raw_name if inv.vendor else "Unknown",
            inv.invoice_date,
            inv.due_date,
            inv.subtotal,
            inv.tax_amount,
            inv.total_amount,
            inv.status
        ])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ledger_export.csv"}
    )

@router.get("/{invoice_id}")
def get_invoice_details(invoice_id: int, session: Session = Depends(get_session)):
    """Populates the Side-by-Side Review Screen."""
    invoice = session.get(Invoice, invoice_id)
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    file_name = os.path.basename(invoice.file_path)
        
    return {
        "id": invoice.id,
        "status": invoice.status,
        "vendor_name": invoice.vendor.raw_name if invoice.vendor else None,
        "vendor_tax_id": invoice.vendor.tax_id if invoice.vendor else None,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "subtotal": invoice.subtotal,
        "tax_amount": invoice.tax_amount,
        "total_amount": invoice.total_amount,
        "line_items": [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total
            } for item in invoice.line_items
        ],
        "file_url": f"http://127.0.0.1:8000/static/{file_name}"
    }

@router.patch("/{invoice_id}")
def update_invoice(invoice_id: int, update_data: InvoiceUpdate, session: Session = Depends(get_session)):
    """Saves human corrections from the Side-by-Side UI."""
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    if update_data.vendor_name and invoice.vendor:
        invoice.vendor.raw_name = update_data.vendor_name
        session.add(invoice.vendor)
        
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if key != "vendor_name" and hasattr(invoice, key):
            setattr(invoice, key, value)
            
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return {"message": "Corrections saved successfully"}

@router.post("/{invoice_id}/approve")
def approve_invoice(invoice_id: int, session: Session = Depends(get_session)):
    """Locks the invoice into the master dataset."""
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    invoice.status = InvoiceStatus.APPROVED
    session.add(invoice)
    session.commit()
    return {"message": "Invoice approved and locked"}