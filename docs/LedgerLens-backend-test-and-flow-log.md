# LedgerLens Backend — Simple Flow, Constraints & Testing Log

## 1. What LedgerLens does

LedgerLens takes invoice files and turns them into structured, validated data.

Supported upload types in the current backend:

- PDF
- JPG
- JPEG
- PNG

The long-term purpose is to replace messy manual invoice-to-Excel work with an automated invoice data pipeline.

---

## 2. Current architecture

```text
Frontend
   |
   | upload invoice
   v
FastAPI API
   |
   +--> Supabase Storage
   |       |
   |       +--> original invoice file
   |
   +--> Supabase PostgreSQL
           |
           +--> invoice record
           |
           +--> vendor
           |
           +--> line items

Background processing
   |
   v
Download invoice from Storage URL
   |
   +--> Image -> Vision LLM
   |
   +--> PDF -> PyMuPDF text extraction -> LLM
   |
   v
Structured invoice JSON
   |
   v
Pydantic validation
   |
   v
Business validation
   |
   +--> math checks
   +--> confidence check
   +--> duplicate check
   |
   v
Invoice status
   |
   +--> VALID
   |
   +--> NEEDS_REVIEW
   |
   +--> APPROVED
```

---

# 3. Upload flow in simple terms

When a user uploads an invoice:

1. FastAPI receives the file.
2. The extension is checked.
3. The file is read into memory.
4. A 15 MB maximum size is enforced.
5. A unique filename is generated.
6. The file is uploaded to the existing Supabase `invoices` bucket.
7. A URL is generated for that stored file.
8. A PostgreSQL `Invoice` row is immediately created with:
   - `status = PROCESSING`
   - `file_path = stored file URL`
9. The invoice ID and file URL are sent to the background processor.
10. The API returns the queued invoice ID.

The important improvement is that the database record exists even if AI processing later fails.

---

# 4. What happens during processing

The background processor receives:

```text
(invoice_id, file_url)
```

For each invoice:

### Step A — Download

The backend downloads the invoice from the Supabase Storage URL.

A 30-second HTTP timeout is used.

If downloading fails, processing goes to the error path.

---

### Step B — Determine document type

The extension is used to determine whether the invoice is:

```text
.jpg
.jpeg
.png
.pdf
```

---

### Step C — Images

For JPG/JPEG/PNG:

1. Read image bytes.
2. Convert to Base64.
3. Create the correct MIME type:
   - JPG/JPEG -> `image/jpeg`
   - PNG -> `image/png`
4. Send the image to the Groq-hosted vision model.
5. Ask the model to return structured JSON.

---

### Step D — PDFs

For PDF:

1. Download PDF bytes.
2. Open the PDF with PyMuPDF.
3. Extract text from all pages.
4. If text exists, send that text to the LLM.
5. If no text exists, processing currently fails with:
   `No digital text found...`

Important limitation:

## Scanned PDFs are NOT currently supported.

A scanned PDF has images of pages rather than machine-readable text.

That is a future improvement unless we explicitly decide to implement OCR/vision for scanned PDFs.

---

# 5. LLM extraction

The LLM is instructed to return JSON matching the Pydantic schema.

The extracted information currently includes:

```text
vendor_name
vendor_tax_id
invoice_number
invoice_date
due_date
subtotal
tax_amount
total_amount
spending_category
line_items
overall_confidence
field_confidences
```

A line item contains:

```text
description
quantity
unit_price
line_total
```

The important rule is:

> The LLM is an extractor, not the final source of truth.

The returned data still goes through application validation.

---

# 6. Validation flow

After extraction:

## Math validation

Current rule:

```text
subtotal + tax_amount == total_amount
```

with a small tolerance of `0.05`.

If it does not match:

```text
NEEDS_REVIEW
```

and a validation warning is stored.

Important limitation:

The current validator does NOT properly model discounts or all possible tax structures.

Do not assume:

```text
subtotal + tax = total
```

is universally correct for every real-world invoice.

---

## Confidence validation

The LLM reports a self-assessed confidence score.

Current threshold:

```text
>= 0.90 -> high confidence
< 0.90  -> review
missing -> review
```

This is NOT a statistically calibrated probability.

It is only an LLM self-assessment.

A missing confidence score must not automatically become 0.90.

---

## Duplicate validation

Current duplicate rule checks:

```text
invoice_number
+
vendor_id
```

If an invoice with the same number already exists for that vendor:

```text
NEEDS_REVIEW
```

This is only a basic duplicate rule.

It is not advanced entity matching.

---

# 7. Vendor handling

Before saving extracted invoice information, the backend finds or creates a vendor.

The current normalization:

```text
"  ABC   Traders  "
        |
        v
"ABC Traders"
```

Vendor matching is case-insensitive.

Therefore:

```text
ABC Traders
ABC TRADERS
```

can resolve to the same existing vendor.

This is intentionally simple.

It does NOT perform:

- fuzzy matching
- embeddings
- semantic entity resolution

Those are future features.

---

# 8. Database update

After extraction and validation, the existing invoice record is updated with:

```text
vendor_id
invoice_number
invoice_date
due_date
subtotal
tax_amount
total_amount
status
confidence_scores
validation_errors
```

Then extracted line items are stored against the invoice.

Relationship:

```text
Invoice
   |
   +---- Vendor
   |
   +---- LineItem
   |
   +---- validation_errors
   |
   +---- confidence_scores
```

---

# 9. Processing failure

The current database enum does NOT contain:

```text
FAILED
```

Therefore the implementation currently uses:

```text
NEEDS_REVIEW
```

with:

```text
validation_errors = [
    "Processing failed: ..."
]
```

This was intentionally done without changing the existing Supabase schema.

A dedicated `FAILED` status would require a database enum/schema change and must not be introduced without explicit approval.

---

# 10. Human review

The invoice details endpoint exposes:

```text
validation_errors
confidence_scores
```

so the frontend can understand why an invoice needs review.

The intended review process is:

```text
Invoice
   |
   +--> Original file
   |
   +--> Extracted values
   |
   +--> Validation warnings
   |
   +--> Confidence information
   |
   v
Human correction
   |
   v
Approve
```

---

# 11. Approval

When an invoice is approved:

```text
status = APPROVED
```

The PATCH endpoint rejects further edits with HTTP 409.

So:

```text
APPROVED
   |
   X
cannot be edited through PATCH
```

This implements the current meaning of "approved = locked".

If the product later needs reopening of approved invoices, that should be an explicit business rule.

---

# 12. CSV export

The backend has:

```text
GET /api/v1/invoices/export/csv
```

It exports:

```text
Invoice ID
Invoice Number
Vendor
Date
Due Date
Subtotal
Tax Amount
Total Amount
Status
```

This is currently invoice-level CSV export.

The richer Excel workbook with multiple sheets is a future feature.

---

# 13. Existing Supabase constraints

These are hard constraints for future development:

1. Supabase Storage is already working.
2. Supabase PostgreSQL is already working.
3. Existing tables are already working.
4. Existing relationships must be preserved.
5. Existing bucket names must not be changed without explicit approval.
6. Do not replace Supabase Storage with local file storage.
7. Do not replace Supabase PostgreSQL with SQLite.
8. Do not run destructive migrations.
9. Do not rename existing tables/columns/enums without approval.
10. Do not modify RLS policies without approval.
11. If a required fix needs a Supabase schema/configuration change, STOP and ask first.

---

# 14. Security constraints

Never commit or distribute:

```text
.env
real API keys
Supabase service-role keys
database passwords
LLM API keys
JWT secrets
```

Use:

```text
.env.example
```

for variable names only.

The actual `.env` must remain local.

---

# 15. Current file-storage constraint

The intended architecture is:

```text
Original invoice
      |
      v
Supabase Storage

Invoice metadata/extracted data
      |
      v
Supabase PostgreSQL
```

Do not start storing invoice binaries inside PostgreSQL.

The current backend uses a Supabase Storage public URL in the invoice record.

IMPORTANT:

Whether the bucket should be public or private is a Supabase configuration/business decision.

Do not silently change it.

If the bucket is private, the current public URL strategy needs to be changed to an approved signed-URL approach.

---

# 16. Current processing limitations

These are known limitations, not necessarily bugs:

### Scanned PDFs

Not currently supported.

```text
Scanned PDF
   |
   X
No machine-readable text
```

Future:

```text
Scanned PDF
   |
   v
Render pages
   |
   v
OCR / Vision
   |
   v
Extraction
```

---

### Advanced duplicate detection

Not currently implemented.

Current rule:

```text
vendor + invoice number
```

Future could include:

```text
vendor
invoice number
date
amount
file hash
similarity
```

---

### Advanced vendor matching

Not currently implemented.

Current matching is deterministic and simple.

---

### Background jobs

Current implementation uses FastAPI `BackgroundTasks`.

This is acceptable for the MVP.

It is not a durable production job queue.

A queue such as Celery/RQ/Redis can be considered later if processing volume requires it.

---

# 17. Important test distinction

There are TWO levels of testing.

## Level 1 — Automated regression tests

The included tests mock:

```text
Supabase Storage
LLM extraction
```

and use a temporary SQLite database.

Therefore they test application logic without touching the real Supabase project.

This is safe for development.

---

## Level 2 — Real integration test

After the automated tests pass, test the actual environment with:

```text
Real .env
Real Supabase Storage
Real Supabase PostgreSQL
Real LLM API
Real invoice files
```

This is the test that proves the complete system works end-to-end.

Do not use fake credentials for this test.

---

# 18. Recommended real-world test sequence

Use a clean virtual environment.

```bash
cd LedgerLens-backend-final

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Then:

```bash
pytest tests/ -v
```

Expected result:

```text
7 passed
```

If tests fail, fix the test/environment problem before testing production integrations.

---

# 19. Local server test

Create a real local `.env` from `.env.example`.

Then run:

```bash
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

Expected:

```json
{
  "status": "online",
  "message": "LedgerLens API is running"
}
```

Also open the FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

---

# 20. Real invoice test

Use one clean digital PDF invoice first.

Then test:

```text
PDF
 |
 v
Supabase Storage
 |
 v
PROCESSING
 |
 v
PyMuPDF
 |
 v
Groq LLM
 |
 v
Pydantic
 |
 v
Validator
 |
 v
PostgreSQL
```

Then call:

```text
GET /api/v1/invoices/{invoice_id}
```

Verify:

- vendor
- invoice number
- dates
- subtotal
- tax
- total
- line items
- status
- confidence scores
- validation errors
- file URL

---

# 21. Test cases to run manually

## Test A — Valid PDF

Expected:

```text
uploaded
PROCESSING
VALID or NEEDS_REVIEW
database record exists
```

---

## Test B — JPG invoice

Expected:

```text
image/jpeg
```

and successful vision processing.

---

## Test C — PNG invoice

Expected:

```text
image/png
```

not:

```text
image/jpeg
```

---

## Test D — Oversized file

Upload >15 MB.

Expected:

```text
not uploaded
listed in skipped_files
```

---

## Test E — Invalid extension

Upload:

```text
invoice.exe
```

Expected:

```text
skipped_files
```

---

## Test F — AI failure

Force extraction to fail.

Expected:

```text
invoice still exists in database
status = NEEDS_REVIEW
validation_errors contains processing failure
```

The record must NOT disappear.

---

## Test G — Low confidence

Use an extraction with:

```text
overall_confidence < 0.90
```

Expected:

```text
NEEDS_REVIEW
```

---

## Test H — Missing confidence

Use:

```text
overall_confidence = null
```

Expected:

```text
NEEDS_REVIEW
```

It must NOT silently become 0.90.

---

## Test I — Duplicate

Process the same vendor + invoice number again.

Expected:

```text
NEEDS_REVIEW
```

with a duplicate warning.

---

## Test J — Approval lock

Approve an invoice.

Then PATCH it.

Expected:

```text
HTTP 409
```

---

# 22. One issue that still needs verification

The current `src/schemas/extraction.py` still defines:

```python
subtotal: float
tax_amount: float
total_amount: float
```

while the extraction prompt says numeric values may be `null`.

That is inconsistent.

Before relying on the backend for invoices with missing financial fields, this needs to be deliberately resolved.

Do NOT change the Supabase database schema just to solve this.

If the application should support missing financial values, the Pydantic schema can be made nullable at the application layer.

This should be tested with a real example.

---

# 23. Another important verification

The current backend uses:

```text
Supabase get_public_url()
```

for the invoice file.

Confirm the `invoices` bucket is actually configured as intended.

If it is private, the frontend/LLM may not be able to access the stored URL.

Do not change the bucket configuration automatically.

---

# 24. What "working" means

LedgerLens is not considered working merely because:

```text
FastAPI starts
```

It needs to prove this:

```text
Real invoice
   ↓
Real upload
   ↓
Real Supabase Storage
   ↓
Real download
   ↓
Real extraction
   ↓
Real validation
   ↓
Real Supabase PostgreSQL record
   ↓
Correct API response
```

That is the real end-to-end test.

---

# 25. Golden rule for future changes

```text
If code can solve it:
    fix the code.

If the Supabase schema/configuration must change:
    STOP and ask.

If requirements are unclear:
    STOP and ask.

If something is already working:
    DO NOT rewrite it.

If a feature is not required for the current MVP:
    defer it.

Never hallucinate infrastructure.
Never invent database fields.
Never silently change business rules.
```

---

# 26. Current MVP definition

The current MVP is successful when:

```text
[✓] Upload invoice
[✓] Store original invoice in Supabase Storage
[✓] Create DB invoice record immediately
[✓] Process invoice
[✓] Extract structured information
[✓] Validate extraction
[✓] Store extracted data
[✓] Store line items
[✓] Surface validation problems
[✓] Surface confidence information
[✓] Review invoice
[✓] Approve invoice
[✓] Prevent editing approved invoice
[✓] Export invoice data as CSV
```

Everything else can come later.

---

# 27. Current status after the audit

The backend has a sensible MVP structure and the major lifecycle problems identified during the audit have been addressed.

However, passing mocked tests does NOT prove the real Supabase + Groq + real-invoice pipeline works.

The next step is therefore:

```text
Automated tests
      ↓
Local API startup
      ↓
Real Supabase Storage test
      ↓
Real Supabase DB verification
      ↓
Real LLM invoice extraction
      ↓
Real PDF/JPG/PNG tests
      ↓
End-to-end verification
```

That is the testing path to follow before adding more features.
