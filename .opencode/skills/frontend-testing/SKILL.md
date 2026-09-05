---
name: frontend-testing
description: Test LedgerLens frontend behavior, API integration, UI states, and visual fidelity without modifying the working backend.
---

---

# LedgerLens Frontend Testing Skill

## Purpose

Use this skill whenever implementing, reviewing, or completing LedgerLens frontend work.

The objective is to verify both:

1. The frontend looks and behaves correctly according to the Stitch designs.
2. The frontend communicates correctly with the existing FastAPI backend.

A feature is not complete merely because it renders without a build error.

---

## Testing Philosophy

Use this sequence:

```text
Implement
   ↓
Build
   ↓
Run
   ↓
Interact
   ↓
Test API integration
   ↓
Test failure states
   ↓
Compare against Stitch
   ↓
Fix
   ↓
Re-test
```

Prefer real application behavior over screenshots or static mock data.

---

## Build Verification

The frontend must successfully build using the project's configured build command.

Check for:

- compilation errors
- TypeScript errors
- unresolved imports
- missing assets
- invalid routes
- dependency problems
- environment configuration problems

Do not consider the frontend complete if the production build fails.

---

## Browser Console

Check the browser developer console during testing.

There should be no unexplained:

- JavaScript exceptions
- React rendering errors
- failed module loads
- repeated API failures
- invalid requests
- broken asset requests

Warnings should be evaluated rather than automatically ignored.

---

## Backend Availability

For integration testing, the FastAPI backend must be running.

Current backend entry point:

```text
backend/main.py
```

The frontend should connect to the configured backend URL.

Do not hardcode a production backend URL.

---

## Core User Flow

Test the complete LedgerLens workflow:

```text
Open application
   ↓
Authentication screen
   ↓
Dashboard
   ↓
Upload invoice
   ↓
Queued
   ↓
Processing
   ↓
Valid / Needs Review
   ↓
Open invoice
   ↓
Review extracted data
   ↓
Correct fields if necessary
   ↓
Approve
   ↓
Approved / Locked
   ↓
Master Ledger
   ↓
CSV Export
```

Each transition must be tested where the backend supports it.

---

## Authentication Screen

Verify:

- page renders
- inputs work
- password field behaves correctly
- remember-device UI works visually
- forgot-password UI is present
- SSO UI is present where designed
- responsive layout works

Do not claim authentication succeeds unless a real authentication implementation exists.

If authentication is not connected yet, test the visual and interaction layer without fabricating authentication success.

---

## Upload Testing

Test supported file types:

```text
PDF
JPG
JPEG
PNG
```

Test:

- single upload
- multiple upload
- drag-and-drop if implemented
- file picker
- upload progress/state
- successful queue response
- skipped/rejected files
- oversized files
- unsupported extensions

Backend limit:

```text
15 MB per file
```

The UI must communicate rejected files clearly.

Do not silently discard upload failures.

---

## Processing Testing

After a successful upload:

Verify that the frontend recognizes:

```text
QUEUED
```

as the upload response state.

Then verify that invoice records transition through:

```text
PROCESSING
```

and eventually reach:

```text
VALID
```

or:

```text
NEEDS_REVIEW
```

The UI must not incorrectly show:

```text
APPROVED
```

immediately after upload.

---

## Polling / Refresh Testing

If polling is implemented:

Verify:

- requests occur at a reasonable interval
- multiple polling loops are not created
- polling stops after processing completes
- polling stops when leaving the page
- errors do not create an infinite loop
- unnecessary requests are avoided

If manual refresh is used instead, verify that it correctly retrieves the latest invoice state.

---

## Invoice List Testing

Test:

```text
GET /api/v1/invoices/
```

Verify:

- invoices render
- vendor names render
- invoice numbers render
- totals render
- dates render
- status badges match actual statuses
- empty state works
- loading state works
- API error state works

Test search using:

```text
search
```

Test status filtering using:

```text
status
```

Do not assume pagination exists.

If pagination is shown in the Stitch design but unsupported by the backend, do not fabricate server-side pagination.

---

## Invoice Details Testing

Open an invoice and verify:

```text
GET /api/v1/invoices/{invoice_id}
```

Verify:

- vendor
- vendor tax ID
- invoice number
- invoice date
- due date
- subtotal
- tax
- total
- validation errors
- confidence scores
- line items
- document preview

Verify that the `file_url` actually loads when the backend provides a usable document URL.

If the document cannot be displayed, show a clear fallback rather than a broken viewer.

---

## Human Review Testing

For a reviewable invoice:

Verify:

- extracted values are visible
- validation warnings are visible
- confidence information is represented correctly
- editable fields are clearly editable
- unsupported fields are not falsely editable
- changes can be saved
- save feedback is displayed

Current editable fields:

```text
vendor_name
invoice_number
invoice_date
subtotal
tax_amount
total_amount
```

Do not test line-item editing as a supported backend operation.

---

## Correction Testing

Use:

```text
PATCH /api/v1/invoices/{invoice_id}
```

Verify:

- only supported fields are submitted
- successful save updates the UI
- API errors are shown
- unsaved changes are not silently lost

Test refreshing the invoice after saving to verify persistence.

Do not rely only on local frontend state to claim a correction was saved.

---

## Approval Testing

Use:

```text
POST /api/v1/invoices/{invoice_id}/approve
```

Verify:

```text
status = APPROVED
```

Then verify the UI becomes read-only.

Check that:

- edit controls disappear or become disabled
- approval action is no longer available
- locked state is clearly communicated
- invoice remains visible in the ledger

---

## Approved Invoice Lock Testing

Attempt to edit an approved invoice.

The backend returns:

```text
HTTP 409
```

The frontend must handle this gracefully.

Expected behavior:

```text
409
 ↓
Refresh invoice
 ↓
Show APPROVED / LOCKED
 ↓
Disable editing
```

Do not show a generic unexplained error when the real cause is that the invoice is locked.

---

## Master Ledger Testing

Verify:

- ledger loads
- approved invoices are represented correctly
- filters work
- search works
- totals display correctly
- empty state works
- loading state works
- API errors work

Do not fabricate analytics values.

If the Stitch design shows statistics that the backend does not currently provide, identify the missing backend capability rather than inventing values.

---

## CSV Export Testing

Trigger:

```text
GET /api/v1/invoices/export/csv
```

Verify:

- download starts
- downloaded file opens
- file contains actual backend data
- filename is appropriate
- exported columns match backend output

Current columns:

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

Do not silently substitute a client-generated schema.

---

## Error Testing

Test at least:

```text
Network failure
404 invoice
409 approved invoice edit
Upload rejection
Oversized file
Unsupported file
Backend unavailable
Malformed/unexpected response
```

Every error should have a sensible UI representation.

Avoid exposing:

- stack traces
- API keys
- database credentials
- internal secrets

---

## Empty States

Explicitly test:

- no invoices
- no search results
- no review items
- no ledger records
- no uploaded files

Empty states should follow the Stitch visual language.

Do not fill empty states with fake production invoices.

---

## Loading States

Test slow responses.

The interface should communicate that work is occurring.

Avoid:

- blank screens
- frozen buttons
- duplicate submissions
- layout jumps where avoidable

---

## Responsive Testing

Check the major screens at:

```text
Desktop
Tablet
Mobile
```

Pay particular attention to:

- sidebar
- invoice tables
- review side-by-side layout
- document viewer
- upload area
- forms
- navigation

Do not simply hide important information to make the layout fit.

---

## Visual Verification

Compare implemented screens against the Stitch designs.

Check:

```text
Layout
Spacing
Typography
Colors
Borders
Radius
Icons
Button sizes
Table density
Cards
Navigation
Alignment
Visual hierarchy
```

Prioritize major visual differences before minor pixel-level differences.

---

## API Contract Verification

When an integration behaves unexpectedly:

1. Inspect the actual backend endpoint.
2. Inspect the actual response.
3. Inspect the frontend request.
4. Identify the mismatch.
5. Fix the frontend if the backend contract is correct.

Do not immediately modify the backend.

---

## Backend Regression

Frontend testing must not break the backend.

After any authorized backend change, run:

```bash
cd backend
pytest tests/ -v
```

Current baseline:

```text
7 passed
```

If backend code was not intentionally changed, do not modify backend tests simply because frontend work exposed an unrelated issue.

---

## Test Data

Use real invoice files for integration testing when available.

Use mock data only for:

- isolated components
- visual development
- explicit demo states
- automated tests

Never allow mock data to silently become the application's production data source.

---

## Completion Criteria

A frontend feature is considered complete only when:

```text
✓ Builds successfully
✓ No unexplained browser errors
✓ Correct API endpoint used
✓ Correct request payload used
✓ Correct response interpreted
✓ Loading state works
✓ Empty state works
✓ Error state works
✓ Success state works
✓ Stitch design is reasonably faithful
✓ Responsive behavior works
✓ Existing backend remains intact
```

For invoice workflow features, also verify the real end-to-end state transition.

---

## Golden Rule

A successful test is not:

```text
"The page rendered."
```

A successful test is:

```text
"The user can perform the intended LedgerLens workflow,
the UI represents the real backend state,
and failures are handled honestly."
```
