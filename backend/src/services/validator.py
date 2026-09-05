from sqlmodel import Session, select
from src.models.model import Invoice, InvoiceStatus
from src.schemas.extraction import ExtractedInvoicePayload

def validate_invoice_data(extracted_data: ExtractedInvoicePayload, vendor_id: int, session: Session) -> tuple[InvoiceStatus, list[str]]:
    """
    Runs automated validation rules:
    1. Math consistency (Subtotal + Tax == Total)
    2. Confidence threshold (>= 0.90)
    3. Duplicate check (Invoice number already exists for this vendor)
    """
    warnings = []
    
    # 1. Math Discrepancy Check
    # 1. Financial completeness + math consistency check
    math_is_valid = True

    if (
        extracted_data.subtotal is None
        or extracted_data.tax_amount is None
        or extracted_data.total_amount is None
    ):
        math_is_valid = False
        warnings.append(
            "Missing financial value: subtotal, tax amount, and total amount "
            "must all be present for automatic validation."
        )
    else:
        calculated_total = extracted_data.subtotal + extracted_data.tax_amount

        if abs(calculated_total - extracted_data.total_amount) > 0.05:
            math_is_valid = False
            warnings.append(
                f"Math mismatch: Subtotal ({extracted_data.subtotal}) "
                f"+ Tax ({extracted_data.tax_amount}) "
                f"!= Total ({extracted_data.total_amount})"
            )

    # 2. Confidence Score Check
    # overall_confidence is a self-reported AI estimate, not a calibrated
    # statistical probability. If the model didn't return one at all, don't
    # assume it was high confidence -- treat it as needing human review.
    if extracted_data.overall_confidence is None:
        is_high_confidence = False
        warnings.append("AI did not report a confidence score for this extraction; flagged for review.")
    else:
        is_high_confidence = extracted_data.overall_confidence >= 0.90
        if not is_high_confidence:
            warnings.append(f"Low self-reported AI confidence: {extracted_data.overall_confidence}")

    # 3. Duplicate Invoice Check
    if extracted_data.invoice_number:
        existing = session.exec(
            select(Invoice).where(
                Invoice.invoice_number == extracted_data.invoice_number,
                Invoice.vendor_id == vendor_id
            )
        ).first()
        if existing:
            warnings.append(f"Duplicate detection: Invoice #{extracted_data.invoice_number} already exists for this vendor.")
            math_is_valid = False # Treat duplicate as needing human review

    # Final Triage Assignment
    if math_is_valid and is_high_confidence and not warnings:
        return InvoiceStatus.VALID, warnings
    else:
        return InvoiceStatus.NEEDS_REVIEW, warnings

