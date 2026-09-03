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

// ---------------------------------------------------------------------------
// Point of sale
// ---------------------------------------------------------------------------

export interface CounterSession {
  uuid: string;
  reference: string;
  facility: string;
  facility_name: string;
  location: string;
  location_code: string;
  counter: string;
  cashier_id: string;
  cashier_name: string;
  status: "open" | "closing" | "closed" | "reconciled";
  opened_at: string;
  closed_at: string | null;
  opening_float: string;
  closing_count: string | null;
  expected_cash: string | null;
  variance: string | null;
  has_variance: boolean;
  variance_reason: string;
  card_total: string;
  wallet_total: string;
  credit_total: string;
  reconciled_at: string | null;
  duration_minutes: number | null;
  notes: string;
}

/** One row from the counter's product lookup. */
export interface CounterProduct {
  uuid: string;
  code: string;
  name: string;
  generic_name: string;
  brand_name: string;
  dosage_form: string;
  base_unit: string;
  barcode: string;
  available: string;
  batch_uuid: string | null;
  batch_number: string;
  expires_on: string | null;
  unit_price: string;
  mrp: string;
  requires_prescription: boolean;
}

/**
 * A priced basket that has not been committed.
 *
 * The counter never computes its own total: the figure a customer is asked
 * for is rounded to the whole rupee server-side, and a client that did its
 * own arithmetic would eventually disagree with the invoice.
 */
export interface SaleQuote {
  lines: {
    product: string;
    product_name: string;
    batch_number: string;
    expires_on: string;
    quantity: string;
    unit_price: string;
    discount_percent: string;
    discount_amount: string;
    tax_percent: string;
    tax_amount: string;
    total: string;
  }[];
  subtotal: string;
  discount_total: string;
  tax_total: string;
  rounding_adjustment: string;
  total: string;
  shortfalls: { product: string; requested: string; available: string }[];
  warnings: string[];
  can_sell: boolean;
}

export interface SaleLine {
  uuid: string;
  product: string;
  product_name: string;
  batch: string;
  batch_number: string;
  expires_on: string;
  quantity: string;
  returned_quantity: string;
  returnable_quantity: string;
  unit_price: string;
  mrp: string;
  discount_percent: string;
  discount_amount: string;
  tax_percent: string;
  tax_amount: string;
  total: string;
}

export interface Sale {
  uuid: string;
  reference: string;
  session: string;
  session_reference: string;
  facility: string;
  location: string;
  sale_type: string;
  patient: string | null;
  customer_label: string;
  customer_name: string;
  customer_phone: string;
  customer_pan: string;
  prescription_reference: string;
  status:
    | "draft"
    | "completed"
    | "partially_returned"
    | "returned"
    | "voided";
  sold_at: string;
  sold_by_name: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  rounding_adjustment: string;
  total: string;
  invoice_number: string;
  void_reason: string;
  notes: string;
  lines: SaleLine[];
}

export interface SaleReturn {
  uuid: string;
  reference: string;
  sale: string;
  sale_reference: string;
  session: string;
  status: "pending" | "approved" | "rejected" | "completed";
  reason: string;
  restock: boolean;
  restock_note: string;
  requested_by_name: string;
  approved_by_name: string;
  approved_at: string | null;
  decision_notes: string;
  refund_total: string;
  refund_method: string;
  credit_note_number: string;
  completed_at: string | null;
  lines: {
    uuid: string;
    sale_line: string;
    product_name: string;
    batch_number: string;
    quantity: string;
    refund_amount: string;
    condition_note: string;
  }[];
}

export interface SessionTakings {
  reference: string;
  sales_count: number;
  sales_total: string;
  cash: string;
  card: string;
  wallet: string;
  credit: string;
  by_method: Record<string, string>;
  /** Only present when the caller asked for a non-blind read. */
  expected_cash?: string;
  opening_float?: string;
}

export interface SalesSummary {
  date: string;
  sales_count: number;
  gross_revenue: string;
  returns_count: number;
  returns_total: string;
  net_revenue: string;
  tax: string;
  cost_of_goods: string;
  cost_recovered: string;
  cost_written_off: string;
  net_cost_of_goods: string;
  gross_margin: string;
  margin_percent: string;
  top_products: { product_name: string; quantity: string; total: string }[];
}

// ---------------------------------------------------------------------------
// Procurement
// ---------------------------------------------------------------------------

export interface Supplier {
  uuid: string;
  code: string;
  name: string;
  legal_name: string;
  pan_number: string;
  vat_number: string;
  contact_person: string;
  phone: string;
  email: string;
  address: string;
  district: string;
  agreed_lead_time_days: number;
  credit_days: number;
  credit_limit: string;
  product_categories: string;
  drug_licence_number: string;
  drug_licence_expires_on: string | null;
  licence_expired: boolean;
  status: string;
  status_reason: string;
  can_order_from: boolean;
  bank_name: string;
  notes: string;
}

export interface SupplierPerformance {
  supplier: string;
  receipts: number;
  agreed_lead_time_days: number;
  measured_lead_time_days: number | null;
  /** Positive means slower than promised. */
  lead_time_variance: number | null;
  expected_units: string;
  received_units: string;
  fill_rate_percent: number | null;
  rejection_rate_percent: number | null;
  orders_late: number;
  currently_overdue: {
    reference: string;
    expected: string;
    days_late: number;
    value: string;
  }[];
}

export interface RequisitionLine {
  uuid: string;
  product: string;
  product_name: string;
  quantity: string;
  ordered_quantity: string;
  outstanding_quantity: string;
  is_fully_ordered: boolean;
  estimated_unit_price: string;
  /** Frozen when the requisition was raised, so an approver sees what the
   *  requester saw rather than today's figure. */
  stock_on_hand: string;
  reorder_level: string;
  notes: string;
}

export interface PurchaseRequisition {
  uuid: string;
  reference: string;
  facility: string;
  facility_name: string;
  department: string | null;
  location: string | null;
  status: string;
  is_open: boolean;
  is_urgent: boolean;
  required_by: string | null;
  justification: string;
  requested_by_name: string;
  decided_by_name: string;
  decided_at: string | null;
  decision_notes: string;
  created_at: string;
  lines: RequisitionLine[];
}

export interface QuotationLine {
  uuid: string;
  product: string;
  product_name: string;
  quantity: string;
  unit_price: string;
  free_quantity: string;
  discount_percent: string;
  tax_percent: string;
  effective_unit_cost: string;
  total: string;
}

export interface Quotation {
  uuid: string;
  reference: string;
  requisition: string;
  supplier: string;
  supplier_name: string;
  status: string;
  quoted_on: string;
  valid_until: string | null;
  is_expired: boolean;
  quoted_lead_time_days: number | null;
  payment_terms: string;
  total_value: string;
  notes: string;
  lines: QuotationLine[];
}

/** Quotations ranked on blended cost per unit, never on total spend. */
export interface QuotationComparison {
  count: number;
  quotations: {
    uuid: string;
    reference: string;
    supplier: string;
    supplier_uuid: string;
    total_value: string;
    total_units: string;
    cost_per_unit: string;
    quoted_lead_time_days: number | null;
    agreed_lead_time_days: number;
    is_expired: boolean;
    can_order_from: boolean;
    valid_until: string | null;
    lines: {
      product: string;
      quantity: string;
      free_quantity: string;
      unit_price: string;
      effective_unit_cost: string;
      total: string;
    }[];
  }[];
  cheapest: string | null;
  cheapest_cost_per_unit: string | null;
  cheapest_total: string | null;
  ineligible: string[];
}

export interface PurchaseOrderLine {
  uuid: string;
  product: string;
  product_code: string;
  product_name: string;
  quantity: string;
  free_quantity: string;
  received_quantity: string;
  outstanding_quantity: string;
  unit_price: string;
  discount_percent: string;
  tax_percent: string;
  total: string;
}

export interface PurchaseOrder {
  uuid: string;
  reference: string;
  facility: string;
  facility_name: string;
  supplier: string;
  supplier_name: string;
  requisition: string | null;
  requisition_reference: string;
  quotation: string | null;
  deliver_to: string | null;
  status: string;
  is_open: boolean;
  is_overdue: boolean;
  days_late: number;
  ordered_on: string | null;
  expected_delivery: string | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total: string;
  currency: string;
  created_by_name: string;
  approved_by_name: string;
  approved_at: string | null;
  payment_terms: string;
  delivery_terms: string;
  notes: string;
  lines: PurchaseOrderLine[];
}

export interface ReceiptLine {
  uuid: string;
  product: string;
  product_name: string;
  batch: string | null;
  batch_number: string;
  expires_on: string;
  manufactured_on: string | null;
  received_quantity: string;
  free_quantity: string;
  rejected_quantity: string;
  accepted_quantity: string;
  total_units: string;
  unit_cost: string;
  effective_unit_cost: string;
  selling_price: string;
  mrp: string;
  rejection_reason: string;
  total: string;
}

export interface GoodsReceipt {
  uuid: string;
  reference: string;
  order: string;
  order_reference: string;
  supplier: string;
  supplier_name: string;
  facility: string;
  location: string;
  location_code: string;
  status: string;
  is_posted: boolean;
  received_on: string;
  received_by_name: string;
  delivery_note_number: string;
  supplier_invoice_number: string;
  supplier_invoice_date: string | null;
  supplier_invoice_amount: string | null;
  /** Null when no supplier invoice has been recorded to match against. */
  invoice_matches: boolean | null;
  quality_checked_at: string | null;
  quality_notes: string;
  posted_at: string | null;
  total_value: string;
  notes: string;
  lines: ReceiptLine[];
}

export interface ProcurementDashboard {
  facility: string;
  requisitions_awaiting_approval: number;
  requisitions_approved_unordered: number;
  orders_awaiting_approval: number;
  orders_open: number;
  orders_overdue: number;
  open_order_value: string;
  receipts_awaiting_check: number;
  receipts_awaiting_posting: number;
  suppliers_blocked: number;
  licences_expiring: number;
  overdue_orders: {
    reference: string;
    supplier: string;
    expected: string;
    days_late: number;
    value: string;
  }[];
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

export interface Position {
  uuid: string;
  code: string;
  title: string;
  title_nepali: string;
  facility: string | null;
  facility_name: string;
  department: string | null;
  department_name: string;
  grade: string;
  reports_to: string | null;
  budgeted_headcount: number;
  filled: number;
  vacancies: number;
  job_description: string;
  is_clinical: boolean;
  /** Takes appointments. A ward nurse is clinical and is not a provider. */
  is_provider: boolean;
  requires_licence: boolean;
  is_active: boolean;
}

export interface Credential {
  uuid: string;
  employee: string;
  credential_type: string;
  name: string;
  issuing_body: string;
  reference_number: string;
  issued_on: string | null;
  expires_on: string | null;
  is_expired: boolean;
  days_to_expiry: number | null;
  /** True when this credential's state stops the person practising. */
  blocks_practice: boolean;
  verification_status: "unverified" | "verified" | "failed";
  verified_by_name: string;
  verified_at: string | null;
  verification_notes: string;
  document_url: string;
  notes: string;
}

export interface Experience {
  uuid: string;
  employee: string;
  organization_name: string;
  job_title: string;
  department: string;
  started_on: string;
  ended_on: string | null;
  months: number;
  years: string;
  responsibilities: string;
  reference_name: string;
  reference_contact: string;
  is_verified: boolean;
  document_url: string;
}

export interface EmployeeSkill {
  uuid: string;
  employee: string;
  name: string;
  level: string;
  assessed_on: string | null;
  assessed_by_name: string;
  notes: string;
}

export interface EmployeeDocument {
  uuid: string;
  employee: string;
  document_type: string;
  title: string;
  file_url: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  expires_on: string | null;
  is_expired: boolean;
  is_mandatory: boolean;
  notes: string;
}

export interface EmploymentEvent {
  uuid: string;
  employee: string;
  event_type: string;
  effective_on: string;
  summary: string;
  from_position: string;
  to_position: string;
  from_facility: string;
  to_facility: string;
  from_department: string;
  to_department: string;
  from_employment_type: string;
  to_employment_type: string;
  reason: string;
  approved_by_name: string;
  notes: string;
  created_at: string;
}

export interface EmploymentContract {
  uuid: string;
  employee: string;
  reference: string;
  employment_type: string;
  starts_on: string;
  ends_on: string | null;
  is_expired: boolean;
  days_to_expiry: number | null;
  notice_period_days: number;
  basic_salary: string;
  rate_basis: string;
  allowances: Record<string, string>;
  gross_monthly: string;
  working_hours_per_week: string;
  status: string;
  signed_on: string | null;
  document_url: string;
  notes: string;
}

export interface EmployeeSummary {
  uuid: string;
  employee_code: string;
  full_name: string;
  first_name: string;
  last_name: string;
  position: string | null;
  position_title: string;
  facility: string;
  facility_name: string;
  department: string | null;
  department_name: string;
  employment_type: string;
  status: string;
  is_working: boolean;
  is_provider: boolean;
  joined_on: string;
  phone: string;
  work_email: string;
  photo_url: string;
}

export interface Employee extends EmployeeSummary {
  middle_name: string;
  name_nepali: string;
  date_of_birth: string | null;
  gender: string;
  citizenship_number: string;
  pan_number: string;
  blood_group: string;
  personal_email: string;
  address: string;
  province: string;
  district: string;
  municipality: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  emergency_contact_relation: string;
  reports_to: string | null;
  manager_name: string;
  on_probation: boolean;
  /** Probation ended and nobody confirmed or terminated — legally ambiguous. */
  probation_overdue: boolean;
  probation_ends_on: string | null;
  confirmed_on: string | null;
  separated_on: string | null;
  separation_reason: string;
  years_of_service: string;
  user_id: string | null;
  bank_name: string;
  bank_account_number: string;
  bank_branch: string;
  notes: string;
  credentials: Credential[];
  experience: Experience[];
  skills: EmployeeSkill[];
  documents: EmployeeDocument[];
}

export interface PracticeStatus {
  employee: string;
  may_practise: boolean;
  is_provider: boolean;
  blockers: { code: string; message: string; credential?: string }[];
}

export interface HrDashboard {
  headcount: {
    total: number;
    by_employment_type: Record<string, number>;
    by_department: { "department__name": string | null; count: number }[];
    budgeted: number;
    filled: number;
    vacancies: number;
    on_probation: number;
    probation_overdue: number;
    suspended: number;
    vacant_positions: {
      code: string;
      title: string;
      budgeted: number;
      filled: number;
      vacancies: number;
    }[];
  };
  expiring_credentials: {
    credential: string;
    employee_code: string;
    employee_name: string;
    position: string;
    type: string;
    name: string;
    reference_number: string;
    expires_on: string;
    days_to_expiry: number;
    is_expired: boolean;
    blocks_practice: boolean;
    verification_status: string;
  }[];
  expiring_contracts: {
    contract: string;
    employee_code: string;
    employee_name: string;
    employment_type: string;
    ends_on: string;
    days_to_expiry: number;
    is_expired: boolean;
    gross_monthly: string;
  }[];
  separations: {
    since: string;
    total: number;
    by_type: Record<string, number>;
    turnover_percent_of_current_headcount: number;
  };
}

// ---------------------------------------------------------------------------
// Time: shifts, roster, attendance and leave
// ---------------------------------------------------------------------------

export interface Shift {
  uuid: string;
  code: string;
  name: string;
  shift_type: string;
  facility: string | null;
  department: string | null;
  starts_at: string;
  ends_at: string;
  /** A night shift's end time is earlier than its start. Stated, not inferred. */
  crosses_midnight: boolean;
  duration_hours: string;
  break_minutes: number;
  grace_minutes: number;
  half_day_hours: string;
  minimum_rest_hours: string;
  is_active: boolean;
  colour: string;
}

export interface Holiday {
  uuid: string;
  name: string;
  name_nepali: string;
  date: string;
  facility: string | null;
  /** Staff may choose to work; absence is not counted either way. */
  is_optional: boolean;
  applies_to: string;
  notes: string;
}

export interface RosterEntry {
  uuid: string;
  employee: string;
  employee_code: string;
  employee_name: string;
  shift: string;
  shift_code: string;
  shift_name: string;
  starts_at: string;
  ends_at: string;
  colour: string;
  date: string;
  facility: string;
  department: string | null;
  status: string;
  published_at: string | null;
  is_on_call: boolean;
  notes: string;
}

export interface AttendanceRecord {
  uuid: string;
  employee: string;
  employee_code: string;
  employee_name: string;
  date: string;
  facility: string;
  roster_entry: string | null;
  checked_in_at: string | null;
  checked_out_at: string | null;
  /** False when somebody checked in and never checked out. */
  is_complete: boolean;
  source: string;
  within_geofence: boolean | null;
  status: string;
  late_minutes: number;
  early_exit_minutes: number;
  worked_hours: string;
  overtime_hours: string;
  is_regularised: boolean;
  notes: string;
}

export interface Regularisation {
  uuid: string;
  attendance: string;
  employee_name: string;
  date: string;
  requested_by_name: string;
  original_checked_in_at: string | null;
  original_checked_out_at: string | null;
  original_status: string;
  requested_checked_in_at: string | null;
  requested_checked_out_at: string | null;
  reason: string;
  status: string;
  decided_by_name: string;
  decided_at: string | null;
  decision_notes: string;
}

export interface LeaveType {
  uuid: string;
  code: string;
  name: string;
  description: string;
  annual_entitlement: string;
  unit: string;
  is_paid: boolean;
  carry_forward: boolean;
  max_carry_forward: string;
  encashable: boolean;
  requires_document: boolean;
  document_required_after_days: string;
  minimum_notice_days: number;
  maximum_consecutive_days: string;
  minimum_service_months: number;
  allow_negative_balance: boolean;
  is_active: boolean;
  colour: string;
}

export interface LeaveRequest {
  uuid: string;
  reference: string;
  employee: string;
  employee_code: string;
  employee_name: string;
  leave_type: string;
  leave_type_name: string;
  starts_on: string;
  ends_on: string;
  is_half_day: boolean;
  calendar_days: string;
  /** Weekly offs and holidays excluded, frozen at application. */
  working_days: string;
  reason: string;
  contact_during_leave: string;
  delegate: string | null;
  delegate_name: string;
  document_url: string;
  status: string;
  is_open: boolean;
  applied_at: string;
  decided_by_name: string;
  decided_at: string | null;
  decision_notes: string;
  cancellation_reason: string;
  is_unpaid: boolean;
  leave_year: string;
}

export interface LeaveBalance {
  leave_type: string;
  leave_type_name: string;
  year: string;
  balance: string;
  pending: string;
  available: string;
  by_reason: Record<string, string>;
  entitlement: string;
}

export interface LeaveBalances {
  employee: string;
  employee_name: string;
  balances: LeaveBalance[];
}

export interface LeaveLedgerEntry {
  uuid: string;
  employee: string;
  leave_type: string;
  leave_type_name: string;
  leave_year: string;
  days: string;
  reason: string;
  effective_on: string;
  reference_type: string;
  reference_id: string;
  recorded_by_name: string;
  notes: string;
}

export interface LeaveCalendarRow {
  reference: string;
  employee_code: string;
  employee_name: string;
  department: string;
  leave_type: string;
  colour: string;
  starts_on: string;
  ends_on: string;
  working_days: string;
  status: string;
  is_unpaid: boolean;
  delegate: string;
}

export interface AttendanceSummary {
  from: string;
  to: string;
  records: number;
  by_status: Record<string, number>;
  total_hours: string;
  overtime_hours: string;
  total_late_minutes: number;
  /** Check-in with no check-out — not the same as a short day. */
  unclosed_days: number;
  by_employee: {
    employee__employee_code: string;
    employee__first_name: string;
    employee__last_name: string;
    days: number;
    late_minutes: number;
    absent: number;
    overtime: string;
  }[];
}

// ---------------------------------------------------------------------------
// Payroll
// ---------------------------------------------------------------------------

export interface PayComponent {
  uuid: string;
  code: string;
  name: string;
  component_type: "earning" | "deduction" | "employer" | "tax" | "reimbursement";
  basis: string;
  rate: string;
  amount: string;
  is_taxable: boolean;
  /** In Nepal, SSF and PF are on basic salary, not gross. */
  counts_towards_contribution_base: boolean;
  is_prorated: boolean;
  sequence: number;
  is_statutory: boolean;
  is_active: boolean;
  notes: string;
}

export interface SalaryStructure {
  uuid: string;
  code: string;
  name: string;
  description: string;
  facility: string | null;
  components: PayComponent[];
  is_active: boolean;
}

export interface TaxSlab {
  uuid: string;
  fiscal_year: string;
  regime: "individual" | "couple";
  sequence: number;
  lower_bound: string;
  upper_bound: string | null;
  width: string | null;
  rate_percent: string;
  /** The 1% band is Nepal's social security tax, replaced by an SSF contribution. */
  waived_for_ssf_contributors: boolean;
  label: string;
}

export interface ContributionScheme {
  uuid: string;
  code: string;
  name: string;
  fiscal_year: string;
  employee_percent: string;
  employer_percent: string;
  total_percent: string;
  on_basic: boolean;
  is_tax_deductible: boolean;
  annual_deduction_ceiling: string;
  replaces_social_security_tax: boolean;
  is_active: boolean;
  notes: string;
}

export interface PayrollRun {
  uuid: string;
  reference: string;
  facility: string;
  facility_name: string;
  fiscal_year: string;
  period_label: string;
  period_start: string;
  period_end: string;
  status:
    | "draft"
    | "calculated"
    | "pending_approval"
    | "approved"
    | "paid"
    | "cancelled";
  is_editable: boolean;
  corrects: string | null;
  calculated_at: string | null;
  approved_at: string | null;
  approved_by_name: string;
  paid_at: string | null;
  employee_count: number;
  gross_total: string;
  deduction_total: string;
  tax_total: string;
  net_total: string;
  /** What the organization pays on top of salaries — not part of net pay. */
  employer_cost_total: string;
  total_cost: string;
  notes: string;
  cancellation_reason: string;
}

export interface PayslipLine {
  uuid: string;
  component: string | null;
  code: string;
  name: string;
  component_type: string;
  basis: string;
  rate: string;
  base_amount: string;
  amount: string;
  is_taxable: boolean;
  sequence: number;
  /** How the figure was arrived at — "10% of 45,000" answers what "4,500" does not. */
  explanation: string;
}

export interface PayslipSummary {
  uuid: string;
  reference: string;
  run: string;
  period_label: string;
  employee: string;
  employee_code: string;
  employee_name: string;
  position_title: string;
  department_name: string;
  payable_days: string;
  gross: string;
  deductions: string;
  tax: string;
  net: string;
  employer_cost: string;
  is_held: boolean;
  hold_reason: string;
}

export interface Payslip extends PayslipSummary {
  run_reference: string;
  run_status: string;
  bank_name: string;
  bank_account_number: string;
  pan_number: string;
  basic_salary: string;
  days_in_period: string;
  days_present: string;
  days_paid_leave: string;
  days_unpaid_leave: string;
  days_absent: string;
  overtime_hours: string;
  taxable_gross: string;
  /** The whole tax derivation, so a payslip explains itself. */
  tax_workings: {
    fiscal_year?: string;
    regime?: string;
    months_projected?: string;
    annual_gross?: string;
    taxable_income?: string;
    annual_tax?: string;
    monthly_tax?: string;
    ssf_contributor?: boolean;
    slabs_missing?: boolean;
    remote_area_allowance?: string;
    disability_allowance?: string;
    retirement?: {
      contributed: string;
      flat_ceiling: string;
      one_third_of_income: string;
      deductible: string;
      binding_cap: string;
    };
    insurance?: {
      life_premium: string;
      life_deductible: string;
      life_cap: string;
      health_premium: string;
      health_deductible: string;
      health_cap: string;
      total: string;
    };
    bands?: {
      band: string;
      lower: string;
      upper: string | null;
      rate_percent: string;
      amount_taxed: string;
      tax: string;
      waived: boolean;
      waiver_reason: string;
    }[];
  };
  notes: string;
  lines: PayslipLine[];
}

export interface PayrollSummary {
  reference: string;
  period: string;
  status: string;
  employees: number;
  gross: string;
  deductions: string;
  tax: string;
  net: string;
  employer_cost: string;
  total_cost: string;
  held: number;
  held_reasons: [string, string][];
  missing_bank_details: number;
  by_component: {
    code: string;
    name: string;
    component_type: string;
    total: string;
    count: number;
  }[];
}

export interface StatutoryReturn {
  period: string;
  fiscal_year: string;
  income_tax: string;
  employee_contributions: string;
  employer_contributions: string;
  total_contributions: string;
  employees: number;
}

export interface PaymentBatch {
  uuid: string;
  reference: string;
  run: string;
  run_reference: string;
  method: string;
  status: string;
  total: string;
  count: number;
  bank_name: string;
  exported_at: string | null;
  confirmed_at: string | null;
  value_date: string;
  notes: string;
}

export interface BankFileRow {
  employee_code: string;
  employee_name: string;
  bank_name: string;
  account_number: string;
  amount: string;
  reference: string;
  /** Non-empty when this row cannot be paid — named, never silently dropped. */
  problem: string;
}

// ---------------------------------------------------------------------------
// Inpatient
// ---------------------------------------------------------------------------

export interface Ward {
  uuid: string;
  code: string;
  name: string;
  ward_type: string;
  facility: string;
  department: string | null;
  unit: string | null;
  floor: string;
  building: string;
  bed_count: number;
  is_critical_care: boolean;
  nurse_to_patient_ratio: string;
  is_gender_segregated: boolean;
  allows_attendant: boolean;
  visiting_hours: string;
  is_active: boolean;
  notes: string;
}

export interface Bed {
  uuid: string;
  ward: string;
  ward_name: string;
  ward_type: string;
  code: string;
  bay: string;
  /** Physical state — clean, dirty, broken. Not the same as occupancy. */
  status: string;
  status_reason: string;
  status_changed_at: string;
  gender_restriction: "any" | "male" | "female";
  has_oxygen: boolean;
  has_suction: boolean;
  has_monitor: boolean;
  has_ventilator: boolean;
  is_isolation: boolean;
  daily_rate: string;
  service_code: string;
  is_active: boolean;
  is_occupied: boolean;
  is_assignable: boolean;
  occupant_name: string;
  occupant_admission: string;
  notes: string;
}

export interface WardOccupancy {
  ward: string;
  ward_name: string;
  ward_type: string;
  total_beds: number;
  occupied: number;
  available: number;
  /** Beds that exist and cannot take a patient — cleaning, broken, blocked. */
  unusable: number;
  by_status: Record<string, number>;
  occupancy_percent: number;
  nurse_to_patient_ratio: string;
  nurses_needed: number | null;
}

export interface BedAssignment {
  uuid: string;
  admission: string;
  bed: string;
  bed_code: string;
  ward: string;
  ward_name: string;
  occupied_at: string;
  vacated_at: string | null;
  is_current: boolean;
  nights: number;
  daily_rate: string;
  reason: string;
  assigned_by_name: string;
}

export interface DischargeClearance {
  uuid: string;
  admission: string;
  kind: string;
  is_cleared: boolean;
  cleared_by_name: string;
  cleared_at: string | null;
  blocking_reason: string;
  notes: string;
}

export interface DailyAccrual {
  uuid: string;
  admission: string;
  accrual_date: string;
  kind: string;
  bed_assignment: string | null;
  service_code: string;
  description: string;
  quantity: string;
  unit_rate: string;
  amount: string;
  charge_uuid: string | null;
  notes: string;
}

export interface NursingRound {
  uuid: string;
  admission: string;
  recorded_at: string;
  shift: string;
  nurse_name: string;
  intake_ml: number;
  output_ml: number;
  balance_ml: number;
  pain_score: number | null;
  observations: string;
  interventions: string;
  escalated: boolean;
  escalation_reason: string;
}

export interface AdmissionSummary {
  uuid: string;
  reference: string;
  patient: string;
  patient_name: string;
  patient_mrn: string;
  facility: string;
  status: string;
  source: string;
  admitted_at: string;
  discharged_at: string | null;
  expected_discharge: string | null;
  consultant_name: string;
  admitting_diagnosis: string;
  bed_code: string;
  ward_name: string;
  length_of_stay_days: number;
  is_in_house: boolean;
  /** Past the expected discharge date and still here. */
  is_overstaying: boolean;
  is_mlc: boolean;
}

export interface Admission extends AdmissionSummary {
  encounter: string | null;
  department: string | null;
  provisional_diagnosis: string;
  final_diagnosis: string;
  attendant_name: string;
  attendant_phone: string;
  attendant_relation: string;
  deposit_expected: string;
  diet_plan: string;
  mlc_number: string;
  police_informed_at: string | null;
  outcome_notes: string;
  discharge_summary: string;
  discharge_advice: string;
  follow_up_on: string | null;
  cancelled_reason: string;
  notes: string;
  bed_assignments: BedAssignment[];
  clearances: DischargeClearance[];
}

export interface StayCharges {
  admission: string;
  nights: number;
  accrued_total: string;
  accruals_by_kind: Record<string, string>;
  charge_total: string;
  charges_by_category: {
    "service__category": string;
    total: string;
    count: number;
  }[];
  uninvoiced: string;
  invoiced: string;
  paid: string;
  outstanding: string;
  unbilled_accruals: number;
}

export interface DischargeBlockers {
  admission: string;
  can_discharge: boolean;
  blockers: { code: string; message: string }[];
}

export interface Census {
  date: string;
  in_house: number;
  awaiting_a_bed: number;
  total_beds: number;
  occupied: number;
  available: number;
  unusable: number;
  occupancy_percent: number;
  admitted_today: number;
  discharged_today: number;
  discharge_in_progress: number;
  overstaying: {
    reference: string;
    patient: string;
    expected: string | null;
    nights: number;
  }[];
  by_ward: WardOccupancy[];
}

export interface FluidBalance {
  admission: string;
  hours: number;
  rounds: number;
  intake_ml: number;
  output_ml: number;
  balance_ml: number;
  escalations: number;
}

// ---------------------------------------------------------------------------
// Platform console
// ---------------------------------------------------------------------------

export interface PlatformRevenue {
  mrr: string;
  arr: string;
  base_mrr: string;
  /** Revenue above the plan the customer originally bought. */
  expansion_mrr: string;
  expansion_share_percent: number;
  paying_customers: number;
  arpu: string;
  trial_customers: number;
  /** Deliberately not added to MRR — a trial is a hope, not revenue. */
  trial_potential_mrr: string;
  by_plan: Record<string, string>;
  by_billing_interval: Record<string, string>;
  currency: string;
}

export interface PlatformDashboard {
  generated_at: string;
  organizations: {
    total: number;
    active: number;
    trial: number;
    past_due: number;
    suspended: number;
    cancelled: number;
    pending_provisioning: number;
  };
  facilities: { total: number; by_type: Record<string, number> };
  revenue: PlatformRevenue;
  concentration: {
    organization: string;
    plan: string;
    mrr: string;
    share_percent: number;
    expansion_mrr: string;
  }[];
  entitled_but_unbilled: {
    organization: string;
    organization_name: string;
    plan: string;
    status: string;
    trial_ends_at: string | null;
    grace_ends_at: string | null;
    contracted_price: string;
  }[];
  change_requests: {
    open: number;
    awaiting_platform: number;
    awaiting_organization: number;
  };
  infrastructure: {
    tenant_databases: number;
    ready: number;
    failed: number;
  };
}

export interface PlatformOrganization {
  uuid: string;
  slug: string;
  legal_name: string;
  display_name: string;
  business_type: string;
  status: string;
  pan_number: string;
  vat_number: string;
  primary_email: string;
  primary_phone: string;
  province: string;
  district: string;
  municipality: string;
  trial_ends_at: string | null;
  activated_at: string | null;
  suspended_at: string | null;
  onboarding_completed_at: string | null;
  created_at: string;
  facility_count: number;
  member_count: number;
  database_status: string | null;
  database_alias: string | null;
}

export interface PlatformSubscriptionAddOn {
  uuid: string;
  addon_code: string;
  addon_name: string;
  target_key: string;
  increment: number;
  quantity: number;
  unit_price: string;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
  source_reference: string;
}

export interface PlatformSubscription {
  uuid: string;
  organization_slug: string;
  organization_name: string;
  plan_code: string;
  plan_name: string;
  status: string;
  is_entitled: boolean;
  billing_interval: string;
  currency: string;
  contracted_price: string;
  discount_percent: string;
  started_at: string | null;
  trial_ends_at: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  grace_ends_at: string | null;
  cancel_at_period_end: boolean;
  auto_renew: boolean;
  addons: PlatformSubscriptionAddOn[];
}

export interface PlatformPlan {
  uuid: string;
  code: string;
  name: string;
  tagline: string;
  description: string;
  base_price: string;
  currency: string;
  billing_interval: string;
  setup_fee: string;
  trial_days: number;
  grace_days: number;
  is_public: boolean;
  is_active: boolean;
  version: number;
  limits: {
    key: string;
    value: number | null;
    is_unlimited: boolean;
    enforcement: string;
    overage_unit_price: string | null;
    warn_at_percent: number;
  }[];
  modules: string[];
  features: string[];
}

// ---------------------------------------------------------------------------
// Emergency
// ---------------------------------------------------------------------------

export interface TriageAssessment {
  uuid: string;
  arrival: string;
  assessed_at: string;
  category: number;
  previous_category: number | null;
  /** A lower number is sicker, so a fall in category is a worsening. */
  is_deterioration: boolean;
  assessed_by_name: string;
  reason: string;
  pulse: number | null;
  systolic: number | null;
  diastolic: number | null;
  respiratory_rate: number | null;
  temperature_c: string | null;
  spo2: number | null;
  gcs: number | null;
  pain_score: number | null;
  notes: string;
}

export interface CriticalAlert {
  uuid: string;
  arrival: string;
  pathway: string;
  activated_at: string;
  activated_by_name: string;
  target_minutes: number;
  /** Arrival to somebody noticing. Often the whole delay. */
  recognition_minutes: number;
  intervention: string;
  intervention_at: string | null;
  door_to_intervention_minutes: number | null;
  met_target: boolean | null;
  stood_down_at: string | null;
  stood_down_reason: string;
  notes: string;
}

export interface ResuscitationEvent {
  uuid: string;
  arrival: string;
  occurred_at: string;
  event_type: string;
  detail: string;
  drug: string;
  dose: string;
  route: string;
  joules: number | null;
  rhythm: string;
  recorded_by_name: string;
}

export interface ResuscitationRecord {
  arrival: string;
  started_at?: string;
  duration_minutes: number;
  shocks?: number;
  drugs?: number;
  rosc?: boolean;
  events: {
    at: string;
    elapsed_minutes: number;
    event_type: string;
    detail: string;
    drug: string;
    dose: string;
    route: string;
    joules: number | null;
    rhythm: string;
    recorded_by: string;
  }[];
}

export interface ArrivalSummary {
  uuid: string;
  reference: string;
  patient: string;
  patient_name: string;
  patient_mrn: string;
  facility: string;
  arrived_at: string;
  arrival_mode: string;
  presenting_complaint: string;
  is_unidentified: boolean;
  /** Stays true forever — identification must not erase how they arrived. */
  arrived_unidentified: boolean;
  provisional_description: string;
  triage_category: number | null;
  triaged_at: string | null;
  first_seen_at: string | null;
  seen_by_name: string;
  waiting_minutes: number;
  target_minutes: number | null;
  minutes_to_breach: number | null;
  is_breaching: boolean;
  total_minutes: number;
  disposition: string;
  disposition_at: string | null;
  is_open: boolean;
  is_mlc: boolean;
}

export interface Arrival extends ArrivalSummary {
  encounter: string | null;
  department: string | null;
  ambulance_reference: string;
  brought_by: string;
  brought_by_phone: string;
  identified_at: string | null;
  minutes_unidentified: number | null;
  disposition_notes: string;
  admission_reference: string;
  referred_to: string;
  mlc_number: string;
  police_informed_at: string | null;
  notes: string;
  assessments: TriageAssessment[];
  alerts: CriticalAlert[];
}

export interface BoardRow {
  reference: string;
  patient: string;
  mrn: string;
  is_unidentified: boolean;
  minutes_unidentified: number | null;
  description: string;
  complaint: string;
  arrival_mode: string;
  arrived_at: string;
  triage_category: number | null;
  waiting_minutes: number;
  target_minutes: number | null;
  minutes_to_breach: number | null;
  is_breaching: boolean;
  seen: boolean;
  seen_by: string;
  is_mlc: boolean;
  alerts: {
    pathway: string;
    target_minutes: number;
    elapsed: number | null;
    met_target: boolean | null;
    stood_down: boolean;
  }[];
}

export interface DepartmentSummary {
  summary: {
    since: string;
    arrivals: number;
    in_department: number;
    by_disposition: Record<string, number>;
    by_triage_category: Record<string, number>;
    by_arrival_mode: Record<string, number>;
    median_wait_minutes: number;
    longest_wait_minutes: number;
    breaches: number;
    breach_percent: number;
    breach_by_category: Record<
      string,
      { seen: number; breached: number; breach_percent: number }
    >;
    left_without_being_seen: number;
    lwbs_percent: number;
    arrived_unidentified: number;
    still_unidentified: number;
    medico_legal: number;
  };
  pathways: {
    pathway: string;
    target_minutes: number;
    activations: number;
    stood_down: number;
    with_intervention: number;
    met_target: number;
    met_target_percent: number | null;
    average_recognition_minutes: number | null;
    average_door_to_intervention_minutes: number | null;
  }[];
}

// ---------------------------------------------------------------------------
// Operating theatre
// ---------------------------------------------------------------------------

export interface OperatingTheatre {
  uuid: string;
  code: string;
  name: string;
  theatre_type: string;
  facility: string;
  department: string | null;
  stock_location: string | null;
  floor: string;
  /** Per room — an orthopaedic theatre and an endoscopy room differ. */
  turnaround_minutes: number;
  session_starts_at: string | null;
  session_ends_at: string | null;
  has_laminar_flow: boolean;
  has_image_intensifier: boolean;
  has_microscope: boolean;
  is_active: boolean;
  notes: string;
}

export interface TheatreTeamMember {
  uuid: string;
  case: string;
  employee: string | null;
  role: string;
  name: string;
  registration_number: string;
  scrubbed_in_at: string | null;
  scrubbed_out_at: string | null;
  notes: string;
}

export interface SafetyChecklistPhase {
  phase: string;
  label: string;
  complete: boolean;
  skipped: boolean;
  skip_reason: string;
  completed_at: string | null;
  completed_by: string;
  unanswered: string[];
  concerns: string;
  negative_answers: string[];
}

export interface ChecklistState {
  state: {
    case: string;
    phases: SafetyChecklistPhase[];
    all_complete: boolean;
    /** The finding the whole model exists to surface. */
    incision_without_timeout: boolean;
  };
  items: Record<string, string[]>;
}

export interface CaseConsumption {
  uuid: string;
  case: string;
  kind: string;
  product: string | null;
  batch: string | null;
  description: string;
  batch_number: string;
  serial_number: string;
  manufacturer: string;
  expires_on: string | null;
  quantity: string;
  unit_cost: string;
  total_cost: string;
  charge_uuid: string | null;
  implanted_site: string;
  recorded_by_name: string;
  notes: string;
}

export interface SurgicalCaseSummary {
  uuid: string;
  reference: string;
  patient: string;
  patient_name: string;
  patient_mrn: string;
  facility: string;
  theatre: string | null;
  theatre_code: string;
  planned_procedure: string;
  performed_procedure: string;
  laterality: string;
  urgency: string;
  asa_grade: number | null;
  status: string;
  is_live: boolean;
  is_day_case: boolean;
  scheduled_start: string | null;
  scheduled_end: string | null;
  planned_minutes: number;
  wheels_in_at: string | null;
  incision_at: string | null;
  closure_at: string | null;
  wheels_out_at: string | null;
  theatre_minutes: number | null;
  operating_minutes: number | null;
  start_delay_minutes: number | null;
  overran_minutes: number | null;
  cancellation_reason: string;
  was_avoidable_cancellation: boolean;
}

export interface SurgicalCase extends SurgicalCaseSummary {
  encounter: string | null;
  procedure_code: string;
  indication: string;
  requested_at: string;
  requested_by_name: string;
  approved_at: string | null;
  approved_by_name: string;
  sent_for_at: string | null;
  anaesthesia_start_at: string | null;
  recovery_out_at: string | null;
  anaesthesia_minutes: number | null;
  cancelled_at: string | null;
  cancellation_notes: string;
  findings: string;
  complications: string;
  blood_loss_ml: number | null;
  specimen_sent: boolean;
  specimen_detail: string;
  post_op_instructions: string;
  notes: string;
  team: TheatreTeamMember[];
  consumption: CaseConsumption[];
}

export interface TheatreListRow {
  reference: string;
  patient: string;
  mrn: string;
  procedure: string;
  laterality: string;
  urgency: string;
  asa_grade: number | null;
  status: string;
  scheduled_start: string;
  scheduled_end: string;
  planned_minutes: number;
  gap_before_minutes: number | null;
  /** Idle time beyond the room's turnaround — theatre time nobody can use. */
  unused_gap_minutes: number | null;
  actual_start: string | null;
  start_delay_minutes: number | null;
  theatre_minutes: number | null;
  overran_minutes: number | null;
}

export interface TheatreUtilisation {
  theatre: string;
  from: string;
  to: string;
  cases: number;
  completed: number;
  cancelled: number;
  avoidable_cancellations: number;
  cancellation_reasons: Record<string, number>;
  session_minutes: number;
  booked_minutes: number;
  used_minutes: number;
  booked_percent: number | null;
  used_percent: number | null;
  average_start_delay_minutes: number | null;
  cases_starting_late: number;
  average_overrun_minutes: number | null;
}

export interface CaseCost {
  case: string;
  items: number;
  by_kind: Record<string, string>;
  total: string;
  implants: {
    description: string;
    serial_number: string;
    site: string;
    cost: string;
  }[];
  unbilled: number;
}

export interface ImplantRecord {
  patient: string;
  mrn: string;
  phone: string;
  case: string;
  operated_on: string | null;
  procedure: string;
  implant: string;
  serial_number: string;
  batch_number: string;
  site: string;
}

export interface SafetyAudit {
  since: string;
  operations: number;
  incisions_without_a_time_out: number;
  breach_percent: number;
  breaching_cases: string[];
  phases_skipped: number;
  fully_compliant_percent: number;
}
