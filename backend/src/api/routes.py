import os
import io
import csv
import uuid
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from supabase import create_client, Client
from sqlmodel import Session, select
from src.services.extractor import process_invoice
from src.services.validator import validate_invoice_data
from src.schemas.extraction import ExtractedInvoicePayload, InvoiceUpdate
from src.models.model import Vendor, Invoice, LineItem, InvoiceStatus
from src.core.database import get_session, engine

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])

# Initialize Supabase Client for Storage
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("CRITICAL: SUPABASE_URL and SUPABASE_KEY must be set in .env")
supabase: Client = create_client(supabase_url, supabase_key)

def background_process_batch(file_urls: List[str]):
    """Runs independently in the background, preventing HTTP timeouts."""
    with Session(engine) as session:
        for file_url in file_urls:
            try:
                # 1. Run AI Extraction from remote URL
                extracted_data = process_invoice(file_url)
                
                # 2. Find or Create Vendor
                vendor_name = extracted_data.vendor_name
                vendor = session.exec(select(Vendor).where(Vendor.raw_name == vendor_name)).first()
                
                if not vendor:
                    vendor = Vendor(raw_name=vendor_name, tax_id=extracted_data.vendor_tax_id)
                    session.add(vendor)
                    session.flush()
                    
                # 3. Validate & Triage
                initial_status, validation_warnings = validate_invoice_data(extracted_data, vendor.id, session)

                # 4. Create Invoice (save cloud URL in file_path)
                db_invoice = Invoice(
                    vendor_id=vendor.id,
                    invoice_number=extracted_data.invoice_number,
                    invoice_date=extracted_data.invoice_date,
                    due_date=extracted_data.due_date,
                    subtotal=extracted_data.subtotal,
                    tax_amount=extracted_data.tax_amount,
                    total_amount=extracted_data.total_amount,
                    status=initial_status,
                    file_path=file_url,
                    confidence_scores=extracted_data.field_confidences,
                    validation_errors=validation_warnings
                )
                session.add(db_invoice)
                session.flush()
                
                # 5. Create Line Items
                for item in extracted_data.line_items:
                    db_line_item = LineItem(
                        invoice_id=db_invoice.id,
                        description=item.description,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        line_total=item.line_total
                    )
                    session.add(db_line_item)
                    
                session.commit()
                
            except Exception as e:
                session.rollback()
                print(f"Failed to process {file_url} in background: {str(e)}")

@router.post("/upload")
async def upload_invoices(
    background_tasks: BackgroundTasks, 
    files: List[UploadFile] = File(...)
):
    allowed_extensions = (".pdf", ".jpg", ".jpeg", ".png")
    uploaded_file_urls = []
    
    for file in files:
        if not file.filename.lower().endswith(allowed_extensions):
            continue
            
        file_bytes = await file.read()
        
        # Generate a unique path to prevent overwriting identical filenames
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        storage_path = f"raw/{unique_filename}"
        
        try:
            # Upload to Supabase 'invoices' bucket
            supabase.storage.from_("invoices").upload(
                path=storage_path, 
                file=file_bytes, 
                file_options={"content-type": file.content_type}
            )
            
            # Get the public URL to save in the database
            public_url = supabase.storage.from_("invoices").get_public_url(storage_path)
            uploaded_file_urls.append(public_url)
        except Exception as e:
            print(f"Storage upload failed for {file.filename}: {e}")
            continue
        
    # Hand the Supabase URLs off to the background worker
    background_tasks.add_task(background_process_batch, uploaded_file_urls)

    return {
        "message": f"Successfully uploaded {len(uploaded_file_urls)} files to cloud storage. Processing in background.",
        "status": "QUEUED"
    }

@router.get("/")
def get_all_invoices(
    status: Optional[InvoiceStatus] = None, 
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
        # Directly pass the Supabase URL to the frontend viewer
        "file_url": invoice.file_path
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