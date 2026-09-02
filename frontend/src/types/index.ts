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

/* -------------------------------------------------------------------------- */
/* Clinical                                                                    */
/* -------------------------------------------------------------------------- */

export interface Patient {
  uuid: string;
  mrn: string;
  full_name: string;
  gender: string;
  age_years: number | null;
  date_of_birth: string | null;
  phone: string;
  district: string;
  municipality: string;
  category: string;
  status: string;
  blood_group: string;
  registered_on: string;
}

export interface PatientAllergy {
  uuid: string;
  substance: string;
  category: string;
  reaction: string;
  severity: string;
  status: string;
  /** Whether prescribing should be stopped. Unconfirmed allergies still do. */
  blocks_prescribing: boolean;
}

export interface PatientCondition {
  uuid: string;
  name: string;
  icd10_code: string;
  category: string;
  status: string;
  onset_date: string | null;
}

export interface PatientDetail extends Patient {
  first_name: string;
  middle_name: string;
  last_name: string;
  is_dob_estimated: boolean;
  is_minor: boolean;
  is_merged: boolean;
  merged_into_mrn: string | null;
  tole: string;
  ward: string;
  guardian_name: string;
  guardian_relationship: string;
  guardian_phone: string;
  alerts: string;
  notes: string;
  allergies: PatientAllergy[];
  conditions: PatientCondition[];
}

export interface QueueToken {
  uuid: string;
  token_number: string;
  /** Needed to open a consultation straight from the queue. */
  patient_uuid: string;
  chief_complaint?: string;
  patient_mrn: string;
  patient_name: string;
  status: string;
  priority: number;
  is_emergency: boolean;
  waiting_minutes: number;
  call_count: number;
  counter: string;
}

export interface QueueStatistics {
  date: string;
  total_tokens: number;
  waiting: number;
  in_service: number;
  completed: number;
  skipped: number;
  left: number;
  emergencies: number;
  average_wait_minutes: number;
  longest_wait_minutes: number;
}

export interface QueueResponse {
  facility: string;
  statistics: QueueStatistics;
  queue: QueueToken[];
}

/** One provider session on one day, with how much room is left in it. */
export interface SessionAvailability {
  schedule_uuid: string;
  provider_uuid: string;
  provider_name: string;
  department: string | null;
  room: string;
  start_time: string;
  end_time: string;
  total_slots: number;
  slot_capacity: number;
  /** total_slots × slot_capacity — how many patients fit in the session. */
  capacity: number;
  booked: number;
  remaining_capacity: number;
  open_slot_times: number;
  is_blocked: boolean;
  next_free: string | null;
}

/* -------------------------------------------------------------------------- */
/* Encounters and prescribing                                                  */
/* -------------------------------------------------------------------------- */

export interface AbnormalFlag {
  field: string;
  level: "low" | "high" | "critical";
  note: string;
}

export interface VitalSigns {
  uuid: string;
  recorded_at: string;
  recorded_by_name: string;
  temperature_c: string | null;
  pulse_bpm: number | null;
  respiratory_rate: number | null;
  systolic_bp: number | null;
  diastolic_bp: number | null;
  blood_pressure: string | null;
  spo2_percent: number | null;
  weight_kg: string | null;
  height_cm: string | null;
  bmi: number | null;
  gcs_total: number | null;
  notes: string;
  abnormal: AbnormalFlag[];
}

export interface ClinicalNote {
  uuid: string;
  note_type: string;
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  body: string;
  author_name: string;
  is_signed: boolean;
  signed_at: string | null;
  is_amendment: boolean;
  amendment_reason: string;
  created_at: string;
}

export interface Diagnosis {
  uuid: string;
  name: string;
  icd10_code: string;
  certainty: string;
  is_primary: boolean;
  is_chronic: boolean;
}

export interface Encounter {
  uuid: string;
  reference: string;
  patient: string;
  patient_mrn: string;
  patient_name: string;
  encounter_type: string;
  status: string;
  facility_name: string;
  provider_name: string;
  chief_complaint: string;
  triage_category: number | null;
  started_at: string;
  ended_at: string | null;
  duration_minutes: number | null;
  is_open: boolean;
  disposition: string;
  is_signed: boolean;
}

export interface EncounterDetail extends Encounter {
  facility?: string;
  department_name: string | null;
  follow_up_date: string | null;
  follow_up_instructions: string;
  vitals: VitalSigns[];
  notes: ClinicalNote[];
  diagnoses: Diagnosis[];
}

/** Everything a clinician wants before they walk into the room. */
export interface ClinicalSummary {
  patient: {
    uuid: string;
    mrn: string;
    name: string;
    age: number | null;
    gender: string;
    blood_group: string;
    alerts: string;
  };
  allergies: {
    substance: string;
    severity: string;
    reaction: string;
    status: string;
    blocks_prescribing: boolean;
  }[];
  conditions: {
    name: string;
    icd10_code: string;
    status: string;
    onset_date: string | null;
  }[];
  latest_vitals: {
    recorded_at: string;
    blood_pressure: string | null;
    pulse_bpm: number | null;
    spo2_percent: number | null;
    bmi: number | null;
    abnormal: AbnormalFlag[];
  } | null;
  recent_encounters: {
    reference: string;
    started_at: string;
    encounter_type: string;
    facility: string;
    chief_complaint: string;
    status: string;
    diagnoses: { name: string; icd10_code: string; is_primary: boolean }[];
  }[];
}

export interface PrescriptionLineInput {
  generic_name: string;
  brand_name?: string;
  strength: string;
  dose: string;
  route: string;
  frequency: string;
  duration_days?: number;
  is_prn: boolean;
  prn_indication: string;
  instructions: string;
}

export interface SafetyWarning {
  type: "allergy" | "interaction" | "duplicate";
  severity: "info" | "moderate" | "high" | "critical";
  message: string;
  drug?: string;
  drugs?: string[];
  substance?: string;
  match?: string;
}

/**
 * The result of the prescribing safety checks.
 *
 * `is_blocking` is always false and is sent explicitly: the server warns and
 * records overrides, it never refuses to prescribe. A client must not present
 * these as a wall.
 */
export interface SafetyReport {
  warnings: SafetyWarning[];
  count: number;
  by_severity: Record<string, number>;
  requires_override: boolean;
  has_critical: boolean;
  is_blocking: false;
}

/* -------------------------------------------------------------------------- */
/* Billing                                                                     */
/* -------------------------------------------------------------------------- */

export interface ServiceItem {
  uuid: string;
  code: string;
  name: string;
  category: string;
  default_price: string;
  tax_treatment: string;
  effective_tax_rate: string;
  max_discount_percent: string;
  is_active: boolean;
}

export interface Charge {
  uuid: string;
  patient_mrn: string;
  service_code: string;
  service_name: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_amount: string;
  total: string;
  /** Which price list produced the price. Shown when a patient disputes it. */
  price_source: string;
  status: string;
  is_billable: boolean;
  charged_at: string;
}

export interface InvoiceLine {
  uuid: string;
  service_code: string;
  description: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_amount: string;
  total: string;
}

export interface Payment {
  uuid: string;
  receipt_number: string | null;
  amount: string;
  method: string;
  method_display: string;
  status: string;
  reference: string;
  received_at: string;
  received_by_name: string;
  is_refund: boolean;
}

export interface Invoice {
  uuid: string;
  number: string | null;
  fiscal_year: string;
  patient_mrn: string;
  bill_to_name: string;
  status: string;
  issued_at: string | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  rounding_adjustment: string;
  total: string;
  amount_paid: string;
  balance_due: string;
  is_settled: boolean;
  is_credit_note: boolean;
  credit_reason: string;
  lines: InvoiceLine[];
  payments: Payment[];
}

export interface PatientAccount {
  patient_uuid: string;
  patient_mrn: string;
  total_billed: string;
  total_paid: string;
  outstanding: string;
  /** Money owed *to* the patient, reported separately from what they owe. */
  credit_balance: string;
  uninvoiced_charges: string;
  uninvoiced_count: number;
  invoices: {
    number: string | null;
    issued_at: string | null;
    total: string;
    paid: string;
    balance: string;
    status: string;
    is_credit_note: boolean;
  }[];
}

export interface DailyCollection {
  date: string;
  facility: string;
  gross_collected: string;
  refunded: string;
  net_collected: string;
  by_method: Record<string, { label: string; total: string }>;
  invoices_issued: number;
  credit_notes_issued: number;
  invoiced_total: string;
  payment_count: number;
}

/* -------------------------------------------------------------------------- */
/* Diagnostics                                                                 */
/* -------------------------------------------------------------------------- */

export interface TestDefinition {
  uuid: string;
  code: string;
  name: string;
  modality: string;
  is_panel: boolean;
  component_codes: string[];
  result_data_type: string;
  unit: string;
  needs_specimen: boolean;
  patient_preparation: string;
  turnaround_minutes: number;
  is_active: boolean;
}

export interface DiagnosticResultRow {
  uuid: string;
  analyte_code: string;
  analyte_name: string;
  display_value: string;
  unit: string;
  reference_text: string;
  /** normal | low | high | abnormal | critical_low | critical_high */
  flag: string;
  is_abnormal: boolean;
  is_critical: boolean;
  entered_by_name: string;
  is_verified: boolean;
  was_amended: boolean;
}

export interface DiagnosticOrder {
  uuid: string;
  reference: string;
  patient: string;
  patient_mrn: string;
  patient_name: string;
  test_code: string;
  test_name: string;
  modality: string;
  priority: string;
  status: string;
  clinical_indication: string;
  ordered_by_name: string;
  ordered_at: string;
  due_at: string | null;
  accession_number: string | null;
  released_at: string | null;
  is_open: boolean;
  /** Past its expected turnaround and still not released. */
  is_overdue: boolean;
  turnaround_minutes: number | null;
}

export interface CriticalAlert {
  uuid: string;
  patient_mrn: string;
  patient_name: string;
  order_reference: string;
  analyte: string;
  value: string;
  flag: string;
  threshold: string;
  status: string;
  raised_at: string;
  notified_person: string;
  notified_via: string;
  notified_at: string | null;
  acknowledged_at: string | null;
  action_taken: string;
  /** Drives the quality report: an alert open for hours is a finding. */
  minutes_outstanding: number;
}

export interface DiagnosticOrderDetail extends DiagnosticOrder {
  facility_name: string;
  encounter_reference: string | null;
  clinical_notes: string;
  specimen_type: string;
  collected_by_name: string;
  rejection_reason: string;
  verified_by_name: string;
  collection_to_result_minutes: number | null;
  results: DiagnosticResultRow[];
  critical_alerts: CriticalAlert[];
}

export interface TurnaroundReport {
  since: string;
  released: number;
  /** Ordered to released. */
  average_total_minutes: number;
  /** Collection to result — the laboratory's own portion, reported apart. */
  average_lab_minutes: number;
  breached: number;
  breach_rate_percent: number;
  open: number;
  overdue: number;
  rejected: number;
  critical_alerts_open: number;
}

/* -------------------------------------------------------------------------- */
/* Pharmacy                                                                    */
/* -------------------------------------------------------------------------- */

export interface PharmacyProduct {
  uuid: string;
  code: string;
  generic_name: string;
  brand_name: string;
  strength: string;
  dosage_form: string;
  display_name: string;
  base_unit: string;
  storage_condition: string;
  needs_cold_chain: boolean;
  control_schedule: string;
  is_controlled: boolean;
  requires_prescription: boolean;
  reorder_level: string;
  is_active: boolean;
}

export interface StockLocation {
  uuid: string;
  code: string;
  name: string;
  location_type: string;
  is_quarantine: boolean;
  /** A store is not a counter — stock cannot be dispensed from one. */
  is_dispensable: boolean;
  is_active: boolean;
}

export interface StockLevel {
  uuid: string;
  product_name: string;
  batch_number: string;
  expires_on: string;
  days_to_expiry: number;
  location_code: string;
  quantity: string;
  reserved: string;
  available: string;
}

/** A FEFO allocation preview — what would leave the shelf, before committing. */
export interface FefoAllocation {
  product: string;
  requested: string;
  allocated: string;
  shortfall: string;
  /** True when a later-expiring batch was chosen over an earlier one. */
  breaks_fefo: boolean;
  earliest_batch: string | null;
  allocation: {
    batch_uuid: string;
    batch_number: string;
    expires_on: string;
    quantity: string;
    unit_price: string;
  }[];
}

export interface ExpiringItem {
  product_code: string;
  product_name: string;
  batch_number: string;
  expires_on: string;
  days_to_expiry: number;
  bucket: string;
  quantity: string;
  location: string;
  value_at_cost: string;
}

export interface ExpiringStockResponse {
  within_days: number;
  count: number;
  total_value_at_cost: string;
  by_bucket: Record<
    string,
    { count: number; value: string; items: ExpiringItem[] }
  >;
}

export interface ReorderSuggestion {
  product_code: string;
  product_name: string;
  on_hand: string;
  reorder_level: string;
  daily_consumption: string;
  lead_time_days: number;
  days_of_cover: number | null;
  /** Stock will run out before a delivery could arrive — order today. */
  stockout_before_delivery: boolean;
  suggested_quantity: string;
}

export interface ReorderResponse {
  count: number;
  urgent: number;
  suggestions: ReorderSuggestion[];
}
