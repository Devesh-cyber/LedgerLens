---
name: ledgerlens-architecture
description: Understand and work within the existing LedgerLens architecture without breaking the working backend, database, or Supabase infrastructure.
---

---

# LedgerLens Architecture Skill

## Purpose

Use this skill whenever implementing or reviewing LedgerLens functionality that interacts with the application architecture.

LedgerLens consists of:

```text
Frontend
   ↓
FastAPI Backend
   ↓
PostgreSQL / Supabase
   +
Supabase Storage
   ↓
AI invoice extraction + validation
```

The current backend is already implemented and tested.

The current task is primarily frontend implementation.

## Existing Backend

Backend location:

```text
backend/
```

Important files:

```text
backend/main.py
backend/src/api/routes.py
backend/src/models/model.py
backend/src/schemas/extraction.py
backend/src/services/extractor.py
backend/src/services/validator.py
```

The backend must be treated as an existing system, not a system to redesign.

## Current API

Invoice API prefix:

```text
/api/v1/invoices
```

Available operations:

```text
POST   /api/v1/invoices/upload
GET    /api/v1/invoices/
GET    /api/v1/invoices/{invoice_id}
PATCH  /api/v1/invoices/{invoice_id}
POST   /api/v1/invoices/{invoice_id}/approve
GET    /api/v1/invoices/export/csv
```

Always inspect the actual backend implementation before assuming behavior.

## Invoice Lifecycle

Use only these statuses:

```text
UPLOADED
PROCESSING
NEEDS_REVIEW
VALID
APPROVED
```

The normal flow is:

```text
Upload
  ↓
PROCESSING
  ↓
VALID
  ↓
APPROVED
```

or:

```text
PROCESSING
  ↓
NEEDS_REVIEW
  ↓
Human correction
  ↓
Approval
  ↓
APPROVED
```

Processing failures are currently represented as `NEEDS_REVIEW` with an error stored in `validation_errors`.

Do not create a new frontend-only status called `FAILED`.

## Data Model

Invoice data currently includes:

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

Do not assume fields exist simply because they appear in the Stitch design.

## Supabase

Supabase Storage and PostgreSQL are existing infrastructure.

Do not:

- create new buckets
- rename buckets
- change bucket policies
- change database schemas
- add migrations
- modify RLS
- replace Supabase
- change existing storage paths

unless the user explicitly requests such a change.

## Frontend Integration

The frontend should consume the existing API through a dedicated API layer.

Prefer:

```text
UI Component
    ↓
Hook / application logic
    ↓
API client
    ↓
FastAPI
```

Avoid scattering raw `fetch()` calls throughout components.

Centralize:

- API base URL
- request handling
- error handling
- response typing

## Asynchronous Processing

Upload does not mean extraction is complete.

After upload:

```text
POST /upload
     ↓
queued_invoice_ids
     ↓
invoice status = PROCESSING
     ↓
frontend refreshes/polls
     ↓
VALID / NEEDS_REVIEW
```

The UI must communicate processing state clearly.

Do not assume the uploaded invoice is immediately available with complete extracted fields.

## Approval Lock

Once an invoice is:

```text
APPROVED
```

the frontend must treat it as read-only.

Do not display editable controls for approved invoices.

The backend returns HTTP 409 if an approved invoice is edited.

The frontend should still enforce the appropriate UI state before making the request.

## Unsupported Functionality

The Stitch designs may contain concepts not currently supported by the backend.

Examples:

```text
advanced analytics
ERP synchronization
additional accounting fields
advanced audit functionality
subscription/usage systems
```

Do not fabricate API responses or create fake persistence.

If a design element cannot currently be backed by the API:

1. Preserve the intended visual design where appropriate.
2. Use a disabled/read-only/future state.
3. Document the missing backend capability.
4. Do not modify the backend automatically.

## Security

Never place these in frontend code:

```text
SUPABASE_SERVICE_ROLE_KEY
database passwords
GROQ_API_KEY
private backend credentials
backend .env contents
```

Only browser-safe configuration may be exposed to the frontend.

## Development Rule

Before changing architecture:

```text
Inspect → Understand → Implement → Test
```

Do not redesign working infrastructure merely to make frontend development easier.

Prefer the smallest change that satisfies the requirement.
