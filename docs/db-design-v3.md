---
title: DB Design v3
sync_to_confluence: true
confluence-labels:
  - technical
  - database
  - schema
---

# DB Schema References — Bandhan Bazar
**DB-SCHEMA-BB-001 v1.1 · NestJS + TypeORM · PostgreSQL 15 + MongoDB 7**

> **Claude Code:** Read this file when working on any entity, migration, repository, service, or query. All TypeORM entity names, column names, constraints, and indexes are defined here. Do not deviate.

---

## Quick reference — all 22 tables + 1 MongoDB collection

| Group | Table | PK type | Purpose |
|---|---|---|---|
| Core | `partner_users` | UUID | Auth + identity. One row per registered partner. |
| Core | `partner_profiles` | UUID | Public listing per category. user_id NOT UNIQUE — multi-profile. |
| Core | `partner_pricing` | UUID | Pricing + packages. Separate from profile — edits never re-trigger moderation. |
| Onboarding | `onboarding_states` | UUID | Wizard state persistence. One row per (user_id, category_id) in progress. |
| Transaction | `otp_verifications_txn` | UUID | OTP audit trail + lockout persistence. |
| Transaction | `admin_reviews_txn` | UUID | Admin approval workflow per profile submission. |
| Inventory | `categories_inventory` | SERIAL | Master list of 13 service categories. |
| Inventory | `service_types_inventory` | SERIAL | Sub-service chip options per category. |
| Config | `field_definitions_config` | SERIAL | Field registry — drives dynamic onboarding form + server validation. |
| JSONB Extra | `partner_extra_fields_details` | UUID | Category-specific attribute values as JSONB. One row per profile. |
| Selected Items | `partner_services_selected_items` | UUID | M:N bridge — profile ↔ service chips. |
| Business | `partner_business_profiles` | UUID | Shared business identity per user. One row per user. |
| Business | `partner_business_social_links` | UUID | Social platform URLs. One row per platform per business. |
| Business | `partner_business_languages` | UUID | Languages spoken. One row per language per business. |
| Business | `partner_business_coverage_areas` | UUID | Cities/regions covered. One row per area per business. |
| Details | `partner_tax_info_details` | UUID | PAN + GST encrypted (AES-256-GCM). Strict RLS. |
| Details | `partner_documents_details` | UUID | KYC document references (S3 URL hashes). |
| Details | `partner_media_details` | UUID | Gallery photos/videos. S3 presigned upload flow. |
| Details | `partner_awards_details` | UUID | Industry awards displayed on listing. |
| Details | `partner_references_details` | UUID | Vouching contacts verified by admin team. |
| History | `audit_logs_history` | BIGSERIAL | Immutable append-only log. PostgreSQL RLS blocks UPDATE/DELETE. |
| Leads | `partner_leads` | UUID | Couple enquiries. Status machine: new → responded/booked/not_relevant/expired. |
| MongoDB | `notification_logs` | ObjectId | WA/SMS/email delivery log. TTL 180 days. |

---

## Global conventions

- **All TypeORM entities use camelCase** (`businessName`, `createdAt`). DB columns are snake_case via `SnakeCaseNamingStrategy`. Never use `synchronize: true`.
- **UUID PKs** on all user-facing tables. `SERIAL`/`BIGSERIAL` on small lookup tables and `audit_logs_history`.
- **Timestamps:** `createdAt TIMESTAMPTZ` (`@CreateDateColumn`), `modifiedAt TIMESTAMPTZ` (`@UpdateDateColumn`), `deletedAt TIMESTAMPTZ` (soft delete, `@DeleteDateColumn`). Filter all queries with `WHERE deletedAt IS NULL`.
- **Soft deletes everywhere** — never hard-delete except PII purge job (runs within 72h of soft delete, DPDP Act 2023).
- **Enums as VARCHAR + CHECK** — never PostgreSQL `ENUM` type (ALTER TYPE locks the table).
- **JSONB fields always have GIN indexes.**
- **Monetary values as INTEGER (INR).** No FLOAT.
- **All migrations reversible** — `down()` required on every migration.
- **updated_at trigger** — apply `trigger_set_updated_at()` to every table on creation.

---

## `partner_users`
*One row per registered partner. Phone is primary login. Multi-profile: one user → many profiles.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK. `uuid_generate_v4()` |
| `salutation` | varchar(10) | No | Mr / Ms / Mrs / Dr |
| `firstName` | varchar(100) | YES | |
| `lastName` | varchar(100) | YES | |
| `phone` | varchar(15) | YES | E.164 (+91XXXXXXXXXX). UNIQUE. |
| `phoneVerified` | boolean | YES | Default false. Flipped after OTP success. |
| `email` | varchar(255) | YES | UNIQUE. |
| `emailVerified` | boolean | YES | Default false. |
| `whatsappNumber` | varchar(15) | No | If null, phone is used for WA notifications. |
| `passwordHash` | varchar(255) | No | bcrypt cost ≥ 12. Null for OTP-only accounts. |
| `isActive` | boolean | YES | Default true (set at registration — both OTPs verified). Controls login access. |
| `isCustomer` | boolean | YES | Default false. Allows partner to also act as a couple. |
| `accountStatus` | varchar(20) | YES | Default `'pending_review'`. CHECK: `pending_review \| active \| suspended`. Admin-controlled. No profiles can be `isListed=true` while `accountStatus != 'active'`. |
| `consentGivenAt` | timestamptz | YES | **DPDP Act 2023.** Set at registration (both OTPs verified). |
| `otpLockUntil` | timestamptz | No | Set after 5 failed OTP attempts. Persists across server restarts. |
| `createdAt` | timestamptz | YES | `@CreateDateColumn` |
| `modifiedAt` | timestamptz | YES | `@UpdateDateColumn` |
| `deletedAt` | timestamptz | No | Soft delete. PII purge within 72h. |

**Constraints:** UNIQUE `phone`, UNIQUE `email`, CHECK `account_status IN ('pending_review','active','suspended')`
**Relations:** 1:M → `partner_profiles` (via `partner_profiles.user_id`), 1:M → `onboarding_states`

---

## `partner_profiles`
*Central listing entity. `user_id` is NOT UNIQUE — one user can have multiple profiles.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `user_id` | UUID FK | YES | → `partner_users`. **NOT UNIQUE** — multi-profile architecture. |
| `category_id` | integer FK | YES | → `categories_inventory`. RESTRICT on delete. |
| `customCategory` | varchar(200) | No | Only when category = 'Other'. |
| `businessName` | varchar(255) | YES | |
| `slug` | varchar(300) | YES | UNIQUE. URL-safe. Immutable after creation. |
| `about` | text | YES | |
| `logoUrl` | varchar(500) | No | CDN URL. |
| `logoUrlHash` | varchar(64) | No | SHA-256 of logo URL for integrity. |
| `isBusinessRegistered` | boolean | YES | |
| `registrationNumber` | varchar(100) | No | MSME / ROC / Shop Estab. |
| `onboarding_status` | varchar(30) | YES | Default `'draft'`. CHECK: `draft \| submitted \| under_review \| approved \| rejected \| suspended` |
| `onboardingStep` | smallint | YES | Last completed step 1–4. |
| `profileCompleteness` | smallint | YES | Default 0. 0–100. Recomputed by `ProfileCompletenessService` on every save. |
| `completenessBreakdown` | jsonb | No | `{ business_info: { earned, max }, portfolio: { ... } }` |
| `verification_tier` | varchar(20) | YES | Default `'tier_0'`. CHECK: `tier_0 \| tier_1 \| tier_2 \| tier_3`. Never decrements automatically. |
| `selfAttestedAt` | timestamptz | No | Tier 1 self-attestation timestamp. |
| `searchVector` | tsvector | No | GIN indexed. Auto-updated by DB trigger on `businessName` + `about`. Phase 2. |
| `isListed` | boolean | YES | Default false. Vendor-controlled visibility toggle. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraints:**
- UNIQUE `(user_id, category_id)` — one profile per category per user (`UQ_partner_profiles_user_category`)
- UNIQUE `slug` (`UQ_partner_profiles_slug`)
- CHECK `onboarding_status IN ('draft','submitted','under_review','approved','rejected','suspended')`
- CHECK `verification_tier IN ('tier_0','tier_1','tier_2','tier_3')`

**Indexes:** `(user_id, category_id)`, `slug` B-tree, `searchVector` GIN

---

## `onboarding_states`
*Server-side wizard state. Enables resume-later UX. One row per (user_id, category_id) in progress. Multiple simultaneous category onboardings supported.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `user_id` | UUID FK | YES | → `partner_users`. CASCADE. |
| `category_id` | integer FK | YES | → `categories_inventory`. |
| `currentStep` | smallint | YES | Default 1. Steps 1–4. |
| `stepData` | jsonb | YES | Default `{}`. **PATCH semantics** — saving step 3 does not wipe step 1 data. Keys mirror onboarding form fields. |
| `status` | varchar(20) | YES | Default `'in_progress'`. CHECK: `in_progress \| submitted \| expired` |
| `submittedAt` | timestamptz | No | Set on final submit. |
| `expiresAt` | timestamptz | YES | Default `NOW() + INTERVAL '30 days'`. Nightly job purges expired rows. |
| `createdAt` | timestamptz | YES | |
| `updatedAt` | timestamptz | YES | Updated on every step save. |

**Constraints:** Partial UNIQUE `(user_id, category_id) WHERE status = 'in_progress'` (`UQ_onboarding_active_session`)

**stepData structure:**
```json
{
  "step1": { "businessName": "...", "about": "...", "baseCity": "...", "baseState": "..." },
  "step2": { "mediaIds": ["uuid1"], "instagramUrl": "...", "websiteUrl": "..." },
  "step3": { "attributes": { "shooting_styles": ["Candid"], "drone_available": true } },
  "step4": { "modelType": "per_package", "startingFee": 40000, "packages": [] }
}
```

---

## `partner_pricing`
*Pricing model and packages. Intentionally separate from `partner_profiles`. Edits NEVER re-trigger admin moderation.*

> **Rule:** Never update `partner_profiles.onboarding_status` when updating `partner_pricing`. No new `admin_reviews_txn` row.

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. **UNIQUE** — one pricing record per profile. |
| `model_type` | varchar(30) | YES | CHECK: `per_event \| per_hour \| per_package \| per_head \| per_unit \| custom_quote` |
| `starting_fee` | integer | No | INR. Null if `model_type = custom_quote`. |
| `packages` | jsonb | YES | Default `[]`. Max 5 at app layer. Structure: `[{ name, priceMin, priceMax, inclusions, deliveryDays?, isPopular? }]` |
| `show_exact_price` | boolean | YES | Default false. |
| `currency` | char(3) | YES | Default `'INR'`. ISO 4217. |
| `negotiable` | boolean | YES | Default false. |
| `weekday_discount` | boolean | YES | Default false. |
| `offseason_discount` | boolean | YES | Default false. |
| `advance_percent` | smallint | No | 0–100. CHECK enforced. |
| `travel_charge_text` | varchar(200) | No | e.g. `'₹5,000/day outside city'` |
| `createdAt` | timestamptz | YES | |
| `updatedAt` | timestamptz | YES | |

**Constraints:** UNIQUE `partner_id` (`UQ_partner_pricing_partner_id`)

---

## `partner_extra_fields_details`
*Category-specific attribute values. One row per profile. `extraData` JSONB keys match `field_definitions_config.fieldKey`.*

> **Rule:** Always `upsert` on `partner_id` — never INSERT a second row.

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. **UNIQUE** (`UQ_partner_extra_fields_partner_id`). |
| `category_id` | integer FK | YES | → `categories_inventory`. Denormalized for faster queries. |
| `extraData` | jsonb | YES | GIN indexed. Keys = `field_definitions_config.fieldKey` for this category. |
| `version` | smallint | YES | Default 1. Increment when `field_definitions_config` schema changes for this category. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Indexes:** GIN on `extraData`, B-tree on `(category_id, partner_id)`

**extraData value types by fieldType:**
| fieldType | JSON value |
|---|---|
| `text` / `textarea` | `string` |
| `number` / `number_with_suffix` | `integer` |
| `toggle` / `boolean` | `boolean` |
| `dropdown` / `select` | `string` |
| `multi_select` / `chips` | `string[]` |

---

## `field_definitions_config`
*Field registry. Drives onboarding form rendering AND server-side validation. Adding a new category field = INSERT here, no migration.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | SERIAL | YES | PK |
| `category_id` | integer FK | YES | → `categories_inventory`. CASCADE. |
| `fieldKey` | varchar(80) | YES | UNIQUE per category. Key used in `extraData` JSONB. |
| `label` | varchar(200) | YES | Form label. |
| `fieldType` | varchar(30) | YES | `text \| number \| boolean \| select \| multi_select \| textarea \| url` |
| `isRequired` | boolean | YES | |
| `options` | jsonb | No | Choices for select/multi_select. |
| `validationRules` | jsonb | No | `{ min, max }` or `{ pattern: 'regex' }` |
| `displayOrder` | smallint | YES | |
| `section` | varchar(100) | No | Group label e.g. `'Floral & Materials'` |
| `isActive` | boolean | YES | False = hidden from form. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraints:** UNIQUE `(category_id, fieldKey)`
**Index:** `(category_id, displayOrder)` — ordered field list for form render

---

## `otp_verifications_txn`
*Durable OTP audit trail. Redis handles TTL (fast path); this table persists `lockedUntil` across server restarts.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `contactValue` | varchar(255) | YES | Phone or email the OTP was sent to. |
| `contactType` | varchar(10) | YES | `phone \| email` |
| `otpHash` | varchar(64) | YES | SHA-256 of OTP. **Plaintext never stored.** |
| `purpose` | varchar(30) | YES | `phone_verification \| email_verification \| password_reset \| onboarding \| login \| reset` |
| `isUsed` | boolean | YES | Default false. Flipped on success. Prevents replay attacks. |
| `attemptCount` | smallint | YES | Default 0. Incremented on each failure. |
| `expiresAt` | timestamptz | YES | 10-minute window. |
| `lockedUntil` | timestamptz | No | Set when `attemptCount` reaches 5. **Always check this before processing OTP.** |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Index:** Partial `(contactValue, contactType) WHERE isUsed = FALSE`

---

## `admin_reviews_txn`
*One row per review cycle per profile. Previous rows preserved as history. Each re-submission creates a new row.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. CASCADE. |
| `reviewer_id` | UUID | No | Admin UUID. No FK constraint. |
| `status` | varchar(20) | YES | CHECK: `pending \| in_review \| approved \| rejected \| info_requested` |
| `checklist` | jsonb | No | `{ pan_verified: true, gallery_ok: null }` — manual admin checklist. |
| `autoCheckResults` | jsonb | YES | Default `{}`. All passing + completeness ≥ 75 → bulk-approve eligible. |
| `rejectionReasonCode` | varchar(50) | No | `insufficient_photos \| fake_content \| duplicate \| low_quality_description \| invalid_documents \| other` |
| `customMessage` | text | No | Sent via WhatsApp on rejection or info_requested. |
| `priority` | smallint | YES | Default 0. `0=normal 1=high 2=urgent`. |
| `completedAt` | timestamptz | No | Set on terminal status. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**autoCheckResults structure:**
```json
{
  "min_description_length": { "passed": true, "value": 142 },
  "photo_uploaded": { "passed": true, "count": 7 },
  "otp_verified": { "passed": true },
  "no_duplicate_name_city": { "passed": false, "conflict_profile_id": "uuid" },
  "pricing_set": { "passed": true, "model": "per_package" },
  "completeness_score": { "passed": true, "score": 78 }
}
```

**Index:** Partial `(status, createdAt) WHERE status IN ('pending','in_review')` — admin queue

---

## `partner_media_details`
*Gallery photos, videos, logo. S3 presigned upload flow. Bull job generates CDN URLs.*

> **Rule:** `originalS3Key` is the actual S3 key for CDN URL construction and deletion. `fileUrlHash` is SHA-256 for integrity checking only — it cannot be used to serve the file.

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. CASCADE. |
| `mediaType` | varchar(20) | YES | `logo \| gallery_image \| gallery_video` |
| `fileUrlHash` | varchar(64) | YES | SHA-256 integrity check only. |
| `originalS3Key` | varchar(500) | No | Actual S3 key. Required to serve/delete the file. |
| `status` | varchar(20) | YES | Default `'pending'`. CHECK: `pending \| ready \| failed` |
| `uploadConfirmedAt` | timestamptz | No | Set on `POST /media/:id/confirm`. |
| `eventTags` | varchar[] | YES | Default `{}`. CHECK: subset of `Haldi, Mehendi, Sangeet, Pheras, Reception, Pre-wedding, Engagement, Other` |
| `thumbUrl` | varchar(500) | No | CDN 300px. Set by Bull job. |
| `mediumUrl` | varchar(500) | No | CDN 800px. Set by Bull job. |
| `fullUrl` | varchar(500) | No | CDN 1600px. Set by Bull job. |
| `contentType` | varchar(50) | No | MIME type. |
| `fileSizeBytes` | integer | No | Original size before compression. |
| `displayOrder` | smallint | YES | 0-based. |
| `isCover` | boolean | YES | Default false. Partial UNIQUE index enforces exactly one cover per profile. |
| `isActive` | boolean | YES | Default true. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraints:**
- CHECK `status IN ('pending','ready','failed')`
- Partial UNIQUE `(partner_id) WHERE isCover = TRUE AND deletedAt IS NULL`

**Indexes:** `(partner_id, mediaType, displayOrder) WHERE isActive = TRUE`, partial `status WHERE status = 'pending'`

---

## `partner_leads`
*Couple enquiries. Status machine: new → responded | booked | not_relevant | expired.*

> **Rule:** `coupleMobile` and `coupleEmail` are AES-256 encrypted via TypeORM column transformer. Never log or expose plaintext. PII purge within 72h of account soft-delete.

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. CASCADE. |
| `coupleName` | varchar(200) | YES | |
| `coupleMobile` | varchar(20) | YES | **AES-256 encrypted.** |
| `coupleEmail` | varchar(255) | No | **AES-256 encrypted.** |
| `weddingDate` | date | No | Null = still exploring. |
| `eventCity` | varchar(100) | YES | |
| `eventTypes` | varchar[] | YES | Default `{}`. e.g. `{Haldi, Reception, Sangeet}` |
| `budget_min` | integer | No | INR. |
| `budget_max` | integer | No | INR. CHECK: `budget_max >= budget_min` when not null. |
| `message` | text | No | |
| `status` | varchar(20) | YES | Default `'new'`. CHECK: `new \| responded \| booked \| not_relevant \| expired` |
| `source` | varchar(30) | YES | Default `'web'`. CHECK: `web \| whatsapp \| admin_manual \| api` |
| `notifiedAt` | timestamptz | No | Set when WA notification delivered. Null = not yet sent. |
| `vendorRespondedAt` | timestamptz | No | Set on first `new → responded` or `new → booked` transition. |
| `createdAt` | timestamptz | YES | |
| `expiresAt` | timestamptz | YES | Default `NOW() + INTERVAL '90 days'`. Nightly job sets `status = 'expired'`. |

**Indexes:**
- `(partner_id, status, createdAt DESC)` — lead inbox query
- Partial `(status, notifiedAt) WHERE status = 'new' AND notifiedAt IS NULL` — WA dispatch job
- Partial `(expiresAt) WHERE status = 'new'` — nightly expiry job

---

## `partner_tax_info_details`
*PAN + GST encrypted. Separate table for strict RLS — most app roles cannot read this.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_business_profiles`. UNIQUE. |
| `panNumberEnc` | bytea | YES | AES-256-GCM ciphertext. AWS KMS. |
| `panNumberHash` | varchar(64) | YES | SHA-256 for PAN deduplication at registration. |
| `gstNumberEnc` | bytea | No | Null if not GST-registered. |
| `gstNumberHash` | varchar(64) | No | Null if not GST-registered. |
| `panVerified` | boolean | YES | Default false. |
| `gstVerified` | boolean | YES | Default false. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Index:** Hash index on `panNumberHash` — O(1) PAN deduplication check

---

## `partner_documents_details`
*KYC document references. Stores SHA-256 hashes of S3 URLs — never the actual key.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_business_profiles`. |
| `docType` | varchar(40) | YES | `pan_card \| gst_cert \| business_registration \| bank_account \| trade_licence \| certification_award` |
| `fileUrlHash` | varchar(64) | YES | SHA-256 of S3 pre-signed URL. |
| `storageKeyHash` | varchar(64) | YES | SHA-256 of S3 object key. **Actual key never stored.** |
| `verificationStatus` | varchar(20) | YES | `pending \| approved \| rejected` |
| `isActive` | boolean | YES | Default true. False on re-upload — old doc preserved for audit. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Index:** Partial `verificationStatus WHERE verificationStatus = 'pending'` — admin doc queue

---

## `document_review_txn`
*One row per admin review action on a document. Append-only — full history preserved.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `document_id` | UUID FK | YES | → `partner_documents_details`. CASCADE on delete. |
| `reviewer_id` | UUID | YES | Admin UUID. No FK constraint (soft reference by design). |
| `action` | varchar(20) | YES | `approved \| rejected \| info_requested` |
| `rejection_code` | varchar(50) | No | `document_unclear \| document_expired \| name_mismatch \| fake_document \| other`. Null if not rejected. |
| `note` | text | No | Internal note or partner-facing message. |
| `created_at` | timestamptz | YES | Append-only — no `modifiedAt` or `deletedAt`. |

**Index:** `document_id`

---

## `partner_services_selected_items`
*M:N bridge — partner_profiles ↔ service_types_inventory.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. |
| `service_type_id` | integer FK | YES | → `service_types_inventory`. |
| `customService` | varchar(200) | No | Free-text when `isCustom = true`. |
| `isCustom` | boolean | YES | True when vendor typed a custom service. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraint:** UNIQUE `(partner_id, service_type_id)`

---

## `partner_business_profiles`
*Shared business identity per user. User-scoped — not per listing. Multi-business deferred.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `user_id` | UUID FK | YES | → `partner_users`. **UNIQUE.** CASCADE on delete. |
| `slug` | varchar(300) | YES | UNIQUE. Auto-generated on first save. Immutable after creation. |
| `business_name` | varchar(255) | No | |
| `about` | text | No | |
| `years_in_business` | smallint | No | |
| `alternate_phone` | varchar(15) | No | E.164 format. |
| `logo_url` | varchar(500) | No | CDN URL. |
| `logo_s3_key` | varchar(500) | No | Staging S3 key for pending logo upload. Cleared after confirm. |
| `logo_content_type` | varchar(50) | No | MIME type of pending logo upload. Cleared after confirm. |
| `is_business_registered` | boolean | YES | Default `false`. |
| `verification_tier` | varchar(20) | YES | Default `'tier_0'`. `tier_0 \| tier_1 \| tier_2 \| tier_3`. |
| `self_attested_at` | timestamptz | No | Set on tier-1 self-attestation. |
| `base_city` | varchar(100) | No | |
| `base_state` | varchar(100) | No | |
| `office_address` | varchar(500) | No | Building, street, landmark. |
| `pin_code` | char(6) | No | |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | Soft delete. |

**Constraints:** UNIQUE `user_id`, UNIQUE `slug`

---

## `partner_business_social_links`
*One row per platform per business. Adding new platforms = insert new rows, no migration required.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `business_id` | UUID FK | YES | → `partner_business_profiles`. CASCADE on delete. |
| `platform` | varchar(50) | YES | `instagram \| google_business \| website \| youtube \| facebook \| linkedin` |
| `url` | varchar(500) | YES | |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraint:** UNIQUE `(business_id, platform)`

---

## `partner_business_languages`
*One row per language per business.*

| Column | Type | Req |
|---|---|---|
| `id` | UUID | YES |
| `business_id` | UUID FK | YES |
| `language` | varchar(50) | YES |
| `createdAt` | timestamptz | YES |
| `modifiedAt` | timestamptz | YES |
| `deletedAt` | timestamptz | No |

---

## `partner_business_coverage_areas`
*Cities and regions served by the business.*

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `business_id` | UUID FK | YES | → `partner_business_profiles`. CASCADE on delete. |
| `area_type` | varchar(20) | YES | `national \| state \| city` |
| `state` | varchar(100) | No | Required when `area_type` is `state` or `city`. |
| `city` | varchar(100) | No | Required when `area_type` is `city`. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraints:**
- CHECK `area_type IN ('national','state','city')`
- Partial unique index on `(business_id) WHERE area_type = 'national' AND deletedAt IS NULL` — only one all-India row per business.

---

## `partner_awards_details`
| Column | Type | Req |
|---|---|---|
| `id` | UUID | YES |
| `partner_id` | UUID FK | YES |
| `title` | varchar(300) | YES |
| `year` | smallint | No |
| `issuingBody` | varchar(200) | No |
| `docUrl` | varchar(500) | No |
| `docUrlHash` | varchar(64) | No |
| `createdAt` | timestamptz | YES |
| `modifiedAt` | timestamptz | YES |
| `deletedAt` | timestamptz | No |

---

## `partner_references_details`
| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | UUID | YES | PK |
| `partner_id` | UUID FK | YES | → `partner_profiles`. |
| `name` | varchar(200) | YES | |
| `phone` | varchar(20) | No | |
| `relationship` | varchar(50) | No | `past_client \| fellow_partner \| other` |
| `isVerified` | boolean | YES | Default false. |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

---

## `categories_inventory`
| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | SERIAL | YES | PK |
| `slug` | varchar(60) | YES | UNIQUE. Drives extra-field rendering. |
| `label` | varchar(100) | YES | Display name. |
| `displayOrder` | smallint | YES | |
| `isActive` | boolean | YES | |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**13 launch categories:** photography, videography, venue, catering, bridal-makeup, mehendi, decor-florals, bridal-wear, dj-entertainment, wedding-planner, pandit-priest, band-baraat, invitation-designer

---

## `service_types_inventory`
| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | SERIAL | YES | PK |
| `category_id` | integer FK | YES | → `categories_inventory`. |
| `slug` | varchar(80) | YES | UNIQUE per category. |
| `label` | varchar(100) | YES | Chip display label. |
| `isActive` | boolean | YES | |
| `createdAt` | timestamptz | YES | |
| `modifiedAt` | timestamptz | YES | |
| `deletedAt` | timestamptz | No | |

**Constraint:** UNIQUE `(category_id, slug)`

---

## `audit_logs_history`
*Immutable. PostgreSQL RLS blocks UPDATE and DELETE for all app roles. No soft delete — append only.*

> **Rule:** Never add `update()` or `delete()` methods to this repository. No `createdAt`/`modifiedAt`/`deletedAt` columns — append-only by design.

| Column | Type | Req | Notes |
|---|---|---|---|
| `id` | BIGSERIAL | YES | Sequential PK. Space-efficient for high write volume. |
| `entityType` | varchar(60) | YES | e.g. `'partner_profiles'` |
| `entityId` | UUID | YES | Polymorphic — no FK constraint. |
| `action` | varchar(30) | YES | `CREATE \| UPDATE \| DELETE \| VERIFY \| APPROVE \| REJECT` |
| `actorType` | varchar(20) | YES | `partner \| admin \| customer \| system` |
| `actorId` | UUID | No | Who performed the action. |
| `oldData` | jsonb | No | Row snapshot before action. |
| `newData` | jsonb | No | Row snapshot after action. |
| `ipAddress` | inet | No | |
| `operatingSystem` | varchar(100) | No | e.g. `'Android 14'` |
| `browserName` | varchar(100) | No | e.g. `'Chrome 124'` |
| `deviceName` | varchar(200) | No | |
| `deviceType` | varchar(20) | No | `mobile \| tablet \| desktop` |
| `country` | varchar(100) | No | Resolved from IP. |
| `state` | varchar(100) | No | |
| `city` | varchar(100) | No | |
| `location` | point | No | GPS as `'(lat,lng)'`. |
| `occurredAt` | timestamptz | YES | Immutable once written. |

**Index:** `(entityType, entityId)` sorted by `occurredAt DESC`

---

## MongoDB — `notification_logs`
*High write volume. Append-only. TTL auto-purge after 180 days.*

```json
{
  "_id": "ObjectId",
  "user_id": "uuid-string",
  "event_type": "otp_sent | profile_approved | profile_rejected | new_lead | lead_reminder | weekly_digest",
  "channel": "whatsapp | sms | email",
  "template_id": "string",
  "status": "queued | sent | delivered | failed | bounced",
  "provider": "interakt | msg91 | aws_ses",
  "provider_msg_id": "string",
  "error_code": "string | null",
  "sent_at": "ISODate",
  "delivered_at": "ISODate | null",
  "created_at": "ISODate"
}
```

**Indexes:**
- Compound `(user_id, event_type)` — notification history per partner
- Compound `(status, sent_at)` — failed notification retry job
- TTL on `created_at` — `expireAfterSeconds: 15552000` (180 days)

---

## Entity relationship summary

| From | Cardinality | To | Notes |
|---|---|---|---|
| `partner_users` | 1:N | `partner_profiles` | `user_id` NOT UNIQUE — multi-profile architecture |
| `partner_users` | 1:N | `onboarding_states` | One state per category being onboarded |
| `partner_profiles` | 1:1 | `partner_pricing` | Separate entity — price edits never re-trigger moderation |
| `partner_profiles` | 1:1 | `partner_extra_fields_details` | One JSONB row per profile |
| `partner_profiles` | 1:N | `partner_media_details` | Up to 20 items |
| `partner_business_profiles` | 1:1 | `partner_tax_info_details` | Strict RLS — most roles cannot read |
| `partner_business_profiles` | 1:N | `partner_documents_details` | KYC docs — scoped to business, not per-category profile |
| `partner_documents_details` | 1:N | `document_review_txn` | Full review history per document |
| `partner_profiles` | 1:N | `partner_services_selected_items` | Service chip selections |
| `partner_profiles` | 1:N | `partner_awards_details` | Awards |
| `partner_profiles` | 1:N | `partner_references_details` | Vouching contacts |
| `partner_profiles` | 1:N | `admin_reviews_txn` | Full review history |
| `partner_profiles` | 1:N | `partner_leads` | Couple enquiries |
| `partner_users` | 1:1 | `partner_business_profiles` | UNIQUE `user_id` — one business per user for now |
| `partner_business_profiles` | 1:N | `partner_business_social_links` | Row per platform |
| `partner_business_profiles` | 1:N | `partner_business_languages` | Row per language |
| `partner_business_profiles` | 1:N | `partner_business_coverage_areas` | Row per coverage area |
| `categories_inventory` | 1:N | `partner_profiles` | RESTRICT on delete |
| `categories_inventory` | 1:N | `field_definitions_config` | Field definitions per category |
| `categories_inventory` | 1:N | `service_types_inventory` | Chip options per category |
| `categories_inventory` | 1:N | `onboarding_states` | |
| `field_definitions_config.fieldKey` | → | `partner_extra_fields_details.extraData` keys | Schema drives JSONB keys |
| All entities | → | `audit_logs_history` | Immutable audit trail |
| `partner_users` | 1:N | `notification_logs` (MongoDB) | Cross-DB string ref — no FK |