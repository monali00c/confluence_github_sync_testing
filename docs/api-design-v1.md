
---
title: API-design-v1
sync_to_confluence: true
confluence-labels:
  - technical
  - spec
  - ipms
---

# API Design Reference — Bandhan Bazar
**API-BB-001 v1.1 · NestJS + TypeORM · Base URL: `https://api.bandhanbaazar.com/api/v1`**

> **Claude Code:** Read this file when implementing any controller, service, guard, or DTO. All endpoint paths, request bodies, response shapes, and error codes are defined here. Do not deviate from these contracts.

---

## Meta

| Property | Value |
|---|---|
| Schema version | DB-SCHEMA-BB-001 v1.1 |
| Architecture | Multi-profile — one `partner_users` account owns many `partner_profiles` |
| Column naming | TypeORM camelCase in request/response — maps to snake_case in DB via NamingStrategy |
| Format | JSON · UTF-8 · `Content-Type: application/json` |
| Pagination | Cursor-based: `after` (UUID), `limit` (default 20, max 100) |
| Error format | `{ code: string, message: string, field?: string }` |
| Versioning | All routes under `/api/v1/` — breaking changes go to `/api/v2/` |

---

## Auth model

| Token | Mechanism | Expiry |
|---|---|---|
| Access token | Bearer JWT in `Authorization` header. Payload: `{ sub: userId, iat, exp }` | 24h |
| Refresh token | httpOnly cookie. Redis set per user (multi-device). | 30 days sliding |
| Admin session | Server-side session + IP whitelist + 2FA. | — |
| OTP | 6-digit, SHA-256 hashed in `otp_verifications_txn`. Redis fast path, DB for persistence. | 10 min |

---

## §1 Design principles

- Routes versioned under `/api/v1/` — never change a published contract
- TypeORM camelCase in request/response bodies maps to snake_case in DB via NamingStrategy
- Every write endpoint returns the updated resource — no separate GET needed after POST/PATCH
- PATCH = partial update — only provided fields modified
- File uploads never through the API server — presigned S3 URLs only
- Multi-profile: all partner-scoped endpoints are scoped to a `profileId` path param
- `partner_pricing` updates never trigger re-moderation of `partner_profiles`
- `audit_logs_history` is append-only — never call update/delete on its repository

---

## §2 Authentication

### Auth model

| Token | Mechanism | Expiry |
|---|---|---|
| Access token | Bearer JWT in `Authorization` header. Payload: `{ sub: userId, email, iat, exp }` | 24h |
| Refresh token | httpOnly cookie `refresh_token`. Opaque 64-byte hex, SHA-256 hash stored in Redis sorted set per user (multi-device). | 30 days sliding |
| Password reset token | Opaque 32-byte hex, SHA-256 hash stored in Redis. Single-use. | 15 min |
| OTP | 6-digit, SHA-256 hashed. Redis fast path + `otp_verifications_txn` for lockout durability. | 10 min |

> **Cookie spec:** `refresh_token` cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api/v1/auth`, `MaxAge=2592000`.
> **Email OTP delivery:** SendGrid with custom template.
> **SMS OTP delivery:** MSG91.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/auth/register` | Public | Create account. Returns JWT pair + sets refresh cookie. |
| POST | `/auth/login` | Public | Email + password. Returns JWT pair + sets refresh cookie. |
| POST | `/auth/refresh` | Cookie | Rotate refresh token. Returns new access token + rotated cookie. |
| DELETE | `/auth/logout` | JWT | Revoke current-device refresh token. Clears cookie. |
| DELETE | `/auth/logout/all` | JWT | Revoke all devices. Clears cookie. |
| POST | `/auth/otp/send` | Public | Send OTP. Purpose: `phone_verification` \| `email_verification` \| `password_reset`. |
| POST | `/auth/otp/verify` | Public | Verify OTP. Marks `phoneVerified=true` or returns `resetToken`. |
| POST | `/auth/forgot-password` | Public | Send password-reset OTP to email. Always 200 (no enumeration). |
| POST | `/auth/reset-password` | Public | Verify reset token + set new password. |

### `POST /auth/register`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `phone` | string | YES | E.164 (+91XXXXXXXXXX). UNIQUE. |
| `phoneOtp` | string | YES | 6-digit. Verified inline. |
| `whatsappNumber` | string | No | E.164. If null, `phone` used for WA notifications. |
| `email` | string | YES | UNIQUE in `partner_users`. |
| `emailOtp` | string | YES | 6-digit. Verified inline. |
| `password` | string | YES | 8–72 chars. bcrypt cost 12. |
| `firstName` | string | YES | Max 100 chars. |
| `lastName` | string | YES | Max 100 chars. |
| `salutation` | string | No | Mr \| Ms \| Mrs \| Dr |
| `categoryIds` | integer[] | YES | Min 1. Each must exist in `categories_inventory`. |
| `baseCity` | string | YES | Max 100 chars. Stored in `onboarding_states.stepData.step1`. Written to `partner_addresses_details` (type: `base`) on onboarding submit. |

**Responses:**
- `200` — `{ accessToken, tokenType: 'Bearer', expiresIn: 86400, user: { id, email, phone, phoneVerified: true, emailVerified: true } }` + `Set-Cookie: refresh_token`
- `409` — `{ code: 'ACCOUNT_EXISTS' }` — phone or email already registered
- `422` — `{ code: 'PHONE_OTP_INVALID' }` — phone OTP wrong or expired
- `422` — `{ code: 'PHONE_OTP_LOCKED', lockedUntil }` — phone OTP locked
- `422` — `{ code: 'EMAIL_OTP_INVALID' }` — email OTP wrong or expired
- `422` — `{ code: 'EMAIL_OTP_LOCKED', lockedUntil }` — email OTP locked
- `422` — `{ code: 'CATEGORY_NOT_FOUND' }` — invalid categoryId
- `422` — `{ code: 'INVALID_MOBILE', field: 'phone' }`

### `POST /auth/login`

**Body:**
| Field | Type | Req |
|---|---|---|
| `email` | string | YES |
| `password` | string | YES |

**Responses:**
- `200` — `{ accessToken, tokenType: 'Bearer', expiresIn: 86400, user: { id, email, phone, phoneVerified } }` + `Set-Cookie: refresh_token`
- `401` — `{ code: 'INVALID_CREDENTIALS' }`
- `401` — `{ code: 'ACCOUNT_INACTIVE' }` — pending admin activation

### `POST /auth/refresh`

**Cookie:** `refresh_token` (read automatically)

**Responses:**
- `200` — `{ accessToken, tokenType: 'Bearer', expiresIn: 86400 }` + rotated `Set-Cookie: refresh_token`
- `401` — `{ code: 'TOKEN_INVALID' }`

### `DELETE /auth/logout` / `DELETE /auth/logout/all`

**Header:** `Authorization: Bearer <accessToken>`

**Responses:**
- `204` — cookie cleared, Redis entry removed

### `POST /auth/otp/send`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `contact` | string | YES | Phone (E.164) for `phone_verification`; email for `email_verification` / `password_reset` |
| `purpose` | string | YES | `phone_verification` \| `email_verification` \| `password_reset` |

**Responses:**
- `200` — `{ message: 'OTP sent', expiresIn: 600 }`
- `422` — `{ code: 'INVALID_CONTACT', field: 'contact' }`
- `423` — `{ code: 'ACCOUNT_LOCKED', lockedUntil: '<ISO>' }`
- `429` — `{ code: 'OTP_RATE_LIMIT', retryAfter: 3600 }`

### `POST /auth/otp/verify`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `contact` | string | YES | |
| `otp` | string | YES | 6-digit |
| `purpose` | string | YES | `phone_verification` \| `password_reset` |

**Responses:**
- `200` (phone_verification) — `{ verified: true }` — side-effect: `phoneVerified=true`, `consentGivenAt=NOW()`
- `200` (password_reset) — `{ verified: true, resetToken: string }` — TTL 15 min
- `401` — `{ code: 'OTP_INVALID' }`
- `401` — `{ code: 'OTP_EXPIRED' }`
- `423` — `{ code: 'ACCOUNT_LOCKED', lockedUntil }`

### `POST /auth/forgot-password`

**Body:** `{ email: string }`

**Responses:**
- `200` — `{ message: 'If this email is registered, a reset OTP has been sent', expiresIn: 600 }` (always 200)

### `POST /auth/reset-password`

**Body:**
| Field | Type | Req |
|---|---|---|
| `resetToken` | string | YES |
| `newPassword` | string | YES |

**Responses:**
- `200` — `{ message: 'Password updated' }`
- `401` — `{ code: 'TOKEN_INVALID' }`

---

## §3 Partner Onboarding ★

> **Multi-profile:** One `onboarding_states` row per `(user_id, category_id)` pair. A partner can onboard Photography and Decoration simultaneously.

### 4-step wizard

| Step | What is saved | Unlocks |
|---|---|---|
| 1 — Business basics | Core fields into `onboarding_states.stepData` | Enquiries panel, portfolio panel |
| 2 — Portfolio & social | Confirmed `mediaIds` + social URLs into `stepData` | Pricing panel |
| 3 — Category details | `extraData` keyed by `field_definitions_config.fieldKey` | Completeness update |
| 4 — Pricing & packages | `partner_pricing` record written | Profile can be submitted |
| Submit | `onboarding_states.status→submitted`. Populates `partner_profiles` + all linked tables. Creates `admin_reviews_txn` row. | Admin review queue |

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/onboarding/state` | JWT | All active `onboarding_states` for this user. Includes `currentStep`, `stepData`, `status`, `expiresAt`. |
| GET | `/onboarding/state/:categorySlug` | JWT | Single onboarding state for this user + category. Used to pre-fill wizard on resume. |
| PUT | `/onboarding/step/basics` | JWT | Save step 1 into `stepData` (PATCH merge). Creates `onboarding_states` row if absent. |
| PUT | `/onboarding/step/:categorySlug/portfolio` | JWT | Save step 2: confirmed `mediaIds` + social URLs. |
| PUT | `/onboarding/step/:categorySlug/category` | JWT | Save step 3: `extraData` via `CategoryAttributeValidationPipe`. |
| PUT | `/onboarding/step/:categorySlug/pricing` | JWT | Save step 4: writes/updates `partner_pricing`. |
| POST | `/onboarding/:categorySlug/submit` | JWT | Final submit. Idempotent. |
| GET | `/onboarding/completeness/:profileId` | JWT | `profileCompleteness` (0–100), `completenessBreakdown`, `next_actions[3]`. |

### `PUT /onboarding/step/basics`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `categorySlug` | string | YES | Slug from `categories_inventory`. Creates `onboarding_states` row if absent. |
| `firstName` | string | YES | Updates `partner_users.firstName` |
| `lastName` | string | YES | Updates `partner_users.lastName` |
| `businessName` | string | YES | 3–255 chars |
| `about` | string | YES | Min 80 chars |
| `baseCity` | string | YES | |
| `baseState` | string | YES | |
| `contactPhone` | string | YES | |
| `whatsappNumber` | string | No | Defaults to phone if null |
| `email` | string | No | Updates `partner_users.email` |
| `isBusinessRegistered` | boolean | YES | |
| `registrationNumber` | string | No | MSME / ROC etc. |

**Responses:**
- `200` — `{ categorySlug, currentStep: 1, completenessScore: number, setupStatus: { basics, portfolio, category, pricing } }`
- `422` — `{ code: 'CATEGORY_NOT_FOUND', field: 'categorySlug' }`
- `409` — `{ code: 'PROFILE_EXISTS', profileId }` — approved profile already exists for this (user, category) pair

### `PUT /onboarding/step/:categorySlug/category`

**Path:** `categorySlug` — used to look up `field_definitions_config` rows

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `attributes` | object | YES | JSONB keyed by `field_definitions_config.fieldKey`. Unknown keys stripped silently. Required fields validated. e.g. `{ shooting_styles: ['Candid'], delivery_days: 21, drone_available: true }` |

**Responses:**
- `200` — `{ currentStep: 3, completenessScore: number }`
- `422` — `{ code: 'REQUIRED_ATTRIBUTE', field: 'shooting_styles' }`
- `422` — `{ code: 'INVALID_OPTION', field: 'shooting_styles[0]', allowed: [...] }`

### `POST /onboarding/:categorySlug/submit`

**Responses:**
- `200` — `{ profileId, slug, status: 'under_review', completenessScore, estimatedReviewHours: 24 }` — idempotent
- `400` — `{ code: 'BASICS_INCOMPLETE' }`
- `409` — `{ code: 'ALREADY_SUBMITTED', profileId }`

---

## §4 Partner Profile

> **Ownership check:** All `/profiles/:profileId` endpoints verify `partner_profiles.user_id` matches JWT `sub`. Returns `403 PROFILE_NOT_OWNED` otherwise.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/profiles` | JWT | All `partner_profiles` for authenticated user. |
| GET | `/profiles/:profileId` | JWT | Full profile + all linked tables. |
| PATCH | `/profiles/:profileId/basic` | JWT | Update core fields. Re-triggers moderation if profile was approved. |
| PATCH | `/profiles/:profileId/services` | JWT | Replace `partner_services_selected_items`. Accepts `serviceTypeSlugs[]` + `customServices[]`. |
| GET | `/profiles/:profileId/completeness` | JWT | `profileCompleteness`, `completenessBreakdown`, `next_actions[3]`. |
| PATCH | `/profiles/:profileId/visibility` | JWT | Toggle `partner_profiles.isListed`. Requires `onboardingStatus = approved`. |
| GET | `/public/partners/:slug` | Public | Public listing page. CDN-cached 5 min. |

### `PATCH /profiles/:profileId/basic`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `businessName` | string | No | 3–255 chars |
| `about` | string | No | Min 80 chars |
| `isBusinessRegistered` | boolean | No | |
| `registrationNumber` | string | No | |
| `logoMediaId` | uuid | No | Sets `logoUrl` + `logoUrlHash` from confirmed media. |

**Responses:**
- `200` — Updated `partner_profiles` object
- `409` — `{ code: 'SLUG_CONFLICT' }` — `UQ_partner_profiles_slug` conflict
- `403` — `{ code: 'PROFILE_NOT_OWNED' }`

### `PATCH /profiles/:profileId/visibility`

**Body:** `{ isListed: boolean }`

**Responses:**
- `200` — `{ isListed, message: 'Listing activated' | 'Listing hidden' }`
- `400` — `{ code: 'NOT_APPROVED' }` — `onboardingStatus` is not `approved`

---

## §4a Business Profile

> Shared business identity for authenticated partner. Not scoped to a specific listing — one per user (multi-business support deferred). All endpoints require JWT Bearer auth. Ownership enforced: `partner_business_profiles.user_id` must match JWT `sub`.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/business-profile` | JWT | Get full business profile for authenticated user. |
| PATCH | `/business-profile/:section` | JWT | Upsert/update one section (`basic` \| `address` \| `languages` \| `social-links`). |

### `GET /business-profile`

**Responses:**
- `200` — Full business profile object (see shape below)
- `404` — `{ code: 'BUSINESS_PROFILE_NOT_FOUND' }` — partner has not saved any data yet

**Response shape:**
```json
{
  "id": "uuid",
  "slug": "sharma-events-a1b2c3",
  "businessName": "Sharma Events & Décor",
  "about": "...",
  "yearsInBusiness": 5,
  "alternatePhone": "+919876543210",
  "logoUrl": "https://cdn.../logo.jpg",
  "isBusinessRegistered": true,
  "contactPhone": "+919876543210",
  "whatsappNumber": "+919876543210",
  "email": "sharma@example.com",
  "address": {
    "baseCity": "Jaipur",
    "baseState": "Rajasthan",
    "officeAddress": "12 MG Road, Near Clock Tower",
    "pinCode": "302001"
  },
  "languages": ["Hindi", "English"],
  "coverageAreas": [
    { "id": "...", "areaType": "state", "state": "Rajasthan", "city": null },
    { "id": "...", "areaType": "national", "state": null, "city": null }
  ],
  "socialLinks": [
    { "platform": "instagram", "url": "https://instagram.com/sharmaevents" },
    { "platform": "website", "url": "https://sharmaevents.com" }
  ]
}
```

### `PATCH /business-profile/:section`

`:section` must be one of: `basic` | `address` | `languages` | `social-links`

First call upserts (creates) the `partner_business_profiles` row if not present. Slug auto-generated on creation. Returns full business profile object after save.

**Responses:**
- `200` — Full business profile object (same shape as GET)
- `400` — `{ code: 'INVALID_SECTION' }` — `:section` not in allowed list
- `403` — `{ code: 'PROFILE_NOT_OWNED' }`

#### Section: `basic`
| Field | Type | Req | Notes |
|---|---|---|---|
| `businessName` | string | No | 3–255 chars |
| `about` | string | No | |
| `yearsInBusiness` | integer | No | 0–100 |
| `alternatePhone` | string | No | E.164 format |
| `logoUrl` | string | No | CDN URL, max 500 chars |
| `isBusinessRegistered` | boolean | No | |

#### Section: `address`
| Field | Type | Req | Notes |
|---|---|---|---|
| `baseCity` | string | No | Max 100 chars |
| `baseState` | string | No | Max 100 chars |
| `officeAddress` | string | No | Max 500 chars |
| `pinCode` | string | No | 6-digit string |
| `coverageAreas` | array | No | Full replacement. Empty array clears all. |

`coverageAreas` item shape:
- `{ areaType: "national" }` — all over India. If any entry is `national`, the entire array is collapsed to this single entry.
- `{ areaType: "state", state: string }` — all over a specific state. `state` is required.
- `{ areaType: "city", state: string, city: string }` — a specific city. Both `state` and `city` are required.

#### Section: `languages`
| Field | Type | Req | Notes |
|---|---|---|---|
| `languages` | string[] | Yes | Full replacement. Empty array clears all. |

#### Section: `social-links`
| Field | Type | Req | Notes |
|---|---|---|---|
| `links` | array | Yes | Upsert per platform. Platforms not in payload left untouched. Send `url: ""` to remove a platform. |

`links` item shape: `{ platform: "instagram"|"google_business"|"website"|"youtube"|"facebook"|"linkedin", url: string }`

**Error reference for §4a:**

| HTTP | Code | When |
|---|---|---|
| 400 | `INVALID_SECTION` | `:section` param not in allowed list |
| 403 | `PROFILE_NOT_OWNED` | `business.userId` does not match JWT `sub` |
| 404 | `BUSINESS_PROFILE_NOT_FOUND` | GET before any data saved |
| 422 | `INVALID_MOBILE` | `alternatePhone` fails E.164 validation |

---

## §5 Media Upload

> **S3 flow:** `status` state machine: `pending` (URL issued) → `ready` (confirmed + thumbnails by Bull) | `failed`
> **Rule:** `originalS3Key` is the actual S3 key for CDN URL construction. `fileUrlHash` is SHA-256 for integrity only — cannot serve the file.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/profiles/:profileId/media/upload-url` | JWT | Request presigned S3 URL. Creates `partner_media_details` row with `status=pending`. |
| POST | `/profiles/:profileId/media/:mediaId/confirm` | JWT | Confirm upload. Triggers Bull job → `thumbUrl`, `mediumUrl`, `fullUrl`. Sets `status=ready`. |
| GET | `/profiles/:profileId/media` | JWT | All media ordered by `displayOrder`. Filtered `isActive=true`. |
| PATCH | `/profiles/:profileId/media/:mediaId` | JWT | Update `eventTags`, `isCover`, `displayOrder`. |
| PUT | `/profiles/:profileId/media/reorder` | JWT | Bulk update `displayOrder`. Single transaction. |
| DELETE | `/profiles/:profileId/media/:mediaId` | JWT | Soft-delete. Bull job cleans S3 async. |
| POST | `/profiles/:profileId/media/logo/upload-url` | JWT | Presigned URL for logo. Max 2 MB. `mediaType=logo`. |

### `POST /profiles/:profileId/media/upload-url`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `filename` | string | YES | Original filename with extension |
| `contentType` | string | YES | `image/jpeg \| image/png \| image/webp \| video/mp4` |
| `fileSizeBytes` | integer | YES | Rejected if > 10 MB (photos) or 100 MB (video). Stored in `fileSizeBytes`. |
| `mediaType` | string | No | `gallery_image` (default) \| `gallery_video` \| `logo` |

**Responses:**
- `200` — `{ mediaId, uploadUrl, cdnUrl, expiresAt }`
- `400` — `{ code: 'FILE_TOO_LARGE', maxBytes: 10485760 }`
- `400` — `{ code: 'UNSUPPORTED_TYPE' }`
- `400` — `{ code: 'MEDIA_LIMIT_REACHED', current: 20, max: 20 }`

### `PATCH /profiles/:profileId/media/:mediaId`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `eventTags` | string[] | No | Subset of: `Haldi, Mehendi, Sangeet, Pheras, Reception, Pre-wedding, Engagement, Other`. Stored in `partner_media_details.eventTags`. |
| `isCover` | boolean | No | Partial UNIQUE index ensures only one cover per profile. |
| `displayOrder` | integer | No | 0-based |

**Responses:**
- `200` — Updated `partner_media_details` object
- `404` — `{ code: 'MEDIA_NOT_FOUND' }`

---

## §6 Pricing & Packages

> **Rule:** `PUT /profiles/:profileId/pricing` never changes `partner_profiles.onboardingStatus`. No new `admin_reviews_txn` row is created. Price edits go live immediately.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/profiles/:profileId/pricing` | JWT | Get `partner_pricing` row. |
| PUT | `/profiles/:profileId/pricing` | JWT | Upsert full pricing config. `UQ_partner_pricing_partner_id`. |
| POST | `/profiles/:profileId/pricing/packages` | JWT | Append one package. Max 5. |
| PATCH | `/profiles/:profileId/pricing/packages/:packageIndex` | JWT | Update one package by 0-based index. |
| DELETE | `/profiles/:profileId/pricing/packages/:packageIndex` | JWT | Remove one package by index. |

### `PUT /profiles/:profileId/pricing`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `modelType` | string | YES | `per_event \| per_hour \| per_package \| per_head \| per_unit \| custom_quote` |
| `startingFee` | integer | No | INR. Null if `modelType=custom_quote`. |
| `packages` | array | No | `[{ name, priceMin, priceMax, inclusions, deliveryDays?, isPopular? }]`. Max 5. |
| `showExactPrice` | boolean | No | Default false. |
| `currency` | string | No | Default `'INR'`. |
| `negotiable` | boolean | No | Default false. |
| `weekdayDiscount` | boolean | No | |
| `offseasonDiscount` | boolean | No | |
| `advancePercent` | integer | No | 0–100. |
| `travelChargeText` | string | No | Free text. |

**Responses:**
- `200` — Full `partner_pricing` object
- `400` — `{ code: 'PACKAGE_LIMIT_EXCEEDED', max: 5 }`
- `422` — `{ code: 'PRICE_RANGE_INVALID' }` — `priceMax < priceMin`

---

## §7 Category Attributes

> **Rule:** `field_definitions_config` is the single source of truth for form rendering AND server-side validation. `fieldKey` is the key in `partner_extra_fields_details.extraData`.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/categories` | Public | All active `categories_inventory` rows with `serviceCount`. Cached 1 hour. |
| GET | `/categories/:slug` | Public | Single active category by slug with `serviceCount`. Cached 1 hour. |
| GET | `/categories/:slug/schema` | JWT | Active `field_definitions_config` rows grouped by section. Partner must have an active onboarding state or approved profile for this category. |
| GET | `/categories/:slug/services` | Public | `service_types_inventory` rows — chip options for Step 1. |
| GET | `/profiles/:profileId/attributes` | JWT | `partner_extra_fields_details` row: `extraData`, `version`, `categoryId`. |
| PUT | `/profiles/:profileId/attributes` | JWT | Upsert `partner_extra_fields_details`. Validates keys against schema. Strips unknown keys. |

### `GET /categories` response shape

```json
[
  {
    "id": 1,
    "slug": "photography",
    "label": "Photography",
    "displayOrder": 1,
    "serviceCount": 8
  }
]
```

### `GET /categories/:slug/schema` response shape

**Auth:** JWT. Partner must have an active `onboarding_states` row or an approved `partner_profiles` row for this category. Returns `403 CATEGORY_ACCESS_DENIED` otherwise.

Fields grouped by `section` (null section key → `""`) and ordered by `displayOrder ASC` within each section. Sections ordered by minimum `displayOrder` of their fields.

```json
{
  "categoryId": 3,
  "slug": "photography",
  "sections": [
    {
      "section": "Style",
      "fields": [
        {
          "fieldKey": "shooting_styles",
          "fieldType": "multi_select",
          "label": "Shooting styles",
          "isRequired": true,
          "options": ["Candid", "Traditional", "Cinematic"],
          "validationRules": null,
          "displayOrder": 1
        }
      ]
    }
  ]
}
```

---

## §8 Verification

> **Tier system:** `tier_0` (submitted) → `tier_1` (self-attested, no doc) → `tier_2` (PAN/GST verified) → `tier_3` (premium, manual).
> `partner_profiles.verificationTier` drives the Verified badge, search ranking, and PANEL_LOCKS.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/profiles/:profileId/verification` | JWT | `verificationTier`, `selfAttestedAt`, doc status per `docType`, badge eligibility. |
| POST | `/profiles/:profileId/verification/self-attest` | JWT | Tier 1 fast-track. Sets `selfAttestedAt=NOW()`. No document required. |
| POST | `/profiles/:profileId/verification/documents/:docType/upload-url` | JWT | Presigned S3 URL. Creates `partner_documents_details` with `verificationStatus=pending`. `docType`: `pan_card \| gst_cert \| business_registration \| trade_licence \| certification_award` |
| POST | `/profiles/:profileId/verification/documents/:docType/confirm` | JWT | Encrypt PAN/GST → `panNumberEnc` (BYTEA) + `panNumberHash` (SHA-256) in `partner_tax_info_details`. Triggers admin queue. |
| GET | `/profiles/:profileId/verification/documents` | JWT | All `partner_documents_details` rows. |
| DELETE | `/profiles/:profileId/verification/documents/:docType` | JWT | Withdraw. Only if `verificationStatus=pending`. |

### `POST /profiles/:profileId/verification/documents/:docType/confirm`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `mediaId` | uuid | YES | Confirmed media UUID. Service reads `originalS3Key` for `storageKeyHash`. |
| `panNumber` | string | Cond. | Required when `docType=pan_card`. Format: `ABCDE1234F`. Encrypted → `panNumberEnc` + `panNumberHash`. |
| `gstNumber` | string | Cond. | Required when `docType=gst_cert`. 15-char. Encrypted → `gstNumberEnc` + `gstNumberHash`. |
| `bankAccountNumber` | string | Cond. | Required when `docType=bank_account`. |
| `bankIfsc` | string | Cond. | 11-char. Required when `docType=bank_account`. |
| `notRegistered` | boolean | Cond. | For `docType=gst_cert`: true if not GST-registered. Skips `gstNumberEnc`. |

**Responses:**
- `200` — `{ docType, verificationStatus: 'pending', submittedAt }`
- `400` — `{ code: 'PAN_FORMAT_INVALID', field: 'panNumber' }`
- `409` — `{ code: 'ALREADY_APPROVED' }`

---

## §9 Admin & Moderation

> **All `/admin/*` endpoints require admin session AND IP in `ADMIN_IP_WHITELIST`. Returns `403` if either check fails.**
> `audit_logs_history` is immutable via PostgreSQL RLS — no UPDATE or DELETE for any app role.

### Moderation queue

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/queue` | Admin | Paginated `admin_reviews_txn WHERE status IN ('pending','in_review')` ORDER BY `priority DESC, createdAt ASC`. |
| GET | `/admin/queue/:reviewId` | Admin | Full detail + `autoCheckResults` + `checklist`. |
| POST | `/admin/queue/:reviewId/approve` | Admin | Sets `status=approved`, `partner_profiles.onboardingStatus=approved`, `verificationTier→tier_1`. Sends WA. |
| POST | `/admin/queue/:reviewId/reject` | Admin | Sets `status=rejected`. Sets `rejectionReasonCode` + `customMessage`. Sends WA. |
| POST | `/admin/queue/:reviewId/request-info` | Admin | Sets `status=info_requested`. Sends WA. Item stays in queue. |
| POST | `/admin/queue/:reviewId/flag` | Admin | Sets `status=in_review`, `isListed=false`. |
| POST | `/admin/queue/bulk-approve` | Admin | Bulk approve WHERE all `autoCheckResults` passed AND `profileCompleteness >= 75`. Returns `{ approved: N, skipped: N }`. |

### `POST /admin/queue/:reviewId/reject`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `rejectionReasonCode` | string | YES | `insufficient_photos \| fake_content \| duplicate \| low_quality_description \| invalid_documents \| other`. Stored in `admin_reviews_txn.rejectionReasonCode`. |
| `customMessage` | string | No | Sent via WhatsApp. |

**Responses:**
- `200` — `{ reviewId, action: 'rejected', completedAt, partnerNotifiedAt }`
- `409` — `{ code: 'ALREADY_ACTIONED', status: 'approved' }`

### Partner management

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/partners` | Admin | Paginated `partner_users`. Filterable by `isActive`, `isCustomer`, `createdAt`. |
| GET | `/admin/partners/:userId` | Admin | User + all profiles + latest review per profile. |
| GET | `/admin/profiles` | Admin | All `partner_profiles`. Filterable by category, status, tier, city, completeness range. |
| GET | `/admin/profiles/:profileId` | Admin | Full profile + all linked tables + review history + audit trail. |
| PATCH | `/admin/profiles/:profileId/tier` | Admin | Change `verificationTier`. Writes to `audit_logs_history`. Never decrements automatically. |
| POST | `/admin/profiles/:profileId/notes` | Admin | Append to `admin_reviews_txn.checklist`. Never visible to partner. |
| PATCH | `/admin/profiles/:profileId/suspend` | Admin | Sets `onboardingStatus=suspended`, `isListed=false`. Sends WA. |
| PATCH | `/admin/partners/:userId/account-status` | Admin | Set `accountStatus` to `active` or `suspended`. Writes `audit_logs_history`. When suspended: sets `isListed=false` on all profiles. |
| GET | `/admin/stats` | Admin | New signups, pending reviews, live profiles, avg completeness, tier distribution. |
| GET | `/admin/export/profiles` | Admin | CSV export. Excludes encrypted PAN/GST. |

### `PATCH /admin/partners/:userId/account-status`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `accountStatus` | string | YES | `active \| suspended` (cannot revert to `pending_review` via API) |
| `reason` | string | No | Written to `audit_logs_history.newData`. |

**Responses:**
- `200` — `{ userId, accountStatus, updatedAt }`
- `400` — `{ code: 'INVALID_STATUS_TRANSITION' }` — e.g. `suspended → pending_review` not allowed
- `404` — `{ code: 'PARTNER_NOT_FOUND' }`

**Side effects:** Writes to `audit_logs_history`. When `accountStatus → suspended`: sets `isListed: false` on all `partner_profiles` for this user.

---

## §9a Admin Category Management

> **All `/admin/categories` endpoints require `AdminJwtAuthGuard`.** Create, update, and delete additionally require `SuperAdminGuard`. Activate/deactivate are available to all admin roles.
> All mutations write to `audit_logs_history` and emit a `category.cache_bust` event for CDN invalidation.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/categories` | Admin | Paginated list of all categories (active + inactive + soft-deleted excluded). |
| GET | `/admin/categories/:id` | Admin | Single category by numeric id. |
| POST | `/admin/categories` | SuperAdmin | Create new category. |
| PATCH | `/admin/categories/:id` | SuperAdmin | Update `label`, `slug`, or `displayOrder`. |
| DELETE | `/admin/categories/:id` | SuperAdmin | Soft-delete. Blocked if active `partner_profiles` reference it. |
| PATCH | `/admin/categories/:id/activate` | Admin | Set `isActive=true`. |
| PATCH | `/admin/categories/:id/deactivate` | Admin | Set `isActive=false`. |

### `GET /admin/categories` query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `after` | number | — | Cursor — last `id` from previous page |
| `limit` | integer | 20 | Max 100 |
| `isActive` | boolean | — | Filter by active status. Omit = return all. |

### `POST /admin/categories`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `slug` | string | YES | Lowercase hyphenated. Max 60 chars. Must be UNIQUE in `categories_inventory`. |
| `label` | string | YES | Display name. Max 100 chars. |
| `displayOrder` | number | YES | Smallint ≥ 0. Controls sort order on public list. |

**Responses:**
- `201` — created category object `{ id, slug, label, displayOrder, isActive, createdAt, modifiedAt }`
- `409` — `{ code: 'CATEGORY_SLUG_CONFLICT' }` — slug already taken

### `PATCH /admin/categories/:id`

**Body:** All fields optional.
| Field | Type | Notes |
|---|---|---|
| `slug` | string | Max 60 chars. Must be UNIQUE if changing. |
| `label` | string | Max 100 chars. |
| `displayOrder` | number | Smallint ≥ 0. |

**Responses:**
- `200` — updated category object
- `404` — `{ code: 'CATEGORY_NOT_FOUND' }`
- `409` — `{ code: 'CATEGORY_SLUG_CONFLICT' }`

### `DELETE /admin/categories/:id`

**Responses:**
- `204` — soft-deleted
- `404` — `{ code: 'CATEGORY_NOT_FOUND' }`
- `409` — `{ code: 'CATEGORY_IN_USE' }` — one or more active `partner_profiles` reference this category; delete blocked by DB `RESTRICT` constraint

### `PATCH /admin/categories/:id/activate` and `/deactivate`

**Responses:**
- `200` — `{ id, slug, isActive, modifiedAt }`
- `404` — `{ code: 'CATEGORY_NOT_FOUND' }`

### Category object shape (admin)

```json
{
  "id": 1,
  "slug": "photography",
  "label": "Photography",
  "displayOrder": 1,
  "isActive": true,
  "createdAt": "2024-01-01T00:00:00Z",
  "modifiedAt": "2024-01-01T00:00:00Z"
}
```

---

## §9b Admin Field Definitions Management

> **All `/admin/categories/:categoryId/fields` endpoints require `AdminJwtAuthGuard`.** The rename-key endpoint additionally requires `SuperAdminGuard`.
> All mutations write to `audit_logs_history` and emit a `category.cache_bust` event.

### Endpoints

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/categories/:categoryId/fields` | Admin | List all fields (active + inactive, non-deleted) for a category |
| GET | `/admin/categories/:categoryId/fields/:fieldId` | Admin | Single field by id |
| POST | `/admin/categories/:categoryId/fields` | Admin | Create new field definition |
| PATCH | `/admin/categories/:categoryId/fields/:fieldId` | Admin | Update field (fieldKey immutable) |
| PATCH | `/admin/categories/:categoryId/fields/:fieldId/rename-key` | SuperAdmin | Atomic fieldKey rename + JSONB migration across all extraData rows |
| DELETE | `/admin/categories/:categoryId/fields/:fieldId` | Admin | Soft-delete |
| PATCH | `/admin/categories/:categoryId/fields/:fieldId/activate` | Admin | Set `isActive=true` |
| PATCH | `/admin/categories/:categoryId/fields/:fieldId/deactivate` | Admin | Set `isActive=false` |

### `POST /admin/categories/:categoryId/fields`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `fieldKey` | string | YES | Snake_case, max 80 chars. Unique within category. Immutable after creation except via rename-key. |
| `label` | string | YES | Display label. Max 200 chars. |
| `fieldType` | string | YES | `text \| number \| boolean \| select \| multi_select \| textarea \| url` |
| `isRequired` | boolean | YES | |
| `options` | string[] | Cond. | Required when `fieldType` is `select` or `multi_select`. |
| `validationRules` | object | No | JSON validation rules. |
| `displayOrder` | integer | YES | Smallint ≥ 0. |
| `section` | string | No | Section heading for grouping. Max 100 chars. |

**Responses:**
- `201` — created field object
- `404` — `{ code: 'CATEGORY_NOT_FOUND' }`
- `409` — `{ code: 'FIELD_KEY_CONFLICT' }` — fieldKey already exists in this category
- `422` — `{ code: 'OPTIONS_REQUIRED' }` — fieldType is select/multi_select but options missing or empty

### `PATCH /admin/categories/:categoryId/fields/:fieldId`

**Body:** All fields optional. `fieldKey` is silently ignored if sent.
| Field | Type | Notes |
|---|---|---|
| `label` | string | Max 200 chars |
| `fieldType` | string | Enum values same as create |
| `isRequired` | boolean | |
| `options` | string[] | Required if fieldType changes to select/multi_select |
| `validationRules` | object | |
| `displayOrder` | integer | Smallint ≥ 0 |
| `section` | string | Max 100 chars |

**Responses:**
- `200` — updated field object
- `404` — `{ code: 'FIELD_NOT_FOUND' }`
- `422` — `{ code: 'OPTIONS_REQUIRED' }`

### `PATCH /admin/categories/:categoryId/fields/:fieldId/rename-key`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `newKey` | string | YES | Snake_case, max 80 chars. Must not exist for this category. |

**Behaviour (single DB transaction):**
1. Verify `newKey` not already taken in this category
2. `UPDATE field_definitions_config SET "fieldKey" = :newKey WHERE id = :fieldId`
3. `UPDATE partner_extra_fields_details SET "extraData" = ("extraData" - :oldKey) || jsonb_build_object(:newKey, "extraData"->:oldKey) WHERE "categoryId" = :categoryId AND "extraData" ? :oldKey`
4. Audit log written outside transaction (best effort)

**Responses:**
- `200` — updated field object with new fieldKey
- `404` — `{ code: 'FIELD_NOT_FOUND' }`
- `409` — `{ code: 'FIELD_KEY_CONFLICT' }`

### `DELETE /admin/categories/:categoryId/fields/:fieldId`

**Responses:**
- `204` — soft-deleted. Existing `partner_extra_fields_details.extraData` values for this key are left as-is.
- `404` — `{ code: 'FIELD_NOT_FOUND' }`

### `PATCH /admin/categories/:categoryId/fields/:fieldId/activate` and `/deactivate`

**Responses:**
- `200` — `{ id, fieldKey, isActive, modifiedAt }`
- `404` — `{ code: 'FIELD_NOT_FOUND' }`

### Field object shape (admin)

```json
{
  "id": 12,
  "categoryId": 3,
  "fieldKey": "shooting_styles",
  "label": "Shooting styles",
  "fieldType": "multi_select",
  "isRequired": true,
  "options": ["Candid", "Traditional", "Cinematic"],
  "validationRules": null,
  "displayOrder": 1,
  "section": "Style",
  "isActive": true,
  "createdAt": "2024-01-01T00:00:00Z",
  "modifiedAt": "2024-01-01T00:00:00Z"
}
```

---

## §10 Dashboard & Lead Inbox

### Dashboard

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/dashboard` | JWT | Unified dashboard for user. Returns `user`, `account`, `listings[]` (merged from `onboarding_states` pre-submission and `partner_profiles` post-submission), and `stats`. |
| GET | `/dashboard/:profileId/overview` | JWT | Single profile stats. `setupStatus: { basics, portfolio, category, pricing }`. |
| GET | `/dashboard/:profileId/setup-status` | JWT | `{ basics: bool, portfolio: bool, category: bool, pricing: bool }`. Drives PANEL_LOCKS. |
| GET | `/dashboard/:profileId/completeness` | JWT | `profileCompleteness` + `completenessBreakdown` + `next_actions[3]`. |

### `GET /dashboard`

**Response:**
```json
{
  "user": { "id", "firstName", "lastName", "baseCity", "phoneVerified", "emailVerified", "accountStatus" },
  "account": { "phoneVerified", "emailVerified" },
  "listings": [
    {
      "categoryId": 3,
      "categorySlug": "photography",
      "categoryLabel": "Photographer / Videographer",
      "profileId": null,
      "onboardingStatus": "in_progress",
      "profileCompleteness": 15,
      "isListed": false,
      "setupStatus": { "businessName": false, "portfolio": false, "categoryDetails": false, "pricing": false, "verification": false }
    }
  ],
  "stats": { "newEnquiries": 0, "profileViews": null, "listingsActivePercent": 0, "bookingsConfirmed": null }
}
```

**Notes:**
- `profileId: null` = sourced from `onboarding_states` (pre-submission). Non-null = sourced from `partner_profiles`.
- `profileCompleteness: 15` is the baseline for a fresh account (phone + email verified + category selected).
- `stats.profileViews` and `stats.bookingsConfirmed` are `null` (render as "—") until at least one profile is live.
- `stats.listingsActivePercent` = `(listings with onboardingStatus='approved' AND isListed=true) / total listings * 100`.

### Lead inbox

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/dashboard/:profileId/leads` | JWT | Paginated `partner_leads`. Filterable by `status`. Sorted by `createdAt DESC`. |
| GET | `/dashboard/:profileId/leads/:leadId` | JWT | Full lead. Decrypts `coupleMobile` + `coupleEmail` (AES-256) at service layer. |
| PATCH | `/dashboard/:profileId/leads/:leadId/status` | JWT | Update status. Sets `vendorRespondedAt` on first `new → responded/booked`. |
| GET | `/dashboard/:profileId/availability` | JWT | Returns coverage areas and `advancePercent` from `partner_pricing`. |
| POST | `/public/partners/:slug/enquiry` | Public | Creates `partner_leads` row. Bull job sends WA to partner within 5 min. |

### `GET /dashboard/:profileId/leads`

**Query:**
| Param | Type | Default | Notes |
|---|---|---|---|
| `status` | string | `all` | `all \| new \| responded \| booked \| not_relevant \| expired` |
| `after` | uuid | — | Cursor — last `partner_leads.id` from previous page |
| `limit` | integer | 20 | Max 100 |

**Response:** `{ leads: [ { id, coupleName, weddingDate, eventCity, eventTypes, budgetMin, budgetMax, status, notifiedAt, createdAt } ], hasMore, nextCursor }`

### `PATCH /dashboard/:profileId/leads/:leadId/status`

**Body:** `{ status: 'new | responded | booked | not_relevant' }`

**Responses:**
- `200` — `{ id, status, vendorRespondedAt }`
- `400` — `{ code: 'INVALID_TRANSITION' }` — e.g. `expired → responded` not allowed

### `POST /public/partners/:slug/enquiry`

**Body:**
| Field | Type | Req | Notes |
|---|---|---|---|
| `coupleName` | string | YES | |
| `coupleMobile` | string | YES | AES-256 encrypted before insert into `partner_leads.coupleMobile` |
| `coupleEmail` | string | No | Encrypted before insert |
| `weddingDate` | string | No | ISO date `YYYY-MM-DD` |
| `eventCity` | string | YES | |
| `eventTypes` | string[] | YES | e.g. `['Haldi','Reception']` |
| `budgetMin` | integer | No | INR |
| `budgetMax` | integer | No | CHECK: `budgetMax >= budgetMin` |
| `message` | string | No | |

**Responses:**
- `201` — `{ leadId, message: 'Enquiry sent. The partner will respond within 24 hours.' }`
- `404` — `{ code: 'PARTNER_NOT_FOUND' }` — slug not found or `isListed=false`

---

## §11 Account Settings

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/settings` | JWT | `partner_users` fields: `isActive`, `isCustomer`, `email`, `emailVerified`, `whatsappNumber`. |
| PATCH | `/settings/notifications` | JWT | Update notification preferences per event type (`whatsappOn`, `emailOn`). |
| PATCH | `/settings/password` | JWT | Set/change `passwordHash` (bcrypt cost 12). Requires OTP if no password set yet. |
| PATCH | `/settings/whatsapp` | JWT | Update `partner_users.whatsappNumber`. Triggers OTP to new number. |
| DELETE | `/account` | JWT | Soft-delete `partner_users`. PII purge (phone, email, `coupleMobile`) within 72h. DPDP Act 2023. |

---

## §12 Error reference

| HTTP | code | When |
|---|---|---|
| 400 | `INVALID_MOBILE` | Mobile fails E.164 / 10-digit Indian format |
| 400 | `BASICS_INCOMPLETE` | `onboarding_states.stepData` missing required step 1 fields |
| 400 | `INVALID_TRANSITION` | `partner_leads` status transition not allowed |
| 400 | `FILE_TOO_LARGE` | > 10 MB photos or 100 MB video |
| 400 | `NOT_APPROVED` | `partner_profiles.onboardingStatus` is not `approved` |
| 401 | `OTP_INVALID` | Wrong OTP — increments `otp_verifications_txn.attemptCount` |
| 401 | `OTP_EXPIRED` | `otp_verifications_txn.expiresAt` elapsed |
| 401 | `TOKEN_EXPIRED` | JWT expired — use `/auth/refresh` |
| 401 | `TOKEN_INVALID` | JWT tampered or revoked |
| 401 | `INVALID_CREDENTIALS` | Wrong email or password — vague by design, no email enumeration |
| 401 | `ACCOUNT_INACTIVE` | `partner_users.isActive = false` — pending admin activation |
| 403 | `PROFILE_NOT_OWNED` | `partner_profiles.user_id` does not match JWT `sub` |
| 403 | `FORBIDDEN` | Admin endpoint without valid session or IP not in whitelist |
| 404 | `CATEGORY_NOT_FOUND` | Category id not found or soft-deleted |
| 404 | `PROFILE_NOT_FOUND` | Row not found or soft-deleted |
| 404 | `MEDIA_NOT_FOUND` | Not found or not owned by profile |
| 404 | `PARTNER_NOT_FOUND` | Slug not found or `isListed=false` |
| 409 | `CATEGORY_SLUG_CONFLICT` | `categories_inventory.slug` already taken |
| 409 | `CATEGORY_IN_USE` | Soft-delete blocked — active `partner_profiles` reference this category |
| 403 | `CATEGORY_ACCESS_DENIED` | Partner has no active onboarding state or approved profile for this category |
| 404 | `FIELD_NOT_FOUND` | `field_definitions_config` id not found or soft-deleted |
| 409 | `FIELD_KEY_CONFLICT` | `fieldKey` already exists for this category |
| 422 | `OPTIONS_REQUIRED` | `fieldType` is select/multi_select but `options` missing or empty |
| 409 | `ACCOUNT_EXISTS` | `partner_users.phone` already registered (UNIQUE constraint) |
| 409 | `PROFILE_EXISTS` | `(user_id, category_id)` pair already has an approved profile (`UQ_partner_profiles_user_category`) |
| 409 | `ALREADY_SUBMITTED` | `admin_reviews_txn` row already `pending/in_review` for this profile |
| 409 | `SLUG_CONFLICT` | Slug already taken (`UQ_partner_profiles_slug`) |
| 409 | `ALREADY_APPROVED` | `partner_documents_details.verificationStatus` is already `approved` |
| 422 | `REQUIRED_ATTRIBUTE` | `field_definitions_config.isRequired=true` field missing from `extraData` |
| 422 | `INVALID_OPTION` | Value not in `field_definitions_config.options` |
| 422 | `PRICE_RANGE_INVALID` | `priceMax < priceMin` in a package |
| 422 | `PAN_FORMAT_INVALID` | PAN does not match `ABCDE1234F` |
| 423 | `ACCOUNT_LOCKED` | `otp_verifications_txn.lockedUntil` is in the future |
| 429 | `OTP_RATE_LIMIT` | Max 5 OTP sends per phone per hour |
| 429 | `RATE_LIMIT_EXCEEDED` | 100 req/min per authenticated user |
| 500 | `INTERNAL_ERROR` | Unexpected error — Sentry alert fired |