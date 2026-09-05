"""
Minimal regression tests for the fixes made during this audit:
  1. Invoice record exists immediately on upload (before processing).
  2. A background-processing failure leaves the invoice visible with a
     descriptive error, instead of silently vanishing.
  3. APPROVED invoices can no longer be edited via PATCH.
  4. Vendor lookup is case/whitespace-insensitive (no duplicate vendors).
  5. Oversized uploads are rejected before hitting storage.

These deliberately mock Supabase Storage and the LLM extraction call so the
suite runs offline and never touches the real project.
"""
from datetime import date
from unittest.mock import patch

from src.schemas.extraction import ExtractedInvoicePayload, ExtractedLineItem

FAKE_EXTRACTION = ExtractedInvoicePayload(
    vendor_name="  ACME   Corp ",
    vendor_tax_id="TAX123",
    invoice_number="INV-001",
    invoice_date=date(2026, 1, 1),
    due_date=date(2026, 2, 1),
    subtotal=100.0,
    tax_amount=18.0,
    total_amount=118.0,
    line_items=[ExtractedLineItem(description="Widget", quantity=2, unit_price=50.0, line_total=100.0)],
    overall_confidence=0.97,
    field_confidences={"vendor_name": 0.99},
)


def _upload(client, filename="test.pdf", content=b"%PDF-1.4 fake"):
    files = {"files": (filename, content, "application/pdf")}
    return client.post("/api/v1/invoices/upload", files=files)


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200


def test_successful_upload_and_processing(client):
    with patch("src.api.routes.process_invoice", return_value=FAKE_EXTRACTION):
        r = _upload(client)
    assert r.status_code == 200
    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert details["status"] == "VALID"
    assert details["vendor_name"] == "ACME Corp"
    assert details["total_amount"] == 118.0


def test_failed_processing_leaves_visible_record(client):
    with patch("src.api.routes.process_invoice", side_effect=ValueError("No digital text found.")):
        r = _upload(client, filename="broken.pdf")
    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(f"/api/v1/invoices/{invoice_id}").json()
    # No dedicated FAILED status exists yet (see final report) -- the invoice
    # must still exist and explain why it needs review, not disappear.
    assert details["status"] == "NEEDS_REVIEW"
    assert any("Processing failed" in msg for msg in details["validation_errors"])


def test_approved_invoice_is_locked(client):
    with patch("src.api.routes.process_invoice", return_value=FAKE_EXTRACTION):
        r = _upload(client)
    invoice_id = r.json()["queued_invoice_ids"][0]

    approve = client.post(f"/api/v1/invoices/{invoice_id}/approve")
    assert approve.status_code == 200

    patch_resp = client.patch(f"/api/v1/invoices/{invoice_id}", json={"invoice_number": "NEW-999"})
    assert patch_resp.status_code == 409


def test_vendor_case_insensitive_dedup(client):
    variant_a = FAKE_EXTRACTION
    variant_b = FAKE_EXTRACTION.model_copy(update={"vendor_name": "ACME CORP", "invoice_number": "INV-002"})

    with patch("src.api.routes.process_invoice", return_value=variant_a):
        _upload(client, filename="a.pdf")
    with patch("src.api.routes.process_invoice", return_value=variant_b):
        _upload(client, filename="b.pdf")

    rows = client.get("/api/v1/invoices/").json()
    vendor_names = {row["vendor_name"] for row in rows}
    assert vendor_names == {"ACME Corp"}, "Different casings of the same vendor should not create duplicates"


def test_oversized_file_rejected(client):
    big_bytes = b"0" * (16 * 1024 * 1024)  # over the 15 MB limit
    r = _upload(client, filename="huge.pdf", content=big_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["queued_invoice_ids"] == []
    assert "huge.pdf" in body["skipped_files"]


def test_missing_confidence_routes_to_review(client):
    no_confidence = FAKE_EXTRACTION.model_copy(update={"overall_confidence": None, "invoice_number": "INV-003"})
    with patch("src.api.routes.process_invoice", return_value=no_confidence):
        r = _upload(client, filename="noconf.pdf")
    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert details["status"] == "NEEDS_REVIEW"
    assert any("did not report a confidence score" in msg for msg in details["validation_errors"])