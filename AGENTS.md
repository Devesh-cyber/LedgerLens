# LedgerLens — OpenCode Project Instructions

## 1. Project Overview

LedgerLens is an AI-powered invoice intelligence platform.

Its core workflow is:

Upload invoice → store document → extract invoice data with AI → validate extracted data → triage → human review when necessary → approve → master ledger → export.

The project currently has a working FastAPI backend. The frontend is now being implemented from the provided Stitch UI/UX designs.

The goal is to build a production-quality frontend that faithfully implements the existing LedgerLens design and integrates with the existing backend.

---

## 2. Source of Truth

There are three sources of truth.

### Visual Source of Truth

The provided Stitch LedgerLens designs are the source of truth for:

- Layout
- Visual hierarchy
- Typography
- Spacing
- Colors
- Components
- Navigation
- Tables
- Forms
- Upload UI
- Review UI
- Empty/loading/error states
- Responsive behavior
- Visual interactions

Do not redesign the application unless explicitly instructed.

### Functional Source of Truth

The existing backend is the source of truth for:

- API endpoints
- Request formats
- Response formats
- Invoice fields
- Invoice statuses
- Processing behavior
- Validation behavior
- Approval behavior
- Export behavior

Inspect the backend before assuming an API exists.

### Project Instructions

This file is the source of truth for implementation constraints and project conventions.

When sources conflict:

1. Explicit user instruction
2. Existing backend behavior
3. Stitch design
4. Reasonable implementation judgment

Never invent backend behavior to make a UI appear functional.

---

## 3. Critical Rules

### DO NOT modify the backend unless explicitly instructed.

The backend has already been tested and is considered working.

Do not:

- Rewrite backend routes
- Refactor backend architecture
- Change database models
- Change Supabase schema
- Change Supabase buckets
- Change Supabase configuration
- Add migrations
- Rename existing database fields
- Replace existing APIs
- Replace the existing extraction pipeline

If frontend requirements expose a genuine backend limitation, report it instead of silently changing the backend.

### DO NOT invent APIs.

Before creating an API client or calling an endpoint, verify the endpoint exists in:

`backend/src/api/routes.py`

If the Stitch design contains functionality that the backend does not currently support, do one of the following:

- Implement the UI state without pretending the backend supports it, or
- Clearly identify the missing backend capability and wait for explicit instruction.

Never create fake endpoints such as `/api/v1/dashboard/stats` simply because the UI needs statistics.

### DO NOT fabricate data.

Do not use fake invoice records in production application flows.

Mock data may only be used intentionally for:

- isolated visual development
- components that have no backend equivalent yet
- loading/empty-state previews
- tests

Clearly separate mock/demo data from real application data.

---

## 4. Current Repository

Current structure:

```text
ledgerlens/
├── backend/
│   ├── main.py
│   ├── init_db.py
│   ├── requirements.txt
│   ├── src/
│   │   ├── api/
│   │   │   └── routes.py
│   │   ├── core/
│   │   │   └── database.py
│   │   ├── models/
│   │   │   └── model.py
│   │   ├── schemas/
│   │   │   └── extraction.py
│   │   └── services/
│   │       ├── extractor.py
│   │       └── validator.py
│   └── tests/
├── docs/
│   └── LedgerLens-backend-test-and-flow-log.md
├── backend.zip
├── .gitignore
└── AGENTS.md
```

A `frontend/` directory will be created for the new frontend implementation.

Do not move or reorganize the existing backend.

---

## 5. Backend API Contract

Base invoice route:

```text
/api/v1/invoices
```

### Upload invoices

```http
POST /api/v1/invoices/upload
```

Accepts multiple uploaded files.

Supported formats:

```text
.pdf
.jpg
.jpeg
.png
```

Maximum file size:

```text
15 MB per file
```

Successful response contains:

```json
{
  "message": "...",
  "status": "QUEUED",
  "queued_invoice_ids": [],
  "skipped_files": []
}
```

The backend creates an invoice record with:

```text
PROCESSING
```

before background extraction begins.

The frontend must therefore support asynchronous processing.

---

## 6. Invoice Processing Lifecycle

Current invoice statuses are:

```text
UPLOADED
PROCESSING
NEEDS_REVIEW
VALID
APPROVED
```

Meaning:

### UPLOADED

Invoice exists but processing has not started or has not advanced.

### PROCESSING

AI extraction/validation is running in the backend.

### NEEDS_REVIEW

Human intervention is required.

This can include:

- Validation warnings
- Low/unknown confidence
- Processing failure
- Other extraction problems

### VALID

Invoice passed automated validation and can proceed toward approval.

### APPROVED

Invoice has been approved and is locked into the master dataset.

The frontend must not invent additional backend statuses.

---

## 7. List Invoices

```http
GET /api/v1/invoices/
```

Supported query parameters:

```text
status
search
```

Example:

```text
/api/v1/invoices/?status=NEEDS_REVIEW
```

Example:

```text
/api/v1/invoices/?search=amazon
```

Current response contains invoice rows with:

```json
{
  "id": 1,
  "invoice_number": "...",
  "vendor_name": "...",
  "status": "VALID",
  "total_amount": 1234.56,
  "date": "2026-09-05"
}
```

Do not assume pagination exists in the current backend.

---

## 8. Invoice Details

```http
GET /api/v1/invoices/{invoice_id}
```

Current response includes:

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

Line items contain:

```text
description
quantity
unit_price
line_total
```

The `file_url` is the stored Supabase document URL and can be used by the frontend invoice/document viewer.

---

## 9. Human Review

Invoice corrections use:

```http
PATCH /api/v1/invoices/{invoice_id}
```

Current editable fields are:

```text
vendor_name
invoice_number
invoice_date
subtotal
tax_amount
total_amount
```

Do not assume other fields are editable through this endpoint.

Approved invoices are locked.

Attempting to modify an approved invoice returns:

```text
409
```

The frontend should visually communicate that approved invoices are read-only.

---

## 10. Approval

```http
POST /api/v1/invoices/{invoice_id}/approve
```

This changes the invoice status to:

```text
APPROVED
```

and locks it from subsequent editing through the current update endpoint.

The UI should clearly distinguish:

```text
Needs Review
Valid
Approved / Locked
```

---

## 11. CSV Export

```http
GET /api/v1/invoices/export/csv
```

The backend returns:

```text
ledger_export.csv
```

Current exported columns are:

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

The frontend should trigger the actual backend download rather than generating a different dataset client-side.

---

## 12. Current Backend Data Model

### Vendor

```text
id
raw_name
canonical_name
tax_id
```

### Invoice

```text
id
vendor_id
invoice_number
invoice_date
due_date
subtotal
tax_amount
total_amount
status
file_path
confidence_scores
validation_errors
created_at
```

### LineItem

```text
id
invoice_id
description
quantity
unit_price
line_total
```

Financial values currently use numeric floating-point fields.

Do not change the backend data representation from the frontend.

---

## 13. Frontend Architecture Principles

The frontend should be modular and maintainable.

Prefer:

```text
frontend/
├── src/
│   ├── api/
│   ├── components/
│   ├── hooks/
│   ├── layouts/
│   ├── pages/
│   ├── types/
│   ├── utils/
│   ├── App.*
│   └── main.*
├── public/
├── package.json
└── ...
```

Exact framework/library choices should follow the explicit frontend setup instructions rather than being invented.

Keep:

- API logic separate from UI
- reusable components separate from pages
- TypeScript types centralized
- invoice-specific logic organized
- environment configuration separate from source code

Do not put large API calls directly inside presentational components.

---

## 14. Frontend Application Flow

The main application flow should correspond to the backend lifecycle:

```text
Login
  ↓
Dashboard / Invoice Queue
  ↓
Upload invoice(s)
  ↓
PROCESSING
  ↓
Refresh/poll invoice state
  ↓
VALID ───────────────┐
                     ↓
NEEDS_REVIEW → Review/Edit
                     ↓
                  Approve
                     ↓
                 APPROVED
                     ↓
                Master Ledger
                     ↓
                   Export
```

The frontend must handle asynchronous processing gracefully.

It should not assume extraction completes immediately after upload.

---

## 15. Loading, Empty, Error and Processing States

Every major API-driven screen should have intentional states for:

- Loading
- Empty
- Processing
- Success
- Validation warning
- API error
- Upload rejection
- Not found
- Locked/approved

Do not leave blank screens while requests are running.

Do not hide backend errors from the user.

Errors should be displayed in a user-readable way while preserving useful technical information for debugging.

---

## 16. Stitch Design Implementation

The Stitch designs define the intended LedgerLens experience.

Implement the provided screens faithfully:

1. Authentication / Login
2. Invoice Ingestion & Triage Dashboard
3. Human-in-the-Loop Review
4. Master Ledger / Export

Preserve the visual language across screens.

Use reusable components rather than duplicating nearly identical markup.

Examples:

```text
Sidebar
Header
StatusBadge
ConfidenceIndicator
InvoiceTable
UploadDropzone
InvoiceSummary
LineItemsTable
ValidationPanel
ReviewForm
DocumentViewer
ExportControls
```

These are examples of component responsibilities, not requirements to create every component immediately.

---

## 17. Design vs Backend Capability

The Stitch design may show functionality that the current backend does not yet expose.

Examples may include:

- advanced analytics
- ERP integrations
- detailed audit systems
- accounting/GL mappings
- advanced fraud systems
- additional invoice metadata
- subscription/usage systems

Do not implement these as fake working backend features.

If necessary:

- preserve the visual design,
- show an appropriate disabled/unavailable state,
- or isolate the UI for future integration.

Clearly identify any backend capability that must be added later.

---

## 18. Authentication

Do not invent an authentication architecture.

The current backend does not expose a frontend authentication API in the invoice router.

If authentication is required for the frontend, first inspect the existing project configuration and explicitly provided requirements.

Do not modify Supabase Auth or backend authentication configuration without explicit instruction.

---

## 19. Security

Never expose:

- Supabase service-role keys
- API keys
- database passwords
- backend `.env` values
- other secrets

Never place backend secrets in frontend source code.

Frontend environment variables must only contain values intended for browser-side use.

---

## 20. Backend Changes

If a frontend feature cannot be implemented because the backend lacks an endpoint or field:

1. Stop before modifying the backend.
2. Identify the missing capability.
3. Explain what is required.
4. Wait for explicit instruction before changing backend or Supabase.

Do not use frontend work as an excuse to redesign the backend.

---

## 21. Testing

Before considering frontend work complete:

- Build the frontend successfully.
- Check browser console for errors.
- Test upload.
- Test processing state.
- Test invoice listing.
- Test search/filter.
- Test invoice details.
- Test review/edit.
- Test approval.
- Test approved read-only behavior.
- Test CSV export.
- Test invalid upload behavior.
- Test API failure states.
- Compare major screens against Stitch designs.

Existing backend tests must continue passing.

Backend regression:

```bash
cd backend
pytest tests/ -v
```

Do not modify backend tests merely to make unrelated frontend work pass.

---

## 22. Git Discipline

Make focused changes.

Do not:

- commit `.env`
- commit secrets
- commit generated caches
- commit unnecessary build artifacts
- overwrite working backend files without reason

Before committing:

```bash
git status
git diff
```

Keep frontend commits separate from backend changes whenever possible.

---

## 23. Implementation Philosophy

Prefer:

```text
Understand → inspect → implement → test → verify
```

over:

```text
Guess → implement → rewrite
```

Before implementing an unfamiliar backend integration, inspect the actual endpoint and response.

Before implementing a Stitch screen, inspect the provided design/code and understand its states.

Before introducing a dependency, determine whether the project already has an appropriate solution.

Keep the implementation simple and maintainable.

Do not over-engineer the MVP.

---

## 24. Current Product Boundary

The current LedgerLens MVP is:

```text
Invoice ingestion
        ↓
AI extraction
        ↓
Validation / triage
        ↓
Human review
        ↓
Approval
        ↓
Master ledger
        ↓
CSV export
```

The frontend should make this workflow excellent before expanding into advanced capabilities.

---

## 25. Important Instruction

When asked to implement a feature:

1. Inspect the relevant existing code.
2. Inspect the Stitch design if the feature has a corresponding design.
3. Determine whether the backend already supports the required behavior.
4. Implement the smallest appropriate frontend change.
5. Test it.
6. Report any missing backend capability instead of inventing one.

Preserve working infrastructure unless explicitly instructed otherwise.
