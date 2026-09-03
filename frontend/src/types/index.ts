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

/* -------------------------------------------------------------------------- */
/* Intensive care                                                              */
/* -------------------------------------------------------------------------- */

/**
 * Decimals arrive as strings. The API renders every `Decimal` as a string so
 * that a rate of 0.050 mcg/kg/min does not become 0.05000000000000000277 on
 * the way through JSON. Format them; never do arithmetic on them here.
 */

export interface IcuObservation {
  uuid: string;
  recorded_at: string;
  source: "manual" | "device" | "calculated";
  device_identifier: string;
  validated_by_name: string;
  validated_at: string | null;
  is_validated: boolean;
  heart_rate: number | null;
  systolic: number | null;
  diastolic: number | null;
  mean_arterial_pressure: number | null;
  map_value: number | null;
  respiratory_rate: number | null;
  spo2: number | null;
  temperature: string | null;
  gcs_eye: number | null;
  gcs_verbal: number | null;
  gcs_motor: number | null;
  gcs_verbal_not_testable: boolean;
  gcs_total: number | null;
  pupil_left_mm: number | null;
  pupil_right_mm: number | null;
  pupils_reactive: boolean | null;
  rass: number | null;
  pain_score: number | null;
  blood_glucose: string | null;
  lactate: string | null;
  notes: string;
}

export interface FluidEntry {
  uuid: string;
  recorded_at: string;
  direction: "in" | "out";
  route: string;
  volume_ml: number;
  signed_ml: number;
  description: string;
  recorded_by_name: string;
  is_reversed: boolean;
}

export interface FluidBalance {
  hours: number;
  intake_ml: number;
  output_ml: number;
  balance_ml: number;
  urine_ml: number;
  /** Null when no weight is recorded — never a guess. */
  urine_ml_per_kg_per_hour: string | null;
  by_route: Record<string, number>;
  entries: number;
}

export interface CumulativeBalanceDay {
  icu_day: number;
  from: string;
  intake_ml: number;
  output_ml: number;
  balance_ml: number;
  cumulative_ml: number;
}

export interface RunningInfusion {
  uuid: string;
  drug_name: string;
  concentration: string;
  rate: string | null;
  rate_unit: string;
  status: "running" | "paused" | "stopped";
  is_titratable: boolean;
  is_vasopressor: boolean;
  target: string;
  maximum_rate: string | null;
  started_at: string;
  last_changed_at: string | null;
  changes: number;
  /** Null for a rate that integrates to a dose rather than a volume. */
  volume_ml: string | null;
}

export interface InfusionRate {
  rate: string;
  changed_at: string;
  reason: string;
  changed_by_name: string;
}

export interface Infusion {
  uuid: string;
  drug_name: string;
  concentration: string;
  rate_unit: string;
  route: string;
  is_titratable: boolean;
  target: string;
  maximum_rate: string | null;
  status: "running" | "paused" | "stopped";
  started_at: string;
  stopped_at: string | null;
  stop_reason: string;
  prescribed_by_name: string;
  notes: string;
  rates: InfusionRate[];
}

export interface VentilationRecord {
  uuid: string;
  recorded_at: string;
  mode: string;
  is_invasive: boolean;
  set_rate: number | null;
  set_tidal_volume: number | null;
  peep: string | null;
  pressure_support: string | null;
  fio2: number | null;
  measured_rate: number | null;
  expired_tidal_volume: number | null;
  peak_pressure: string | null;
  plateau_pressure: string | null;
  minute_volume: string | null;
  etco2: number | null;
  pao2: string | null;
  paco2: string | null;
  ph: string | null;
  pf_ratio: string | null;
  driving_pressure: string | null;
  source: string;
  notes: string;
}

export interface VentilatorSummary {
  invasive_hours: string;
  non_invasive_hours: string;
  invasive_days?: string;
  records: number;
  current_mode: string | null;
  current_fio2?: number | null;
  current_peep?: string | null;
  pf_ratio?: string | null;
  driving_pressure?: string | null;
}

export interface InvasiveDevice {
  uuid: string;
  device_type: string;
  site: string;
  size: string;
  inserted_at: string;
  inserted_by_name: string;
  inserted_in_emergency: boolean;
  removed_at: string | null;
  removal_reason: string;
  was_infected: boolean;
  next_change_due: string | null;
  days_in_situ: string;
  notes: string;
}

export interface OverdueDevice {
  uuid: string;
  device: string;
  site: string;
  due: string | null;
  days_in_situ: string;
  reason: string;
}

export interface IcuAlert {
  uuid: string;
  raised_at: string;
  severity: "warning" | "critical";
  parameter: string;
  value: string;
  threshold: string;
  message: string;
  from_unvalidated_device: boolean;
  acknowledged_at: string | null;
  acknowledged_by_name: string;
  action_taken: string;
  is_acknowledged: boolean;
  minutes_to_acknowledge: number | null;
}

export interface AlertSummary {
  hours: number;
  total: number;
  critical: number;
  unacknowledged: number;
  from_unvalidated_devices: number;
  median_minutes_to_acknowledge: number | null;
  by_parameter: Record<string, number>;
}

export interface IcuRound {
  uuid: string;
  round_at: string;
  icu_day: number;
  consultant_name: string;
  assessment: string;
  plan: string;
  fasthug: Record<string, boolean>;
  fasthug_reasons: Record<string, string>;
  /** Items nobody answered either way — not the same as answered "no". */
  missed_items: string[];
  negative_items: string[];
  is_ready_for_sedation_hold: boolean | null;
  is_ready_for_weaning_trial: boolean | null;
  is_ready_for_step_down: boolean;
  step_down_blockers: string;
  family_updated: boolean;
  family_update_notes: string;
}

export interface SofaDay {
  icu_day: number;
  date: string;
  total: number;
  respiratory: number;
  coagulation: number;
  liver: number;
  cardiovascular: number;
  neurological: number;
  renal: number;
  /** False when a system had no data. A partial score is not comparable. */
  complete: boolean;
  missing: string[];
}

export interface StepDownBlocker {
  kind: "clinical" | "record";
  detail: string;
}

export interface IcuStaySummary {
  uuid: string;
  patient_name: string;
  patient_mrn: string;
  admission: string;
  ward_name: string;
  bed_code: string;
  admitted_at: string;
  discharged_at: string | null;
  hours: string;
  icu_day: number;
  route: string;
  reason: string;
  primary_diagnosis: string;
  consultant_name: string;
  outcome: string;
  apache_ii: number | null;
  is_for_resuscitation: boolean;
  weight_kg: string | null;
}

export interface IcuStay extends IcuStaySummary {
  height_cm: number | null;
  ceiling_of_care: string;
  ceiling_set_by: string;
  ceiling_set_at: string | null;
  outcome_notes: string;
  notes: string;
  observations: IcuObservation[];
  infusions: RunningInfusion[];
  ventilation: VentilationRecord[];
  devices: InvasiveDevice[];
  alerts: IcuAlert[];
  rounds: IcuRound[];
  balance: FluidBalance;
  ventilator: VentilatorSummary;
  blockers: StepDownBlocker[];
  sofa: SofaDay[];
}

export interface UnitBoardRow {
  stay: string;
  bed: string;
  patient: string;
  mrn: string;
  admission: string;
  icu_day: number;
  hours: string;
  diagnosis: string;
  consultant: string;
  sofa: number | null;
  sofa_complete: boolean | null;
  ventilated: boolean;
  mode: string | null;
  fio2: number | null;
  vasopressors: string[];
  for_resuscitation: boolean;
  ceiling_of_care: string;
  last_observation_at: string | null;
  unacknowledged_alerts: number;
  critical_alerts: number;
  balance_24h_ml: number;
}

export interface UnitStatistics {
  since: string;
  admissions: number;
  current: number;
  completed: number;
  died: number;
  mortality_percent: number | null;
  transferred_out: number;
  left_against_advice: number;
  outcome_unknown: number;
  median_hours: number | null;
  ventilated: number;
  invasive_ventilator_days: string;
  readmissions_within_48h: number;
  readmission_percent: number | null;
  by_route: Record<string, number>;
}

export interface DeviceSurveillance {
  from: string;
  to: string;
  by_type: Record<
    string,
    {
      device_days: string;
      devices: number;
      infections: number;
      per_thousand_device_days: string | null;
    }
  >;
}

export interface FasthugCompliance {
  since: string;
  rounds: number;
  items: {
    item: string;
    answered: number;
    not_answered: number;
    answered_percent: number | null;
    declined: number;
  }[];
}

export interface IcuSummary {
  unit: UnitStatistics;
  devices: DeviceSurveillance;
  fasthug: FasthugCompliance;
}

export interface TrendPoint {
  at: string;
  value: number | string;
  source: string;
  validated: boolean;
}

/* -------------------------------------------------------------------------- */
/* Finance                                                                     */
/* -------------------------------------------------------------------------- */

/** Money arrives as a string. Format it; never do arithmetic on it here. */

export interface LedgerAccount {
  uuid: string;
  code: string;
  name: string;
  name_nepali: string;
  account_type: "asset" | "liability" | "equity" | "income" | "expense";
  parent: string | null;
  is_postable: boolean;
  control_key: string;
  is_control: boolean;
  facility: string | null;
  is_active: boolean;
  description: string;
  normal_balance: "debit" | "credit";
}

export interface AccountingPeriod {
  uuid: string;
  fiscal_year: string;
  period_number: number;
  name: string;
  starts_on: string;
  ends_on: string;
  status: "open" | "soft_closed" | "locked";
  closed_at: string | null;
  closed_by_name: string;
  notes: string;
  accepts_postings: boolean;
  entries: number;
}

export interface JournalLine {
  uuid: string;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  narration: string;
  party_type: string;
  party_reference: string;
  party_name: string;
  cost_centre: string;
}

export interface JournalEntry {
  uuid: string;
  reference: string;
  document_date: string;
  posting_date: string;
  period_name: string;
  facility_name: string;
  narration: string;
  source: string;
  source_reference: string;
  status: "draft" | "posted" | "reversed";
  posted_at: string | null;
  posted_by_name: string;
  total_debit: string;
  total_credit: string;
  reversal_reason: string;
  reversed_by_reference: string;
  /** The document's own date and the day it hit the books are different. */
  posted_late: boolean;
  lines: JournalLine[];
}

export interface TrialBalanceRow {
  code: string;
  name: string;
  type: string;
  debit: string;
  credit: string;
  balance: string;
}

export interface TrialBalance {
  as_at: string;
  rows: TrialBalanceRow[];
  total_debit: string;
  total_credit: string;
  difference: string;
  balances: boolean;
}

export interface ProfitAndLoss {
  from: string;
  to: string;
  income: { code: string; name: string; amount: string }[];
  expenses: { code: string; name: string; amount: string }[];
  total_income: string;
  total_expense: string;
  surplus: string;
}

export interface BalanceSheet {
  as_at: string;
  assets: { code: string; name: string; amount: string }[];
  liabilities: { code: string; name: string; amount: string }[];
  equity: { code: string; name: string; amount: string }[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  surplus_for_the_period: string;
  accumulated_surplus: string;
  difference: string;
  balances: boolean;
}

export interface ReceivablesAgeing {
  as_at: string;
  buckets: Record<string, string>;
  total: string;
  invoices: {
    invoice: string;
    patient: string;
    issued: string;
    days: number;
    total: string;
    paid: string;
    outstanding: string;
  }[];
  over_90: string;
}

export interface PayablesAgeing {
  as_at: string;
  buckets: Record<string, string>;
  total: string;
  invoices: {
    invoice: string;
    supplier: string;
    supplier_number: string;
    due: string;
    days_overdue: number;
    outstanding: string;
    disputed: boolean;
  }[];
  overdue: string;
}

export interface ReceivablesAgreement {
  as_at: string;
  /** From the invoices. */
  subledger: string;
  /** From the ledger's control account. Independently computed. */
  ledger: string;
  difference: string;
  agrees: boolean;
  invoices_not_posted: string[];
  invoices_not_posted_count: number;
}

export interface VatReturn {
  from: string;
  to: string;
  output_tax: string;
  input_tax: string;
  payable: string;
}

export interface AccountLedger {
  account: string;
  opening: string;
  closing: string;
  rows: {
    date: string;
    reference: string;
    narration: string;
    source: string;
    party: string;
    debit: string;
    credit: string;
    balance: string;
  }[];
}

export interface SupplierInvoice {
  uuid: string;
  reference: string;
  supplier_invoice_number: string;
  supplier_uuid: string;
  supplier_name: string;
  facility: string;
  invoice_date: string;
  due_date: string;
  received_on: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  paid_amount: string;
  goods_receipts: string[];
  variance: string;
  variance_notes: string;
  status: string;
  approved_by_name: string;
  approved_at: string | null;
  notes: string;
  outstanding: string;
  is_overdue: boolean;
}

export interface LedgerExpense {
  uuid: string;
  reference: string;
  facility: string;
  spent_on: string;
  account: string;
  account_name: string;
  cost_centre: string;
  description: string;
  amount: string;
  tax_amount: string;
  claimed_by_name: string;
  payment_method: string;
  receipt_number: string;
  has_receipt: boolean;
  status: string;
  approved_by_name: string;
  approved_at: string | null;
  rejection_reason: string;
}

export interface LedgerBankAccount {
  uuid: string;
  name: string;
  bank_name: string;
  branch: string;
  account_number: string;
  account: string;
  facility: string | null;
  is_active: boolean;
  notes: string;
}

export interface BankReconciliation {
  bank_account: string;
  from: string;
  to: string;
  statement_lines: number;
  statement_total: string;
  ledger_total: string;
  difference: string;
  unmatched_on_the_statement: {
    uuid: string;
    date: string;
    description: string;
    reference: string;
    amount: string;
  }[];
  unmatched_in_the_ledger: {
    uuid: string;
    date: string;
    reference: string;
    narration: string;
    amount: string;
  }[];
  matched: number;
}

/* -------------------------------------------------------------------------- */
/* Insurance and claims                                                        */
/* -------------------------------------------------------------------------- */

/** Money arrives as a string. Format it; never do arithmetic on it here. */

export interface Payer {
  uuid: string;
  code: string;
  name: string;
  name_nepali: string;
  kind: "insurer" | "tpa" | "government" | "corporate" | "embassy";
  administers_for: string | null;
  registration_number: string;
  pan_number: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string;
  address: string;
  price_list_code: string;
  /** Days from the date of service to submit. Missing it voids the claim. */
  submission_window_days: number;
  settlement_days: number;
  requires_preauthorisation: boolean;
  preauthorisation_threshold: string;
  is_active: boolean;
  notes: string;
  is_scheme: boolean;
}

export interface Policy {
  uuid: string;
  policy_number: string;
  payer: string;
  payer_name: string;
  patient: string;
  patient_name: string;
  principal_name: string;
  relationship: string;
  valid_from: string;
  valid_to: string;
  status: "active" | "lapsed" | "suspended" | "cancelled";
  /** Null means uncapped, which is not the same as zero. */
  sum_insured: string | null;
  utilised: string;
  remaining: string | null;
  deductible: string;
  co_payment_percent: string;
  sub_limits: Record<string, number>;
  exclusions: string[];
  waiting_period_until: string | null;
  card_number: string;
  notes: string;
}

export interface EligibilityRow {
  policy: string;
  policy_number: string;
  payer: string;
  payer_kind: string;
  valid_from: string;
  valid_to: string;
  eligible: boolean;
  /** Sentences, so reception can tell the patient which card to hand over. */
  problems: string[];
  sum_insured: string | null;
  remaining: string | null;
  deductible: string;
  co_payment_percent: string;
  sub_limits: Record<string, number>;
  exclusions: string[];
}

export interface Eligibility {
  patient: string;
  mrn: string;
  as_at: string;
  policies: EligibilityRow[];
  any_eligible: boolean;
}

export interface CoverEstimate {
  billed: string;
  payer_pays: string;
  patient_pays: string;
  reductions: { reason: string; amount: string; detail: string }[];
  eligible: boolean;
}

export interface PreAuthorisation {
  uuid: string;
  reference: string;
  policy_number: string;
  payer_name: string;
  patient_name: string;
  requested_at: string;
  requested_by_name: string;
  planned_treatment: string;
  diagnosis: string;
  diagnosis_code: string;
  planned_admission_on: string | null;
  estimated_days: number | null;
  estimated_amount: string;
  status:
    | "requested"
    | "approved"
    | "partially_approved"
    | "rejected"
    | "expired"
    | "used"
    | "cancelled";
  payer_reference: string;
  responded_at: string | null;
  approved_amount: string;
  valid_until: string | null;
  conditions: string;
  rejection_reason: string;
  notes: string;
  is_usable: boolean;
  days_until_expiry: number | null;
  warnings: string[];
}

export interface ExpiringPreAuth {
  reference: string;
  patient: string;
  mrn: string;
  payer: string;
  treatment: string;
  approved: string;
  valid_until: string;
  days_left: number | null;
  expired: boolean;
}

export interface ClaimLine {
  uuid: string;
  description: string;
  service_code: string;
  category: string;
  quantity: string;
  unit_price: string;
  claimed_amount: string;
  approved_amount: string;
  deducted_amount: string;
  /** From a fixed list — the only useful thing about a deduction. */
  deduction_reason: string;
  deduction_notes: string;
}

export interface ClaimEvent {
  happened_at: string;
  event: string;
  detail: string;
  amount: string | null;
  actor_name: string;
}

export interface SubmissionDeadline {
  window_days: number;
  deadline: string;
  days_left: number;
  expired: boolean;
  urgent: boolean;
}

export type ClaimStatus =
  | "draft"
  | "submitted"
  | "queried"
  | "approved"
  | "partially_approved"
  | "rejected"
  | "appealed"
  | "settled"
  | "written_off";

export interface ClaimSummary {
  uuid: string;
  reference: string;
  payer_name: string;
  patient_name: string;
  patient_mrn: string;
  invoice_number: string;
  service_date: string;
  discharge_date: string | null;
  diagnosis: string;
  status: ClaimStatus;
  submitted_at: string | null;
  submission_count: number;
  payer_reference: string;
  /** Four separate amounts, not one amount with a status. */
  claimed_amount: string;
  approved_amount: string;
  deducted_amount: string;
  settled_amount: string;
  patient_liability: string;
  outstanding: string;
  shortfall: string;
  days_since_submission: number | null;
  rejection_reason: string;
  query_text: string;
  deadline: SubmissionDeadline;
}

export interface Claim extends ClaimSummary {
  policy_number: string;
  preauth_reference: string;
  treatment_summary: string;
  diagnosis_code: string;
  responded_at: string | null;
  settled_at: string | null;
  query_raised_at: string | null;
  query_answered_at: string | null;
  notes: string;
  lines: ClaimLine[];
  events: ClaimEvent[];
}

export interface ClaimsAgeing {
  buckets: Record<string, string>;
  total: string;
  /** Past the payer's own promised days, not a generic thirty. */
  overdue: string;
  claims: {
    claim: string;
    payer: string;
    patient: string;
    status: string;
    submitted: string;
    days: number;
    promised_days: number;
    past_promise: boolean;
    claimed: string;
    approved: string;
    outstanding: string;
  }[];
}

export interface DeductionAnalysis {
  since: string;
  total_deducted: string;
  by_reason: {
    reason: string;
    amount: string;
    lines: number;
    share_percent: string | null;
  }[];
  by_category: Record<string, string>;
}

export interface PayerPerformance {
  payer: string;
  kind: string;
  claims: number;
  claimed: string;
  approved: string;
  settled: string;
  outstanding: string;
  approval_percent: string | null;
  rejected: number;
  rejection_percent: number;
  resubmitted: number;
  written_off: string;
  median_days_to_respond: number | null;
  promised_days: number;
}

export interface DeductionReason {
  key: string;
  label: string;
}

export interface SchemePackage {
  uuid: string;
  payer: string;
  code: string;
  name: string;
  name_nepali: string;
  category: string;
  package_amount: string;
  maximum_per_year: number | null;
  includes: string;
  excludes: string;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
}

/* -------------------------------------------------------------------------- */
/* Blood bank                                                                  */
/* -------------------------------------------------------------------------- */

export type BloodGroup =
  | "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-";

export type BloodComponent =
  | "whole_blood" | "red_cells" | "plasma" | "platelets" | "cryo";

export type UnitStatus =
  | "quarantined" | "available" | "reserved" | "crossmatched"
  | "issued" | "transfused" | "returned" | "expired" | "discarded";

export interface Donor {
  uuid: string;
  donor_number: string;
  full_name: string;
  full_name_nepali: string;
  date_of_birth: string | null;
  gender: string;
  blood_group: BloodGroup | "";
  phone: string;
  alternate_phone: string;
  email: string;
  address: string;
  citizenship_number: string;
  donor_type: string;
  status: "active" | "temporary" | "permanent" | "deceased";
  deferral_reason: string;
  deferred_until: string | null;
  deferred_by_name: string;
  donation_count: number;
  last_donated_on: string | null;
  is_contactable: boolean;
  notes: string;
  eligible_now: boolean;
  /** Sentences, so the desk can tell the donor something. */
  problems: string[];
}

export interface DonorCallRow {
  donor_number: string;
  name: string;
  phone: string;
  blood_group: string;
  donations: number;
  last_donated: string | null;
  eligible_now: boolean;
  problems: string[];
}

export interface Grouping {
  uuid: string;
  blood_group: BloodGroup;
  forward_result: string;
  reverse_result: string;
  is_weak_d: boolean;
  antibody_screen: string;
  performed_at: string;
  performed_by_name: string;
  method: string;
}

export interface Screening {
  uuid: string;
  results: Record<string, string>;
  values: Record<string, string>;
  performed_at: string;
  performed_by_name: string;
  verified_by_name: string;
  verified_at: string | null;
  kit_lot_number: string;
  notes: string;
  /** Missing is not negative — these are the infections with no result. */
  untested: string[];
  reactive: string[];
  is_complete: boolean;
  is_safe: boolean;
}

export interface Donation {
  uuid: string;
  donation_number: string;
  donor_name: string;
  donor_number: string;
  collected_at: string;
  collected_by_name: string;
  collection_site: string;
  is_mobile_drive: boolean;
  volume_ml: number;
  bag_type: string;
  haemoglobin: string | null;
  donor_weight_kg: string | null;
  had_adverse_event: boolean;
  adverse_event_detail: string;
  status: "collected" | "processed" | "discarded";
  discard_reason: string;
  notes: string;
  groupings: Grouping[];
  screening: Screening | null;
  /** Empty until two people have grouped it and agreed. */
  group: string;
  blockers: string[];
  units: {
    uuid: string;
    unit_number: string;
    component: BloodComponent;
    status: UnitStatus;
    expires_on: string;
  }[];
}

export interface BloodUnit {
  uuid: string;
  unit_number: string;
  donation_number: string;
  component: BloodComponent;
  blood_group: BloodGroup;
  volume_ml: number;
  prepared_at: string;
  expires_on: string;
  days_to_expiry: number;
  is_expired: boolean;
  storage_location: string;
  storage_min_c: string;
  storage_max_c: string;
  status: UnitStatus;
  reserved_for: string | null;
  reserved_for_name: string;
  reserved_until: string | null;
  reserved_reason: string;
  issued_at: string | null;
  issued_to_name: string;
  left_storage_at: string | null;
  returned_at: string | null;
  discard_reason: string;
  notes: string;
}

export interface CrossMatch {
  uuid: string;
  unit_number: string;
  unit_group: BloodGroup;
  patient_name: string;
  performed_at: string;
  performed_by_name: string;
  valid_until: string;
  result: "compatible" | "incompatible" | "caution";
  method: string;
  patient_group: string;
  antibody_screen: string;
  incompatibility_detail: string;
  notes: string;
  is_valid: boolean;
}

export interface BloodRequest {
  uuid: string;
  reference: string;
  patient_name: string;
  patient_mrn: string;
  requested_at: string;
  requested_by_name: string;
  required_by: string | null;
  urgency: "routine" | "urgent" | "emergency";
  component: BloodComponent;
  units_requested: number;
  units_given: number;
  indication: string;
  stated_group: string;
  haemoglobin: string | null;
  status: "pending" | "part_filled" | "filled" | "cancelled";
  cancelled_reason: string;
  notes: string;
}

export interface TransfusionReaction {
  uuid: string;
  reported_at: string;
  reported_by_name: string;
  minutes_into_transfusion: number | null;
  reaction_type: string;
  severity: "mild" | "moderate" | "severe" | "life_threatening" | "fatal";
  symptoms: string;
  transfusion_stopped: boolean;
  volume_transfused_ml: number | null;
  treatment_given: string;
  unit_returned_to_bank: boolean;
  repeat_grouping_done: boolean;
  repeat_crossmatch_done: boolean;
  culture_sent: boolean;
  investigation_findings: string;
  is_clerical_error: boolean;
  reported_to_authority: boolean;
  reported_to_authority_at: string | null;
  notes: string;
}

export interface Transfusion {
  uuid: string;
  unit_number: string;
  unit_group: BloodGroup;
  component: BloodComponent;
  patient_name: string;
  started_at: string;
  finished_at: string | null;
  volume_given_ml: number | null;
  outcome: "completed" | "stopped" | "not_started";
  checked_by_first: string;
  checked_by_second: string;
  identity_confirmed: boolean;
  observations: Record<string, string>[];
  notes: string;
  reactions: TransfusionReaction[];
}

export interface BloodStock {
  facility: string;
  total: number;
  available: number;
  held: number;
  expiring_within_7_days: number;
  quarantined: number;
  /** component → group → counts. The shape, not the total. */
  by_component: Record<
    string,
    Record<string, { available: number; held: number; expiring: number }>
  >;
}

export interface BloodWastage {
  since: string;
  discarded: number;
  issued: number;
  wastage_percent: number | null;
  by_reason: Record<string, number>;
}

export interface Haemovigilance {
  since: string;
  transfusions: number;
  reactions: number;
  reaction_rate_percent: number | null;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  clerical_errors: number;
  not_reported_to_authority: number;
}

export interface LookBackRow {
  donation: string;
  collected_on: string;
  unit: string;
  component: string;
  status: string;
  patient: string | null;
  mrn: string | null;
  phone: string | null;
  transfused_on: string | null;
}

export interface LookBack {
  donor: string;
  donor_number: string;
  donations: number;
  units: number;
  recipients: number;
  rows: LookBackRow[];
}

export interface ScreeningPanelItem {
  key: string;
  label: string;
  permanent_deferral: boolean;
}

/* -------------------------------------------------------------------------- */
/* Referrals                                                                   */
/* -------------------------------------------------------------------------- */

export type ReferralStatus =
  | "draft" | "sent" | "acknowledged" | "accepted" | "declined" | "booked"
  | "seen" | "responded" | "completed" | "dna" | "cancelled" | "lapsed";

export type ReferralUrgency = "routine" | "soon" | "urgent" | "emergency";

export type ReferralDirection = "internal" | "outbound" | "inbound";

export interface ExternalProvider {
  uuid: string;
  code: string;
  name: string;
  name_nepali: string;
  provider_type: string;
  specialties: string[];
  contact_name: string;
  phone: string;
  email: string;
  address: string;
  district: string;
  /** A referral emailed to somebody with no email never left the building. */
  accepts_email: boolean;
  accepts_paper: boolean;
  notes: string;
  is_active: boolean;
}

export interface ReferralResponse {
  uuid: string;
  responded_at: string;
  responder_name: string;
  /** The answer to the referrer's question, kept apart from the findings. */
  answer: string;
  findings: string;
  diagnosis: string;
  treatment: string;
  advice_to_referrer: string;
  care_handed_back: boolean;
  follow_up_here: boolean;
  follow_up_on: string | null;
  is_interim: boolean;
  attachments: unknown[];
}

export interface ReferralEvent {
  happened_at: string;
  event: string;
  detail: string;
  actor_name: string;
}

export interface ReferralSummary {
  uuid: string;
  reference: string;
  patient_name: string;
  patient_mrn: string;
  direction: ReferralDirection;
  specialty: string;
  urgency: ReferralUrgency;
  status: ReferralStatus;
  reason: string;
  /** The specific thing the referrer wants to know. */
  question: string;
  referrer_name: string;
  to_provider_name: string;
  to_department_name: string;
  to_clinician_name: string;
  created_on: string;
  sent_at: string | null;
  acknowledged_at: string | null;
  accepted_at: string | null;
  declined_at: string | null;
  decline_reason: string;
  decline_notes: string;
  booked_for: string | null;
  seen_at: string | null;
  responded_at: string | null;
  closed_at: string | null;
  target_date: string | null;
  days_waiting: number | null;
  days_to_target: number | null;
  /** Stays true after a late sighting — a breach nobody counts is no breach. */
  is_breaching: boolean;
  /** Seen, and the referrer has still been told nothing. */
  awaiting_answer: boolean;
  is_open: boolean;
}

export interface Referral extends ReferralSummary {
  patient: string;
  clinical_summary: string;
  provisional_diagnosis: string;
  diagnosis_code: string;
  referrer_registration: string;
  referrer_contact: string;
  /** Frozen at the moment of sending. */
  letter: Record<string, unknown>;
  letter_generated_at: string | null;
  sent_by_method: string;
  sent_notes: string;
  cancelled_reason: string;
  notes: string;
  responses: ReferralResponse[];
  events: ReferralEvent[];
}

export interface ReferralWorklistRow {
  reference: string;
  patient: string;
  mrn: string;
  specialty: string;
  urgency: ReferralUrgency;
  status: ReferralStatus;
  direction: ReferralDirection;
  referrer: string;
  sent_at: string | null;
  days_waiting: number | null;
  target_date: string | null;
  days_to_target: number | null;
  breaching: boolean;
  awaiting_answer: boolean;
  question: string;
}

export interface UnansweredReferral {
  reference: string;
  patient: string;
  mrn: string;
  specialty: string;
  referrer: string;
  seen_at: string;
  days_since_seen: number;
  question: string;
}

export interface ReferralSummaryReport {
  since: string;
  total: number;
  sent: number;
  seen: number;
  breached: number;
  breach_percent: number | null;
  declined: number;
  decline_reasons: Record<string, number>;
  lapsed: number;
  did_not_attend: number;
  answered: number;
  answered_percent: number | null;
  seen_but_unanswered: number;
  median_days_to_be_seen: number | null;
  median_days_to_answer: number | null;
  by_specialty: Record<
    string,
    { sent: number; seen: number; breached: number; answered: number }
  >;
}

export interface ReferralHistoryRow {
  reference: string;
  specialty: string;
  created_on: string;
  status: ReferralStatus;
  urgency: ReferralUrgency;
  reason: string;
  question: string;
  seen_at: string | null;
  answers: {
    responded_at: string;
    responder: string;
    answer: string;
    diagnosis: string;
    handed_back: boolean;
    interim: boolean;
  }[];
}

export interface DeclineReason {
  key: string;
  label: string;
}

export interface ReferralTarget {
  urgency: ReferralUrgency;
  days: number;
}
