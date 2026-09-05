import os
import io
import csv
import uuid
import logging
from typing import Optional, List, Tuple
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from supabase import create_client, Client
from sqlmodel import Session, select
from sqlalchemy import func
from src.services.extractor import process_invoice
from src.services.validator import validate_invoice_data
from src.schemas.extraction import ExtractedInvoicePayload, InvoiceUpdate
from src.models.model import Vendor, Invoice, LineItem, InvoiceStatus
from src.core.database import get_session, engine

logger = logging.getLogger("ledgerlens.invoices")

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])

# Initialize Supabase Client for Storage
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("CRITICAL: SUPABASE_URL and SUPABASE_KEY must be set in .env")
supabase: Client = create_client(supabase_url, supabase_key)

# Reject absurdly large uploads before they ever hit Supabase Storage / the LLM.
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def _normalize_vendor_name(raw_name: str) -> str:
    """Collapse repeated whitespace so 'ABC Traders' and '  ABC   Traders ' resolve
    to the same lookup key. Deliberately simple -- not fuzzy/entity matching."""
    return " ".join((raw_name or "").split())


def _find_or_create_vendor(session: Session, vendor_name: str, vendor_tax_id: Optional[str]) -> Vendor:
    normalized = _normalize_vendor_name(vendor_name)

    # Case-insensitive match on the existing raw_name column so "ABC Traders" and
    # "ABC TRADERS" resolve to the same vendor instead of being duplicated.
    vendor = session.exec(
        select(Vendor).where(func.lower(Vendor.raw_name) == normalized.lower())
    ).first()

    if not vendor:
        vendor = Vendor(raw_name=normalized, canonical_name=normalized, tax_id=vendor_tax_id)
        session.add(vendor)
        session.flush()

    return vendor


def _mark_invoice_failed(invoice_id: int, error_message: str) -> None:
    """Best-effort: leave a permanent, visible failure record on the invoice that
    was already created at upload time, instead of losing the failure silently.

    NOTE: the current InvoiceStatus enum has no dedicated FAILED value, so this
    reuses NEEDS_REVIEW (with the real error recorded in validation_errors) to
    keep the failed invoice visible in the review queue. See final report for a
    proposed dedicated FAILED status, which would require a Supabase schema
    change and is intentionally NOT made here without confirmation.
    """
    with Session(engine) as session:
        try:
            invoice = session.get(Invoice, invoice_id)
            if invoice is None:
                logger.error("Cannot mark invoice %s failed: record no longer exists", invoice_id)
                return
            invoice.status = InvoiceStatus.NEEDS_REVIEW
            invoice.validation_errors = [f"Processing failed: {error_message}"]
            session.add(invoice)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to persist failure state for invoice %s", invoice_id)


def background_process_batch(queued_invoices: List[Tuple[int, str]]):
    """Runs independently in the background, preventing HTTP timeouts.

    Each item is (invoice_id, file_url) for an Invoice row that was already
    created (status=PROCESSING) at upload time, so a failure here always has
    an existing record to update rather than vanishing silently.
    """
    with Session(engine) as session:
        for invoice_id, file_url in queued_invoices:
            try:
                # 1. Run AI Extraction from remote URL
                extracted_data = process_invoice(file_url)

                # 2. Find or Create Vendor (case/whitespace-normalized lookup)
                vendor = _find_or_create_vendor(session, extracted_data.vendor_name, extracted_data.vendor_tax_id)

                # 3. Validate & Triage
                initial_status, validation_warnings = validate_invoice_data(extracted_data, vendor.id, session)

                # 4. Update the invoice record created at upload time
                db_invoice = session.get(Invoice, invoice_id)
                if db_invoice is None:
                    logger.error("Invoice %s vanished before processing could complete", invoice_id)
                    continue

                db_invoice.vendor_id = vendor.id
                db_invoice.invoice_number = extracted_data.invoice_number
                db_invoice.invoice_date = extracted_data.invoice_date
                db_invoice.due_date = extracted_data.due_date
                db_invoice.subtotal = extracted_data.subtotal
                db_invoice.tax_amount = extracted_data.tax_amount
                db_invoice.total_amount = extracted_data.total_amount
                db_invoice.status = initial_status
                db_invoice.confidence_scores = {
                "overall": extracted_data.overall_confidence,
                **extracted_data.field_confidences,
            }
                db_invoice.validation_errors = validation_warnings
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
                logger.exception("Failed to process invoice %s (%s)", invoice_id, file_url)
                _mark_invoice_failed(invoice_id, str(e))

@router.post("/upload")
async def upload_invoices(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_session)
):
    allowed_extensions = (".pdf", ".jpg", ".jpeg", ".png")
    queued_invoices: List[Tuple[int, str]] = []
    skipped_files: List[str] = []

    for file in files:
        if not file.filename.lower().endswith(allowed_extensions):
            skipped_files.append(file.filename)
            continue

        file_bytes = await file.read()

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            logger.warning("Rejected %s: exceeds max upload size", file.filename)
            skipped_files.append(file.filename)
            continue

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
        except Exception as e:
            logger.exception("Storage upload failed for %s", file.filename)
            skipped_files.append(file.filename)
            continue

        # Create the invoice record immediately, before background processing,
        # so it's visible in the dashboard (status=PROCESSING) even if
        # extraction later fails.
        db_invoice = Invoice(
            status=InvoiceStatus.PROCESSING,
            file_path=public_url,
        )
        session.add(db_invoice)
        session.commit()
        session.refresh(db_invoice)

        queued_invoices.append((db_invoice.id, public_url))

    # Hand the created invoice ids + Supabase URLs off to the background worker
    background_tasks.add_task(background_process_batch, queued_invoices)

    return {
        "message": f"Successfully uploaded {len(queued_invoices)} files to cloud storage. Processing in background.",
        "status": "QUEUED",
        "queued_invoice_ids": [invoice_id for invoice_id, _ in queued_invoices],
        "skipped_files": skipped_files,
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
        "validation_errors": invoice.validation_errors,
        "confidence_scores": invoice.confidence_scores,
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

    # APPROVED invoices are locked into the master dataset and must not be
    # editable through this endpoint (previously this check was missing).
    if invoice.status == InvoiceStatus.PROCESSING:
        raise HTTPException(
            status_code=409,
            detail="Invoice is still processing and cannot be modified."
        )

    if invoice.status == InvoiceStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Invoice is approved and locked; it cannot be modified."
        )

    update_dict = update_data.model_dump(exclude_unset=True)

    if "vendor_name" in update_dict:
        normalized_vendor_name = _normalize_vendor_name(update_dict["vendor_name"])

        if not normalized_vendor_name:
            raise HTTPException(
                status_code=400,
                detail="Vendor name cannot be empty."
            )

        vendor = _find_or_create_vendor(
            session,
            normalized_vendor_name,
            invoice.vendor.tax_id if invoice.vendor else None,
        )

        invoice.vendor_id = vendor.id

    for key, value in update_dict.items():
        if key != "vendor_name" and hasattr(invoice, key):
            setattr(invoice, key, value)
            
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return {"message": "Corrections saved successfully"}

@router.post("/{invoice_id}/approve")
def approve_invoice(invoice_id: int, session: Session = Depends(get_session)):
    """Locks the invoice into the master dataset after human approval."""
    invoice = session.get(Invoice, invoice_id)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status not in {
        InvoiceStatus.VALID,
        InvoiceStatus.NEEDS_REVIEW,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Invoice cannot be approved from status {invoice.status.value}",
        )

    invoice.status = InvoiceStatus.APPROVED
    session.add(invoice)
    session.commit()

    return {"message": "Invoice approved and locked"}