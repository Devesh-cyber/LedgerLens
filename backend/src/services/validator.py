from sqlmodel import Session, select
from src.models.model import Invoice, InvoiceStatus
from src.schemas.extraction import ExtractedInvoicePayload

CRITICAL_FIELDS = {
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
}

def validate_line_items(line_items) -> list[str]:
    """Validate quantity × unit price against each line item's total."""
    warnings = []

    for index, line_item in enumerate(line_items, start=1):
        expected_line_total = (
            line_item.quantity * line_item.unit_price
        )

        if abs(expected_line_total - line_item.line_total) > 0.05:
            warnings.append(
                f"Line item {index} math mismatch: "
                f"Quantity ({line_item.quantity}) × "
                f"Unit price ({line_item.unit_price}) "
                f"!= Line total ({line_item.line_total})"
            )

    return warnings

def validate_invoice_data(extracted_data: ExtractedInvoicePayload, vendor_id: int, session: Session) -> tuple[InvoiceStatus, list[str]]:
    """
    Runs automated validation rules:
    1. Math consistency (Subtotal + Tax == Total)
    2. Confidence threshold (>= 0.90)
    3. Duplicate check (Invoice number already exists for this vendor)
    """
    warnings = []

    # 0. Critical field completeness check
    for field_name in CRITICAL_FIELDS:
        value = getattr(extracted_data, field_name)

        if value is None or (
            isinstance(value, str) and not value.strip()
        ):
            warnings.append(
                f"Missing critical field: {field_name}"
            )

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

    # 2. Line-item mathematical consistency
    warnings.extend(
        validate_line_items(extracted_data.line_items)
    )

    # 3. Confidence Score Check
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


def validate_saved_invoice(invoice: Invoice, session: Session) -> tuple[InvoiceStatus, list[str]]:
    """
    Validate an invoice after human corrections have been saved.

    This validation operates only on persisted invoice fields and does not
    call the LLM.
    """
    warnings = []

    field_values = {
        "vendor_name": invoice.vendor.raw_name if invoice.vendor else None,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "total_amount": invoice.total_amount,
    }

    # 1. Critical field completeness
    for field_name in CRITICAL_FIELDS:
        value = field_values[field_name]

        if value is None or (
            isinstance(value, str) and not value.strip()
        ):
            warnings.append(
                f"Missing critical field: {field_name}"
            )

    # 2. Financial completeness and consistency
    if (
        invoice.subtotal is None
        or invoice.tax_amount is None
        or invoice.total_amount is None
    ):
        warnings.append(
            "Missing financial value: subtotal, tax amount, and total amount "
            "must all be present for automatic validation."
        )
    else:
        calculated_total = invoice.subtotal + invoice.tax_amount

        if abs(calculated_total - invoice.total_amount) > 0.05:
            warnings.append(
                f"Math mismatch: Subtotal ({invoice.subtotal}) "
                f"+ Tax ({invoice.tax_amount}) "
                f"!= Total ({invoice.total_amount})"
            )

    # 3. Line-item mathematical consistency
    warnings.extend(
        validate_line_items(invoice.line_items)
    )


    # 4. Duplicate invoice number
    if invoice.invoice_number and invoice.vendor_id:
        existing = session.exec(
            select(Invoice).where(
                Invoice.invoice_number == invoice.invoice_number,
                Invoice.vendor_id == invoice.vendor_id,
                Invoice.id != invoice.id,
            )
        ).first()

        if existing:
            warnings.append(
                f"Duplicate detection: Invoice "
                f"#{invoice.invoice_number} already exists for this vendor."
            )

    if not warnings:
        return InvoiceStatus.VALID, warnings

    return InvoiceStatus.NEEDS_REVIEW, warnings