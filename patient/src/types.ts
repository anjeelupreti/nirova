/** What `/api/me/` returns. Money and decimals arrive as strings. */

export interface AccessibleRecord {
  uuid: string;
  name: string;
  relationship: string;
  via_proxy: boolean;
}

export interface HomeScreen {
  patient: string;
  mrn: string;
  via_proxy: boolean;
  relationship: string;
  next_appointment: Appointment | null;
  upcoming_appointments: number;
  results_ready: number;
  /** Ready, but a clinician is ringing first. Counted separately on purpose. */
  results_being_discussed: number;
  outstanding: string;
  unread_messages: number;
  can_see_results: boolean;
  can_see_invoices: boolean;
  can_book_appointments: boolean;
  records: AccessibleRecord[];
}

export interface ResultValue {
  analyte: string;
  value: string;
  unit: string;
  reference_range: string;
  abnormal: boolean;
}

export interface ResultRow {
  reference: string;
  test: string;
  ordered_at: string;
  status: string;
  /** False when it is ready but held; `message` then says why. */
  visible: boolean;
  message: string;
  available_at: string | null;
  results: ResultValue[];
}

export interface Appointment {
  reference: string;
  when: string;
  minutes: number;
  status: string;
  provider: string;
  facility: string;
  reason: string;
  upcoming: boolean;
}

export interface InvoiceRow {
  number: string;
  issued_on: string | null;
  total: string;
  paid: string;
  balance: string;
  status: string;
  is_credit_note: boolean;
}

export interface Invoices {
  outstanding: string;
  invoices: InvoiceRow[];
}

export interface PrescriptionLine {
  drug: string;
  brand: string;
  dose: string;
  frequency: string;
  duration_days: number | null;
  instructions: string;
}

export interface Prescription {
  reference: string;
  prescribed_on: string;
  prescriber: string;
  status: string;
  lines: PrescriptionLine[];
}

export interface ReferralRow {
  reference: string;
  specialty: string;
  status: string;
  created_on: string;
  seen_at: string | null;
  answered: boolean;
}

export interface MessageRow {
  uuid: string;
  direction: "from_patient" | "to_patient";
  subject: string;
  body: string;
  sent_at: string;
  sender: string;
  read: boolean;
  answered: boolean;
}

export interface SessionRow {
  uuid: string;
  issued_at: string;
  expires_at: string;
  last_seen_at: string | null;
  device_label: string;
  ip_address: string | null;
  revoked_at: string | null;
  is_live: boolean;
}

export interface SignInResult {
  token: string;
  expires_at: string;
  account: {
    uuid: string;
    patient_name: string;
    patient_mrn: string;
    login_identifier: string;
  };
}

export interface PatientCorrectionRow {
  uuid: string;
  field_name: string;
  field_label: string;
  old_value: string;
  proposed_value: string;
  reason: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  requested_at: string;
  decided_at?: string | null;
  decided_by_name?: string;
  decision_notes?: string;
}

export interface PatientProfile {
  uuid: string;
  mrn: string;
  full_name: string;
  phone: string;
  alternate_phone: string;
  email: string;
  gender: string;
  date_of_birth: string | null;
  stated_age_years: number | null;
  temporary_address: string;
  tole: string;
  municipality: string;
  district: string;
  province: string;
  guardian_name: string;
  guardian_phone: string;
  guardian_relationship: string;
  pending_corrections: PatientCorrectionRow[];
  recent_corrections: PatientCorrectionRow[];
}

export interface DocumentResponse {
  html: string;
  reference: string;
  title: string;
}

