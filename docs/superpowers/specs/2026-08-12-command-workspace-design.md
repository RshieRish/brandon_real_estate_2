# Brandon Command Workspace Design

**Date:** 2026-08-12  
**Status:** Approved design; implementation plan pending review

## Goal

Add a new authenticated `/admin/command` route alongside the current admin panel. It will provide a premium, Brandon-branded operational workspace inspired by the captured Command and DocuSign interaction patterns, while using the application's FastAPI and PostgreSQL stack as the system of record.

The workspace must be fully wired to real data from day one. It is not a visual mockup and must not duplicate or displace the existing `/admin/*` pages.

## Product Boundaries

- Preserve all existing admin routes and their current behavior.
- Keep all API/business logic in FastAPI; Next.js is a presentation and interaction layer only.
- Use PostgreSQL for durable CRM, task, opportunity, automation, agreement, activity, and audit data.
- Use configured object storage for agreement/template file bytes. PostgreSQL stores file metadata, ownership, lifecycle state, and relationships.
- Do not integrate the DocuSign API in this release.
- Agreement management provides internal templates, PDFs, recipients, lifecycle tracking, and immutable audit activity. Executing legally binding signatures is deferred until a dedicated signature provider or in-house signing architecture is approved.
- Preserve current lead, booking, funnel, content, analytics, compliance, and Maps behavior as authoritative sources rather than copying data into parallel systems.

## Information Architecture

### Command Home

An operational dashboard with:

- leads never contacted and recently active contact queues;
- birthdays and anniversaries;
- personal/team/all task widget;
- upcoming bookings, market-center/event placeholder, database health, and pipeline health;
- AI briefing with grounded, auditable recommendations.

### Contacts

- Searchable/filterable contact directory backed by legacy leads plus normalized `crm_contacts`.
- Contact profile tabs: Timeline, Opportunities, Smart Plans, Tasks, Notes, Saved Searches.
- Profile identity, tags, contact preferences, linked bookings, ownership/assignee, neighborhood/property context, and map.
- Timeline combines legacy lead/booking/funnel events with first-class CRM activities.

### Tasks

- To Do, Completed, and Archived views.
- Priority, due date, assignee, source, links, filters, bulk updates, task details, and state transitions.
- Tasks can link to contacts, bookings, opportunities, campaigns, or agreements.

### Smart Plans

- Plans and library views.
- Step types: wait/delay, task, email, note, tag, notification, and condition-ready extension point.
- Enrollment, activity history, ownership, publishing state, and plan step expansion.
- Automated sends/actions must be executed by backend jobs, with compliance review before enablement.

### Opportunities

- Buyer, seller, investor, listing, and lease pipeline types.
- Board, phase, value, expected close, owner/assignee, and contact linkage.
- Detail tabs: Details, Documents, Offers & Commissions, Vendors, Notes, Timeline, Tasks.

### Marketing

- Existing funnels and content blocks surfaced as campaign/design resources.
- Email campaign records, social calendar, direct-mail records, campaign metrics, and design/content links.
- Existing content and analytics remain authoritative; CRM records provide organization and cross-links.

### Agreements

- Template list and template file attachment.
- Agreement record, linked PDF/file assets, recipients, status, expiry, internal owner, linked contact/opportunity, and internal audit timeline.
- States: Draft, In Review, Ready, Sent/Shared, Viewed, Completed, Voided, Expired.
- The first release records and manages the lifecycle but never misrepresents an internal review record as a legally executed signature.

### Reports

- Lead conversion, booking, pipeline, marketing, task, agreement, and database-health reporting.
- Existing analytics events are reused; new CRM events are added through the same analytics/audit conventions.

### Listings, Search, and Map

- Listing records, saved searches, property/contact links, map/filter experience, and listing-related opportunities.
- All Maps/provider calls remain server mediated through the existing backend Maps service.

### Websites

- A Command module that links/surfaces existing content and funnel management without duplicating editing logic.

### AI Workspace

- Brandon Briefing dashboard: workload, contact risk, overdue follow-up, pipeline movement, and booking insights.
- Context actions: summarize contact, recommend next step, draft follow-up, summarize opportunity, flag activity risk, and generate compliant marketing copy.
- Every AI request runs in FastAPI, is compliance-scanned, and writes an audit record. UI never calls Gemini directly.

## Data Model

Existing models remain authoritative: `leads`, `bookings`, `funnels`, `content_blocks`, `analytics_events`, and current admin/auth models.

New SQLAlchemy/Alembic models:

- `crm_contacts` — normalized contact record with optional legacy lead linkage and owner/assignee.
- `crm_tags`, `crm_contact_tags` — reusable contact categorization.
- `crm_activities` — append-only activity stream with typed source/metadata.
- `crm_notes` — contact/opportunity scoped notes.
- `crm_tasks`, `crm_task_links` — durable work items and polymorphic links.
- `crm_smart_plans`, `crm_smart_plan_steps`, `crm_smart_plan_enrollments` — automation plans, steps, and enrollment activity.
- `crm_opportunities`, `crm_opportunity_contacts`, `crm_opportunity_vendors`, `crm_opportunity_offers` — deal workflow.
- `crm_saved_searches`, `crm_listing_records` — saved property searches and internal listing context.
- `crm_agreement_templates`, `crm_agreements`, `crm_agreement_recipients`, `crm_agreement_events`, `crm_file_assets` — internal agreement workspace and file metadata.

Relationships use foreign keys where the entity is owned by the new CRM domain and stable typed identifiers for cross-domain legacy links. Creation/migration must be idempotent: legacy leads/bookings should be linked to contacts without loss or duplicate CRM contacts.

## API Design

New FastAPI router family under `/api/v1/command`:

- `/overview`
- `/contacts`, `/contacts/{id}`, `/contacts/{id}/timeline`, `/contacts/{id}/notes`, `/contacts/{id}/tasks`, `/contacts/{id}/opportunities`, `/contacts/{id}/smart-plans`, `/contacts/{id}/saved-searches`
- `/tasks`, `/tasks/{id}`
- `/smart-plans`, `/smart-plans/{id}`, `/smart-plans/{id}/enrollments`
- `/opportunities`, `/opportunities/{id}`, and child resources
- `/agreements`, `/agreement-templates`, `/files`
- `/reports/*`
- `/ai/*`

All routes require current admin authentication and return typed schemas. Pagination, filtering, sorting, ownership boundaries, validation, audit records, and consistent error responses are mandatory.

## Frontend Architecture

- Route: `frontend/src/app/admin/command/page.tsx` with nested client workspace components.
- Keep page-level data loading and mutations behind typed `frontend/src/lib/api.ts` command-client helpers.
- Break screens into independently testable modules: shell/navigation, shared data grid, details pane, timeline, tasks, opportunities, smart plans, agreements, reporting, maps, and AI actions.
- Use loading skeletons, explicit empty states, optimistic updates only when rollback/error states are present, and mobile-responsive detail drawers.

## Visual and Interaction Direction

- Follow the captured Command UI's information architecture: persistent rail, dense utility header, list-to-detail flow, tabs, boards, detail panels, filters, and full-screen workspace modules.
- Do not copy Keller Williams trademarks, logo, wording, or colors.
- Apply Sold With Sweeney & Co. brand: black `#0a0a0a`, gold `#eac469`, white, gray, bronze, Montserrat, dark premium surfaces, gold halftone texture, glass panels, and restrained cinematic motion.
- Use `@phosphor-icons/react`; no emojis.
- Use `min-h-[100dvh]`, not `h-screen`.
- Framer Motion transitions use spring `{ stiffness: 100, damping: 20 }`, staggered entrances, and `AnimatePresence` for panels/drawers.
- Use accessible labels, keyboard-operable tabs/drawers, and non-color-only status affordances.

## Error Handling and Audit

- API errors use a consistent detail/schema with human-readable UI states.
- File upload validates type, size, ownership, and storage availability before a durable record is created.
- Agreements show state history and avoid implying e-signature execution.
- AI failures preserve user context, display retry affordances, and never lose manual edits.
- Mutations to task, opportunity, agreement, AI, and file lifecycle write audit activity.

## Testing and Verification

- Alembic migration tests plus unit tests for link/idempotency behavior.
- FastAPI router tests for auth, CRUD validation, lifecycle transitions, pagination, and file metadata guards.
- Frontend tests for data transformations and high-risk interactive components.
- TypeScript, lint, production build, and targeted browser validation of route authentication, shell navigation, contact/tabs, tasks, opportunity details, agreement lifecycle, and error/empty states.

## Delivery Order

1. Data models, migrations, contact linking, router base, and typed client.
2. Command shell, overview, contacts, tasks, and shared activity/timeline.
3. Opportunities, Smart Plans, reports, Listings/Map/search integration.
4. Agreements/templates/files and audit UI.
5. Marketing/website surfaces, AI briefing/actions, full visual QA, and production verification.
