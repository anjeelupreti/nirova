/**
 * Types mirroring the backend's response shapes.
 *
 * Hand-written for now. Once the API stabilises these should be generated
 * from the OpenAPI schema at `/api/schema/` so they cannot drift — a
 * hand-maintained type that has quietly diverged from the server is worse
 * than no type at all, because it is believed.
 */

export interface User {
  uuid: string;
  email: string;
  full_name: string;
  display_name: string;
  is_platform_staff: boolean;
  mfa_enabled: boolean;
}

export interface Membership {
  uuid: string;
  organization_uuid: string;
  organization_slug: string;
  organization_name: string;
  organization_status: string;
  business_type: string;
  status: string;
  is_default: boolean;
  is_organization_owner: boolean;
}

export interface Organization {
  uuid: string;
  slug: string;
  display_name: string;
  business_type: string;
  status: string;
  primary_color: string;
  is_read_only: boolean;
}

export interface GrantedPermission {
  scope: string;
  facility_ids: string[];
  sources: string[];
}

export interface Authorization {
  user_id: string;
  organization_id: string;
  is_organization_owner: boolean;
  permissions: Record<string, GrantedPermission>;
}

/** One resolved limit, with the provenance of the number. */
export interface LimitSpec {
  key: string;
  value: number | null;
  unlimited: boolean;
  enforcement: "hard" | "soft" | "grace" | "metered";
  warn_at_percent: number;
  sources: string[];
}

export interface Entitlements {
  organization_id: string;
  plan_code: string;
  subscription_status: string;
  is_entitled: boolean;
  modules: Record<string, boolean>;
  features: Record<string, boolean>;
  limits: Record<string, LimitSpec>;
  provenance: Record<string, string[]>;
}

export interface Session {
  user: User;
  memberships: Membership[];
  organization: Organization | null;
  authorization: Authorization | null;
  entitlements: Entitlements | null;
  tenant_error?: { code: string; message: string };
}

export interface Facility {
  uuid: string;
  code: string;
  name: string;
  facility_type: string;
  status: string;
  is_operational: boolean;
  district: string;
  municipality: string;
  department_count: number;
  opened_on: string | null;
  origin_reference: string;
}

/** Capacity for one facility type. Drives the capacity screen. */
export interface CapacityRow {
  facility_type: string;
  limit: number | null;
  unlimited: boolean;
  used: number;
  remaining: number | null;
  enforcement: string;
  module_entitled: boolean;
  sources: string[];
}

export interface CapacityResponse {
  plan: string;
  subscription_status: string;
  is_entitled: boolean;
  overall: {
    limit: number | null;
    unlimited: boolean;
    used: number;
    remaining: number | null;
    sources: string[];
  };
  by_type: Record<string, CapacityRow>;
}

export interface QuotaDecision {
  key: string;
  allowed: boolean;
  limit: number | null;
  unlimited: boolean;
  current_usage: number;
  requested: number;
  remaining: number | null;
  usage_percent: number | null;
  enforcement: string;
  reason: string;
  is_overage: boolean;
  is_warning: boolean;
  sources: string[];
  remediation: { action: string; label: string; detail: string }[];
}

export interface EscalationReason {
  code: string;
  message: string;
  key?: string;
  limit?: number | null;
  current_usage?: number;
}

/** What `POST /facility-requests/preview/` returns. */
export interface ChangePreview {
  evaluated_at: string;
  plan_code: string;
  subscription_status: string;
  quota_decisions: QuotaDecision[];
  escalation_reasons: EscalationReason[];
  within_entitlement: boolean;
  churn: {
    window_days?: number;
    closures_in_window?: number;
    is_churn_signal?: boolean;
    recent?: { name: string; code: string; closed_at: string | null }[];
  };
  required_module: string | null;
  approval_level: "automatic" | "organization" | "platform" | "both";
}

export interface ChangeRequestDecision {
  uuid: string;
  level: string;
  decision: string;
  decided_by_email: string;
  decided_at: string;
  comment: string;
}

export interface FacilityChangeRequest {
  uuid: string;
  reference: string;
  organization_slug: string;
  organization_name: string;
  request_type: string;
  status: string;
  approval_level: string;
  facility_type: string;
  proposed_name: string;
  proposed_code: string;
  justification: string;
  requires_capacity_purchase: boolean;
  escalation_reasons: EscalationReason[];
  churn_signal: Record<string, unknown>;
  requested_by_email: string;
  submitted_at: string | null;
  decided_at: string | null;
  executed_at: string | null;
  execution_error: string;
  is_open: boolean;
  age_in_days: number;
  decisions: ChangeRequestDecision[];
  created_at: string;
}

export interface Paginated<T> {
  count: number;
  page: number;
  pages: number;
  page_size: number;
  results: T[];
}
