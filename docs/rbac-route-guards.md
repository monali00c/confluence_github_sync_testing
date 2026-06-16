---
title: RBAC Route Guards
sync_to_confluence: true
confluence-labels:
  - technical
  - security
  - rbac
---

# Route Guards Reference

Documents every route's current auth guards and the suggested RBAC module guard to add.

**Guard types in use:**
- `AdminJwtAuthGuard` — verifies admin JWT (`ADMIN_JWT_SECRET`)
- `SuperAdminGuard` — requires `role === 'super_admin'`
- `AdminModuleGuard` — requires the admin's `permissions` array to include the module name (or `'*'`)
- `JwtAuthGuard` — verifies partner/customer JWT (`JWT_SECRET`)
- `PartnerModuleGuard` — requires `partnerPermissions` array to include the module name

`AdminModuleGuard` is redundant on routes already behind `SuperAdminGuard` (super_admin bypasses it). The suggestions below focus on routes that are behind `AdminJwtAuthGuard` **without** `SuperAdminGuard` — those are the gaps where a regular admin could access anything.

---

## Public Routes (no auth)

| Method | Path | Current Guards | Suggested Change |
|--------|------|----------------|-----------------|
| POST | `/api/v1/auth/register` | None | — |
| POST | `/api/v1/auth/login` | None | — |
| POST | `/api/v1/auth/refresh` | None | — |
| POST | `/api/v1/auth/otp/send` | None | — |
| POST | `/api/v1/auth/forgot-password` | None | — |
| POST | `/api/v1/auth/reset-password` | None | — |
| GET | `/api/v1/categories` | None | — |
| GET | `/api/v1/categories/:slug` | None | — |
| POST | `/api/v1/admin/auth/login` | None | — |

---

## Partner / Customer Routes

| Method | Path | Current Guards | Suggested Addition |
|--------|------|----------------|-------------------|
| DELETE | `/api/v1/auth/logout` | `JwtAuthGuard` | — |
| DELETE | `/api/v1/auth/logout/all` | `JwtAuthGuard` | — |
| GET | `/api/v1/categories/:slug/schema` | `JwtAuthGuard` | — |
| GET | `/api/v1/users/:id` | `JwtAuthGuard` | — |
| PATCH | `/api/v1/users/:id` | `JwtAuthGuard` | — |
| DELETE | `/api/v1/users/:id` | `JwtAuthGuard` | — |
| GET | `/api/v1/dashboard` | `JwtAuthGuard` | `PartnerModuleGuard` + `@RequiresPartnerModule(PARTNER_MODULES.DASHBOARD.name)` |

---

## Admin Routes — SuperAdmin only (no module guard needed)

These are already fully locked to `super_admin`. `AdminModuleGuard` would be redundant here since super_admin gets `permissions: ['*']`.

| Method | Path | Current Guards |
|--------|------|----------------|
| POST | `/api/v1/admin/admins` | `AdminJwtAuthGuard, SuperAdminGuard` |
| PATCH | `/api/v1/admin/admins/:id/status` | `AdminJwtAuthGuard, SuperAdminGuard` |
| GET | `/api/v1/admin/admins` | `AdminJwtAuthGuard, SuperAdminGuard` |
| POST | `/api/v1/admin/categories` | `AdminJwtAuthGuard, SuperAdminGuard` |
| PATCH | `/api/v1/admin/categories/:id` | `AdminJwtAuthGuard, SuperAdminGuard` |
| DELETE | `/api/v1/admin/categories/:id` | `AdminJwtAuthGuard, SuperAdminGuard` |
| PATCH | `/api/v1/admin/categories/:id/restore` | `AdminJwtAuthGuard, SuperAdminGuard` |
| PATCH | `/api/v1/admin/categories/:categoryId/fields/:fieldId/rename-key` | `AdminJwtAuthGuard, SuperAdminGuard` |
| All 9 | `/api/v1/admin/rbac/*` | `AdminJwtAuthGuard, SuperAdminGuard` |
| All 14 | `/api/v1/admin/partner-tiers/*`, `/admin/customer-tiers/*`, `/admin/users/:id/*-tier` | `AdminJwtAuthGuard, SuperAdminGuard` |

---

## Admin Routes — Gap: AdminJwtAuthGuard only, no module gate

These are accessible to **any** admin regardless of role assignment. Add `AdminModuleGuard` + `@RequiresModule(...)` to enforce per-role access control.

### Categories module

| Method | Path | Current Guards | Add |
|--------|------|----------------|-----|
| GET | `/api/v1/admin/categories` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| GET | `/api/v1/admin/categories/:id` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:id/activate` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:id/deactivate` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| GET | `/api/v1/admin/categories/:categoryId/fields` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| GET | `/api/v1/admin/categories/:categoryId/fields/:fieldId` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| POST | `/api/v1/admin/categories/:categoryId/fields` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:categoryId/fields/:fieldId` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| DELETE | `/api/v1/admin/categories/:categoryId/fields/:fieldId` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:categoryId/fields/:fieldId/restore` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:categoryId/fields/:fieldId/activate` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |
| PATCH | `/api/v1/admin/categories/:categoryId/fields/:fieldId/deactivate` | `AdminJwtAuthGuard` | `AdminModuleGuard` + `@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)` |

**Quickest way to apply:** Add at the class level on both `AdminCategoriesController` and `AdminFieldDefinitionsController`:

```typescript
@UseGuards(AdminJwtAuthGuard, AdminModuleGuard)
@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)
```

---

## How to apply

```typescript
// At class level (gates entire controller)
import { AdminModuleGuard } from '@modules/admin/guards/admin-module.guard';
import { RequiresModule } from '@common/decorators/requires-module.decorator';
import { INTERNAL_MODULES } from '@common/constants/rbac-modules';

@UseGuards(AdminJwtAuthGuard, AdminModuleGuard)
@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)
@Controller('admin/categories')
export class AdminCategoriesController { ... }

// At method level (gates a single route)
@UseGuards(AdminModuleGuard)
@RequiresModule(INTERNAL_MODULES.CATEGORIES.name)
@Get()
listCategories() { ... }

// Partner route
import { PartnerModuleGuard } from '@common/guards/partner-module.guard';
import { RequiresPartnerModule } from '@common/decorators/requires-partner-module.decorator';
import { PARTNER_MODULES } from '@common/constants/rbac-modules';

@UseGuards(JwtAuthGuard, PartnerModuleGuard)
@RequiresPartnerModule(PARTNER_MODULES.DASHBOARD.name)
@Controller('dashboard')
export class DashboardController { ... }
```

---

## Summary of gaps

| Priority | Action |
|----------|--------|
| High | Add `AdminModuleGuard` + `@RequiresModule(CATEGORIES)` to `AdminCategoriesController` and `AdminFieldDefinitionsController` |
| Medium | Add `PartnerModuleGuard` + `@RequiresPartnerModule(DASHBOARD)` to `DashboardController` |
| Low | `USER_MANAGEMENT`, `RBAC`, `TIER_MANAGEMENT` modules are already `SuperAdminGuard`-only — no gap today, but if you ever create non-super admin roles that need access to these, add `AdminModuleGuard` then |