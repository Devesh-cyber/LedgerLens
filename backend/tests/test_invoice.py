"""
Minimal regression tests for the fixes made during this audit:

1. Invoice record exists immediately on upload (before processing).
2. A background-processing failure leaves the invoice visible with a
   descriptive error, instead of silently vanishing.
3. APPROVED invoices can no longer be edited via PATCH.
4. Vendor lookup is case/whitespace-insensitive (no duplicate vendors).
5. Oversized uploads are rejected before hitting storage.
6. Missing confidence routes the invoice to review.
7. Missing financial values route the invoice to review.
8. Correcting a vendor on one invoice does not modify another invoice.
9. PROCESSING invoices cannot be edited.
10. Math mismatches route the invoice to review.
11. Duplicate invoice numbers route the invoice to review.
12. Confidence scores must be between 0 and 1.
13. Overall confidence is persisted with field confidences.
14. Missing critical fields route the invoice to review.
15. review_fields identifies missing critical fields.
16. Multiple missing critical fields are all identified.

These deliberately mock Supabase Storage and the LLM extraction call
so the suite runs offline and never touches the real project.
"""

from datetime import date
from unittest.mock import patch

import pytest
from sqlmodel import Session

from src.models.model import Invoice, InvoiceStatus
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
    line_items=[
        ExtractedLineItem(
            description="Widget",
            quantity=2,
            unit_price=50.0,
            line_total=100.0,
        )
    ],
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
    with patch(
        "src.api.routes.process_invoice",
        return_value=FAKE_EXTRACTION,
    ):
        r = _upload(client)

    assert r.status_code == 200

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "VALID"
    assert details["vendor_name"] == "ACME Corp"
    assert details["total_amount"] == 118.0


def test_failed_processing_leaves_visible_record(client):
    with patch(
        "src.api.routes.process_invoice",
        side_effect=ValueError("No digital text found."),
    ):
        r = _upload(
            client,
            filename="broken.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    # No dedicated FAILED status exists yet.
    # The invoice must still exist and explain why it needs review.
    assert details["status"] == "NEEDS_REVIEW"
    assert any(
        "Processing failed" in msg
        for msg in details["validation_errors"]
    )


def test_approved_invoice_is_locked(client):
    with patch(
        "src.api.routes.process_invoice",
        return_value=FAKE_EXTRACTION,
    ):
        r = _upload(client)

    invoice_id = r.json()["queued_invoice_ids"][0]

    approve = client.post(
        f"/api/v1/invoices/{invoice_id}/approve"
    )

    assert approve.status_code == 200

    patch_resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"invoice_number": "NEW-999"},
    )

    assert patch_resp.status_code == 409


def test_vendor_case_insensitive_dedup(client):
    variant_a = FAKE_EXTRACTION

    variant_b = FAKE_EXTRACTION.model_copy(
        update={
            "vendor_name": "ACME CORP",
            "invoice_number": "INV-002",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=variant_a,
    ):
        _upload(client, filename="a.pdf")

    with patch(
        "src.api.routes.process_invoice",
        return_value=variant_b,
    ):
        _upload(client, filename="b.pdf")

    rows = client.get(
        "/api/v1/invoices/"
    ).json()

    vendor_names = {
        row["vendor_name"]
        for row in rows
    }

    assert vendor_names == {
        "ACME Corp"
    }, "Different casings of the same vendor should not create duplicates"


def test_oversized_file_rejected(client):
    big_bytes = b"0" * (16 * 1024 * 1024)

    r = _upload(
        client,
        filename="huge.pdf",
        content=big_bytes,
    )

    assert r.status_code == 200

    body = r.json()

    assert body["queued_invoice_ids"] == []
    assert "huge.pdf" in body["skipped_files"]


def test_missing_confidence_routes_to_review(client):
    no_confidence = FAKE_EXTRACTION.model_copy(
        update={
            "overall_confidence": None,
            "invoice_number": "INV-003",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=no_confidence,
    ):
        r = _upload(
            client,
            filename="noconf.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "did not report a confidence score" in msg
        for msg in details["validation_errors"]
    )


def test_missing_financial_value_routes_to_review(client):
    missing_tax = FAKE_EXTRACTION.model_copy(
        update={
            "tax_amount": None,
            "invoice_number": "INV-004",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=missing_tax,
    ):
        r = _upload(
            client,
            filename="missing-tax.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "Missing financial value" in msg
        for msg in details["validation_errors"]
    )


def test_review_fields_identify_missing_critical_fields(client):
    missing_invoice_number = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=missing_invoice_number,
    ):
        r = _upload(
            client,
            filename="missing-invoice-number.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"
    assert details["review_fields"] == ["invoice_number"]


def test_multiple_missing_critical_fields_are_identified(client):
    missing_fields = FAKE_EXTRACTION.model_copy(
        update={
            "vendor_name": "",
            "invoice_number": None,
            "invoice_date": None,
            "total_amount": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=missing_fields,
    ):
        r = _upload(
            client,
            filename="multiple-missing-fields.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert set(details["review_fields"]) == {
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "total_amount",
    }


def test_vendor_correction_does_not_modify_shared_vendor(client):
    first_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-005",
        }
    )

    second_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-006",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=first_invoice,
    ):
        first_response = _upload(
            client,
            filename="first.pdf",
        )

    with patch(
        "src.api.routes.process_invoice",
        return_value=second_invoice,
    ):
        second_response = _upload(
            client,
            filename="second.pdf",
        )

    first_id = first_response.json()["queued_invoice_ids"][0]
    second_id = second_response.json()["queued_invoice_ids"][0]

    correction = client.patch(
        f"/api/v1/invoices/{first_id}",
        json={"vendor_name": "Different Vendor"},
    )

    assert correction.status_code == 200

    first_details = client.get(
        f"/api/v1/invoices/{first_id}"
    ).json()

    second_details = client.get(
        f"/api/v1/invoices/{second_id}"
    ).json()

    assert first_details["vendor_name"] == "Different Vendor"
    assert second_details["vendor_name"] == "ACME Corp"


def test_processing_invoice_cannot_be_edited(client):
    routes_module = client.routes_module

    with Session(routes_module.engine) as session:
        invoice = Invoice(
            status=InvoiceStatus.PROCESSING,
            file_path="https://example.supabase.co/test.pdf",
        )

        session.add(invoice)
        session.commit()
        session.refresh(invoice)

        invoice_id = invoice.id

    patch_resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"invoice_number": "SHOULD-NOT-SAVE"},
    )

    assert patch_resp.status_code == 409

    with Session(routes_module.engine) as session:
        saved_invoice = session.get(
            Invoice,
            invoice_id,
        )

        assert saved_invoice is not None
        assert saved_invoice.invoice_number is None


def test_math_mismatch_routes_to_review(client):
    invalid_math = FAKE_EXTRACTION.model_copy(
        update={
            "subtotal": 100.0,
            "tax_amount": 18.0,
            "total_amount": 120.0,
            "invoice_number": "INV-007",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_math,
    ):
        r = _upload(
            client,
            filename="math-mismatch.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "Math mismatch" in msg
        for msg in details["validation_errors"]
    )


def test_duplicate_invoice_number_routes_to_review(client):
    first_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-DUP-001",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=first_invoice,
    ):
        r1 = _upload(
            client,
            filename="duplicate-first.pdf",
        )

    first_id = r1.json()["queued_invoice_ids"][0]

    first_details = client.get(
        f"/api/v1/invoices/{first_id}"
    ).json()

    assert first_details["status"] == "VALID"

    second_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-DUP-001",
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=second_invoice,
    ):
        r2 = _upload(
            client,
            filename="duplicate-second.pdf",
        )

    second_id = r2.json()["queued_invoice_ids"][0]

    second_details = client.get(
        f"/api/v1/invoices/{second_id}"
    ).json()

    assert second_details["status"] == "NEEDS_REVIEW"

    assert any(
        "Duplicate detection" in msg
        for msg in second_details["validation_errors"]
    )


def test_confidence_score_must_be_between_zero_and_one():
    with pytest.raises(ValueError):
        ExtractedInvoicePayload.model_validate(
            {
                **FAKE_EXTRACTION.model_dump(),
                "overall_confidence": 1.5,
            }
        )

    with pytest.raises(ValueError):
        ExtractedInvoicePayload.model_validate(
            {
                **FAKE_EXTRACTION.model_dump(),
                "overall_confidence": -0.1,
            }
        )


def test_overall_confidence_is_persisted(client):
    with patch(
        "src.api.routes.process_invoice",
        return_value=FAKE_EXTRACTION,
    ):
        r = _upload(
            client,
            filename="confidence-persistence.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["confidence_scores"]["overall"] == 0.97
    assert details["confidence_scores"]["vendor_name"] == 0.99


def test_missing_critical_field_routes_to_review(client):
    missing_invoice_number = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=missing_invoice_number,
    ):
        r = _upload(
            client,
            filename="missing-invoice-number.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "Missing critical field: invoice_number" in msg
        for msg in details["validation_errors"]
    )

def test_review_invoice_can_be_corrected_and_revalidated(client):
    invalid_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_invoice,
    ):
        r = _upload(
            client,
            filename="needs-review.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    before = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert before["status"] == "NEEDS_REVIEW"
    assert before["review_fields"] == ["invoice_number"]

    correction = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={
            "invoice_number": "INV-CORRECTED-001",
        },
    )

    assert correction.status_code == 200

    after = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert after["invoice_number"] == "INV-CORRECTED-001"
    assert after["status"] == "VALID"
    assert after["validation_errors"] == []
    assert after["review_fields"] == []


def test_invalid_correction_remains_needs_review(client):
    invalid_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_invoice,
    ):
        r = _upload(
            client,
            filename="invalid-correction.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    correction = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={
            "invoice_number": "INV-CORRECTED-002",
            "total_amount": 120.0,
        },
    )

    assert correction.status_code == 200

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "Math mismatch" in msg
        for msg in details["validation_errors"]
    )


def test_corrected_invoice_can_be_approved(client):
    invalid_invoice = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": None,
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_invoice,
    ):
        r = _upload(
            client,
            filename="correct-and-approve.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    assert client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()["status"] == "NEEDS_REVIEW"

    correction = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={
            "invoice_number": "INV-APPROVED-001",
        },
    )

    assert correction.status_code == 200
    assert correction.json()["status"] == "VALID"

    approve = client.post(
        f"/api/v1/invoices/{invoice_id}/approve"
    )

    assert approve.status_code == 200

    final_details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert final_details["status"] == "APPROVED"

def test_line_item_math_mismatch_routes_to_review(client):
    invalid_line_item = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-LINE-MISMATCH",
            "line_items": [
                ExtractedLineItem(
                    description="Widget",
                    quantity=2,
                    unit_price=50.0,
                    line_total=120.0,
                )
            ],
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_line_item,
    ):
        r = _upload(
            client,
            filename="line-item-mismatch.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    details = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert details["status"] == "NEEDS_REVIEW"

    assert any(
        "Line item 1 math mismatch" in msg
        for msg in details["validation_errors"]
    )

def test_line_item_can_be_corrected_and_revalidated(client):
    invalid_line_item = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-LINE-CORRECTION",
            "line_items": [
                ExtractedLineItem(
                    description="Widget",
                    quantity=2,
                    unit_price=50.0,
                    line_total=120.0,
                )
            ],
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_line_item,
    ):
        r = _upload(
            client,
            filename="line-item-correction.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    before = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert before["status"] == "NEEDS_REVIEW"

    correction = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={
            "line_items": [
                {
                    "description": "Widget",
                    "quantity": 2,
                    "unit_price": 50.0,
                    "line_total": 100.0,
                }
            ]
        },
    )

    assert correction.status_code == 200
    assert correction.json()["status"] == "VALID"

    after = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert after["status"] == "VALID"
    assert after["validation_errors"] == []
    assert after["review_fields"] == []

    assert len(after["line_items"]) == 1
    assert after["line_items"][0]["description"] == "Widget"
    assert after["line_items"][0]["quantity"] == 2
    assert after["line_items"][0]["unit_price"] == 50.0
    assert after["line_items"][0]["line_total"] == 100.0


def test_invalid_line_item_correction_remains_needs_review(client):
    invalid_line_item = FAKE_EXTRACTION.model_copy(
        update={
            "invoice_number": "INV-LINE-INVALID-CORRECTION",
            "line_items": [
                ExtractedLineItem(
                    description="Widget",
                    quantity=2,
                    unit_price=50.0,
                    line_total=120.0,
                )
            ],
        }
    )

    with patch(
        "src.api.routes.process_invoice",
        return_value=invalid_line_item,
    ):
        r = _upload(
            client,
            filename="invalid-line-item-correction.pdf",
        )

    invoice_id = r.json()["queued_invoice_ids"][0]

    before = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert before["status"] == "NEEDS_REVIEW"

    correction = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={
            "line_items": [
                {
                    "description": "Widget",
                    "quantity": 2,
                    "unit_price": 50.0,
                    "line_total": 125.0,
                }
            ]
        },
    )

    assert correction.status_code == 200
    assert correction.json()["status"] == "NEEDS_REVIEW"

    after = client.get(
        f"/api/v1/invoices/{invoice_id}"
    ).json()

    assert after["status"] == "NEEDS_REVIEW"

    assert any(
        "Line item 1 math mismatch" in msg
        for msg in after["validation_errors"]
    )