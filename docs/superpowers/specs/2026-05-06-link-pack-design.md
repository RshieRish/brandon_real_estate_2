# Link Pack — Brandon's Link-in-Bio Page

**Status:** Approved design, ready for implementation plan.
**Date:** 2026-05-06
**Author:** Brainstormed with Rishab.

---

## 1. Goal

Replace Brandon's externally-hosted `linktr.ee/soldwithsweeney` page with a self-hosted equivalent at `soldwithsweeney.com/links`, fully editable from the existing admin panel. The public page must visually match Brandon's current Linktree theme on first launch, but the theme is also editable so Brandon can re-skin without code changes.

This is a **reimplementation** built from Brandon's own theme configuration values (colors, fonts, geometry) and Brandon's own content (profile, photos, links). It is not a copy of Linktree's source code or any third-party UI components. Brand identity, layout, and styling decisions are recreated from the configuration token values, which are unprotectable design parameters.

The page is **separate from the existing Funnel system** (`apps/funnels`) — it has different content shape (link list vs. event-with-registration form) and a different lifecycle (singleton vs. multiple campaign pages).

## 2. Scope

**In v1:**
- Singleton public page at `/links`
- Admin CRUD at `/admin/link-pack` (4 tabs: Profile, Social, Links, Theme)
- 4 link types: `classic`, `thumbnail`, `group` (max 1 level deep), `email_gate`
- Theme editor (background, button style, font, social icon color)
- Per-link animations with `prefers-reduced-motion` respect
- Full SEO: title, description, OG/Twitter, JSON-LD `Person`
- Preview → Publish workflow (draft state → snapshot)
- Lead capture via email-gate, integrated with existing notification queue
- Analytics events on every link click
- Initial seed script that ports Brandon's current Linktree content to the DB

**Out of scope (deferred):**
- Multiple link-pack pages (only one ever exists)
- Custom domain / root URL rewrite (page is fixed at `/links`)
- Drag-and-drop between groups (reorder works within a parent only)
- Nested groups (groups cannot contain groups)
- Avatar shape variants (circle only)
- Banner image/video header above avatar
- A/B testing, scheduled publishing, link expiry
- Importing live from Linktree at runtime (one-shot seed only)
- i18n (English only)

## 3. Architecture overview

**Backend (FastAPI):** Two new SQLAlchemy models — `LinkPack` (singleton row, `id = 1`) holding profile + social + theme + published snapshot, and `LinkPackItem` (rows for each link, with optional `parent_id` for group children). New router `backend/routers/link_pack.py` mounted at `/api/v1/link-pack`. Image bytes stored in `LargeBinary` columns and served via dedicated endpoints — same pattern as the existing `Funnel.hero_image_data` flow, no S3 dependency.

**Frontend (Next.js):**
- Admin page: `frontend/src/app/admin/link-pack/page.tsx` — tabbed editor.
- Public page: `frontend/src/app/(linkpack)/links/page.tsx` with its own layout `(linkpack)/layout.tsx` — opts out of the main site's nav/footer so the page is full-bleed.
- Components: `LinkPackPage`, `LinkPackButton` (classic), `LinkPackThumbnailCard`, `LinkPackGroup`, `LinkPackEmailGate`, `LinkPackSocialRow`, `Avatar` (with optional verified badge).

**Theme application:** Theme tokens stored as JSON, applied at render time as CSS custom properties on the page wrapper. No Tailwind config changes needed for theme — the public page uses CSS variables directly.

## 4. Data model

```python
# backend/models/link_pack.py

class LinkPack(Base):
    __tablename__ = "link_pack"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1

    # Profile
    profile_name: Mapped[str] = mapped_column(String(255), default="")
    profile_bio: Mapped[str] = mapped_column(Text, default="")
    profile_photo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    profile_photo_mime: Mapped[str | None] = mapped_column(String(100))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Social row (any field can be empty — empty = hidden)
    social_phone: Mapped[str | None] = mapped_column(String(50))
    social_email: Mapped[str | None] = mapped_column(String(255))
    social_instagram: Mapped[str | None] = mapped_column(String(255))
    social_facebook: Mapped[str | None] = mapped_column(String(255))
    social_youtube: Mapped[str | None] = mapped_column(String(255))
    social_website: Mapped[str | None] = mapped_column(String(255))
    social_tiktok: Mapped[str | None] = mapped_column(String(255))
    social_x: Mapped[str | None] = mapped_column(String(255))

    # Theme (JSON — see Section 9)
    theme: Mapped[dict] = mapped_column(JSON, default=dict)

    # Background image (one slot, used by theme.background.type == 'image')
    background_image_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    background_image_mime: Mapped[str | None] = mapped_column(String(100))

    # Preview/publish workflow
    published_snapshot: Mapped[dict | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_unpublished_changes: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bookkeeping
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LinkPackItem(Base):
    __tablename__ = "link_pack_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_pack_id: Mapped[int] = mapped_column(ForeignKey("link_pack.id"), default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("link_pack_items.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)

    kind: Mapped[str] = mapped_column(String(20))  # classic | thumbnail | group | email_gate
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048))

    # Thumbnail (for kind='thumbnail' — property listings)
    thumbnail_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    thumbnail_mime: Mapped[str | None] = mapped_column(String(100))

    # Email-gate fields (for kind='email_gate')
    gated_file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    gated_file_mime: Mapped[str | None] = mapped_column(String(100))
    gated_filename: Mapped[str | None] = mapped_column(String(255))
    gate_modal_headline: Mapped[str | None] = mapped_column(String(255))
    gate_modal_subtext: Mapped[str | None] = mapped_column(Text)

    # Animation (applies to all kinds)
    animation: Mapped[str] = mapped_column(String(20), default="none")
    # none | pulse | wobble | shake | breathe | bounce

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**Validation invariants** (enforced in router/Pydantic schemas):
- `parent_id` may only point to an item where `kind = 'group'` (no nested groups).
- A `group` item may not have a `parent_id` (1-level depth).
- `kind = 'thumbnail'` requires `thumbnail_data` to be set.
- `kind = 'email_gate'` requires `gated_file_data` to be set.
- `kind = 'group'` ignores `url`.
- Items within the same `parent_id` (or all top-level items, where `parent_id IS NULL`) must have unique `position` values; `position` is reassigned on every reorder.

**Migration:** Single Alembic migration creates both tables. No schema changes to existing tables.

## 5. Backend API

All admin endpoints require `Depends(require_admin)`. Public endpoints are unauthenticated unless noted.

**Public:**
- `GET /api/v1/link-pack` — returns `published_snapshot` (or 404 if never published).
- `GET /api/v1/link-pack/images/profile` — serves `profile_photo_data` from published snapshot.
- `GET /api/v1/link-pack/images/background` — serves `background_image_data` from published snapshot.
- `GET /api/v1/link-pack/images/items/{item_id}/thumbnail` — serves item thumbnail from published snapshot.
- `POST /api/v1/link-pack/items/{item_id}/track-click` — increments `click_count`, writes `analytics_event(event_type="link_pack_click", payload={item_id, title, url})`.
- `POST /api/v1/link-pack/items/{item_id}/email-gate` — body `{name, email, phone?}`. Creates `Lead`, calls `enqueue_notification(event_type="link_pack_lead", ...)`, returns `{file_url, filename}` where `file_url` is a 5-minute signed JWT URL.
- `GET /api/v1/link-pack/gated/{item_id}?token=<jwt>` — serves `gated_file_data` if token is valid.

**Admin:**
- `GET /api/v1/link-pack/draft` — returns live (work-in-progress) state with all items.
- `PUT /api/v1/link-pack/profile` — updates profile fields. Sets `has_unpublished_changes = true`.
- `PUT /api/v1/link-pack/social` — updates social fields. Sets dirty flag.
- `PUT /api/v1/link-pack/theme` — updates theme JSON. Sets dirty flag.
- `POST /api/v1/link-pack/profile-photo` — multipart upload. Sets dirty flag.
- `POST /api/v1/link-pack/background-image` — multipart upload. Sets dirty flag.
- `POST /api/v1/link-pack/items` — create. Body validates against invariants. Sets dirty flag.
- `PATCH /api/v1/link-pack/items/{id}` — update. Sets dirty flag.
- `DELETE /api/v1/link-pack/items/{id}` — delete. If `kind = 'group'`, all children are deleted via cascade (`relationship(..., cascade="all, delete-orphan")` in SQLAlchemy). Sets dirty flag. Note: the `published_snapshot` may still reference this item until next publish — see "Snapshot/live-row drift" below.
- `POST /api/v1/link-pack/items/{id}/thumbnail` — multipart upload (image). Sets dirty flag.
- `POST /api/v1/link-pack/items/{id}/gated-file` — multipart upload (PDF, max 10MB). Sets dirty flag.
- `POST /api/v1/link-pack/items/reorder` — body `{parent_id: int|null, ordered_ids: [int, ...]}`. Reassigns `position` values. Sets dirty flag.
- `POST /api/v1/link-pack/publish` — serializes current live state → writes `published_snapshot`, sets `published_at = now()`, clears `has_unpublished_changes`.

**Constants:**
- `MAX_IMAGE_SIZE = 5 MB` (profile, thumbnails, background)
- `MAX_PDF_SIZE = 10 MB` (gated files)
- `ALLOWED_IMAGE_MIMES = {image/jpeg, image/png, image/webp, image/gif}`
- `ALLOWED_PDF_MIMES = {application/pdf}`
- Signed-URL TTL: 5 minutes; signing uses existing JWT secret with claim `{"item_id": int, "exp": ts}`.

## 6. Admin UX (`/admin/link-pack`)

**Sidebar:** Add "Link Pack" entry to `frontend/src/app/admin/layout.tsx`, between "Funnels" and "Content".

**Top status bar (sticky):**
- Status badge: `Live` (green) / `Draft changes pending` (gold) / `Not yet published` (gray)
- Last-published timestamp
- **Preview** button → opens `/links?preview=1` in a new tab
- **Publish changes** button — disabled when `has_unpublished_changes = false`. On click, opens a confirmation dialog: "Publish current draft to soldwithsweeney.com/links?". Success toast on completion.

**Tabs:**

1. **Profile**
   - Photo upload (with current image preview, replace/remove)
   - Name (text input)
   - Bio (textarea, 160-char hint)
   - Verified badge toggle
   - "Save Profile" button

2. **Social**
   - 8 fields: Phone, Email, Instagram, Facebook, YouTube, Website, TikTok, X
   - Empty field = hidden icon
   - "Save Social" button

3. **Links**
   - "+ Add Link" button at top right
   - Add/edit form:
     - Title (required)
     - Type dropdown: `Classic button` | `Thumbnail card (for properties)` | `Group (expandable)` | `Email-gated download`
     - URL (shown for Classic and Thumbnail; optional fallback for Email-gate; hidden for Group)
     - Thumbnail upload (shown only for Thumbnail; required there)
     - Gated file upload — PDF (shown only for Email-gate; required there)
     - Modal headline + subtext (shown only for Email-gate)
     - Animation dropdown (`none | pulse | wobble | shake | breathe | bounce`; default `none`)
     - Active toggle
   - List below: each item is a row with drag handle, title, type badge, animation badge, edit / delete buttons
   - Drag-and-drop reorder via `@dnd-kit/sortable`. Reorder is constrained to within the same parent (top-level or within a group); cross-container drag is not supported in v1.
   - Group rows expand inline showing children, each child editable; "+ Add child" button at the bottom of the children list inside an open group.

4. **Theme**
   - **Background** subsection: type radio (`solid` | `image`); color picker (visible always, used as `solid` color and as fallback under `image`); image upload (shown when type is `image`)
   - **Button** subsection: background color picker, text color picker, shadow color picker, corner radius radio (`pill` | `rounded` | `square`)
   - **Typography** subsection: font dropdown (`Montserrat` | `Inter` | `Roboto` | `Poppins` | `Playfair Display`) — all loaded via `next/font/google` in the public layout
   - **Social** subsection: icon color picker
   - "Save Theme" button
   - "Reset to default" button (re-seeds the original gold/black/Montserrat values)

Inline live preview is **not** in v1 — admin clicks Preview to open the public page in a new tab against draft state.

## 7. Public page (`/links`) — visual fidelity

**Route:** `frontend/src/app/(linkpack)/links/page.tsx` with sibling layout `(linkpack)/layout.tsx`. The route group ensures the page does not inherit the main site's header/footer.

**Rendering:** Server Component fetches `GET /api/v1/link-pack` at request time. `export const dynamic = 'force-dynamic'` (or `revalidate: 0`) — admin edits show on next request after publish.

**Theme application:** The page wrapper sets CSS custom properties from the published `theme` JSON:

```jsx
<div style={{
  '--lp-bg-color': theme.background.color,
  '--lp-btn-bg': theme.button.bg,
  '--lp-btn-text': theme.button.text,
  '--lp-btn-shadow': theme.button.shadow,
  '--lp-btn-radius': cornerRadiusValue,  // pill -> 9999px, rounded -> 12px, square -> 0
  '--lp-social-color': theme.social.color,
  '--lp-font': fontFamilyValue,
}}>
```

All component styles reference these variables, so changing theme in admin changes everything.

**Layout (top to bottom):**

1. Background layer — fixed full-viewport `<div>` with `--lp-bg-color` solid fill and (when `theme.background.type === 'image'`) the background image with `object-fit: cover`, centered.
2. Avatar — circular, 96px, white border ring, ~56px from top, centered. Verified blue checkmark badge (Phosphor `SealCheck` icon, blue `#2196f3`, white inner stroke) positioned at top-right of avatar when `is_verified === true`. We use the off-the-shelf Phosphor icon — not a copy of Linktree's specific verified mark.
3. Name — `<h1>`, 700 weight, `--lp-font`, white, ~18px, ~12px below avatar.
4. Bio — `<p>`, 400 weight, `--lp-font`, white, ~14px, max-width ~600px, centered.
5. Link list — vertical stack, max-width ~640px, centered, ~16px gap. Each item rendered by the right component for its `kind`.
6. Social row — horizontal centered row of icon-only links, color `--lp-social-color`, ~28px icons, ~24px gap, ~32px top margin.
7. Bottom padding ~64px.

**Default theme tokens** (initial seed, matches Brandon's current Linktree look):
```json
{
  "background": { "type": "image", "color": "#c78829" },
  "button":     { "bg": "#ffffff", "text": "#1E2330", "shadow": "#eac469", "corner": "pill" },
  "social":     { "color": "#ffffff" },
  "typography": { "font": "Montserrat", "color": "#ffffff" }
}
```

**Classic button** (`LinkPackButton`):
```css
background: var(--lp-btn-bg);
color: var(--lp-btn-text);
border-radius: var(--lp-btn-radius);
padding: 16px 24px;
font: 600 15px var(--lp-font);
text-align: center;
box-shadow: 0 6px 0 0 var(--lp-btn-shadow);
transition: transform 60ms;

&:active {
  transform: translateY(2px);
  box-shadow: 0 4px 0 0 var(--lp-btn-shadow);
}
```

**Thumbnail card** (`LinkPackThumbnailCard`) — for property listings. Same pill background and shadow as Classic, but with a 56px square thumbnail inset 8px on the left:
```
[ ▢ thumb ] [   Title text, vertically centered          ]
```
Title is left-aligned in this variant.

**Group** (`LinkPackGroup`) — same pill button, with a chevron-down on the right that rotates 180° when expanded. Click toggles `aria-expanded`. Children render inside a container with `display: grid; grid-template-rows: 0fr → 1fr` height transition (smooth open/close, no max-height hack). Closed by default. Each child is rendered as the appropriate sub-component (Classic / Thumbnail), slightly inset from the parent edges (~12px). Empty groups render as a 60% opacity, non-interactive button.

**Email-gate** (`LinkPackEmailGate`) — same pill button. Click opens a `<dialog>`-based modal with a dark overlay. Form fields: Name (required), Email (required, validated), Phone (optional). Submit button text comes from item's `title` or a sane default. On submit, POSTs to email-gate endpoint, receives signed file URL, triggers `<a download>` click, closes modal, shows a toast for 4 seconds.

**Social row** (`LinkPackSocialRow`) — horizontal flex row, ~24px gap. Phosphor Icons (`Phone`, `Envelope`, `InstagramLogo`, `FacebookLogo`, `YoutubeLogo`, `Globe`, `TiktokLogo`, `XLogo`), all at `--lp-social-color`, weight `regular`, 28px. Order: phone, email, instagram, facebook, youtube, website, tiktok, x — empty fields skipped.

**Responsive:** `max-w-[640px] mx-auto px-5`. Identical at 375px / 768px / 1024px+ — no special wide-viewport behavior.

## 8. Special link types

### Group (expandable accordion)
- Max 1 level deep; children of a group cannot themselves be groups (validated server-side).
- Empty groups visible but disabled-looking on public page.
- On admin: expandable inline, "+ Add child" button at the bottom of children list when expanded.

### Email-gate (lead-capture download)
- Backend flow: `POST /api/v1/link-pack/items/{id}/email-gate` body `{name, email, phone?}` → creates `Lead` row (`source = "link-pack:<item-id>"`, `lead_type = "link_pack"`, metadata includes item title) → calls `enqueue_notification(event_type="link_pack_lead", payload={item_id, item_title, name, email, phone})` (reuses existing notification queue from Funnel system) → mints a 5-minute JWT signed with the existing JWT secret, claim `{"item_id": int, "exp": <ts>}` → returns `{file_url: "/api/v1/link-pack/gated/<id>?token=<jwt>", filename: gated_filename}`.
- File-serving endpoint validates the token (exp, item_id match), returns the bytes with `Content-Disposition: attachment; filename=<gated_filename>`.
- Frontend: receives URL, triggers download via programmatic anchor click, closes modal, shows success toast.
- Lead row is the durable record even if the file fails to deliver.

## 9. Theme editor

Theme JSON shape:
```json
{
  "background": {
    "type": "solid" | "image",
    "color": "#RRGGBB"
  },
  "button": {
    "bg": "#RRGGBB",
    "text": "#RRGGBB",
    "shadow": "#RRGGBB",
    "corner": "pill" | "rounded" | "square"
  },
  "social": {
    "color": "#RRGGBB"
  },
  "typography": {
    "font": "Montserrat" | "Inter" | "Roboto" | "Poppins" | "Playfair Display",
    "color": "#RRGGBB"
  }
}
```

- Validated server-side via Pydantic — only allowed values for enum fields, hex-color regex for color fields.
- Fonts loaded via `next/font/google` in `(linkpack)/layout.tsx`. All five fonts loaded but only the chosen one's CSS variable is applied — keeps the bundle simple and changes apply instantly without rebuild.
- `corner` enum maps in CSS: `pill → 9999px`, `rounded → 12px`, `square → 0`.
- Background `color` is always set on the body (used as solid color, or as fallback under image).
- Background image is uploaded separately via `POST /api/v1/link-pack/background-image`. When `theme.background.type === 'image'` and a background image is set, the image renders on top of the color.

## 10. Animations

Per-link, optional. Field on `LinkPackItem`: `animation` enum `none | pulse | wobble | shake | breathe | bounce`. Default `none`.

CSS keyframes defined globally in the `(linkpack)/layout.tsx`:
- `pulse` — scale 1.0 → 1.04 → 1.0 over 2.4s, infinite
- `wobble` — rotate ±2deg over 2s, infinite
- `shake` — translateX ±3px over 0.6s, infinite (more attention-grabbing — good for limited-time CTAs)
- `breathe` — opacity 1 → 0.85 → 1 over 3s, infinite
- `bounce` — translateY 0 → -6px → 0 over 1.4s, infinite

Each `LinkPackButton` / `LinkPackThumbnailCard` / `LinkPackGroup` / `LinkPackEmailGate` applies `animation: var(--lp-anim-<kind>)` based on its item's `animation` field.

**Accessibility:** wrapped in:
```css
@media (prefers-reduced-motion: reduce) {
  .lp-anim-* { animation: none !important; }
}
```
Per WCAG 2.3.3.

## 11. SEO

`generateMetadata` in `(linkpack)/links/page.tsx`:

```ts
export async function generateMetadata(): Promise<Metadata> {
  const lp = await fetchPublishedLinkPack();
  if (!lp) return { title: 'Coming soon' };
  return {
    title: lp.profile_name,
    description: lp.profile_bio,
    openGraph: {
      title: lp.profile_name,
      description: lp.profile_bio,
      images: [{ url: lp.profile_photo_url, width: 800, height: 800 }],
      type: 'profile',
      url: 'https://soldwithsweeney.com/links',
    },
    twitter: {
      card: 'summary_large_image',
      title: lp.profile_name,
      description: lp.profile_bio,
      images: [lp.profile_photo_url],
    },
    alternates: { canonical: '/links' },
    robots: { index: true, follow: true },
  };
}
```

Plus an inline JSON-LD `<script type="application/ld+json">` rendered in the page body:
```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "<profile_name>",
  "image": "<profile_photo_url>",
  "url": "https://soldwithsweeney.com/links",
  "jobTitle": "Realtor",
  "sameAs": ["<instagram_url>", "<facebook_url>", "<youtube_url>", ...]
}
```

`sameAs` populated from the social fields that are non-empty. Improves Knowledge Graph / search-result entity recognition for Brandon's name.

## 12. Preview → Publish workflow

- Admin always edits **live** rows directly. Any write sets `LinkPack.has_unpublished_changes = true` (set explicitly in each mutating router; no DB triggers).
- Preview = `/links?preview=1`. Server-side checks for an admin JWT in the cookie; if valid, reads draft state instead of `published_snapshot`. If not authenticated, redirects to `/admin/login`.
- Publish = `POST /api/v1/link-pack/publish`. Serializes the full live state — profile fields, theme, social fields, all items (recursively, with parent/child structure preserved as nested arrays) — into `published_snapshot` JSON. Image bytes are NOT inlined into the JSON; they remain in their existing columns and the snapshot stores the public URLs. Sets `published_at = now()`, clears `has_unpublished_changes`.
- Public `/links` reads from `published_snapshot` only. If null (never published), renders a minimal "Coming soon" placeholder using just the profile name (gracefully handles initial deploy before first publish).

**Snapshot shape:**
```json
{
  "profile": { "name": "...", "bio": "...", "photo_url": "...", "is_verified": true },
  "social":  { "phone": "...", "email": "...", ... },
  "theme":   { ... },
  "background_image_url": "...",
  "items": [
    { "id": 1, "kind": "thumbnail", "title": "...", "url": "...", "thumbnail_url": "...", "animation": "none", "is_active": true, "children": [] },
    { "id": 4, "kind": "group", "title": "SWS AVAILABLE HOMES", "is_active": true, "children": [
      { "id": 5, "kind": "thumbnail", ... }
    ]}
  ]
}
```

Snapshot is regenerated atomically on every publish; no diffing.

**Snapshot/live-row drift:** Because the snapshot stores image URLs (not bytes), and image URLs resolve against the live `link_pack` / `link_pack_items` rows, deleting an item between publishes can leave the published page referencing a deleted image. Mitigation:
- Image-serving endpoints (`/api/v1/link-pack/images/items/{id}/thumbnail` etc.) return a 1×1 transparent PNG with `Cache-Control: no-store` if the underlying row or column is missing — the link still renders with its snapshotted text and shadow, just no image.
- Admin status bar shows the publish-needed indicator immediately on every mutation, nudging Brandon to re-publish.
- Documented as a known v1 quirk; if it ever becomes a real problem, v2 can copy image bytes into a snapshot-scoped store at publish time.

## 13. Asset pipeline + initial seed

**Theme background image** (Brandon's gold-and-black Linktree background): downloaded once at install time from Brandon's existing CDN URL and committed to `frontend/public/link-pack/initial-background.png`. The seed script reads this file and uploads it via the same path as the admin background-image endpoint, so it lives in the DB like any other admin upload. After install, the file under `public/` is no longer used and could be deleted.

**Profile photo and property thumbnails:** Stored in DB as `LargeBinary`. Initial seed downloads from Brandon's Linktree CDN URLs and writes to the appropriate columns.

**Seed script** `backend/scripts/seed_link_pack.py`:
1. Idempotent: if `LinkPack` row with `id = 1` exists, skip.
2. Fetch theme background, Brandon's headshot, and the two property thumbnails from their public CDN URLs (HTTP GET with browser User-Agent).
3. Create `LinkPack` row with profile name, bio, social fields, default theme, photo bytes, background bytes, `is_verified = true`.
4. Create the 11 `LinkPackItem` rows (top-level and group children) with the exact titles and URLs from Brandon's current Linktree (extracted from `__NEXT_DATA__` parsing).
5. Set thumbnails for the two listing items.
6. Mark `kind = 'email_gate'` for "SELLERS SURVIVAL GUIDE" with no file initially (Brandon uploads the PDF himself in admin); set its modal headline/subtext to sensible defaults.
7. Run an initial publish so `/links` renders immediately on first deploy.

**Run targets:**
- Locally: `python -m scripts.seed_link_pack` after `alembic upgrade head`.
- Railway: `python -m scripts.seed_link_pack` once after migration deploy.

## 14. Analytics

Every public link click fires `POST /api/v1/link-pack/items/{id}/track-click` (fire-and-forget from the frontend, `keepalive: true` so it survives navigation). Backend writes an `analytics_event` row with `event_type = "link_pack_click"`, `payload = {item_id, title, url}`, plus the existing fields the analytics router already records (timestamp, user-agent, referrer).

Email-gate submissions also fire a `link_pack_lead` analytics event (in addition to the Lead row + notification).

The existing `/admin/analytics` page will pick these up automatically since it reads from `analytics_events` already; a future enhancement could add a "Link Pack" filter, but that's out of scope for v1.

## 15. Accessibility

- All buttons and links have proper text or `aria-label`.
- Social row icons get `aria-label` based on the platform name.
- Verified badge has `<span class="sr-only">Verified</span>` for screen readers.
- Group buttons use `aria-expanded` and `aria-controls` linking to the children container's `id`.
- Email-gate modal uses `<dialog>` + `inert` on background + focus trap + `Esc` to close + return focus to invoking button.
- All animations respect `prefers-reduced-motion: reduce`.
- Color contrast: theme color picker shows a warning (non-blocking) if the chosen button text/bg pair fails WCAG AA (4.5:1). Admin can save anyway but is informed.
- Keyboard navigation: all interactive elements reachable via Tab; group expand toggles via Enter/Space.

## 16. Testing strategy

**Backend:**
- Pytest tests for each router endpoint: auth gating (admin endpoints reject without valid JWT), validation (kind invariants enforced, file size limits enforced), reorder correctness (positions reassigned monotonically per parent group).
- Integration test: seed script idempotency (run twice → no duplicates).
- Integration test: publish workflow (mutate → snapshot has new state, public read returns it).
- JWT signing/verification tests for the email-gate flow (5-minute expiry honoured, wrong item_id rejected).

**Frontend:**
- Component tests (Vitest + Testing Library) for `LinkPackButton`, `LinkPackThumbnailCard`, `LinkPackGroup`, `LinkPackEmailGate`, `LinkPackSocialRow` covering: rendering, animation classes, theme variable application.
- Admin form tests: type-switching shows/hides correct fields; reorder POST has correct payload; publish disabled when no pending changes.
- E2E test (Playwright if already set up; otherwise manual checklist) for the user journey: login → edit → preview → publish → public page reflects change.

**Visual QA:** After implementation, screenshot `localhost:3000/links` against `linktr.ee/soldwithsweeney` at 375px and 1024px viewports and check spacing, button corner radius, shadow distance, font size, and line height for drift. Tighten as needed.

## 17. Migration & rollout

**Phase 1 — Backend foundation**
- Create Alembic migration for `link_pack` and `link_pack_items` tables.
- Implement SQLAlchemy models, Pydantic schemas, router with admin CRUD + public GET + image serving + signed-URL email-gate.
- Tests for all endpoints.

**Phase 2 — Public page**
- Create `(linkpack)` route group + layout + `/links` page.
- Implement components: `LinkPackPage`, `LinkPackButton`, `LinkPackThumbnailCard`, `LinkPackGroup`, `LinkPackEmailGate`, `LinkPackSocialRow`, `Avatar`.
- Theme variable wiring + animations + `prefers-reduced-motion` guards.
- SEO (`generateMetadata` + JSON-LD).
- Component tests.

**Phase 3 — Admin UI**
- Add sidebar entry.
- Admin page with 4 tabs (Profile / Social / Links / Theme).
- `@dnd-kit` drag-and-drop reorder (within parent only).
- Status bar with Preview / Publish controls + confirmation dialog.
- Admin form tests.

**Phase 4 — Seed + ship**
- Write seed script.
- Run locally end-to-end against a fresh DB; verify the live page matches Brandon's Linktree visually.
- Deploy: backend migration → seed → frontend deploy → publish.
- Update Brandon's Instagram bio link from `linktr.ee/soldwithsweeney` to `soldwithsweeney.com/links`.

**Rollback plan:** `/links` is a new route; if anything breaks, the old Linktree URL still works. Removing the migration is destructive (loses admin edits Brandon has made), so during the first week we keep both live and only switch the bio link once we're confident.

---

## Decisions log (for context)

- **Why a separate model from `Funnel`?** Different content shape (link list vs. registration form), different lifecycle (singleton vs. multiple), and Brandon will manage them at different cadences.
- **Why bytes-in-DB for images?** Matches the existing `Funnel.hero_image_data` pattern. No S3 dependency. Will revisit if the page gets very heavy.
- **Why max 1-level group depth?** Brandon's existing Linktree never nests deeper. Limits UI complexity.
- **Why route group `(linkpack)` instead of just `/links`?** Lets the page opt out of the main site's nav/footer cleanly, no conditional layout logic.
- **Why "preview → publish" instead of full dynamic?** Brandon explicitly requested it; matches the existing Funnel system's draft/publish flow he already knows.
- **Why all five fonts loaded eagerly?** Theme can change instantly without rebuild. Five Google Fonts is acceptable bundle weight; if it becomes an issue, lazy-load.
