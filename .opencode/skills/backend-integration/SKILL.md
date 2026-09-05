---
name: backend-integration
description: Integrate the LedgerLens frontend with the existing FastAPI backend using verified API contracts without inventing endpoints, fields, or backend behavior.
---

---

# LedgerLens Backend Integration Skill

## Purpose

Use this skill whenever frontend code communicates with the LedgerLens FastAPI backend.

The backend already exists and is working.

The frontend must adapt to the backend, not redesign the backend around the frontend.

## Backend Location

The backend is located at:

```text
backend/
```

Primary API implementation:

```text
backend/src/api/routes.py
```

Backend application:

```text
backend/main.py
```

Before implementing an integration, inspect the actual backend source when necessary.

## API Base

The invoice API is:

```text
/api/v1/invoices
```

The frontend base URL must be configurable through frontend environment configuration.

Do not hardcode a production URL.

For local development, the backend currently runs separately from the frontend.

## Verified Endpoints

### Upload

```http
POST /api/v1/invoices/upload
```

Request:

```text
multipart/form-data
files
```

Multiple files are supported.

Supported extensions:

```text
.pdf
.jpg
.jpeg
.png
```

Maximum file size:

```text
15 MB
```

Response:

```json
{
  "message": "...",
  "status": "QUEUED",
  "queued_invoice_ids": [],
  "skipped_files": []
}
```

Important:

`QUEUED` is the upload response status.

It is not an `InvoiceStatus`.

The created invoice records subsequently use:

```text
PROCESSING
```

while background extraction is running.

## List Invoices

```http
GET /api/v1/invoices/
```

Optional query parameters:

```text
status
search
```

Do not assume pagination exists.

Current invoice list response fields:

```text
id
invoice_number
vendor_name
status
total_amount
date
```

Do not assume the list endpoint returns the complete invoice object.

Use the details endpoint when complete invoice data is required.

## Invoice Details

```http
GET /api/v1/invoices/{invoice_id}
```

Current response fields:

```text
id
status
vendor_name
vendor_tax_id
invoice_number
invoice_date
due_date
subtotal
tax_amount
total_amount
validation_errors
confidence_scores
line_items
file_url
```

Line item fields:

```text
description
quantity
unit_price
line_total
```

## Update Invoice

```http
PATCH /api/v1/invoices/{invoice_id}
```

Current supported update fields:

```text
vendor_name
invoice_number
invoice_date
subtotal
tax_amount
total_amount
```

Do not send unsupported fields.

The backend rejects modifications to approved invoices with:

```text
HTTP 409
```

The frontend should prevent editing approved invoices in the first place.

## Approve Invoice

```http
POST /api/v1/invoices/{invoice_id}/approve
```

This changes the invoice status to:

```text
APPROVED
```

Approved invoices are locked.

## CSV Export

```http
GET /api/v1/invoices/export/csv
```

This returns a CSV download.

The backend-generated filename is:

```text
ledger_export.csv
```

Do not recreate the export data on the client unless explicitly instructed.

## Invoice Statuses

Only these statuses currently exist:

```text
UPLOADED
PROCESSING
NEEDS_REVIEW
VALID
APPROVED
```

Never invent:

```text
FAILED
COMPLETED
PENDING_REVIEW
REJECTED
SYNCED
```

or other frontend-only backend statuses.

If a processing failure occurs, the current backend uses:

```text
NEEDS_REVIEW
```

and stores the error in:

```text
validation_errors
```

## Async Processing

Uploading a file and processing a file are separate operations.

Correct frontend sequence:

```text
POST /upload
     ↓
receive queued_invoice_ids
     ↓
display processing state
     ↓
GET invoice records
     ↓
observe PROCESSING
     ↓
eventually observe VALID / NEEDS_REVIEW
```

Do not assume processing is synchronous.

Do not block the upload screen waiting for the extraction request to finish.

## Polling / Refresh

If automatic status updates are implemented:

- use a controlled polling interval
- stop polling when processing finishes
- stop polling when the component unmounts
- avoid duplicate polling loops
- handle API failures
- avoid unnecessary requests

A simple implementation is preferred over introducing a complex real-time system when the backend does not provide one.

## API Client

Centralize backend communication.

Prefer a structure similar to:

```text
frontend/src/api/
├── client
└── invoices
```

The exact filenames depend on the chosen frontend stack.

The API layer should handle:

- base URL
- HTTP requests
- headers
- multipart upload
- response parsing
- errors
- typed responses

UI components should not duplicate API request logic.

## Type Safety

Create frontend types corresponding to the actual backend response structures.

For example:

```text
InvoiceStatus
InvoiceListItem
InvoiceDetails
LineItem
UploadResponse
InvoiceUpdate
```

Do not add fields to types simply because the Stitch design displays them.

If a field is not returned by the backend, it is not automatically part of the API type.

## Error Handling

Handle HTTP errors intentionally.

At minimum, account for:

```text
400-level errors
404 Not Found
409 Approved/Locked
500-level errors
network failures
upload failures
```

The UI should show useful user-facing messages.

Do not expose raw stack traces or secrets.

Preserve useful error information in development where appropriate.

## Upload Errors

The upload endpoint may return skipped files.

The frontend should inspect:

```text
skipped_files
```

and communicate rejected files to the user.

Do not claim that every selected file was successfully queued.

## Details Errors

For:

```text
GET /api/v1/invoices/{id}
```

handle:

```text
404
```

as an invoice-not-found state.

Do not render an empty review page as though the invoice exists.

## Update Errors

For:

```text
PATCH /api/v1/invoices/{id}
```

handle:

```text
409
```

as an approved/locked invoice state.

If the UI became stale while another action approved the invoice, refresh the invoice and switch to read-only mode.

## Approval Errors

After approval:

1. Refresh or update the local invoice state.
2. Represent it as `APPROVED`.
3. Disable editing.
4. Show the locked state.

Do not continue showing an editable review form after successful approval.

## Export

Export should trigger the backend's CSV response.

Do not silently replace it with:

- client-generated CSV
- hardcoded demo data
- a different column schema

unless explicitly instructed.

## API Contract Changes

If the frontend requires an endpoint that does not exist:

Do not create it automatically.

Instead report:

```text
Missing backend capability:
<what is needed>

Current backend:
<what exists>

Frontend requirement:
<what the UI needs>
```

Wait for explicit approval before modifying backend code.

## Backend Protection

Never modify:

```text
backend/src/api/routes.py
backend/src/models/model.py
backend/src/schemas/extraction.py
backend/src/services/
backend/src/core/database.py
```

during ordinary frontend integration work.

If a change is explicitly authorized, keep it minimal and verify existing backend tests afterward.

## Supabase Protection

The frontend must not directly use privileged Supabase credentials.

Never expose:

```text
SUPABASE_KEY
service-role credentials
database credentials
GROQ_API_KEY
```

in browser code.

The current invoice workflow should communicate through the FastAPI API.

## Authentication Boundary

Do not invent authentication endpoints.

The current invoice API contract does not provide authentication routes.

If authentication integration is requested:

1. Inspect the actual configured authentication system.
2. Determine the existing authentication boundary.
3. Use browser-safe credentials/configuration only.
4. Do not modify Supabase Auth or backend authentication without explicit authorization.

## Backend Regression Check

After frontend work, the backend should remain unchanged and functional.

Backend tests:

```bash
cd backend
pytest tests/ -v
```

Expected current result:

```text
7 passed
```

A warning in the existing dependency stack is not automatically a LedgerLens failure.

## Golden Rule

The frontend must be a truthful client of the backend.

```text
Design says what it should look like.
Backend says what it can actually do.
Frontend connects the two.
```

Never make the backend appear more capable than it is.
