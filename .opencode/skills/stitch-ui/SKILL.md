---
name: stitch-ui
description: Implement the LedgerLens frontend faithfully from the provided Stitch UI/UX designs while preserving the existing design system and interaction patterns.
---

---

# Stitch UI Implementation Skill

## Purpose

Use this skill whenever implementing, reviewing, or modifying LedgerLens frontend UI based on the provided Stitch designs.

The Stitch designs are the primary visual reference for LedgerLens.

The goal is not to create a similar-looking application.

The goal is to reproduce the intended LedgerLens experience faithfully while adapting it to the real backend.

## Design Source

The provided Stitch project contains four primary screens:

```text
1. Authentication / Login
2. Invoice Ingestion & Triage Dashboard
3. Human-in-the-Loop Review
4. Master Ledger / Export
```

There is also a design specification:

```text
calm_intelligence/DESIGN.md
```

Use the supplied Stitch screen implementations and design specification as references when available.

Do not invent a separate visual language.

## Visual Fidelity

Preserve the design's:

- Overall layout
- Visual hierarchy
- Typography
- Spacing
- Borders
- Corner radii
- Cards
- Tables
- Navigation
- Icons
- Buttons
- Form controls
- Status indicators
- Upload experience
- Document review layout
- Empty states
- Loading states
- Error states
- Responsive behavior

Avoid unnecessary visual reinterpretation.

Do not replace the design with generic dashboard templates.

## Design System

Before implementing individual screens:

1. Inspect the supplied Stitch design.
2. Identify recurring design tokens.
3. Reuse those tokens consistently.

Pay particular attention to:

```text
Typography
Spacing
Surface/background hierarchy
Border treatment
Corner radius
Button styles
Input styles
Status colors
Table styling
Sidebar navigation
Card styling
Icon treatment
```

Create reusable frontend primitives where the same visual pattern appears repeatedly.

## Component Reuse

Prefer reusable components for recurring UI patterns.

Examples:

```text
AppShell
Sidebar
TopBar
Button
Input
Select
Modal
StatusBadge
ConfidenceIndicator
InvoiceTable
InvoiceRow
UploadDropzone
StatCard
ReviewPanel
LineItemsTable
ValidationAlert
DocumentViewer
```

These are examples rather than mandatory component names.

Create components based on actual repetition in the design.

Do not create excessive abstraction for tiny one-off elements.

## Screen 1 — Authentication

The Stitch authentication design should be implemented as the visual reference for the login experience.

Preserve:

- LedgerLens branding
- Login layout
- Input styling
- Remember-device UI
- Password recovery UI
- SSO presentation
- Supporting text
- Visual hierarchy

Authentication functionality must only use a real authentication system if one is actually configured.

Do not fabricate successful authentication.

If authentication is not yet connected, keep the visual implementation separate from fake authentication logic.

## Screen 2 — Ingestion & Triage Dashboard

This is the primary operational screen.

The UI should support the actual backend workflow:

```text
Upload
  ↓
PROCESSING
  ↓
VALID / NEEDS_REVIEW
```

The dashboard should consume real invoice data from:

```text
GET /api/v1/invoices/
```

The upload experience should use:

```text
POST /api/v1/invoices/upload
```

Support the backend's actual accepted file types:

```text
PDF
JPG
JPEG
PNG
```

Respect the 15 MB backend limit.

Do not pretend unsupported files were successfully uploaded.

## Processing State

After upload, the backend may return:

```text
status = QUEUED
```

with invoice IDs.

The frontend should then retrieve the invoice records and represent:

```text
PROCESSING
```

visually.

Do not immediately display an invoice as VALID merely because the upload request succeeded.

## Triage

Use the actual backend statuses:

```text
UPLOADED
PROCESSING
NEEDS_REVIEW
VALID
APPROVED
```

Map these statuses to the visual language established by Stitch.

Do not create additional backend statuses.

## Screen 3 — Human-in-the-Loop Review

The review screen should use the Stitch side-by-side workflow:

```text
Document
    ↔
Extracted invoice data
```

Retrieve the actual invoice through:

```text
GET /api/v1/invoices/{invoice_id}
```

The response may contain:

```text
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

Use these actual fields.

Do not display editable fields as though the backend supports editing them unless the update endpoint supports them.

Current editable fields are:

```text
vendor_name
invoice_number
invoice_date
subtotal
tax_amount
total_amount
```

Line-item editing is not currently supported by the backend update endpoint.

## Review Validation

Display backend validation warnings from:

```text
validation_errors
```

Display confidence information from:

```text
confidence_scores
```

Do not invent confidence values.

If confidence is missing, represent it as unknown/review rather than displaying a fabricated confidence score.

## Saving Corrections

Use:

```text
PATCH /api/v1/invoices/{invoice_id}
```

Only send fields supported by the backend.

Do not send unsupported fields merely because they appear in the visual design.

After saving:

- refresh the invoice state if appropriate
- provide clear success/error feedback
- preserve unsaved changes safely

## Approval

Use:

```text
POST /api/v1/invoices/{invoice_id}/approve
```

After approval:

```text
status = APPROVED
```

The UI must switch to a read-only state.

Do not leave editable controls active after approval.

## Screen 4 — Master Ledger

The master ledger should be based on actual invoice data.

Use:

```text
GET /api/v1/invoices/
```

and the supported status/search filters.

Approved invoices should be visually recognizable as approved/locked.

The export action should use:

```text
GET /api/v1/invoices/export/csv
```

Do not generate a different client-side CSV format unless explicitly instructed.

## Unsupported Design Features

Stitch may contain UI elements representing future functionality.

Examples:

```text
Advanced analytics
ERP synchronization
Advanced accounting mappings
Extended audit functionality
Additional invoice metadata
Subscription/usage information
```

Do not fabricate functionality to make these appear operational.

Instead use:

- disabled controls
- informative empty states
- future-feature presentation
- appropriate read-only UI

while preserving the intended design where practical.

## Responsive Design

The Stitch design should be treated as the visual reference across viewport sizes.

Do not simply allow desktop layouts to overflow on smaller screens.

Consider:

- sidebar behavior
- table overflow
- review panel layout
- document preview
- upload area
- navigation
- form controls

Maintain usability while staying faithful to the design.

## UI State Completeness

Every API-driven screen should intentionally support:

```text
Initial loading
Loading
Empty
Processing
Success
Validation warning
Error
Not found
Approved / locked
```

Do not rely on browser defaults for these states.

## Icons and Assets

Prefer the icon and asset approach already established by the Stitch implementation.

Do not replace the interface with arbitrary emoji or unrelated iconography.

If an exact asset is unavailable, choose the closest consistent implementation rather than introducing a visually unrelated element.

## Implementation Rule

For every Stitch screen:

```text
Inspect design
    ↓
Identify reusable patterns
    ↓
Map UI data to actual backend fields
    ↓
Implement
    ↓
Test interaction states
    ↓
Compare visually with Stitch
```

Do not begin by rewriting the entire application.

Implement incrementally.

## Golden Rule

When visual fidelity and backend capability conflict:

```text
Preserve the visual intent.
Never fake backend functionality.
```

The UI should look like LedgerLens.

The behavior should be truthful to the actual LedgerLens backend.
