/**
 * Self-Service Workspace for hospital employees and managers.
 *
 * Phase 5 §95:
 * - My Profile: credentials tracking, contact info, bank details, change requests
 * - My Time: punch in/out, monthly attendance ledger, clock regularisation
 * - Shift Swaps: propose a swap, colleague accept/decline, manager sign-off
 * - My Leave: ledger-derived balances, holiday-aware applications, cancel/amend
 * - My Pay: approved payslips, line items, tax workings, printable export
 * - Manager Hub: unified approval queue for leave, regularisations, swaps, and profile updates
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRightLeft,
  CheckCircle2,
  Clock,
  FileCheck,
  Loader2,
  LogIn,
  LogOut,
  Plane,
  Printer,
  ShieldAlert,
  UserCheck,
  UserCog,
  Users,
  Wallet,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  AttendanceRecord,
  ESSMeSummary,
  LeaveRequest,
  LeaveType,
  ManagerQueueItem,
  ManagerQueueResponse,
  Paginated,
  PayslipSummary,
  ProfileCorrectionRow,
  ShiftSwapRow,
} from "@/types";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui/primitives";

type Tab = "profile" | "time" | "swaps" | "leave" | "pay" | "manager";

export default function SelfServicePage() {
  const [activeTab, setActiveTab] = useState<Tab>("profile");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<ESSMeSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Sub-data states
  const [attendanceRecords, setAttendanceRecords] = useState<AttendanceRecord[]>([]);
  const [leaveRequests, setLeaveRequests] = useState<LeaveRequest[]>([]);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [payslips, setPayslips] = useState<PayslipSummary[]>([]);
  const [corrections, setCorrections] = useState<ProfileCorrectionRow[]>([]);
  const [swaps, setSwaps] = useState<ShiftSwapRow[]>([]);
  const [managerQueue, setManagerQueue] = useState<ManagerQueueResponse | null>(null);

  // Dialog / action states
  const [clocking, setClocking] = useState(false);
  const [correctionModal, setCorrectionModal] = useState(false);
  const [swapModal, setSwapModal] = useState(false);
  const [leaveModal, setLeaveModal] = useState(false);
  const [regModal, setRegModal] = useState<string | null>(null); // attendance uuid
  const [payslipModal, setPayslipModal] = useState<any | null>(null);

  // Correction form
  const [corrPhone, setCorrPhone] = useState("");
  const [corrEmail, setCorrEmail] = useState("");
  const [corrAddress, setCorrAddress] = useState("");
  const [corrBankName, setCorrBankName] = useState("");
  const [corrAccountNo, setCorrAccountNo] = useState("");
  const [corrReason, setCorrReason] = useState("");

  // Leave form
  const [leaveType, setLeaveType] = useState("");
  const [leaveStarts, setLeaveStarts] = useState("");
  const [leaveEnds, setLeaveEnds] = useState("");
  const [leaveReason, setLeaveReason] = useState("");

  // Swap form
  const [swapEntry, setSwapEntry] = useState("");
  const [swapTargetEmp, setSwapTargetEmp] = useState("");
  const [swapReason, setSwapReason] = useState("");
  const [colleagues, setColleagues] = useState<{ uuid: string; full_name: string; code: string }[]>([]);

  // Regularisation form
  const [regInTime, setRegInTime] = useState("");
  const [regOutTime, setRegOutTime] = useState("");
  const [regReason, setRegReason] = useState("");

  // Load primary summary
  const loadSummary = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.get<ESSMeSummary>("/api/hr/me/summary/");
      setSummary(res);

      if (res?.employee) {
        setCorrPhone(res.employee.phone || "");
        setCorrEmail(res.employee.personal_email || "");
        setCorrAddress(res.employee.address || "");
        setCorrBankName(res.employee.bank_name || "");
        setCorrAccountNo(res.employee.bank_account_number || "");
      }
    } catch (err: any) {
      if (err?.status === 204) {
        setError("Your account is not linked to an employee record in this facility.");
      } else {
        setError(err instanceof ApiError ? err.message : "Failed to load summary.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Load secondary tab data
  const loadTabData = useCallback(async (tab: Tab) => {
    try {
      if (tab === "time") {
        const attRes = await api.get<Paginated<AttendanceRecord>>("/api/hr/attendance/?mine=true");
        setAttendanceRecords(attRes.results || []);
      } else if (tab === "leave") {
        const [reqRes, typeRes] = await Promise.all([
          api.get<Paginated<LeaveRequest>>("/api/hr/leave/?mine=true"),
          api.get<Paginated<LeaveType>>("/api/hr/leave-types/"),
        ]);
        setLeaveRequests(reqRes.results || []);
        setLeaveTypes(typeRes.results || []);
      } else if (tab === "pay") {
        const payRes = await api.get<PayslipSummary[]>("/api/payroll/payslips/mine/");
        setPayslips(payRes || []);
      } else if (tab === "swaps") {
        const swapRes = await api.get<Paginated<ShiftSwapRow>>("/api/hr/shift-swaps/mine/");
        setSwaps(swapRes.results || []);
        const empRes = await api.get<Paginated<any>>("/api/hr/employees/");
        setColleagues(
          (empRes.results || []).map((e: any) => ({
            uuid: e.uuid,
            full_name: `${e.first_name} ${e.last_name}`,
            code: e.employee_code,
          }))
        );
      } else if (tab === "profile") {
        const corrRes = await api.get<Paginated<ProfileCorrectionRow>>("/api/hr/profile-corrections/");
        setCorrections(corrRes.results || []);
      } else if (tab === "manager") {
        const mgrRes = await api.get<ManagerQueueResponse>("/api/hr/manager-queue/");
        setManagerQueue(mgrRes);
      }
    } catch (err: any) {
      console.error("Tab load failed", err);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    if (summary) {
      loadTabData(activeTab);
    }
  }, [activeTab, summary, loadTabData]);

  // Handle punch in/out
  const handlePunch = async (action: "in" | "out") => {
    try {
      setClocking(true);
      setError(null);
      const url = action === "in" ? "/api/hr/attendance/check-in/" : "/api/hr/attendance/check-out/";
      await api.post(url, { source: "web" });
      setSuccess(`Successfully marked attendance: checked ${action}.`);
      await loadSummary();
      loadTabData("time");
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : `Failed to check ${action}.`);
    } finally {
      setClocking(false);
    }
  };

  // Submit Profile Correction
  const handleCorrectionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setError(null);
      await api.post("/api/hr/profile-corrections/", {
        fields_payload: {
          phone: corrPhone,
          personal_email: corrEmail,
          address: corrAddress,
          bank_name: corrBankName,
          bank_account_number: corrAccountNo,
        },
        reason: corrReason,
      });
      setSuccess("Profile correction request submitted for approval.");
      setCorrectionModal(false);
      setCorrReason("");
      loadTabData("profile");
      loadSummary();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Failed to submit correction.");
    }
  };

  // Submit Leave Request
  const handleLeaveSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setError(null);
      await api.post("/api/hr/leave/", {
        leave_type: leaveType,
        starts_on: leaveStarts,
        ends_on: leaveEnds,
        reason: leaveReason,
      });
      setSuccess("Leave application submitted.");
      setLeaveModal(false);
      setLeaveReason("");
      loadTabData("leave");
      loadSummary();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Failed to submit leave request.");
    }
  };

  // Submit Shift Swap Request
  const handleSwapSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setError(null);
      await api.post("/api/hr/shift-swaps/", {
        requester_entry: swapEntry,
        target_employee: swapTargetEmp,
        reason: swapReason,
      });
      setSuccess("Shift swap request sent to colleague.");
      setSwapModal(false);
      setSwapReason("");
      loadTabData("swaps");
      loadSummary();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Failed to propose shift swap.");
    }
  };

  // Colleague decide swap
  const handlePeerDecide = async (uuid: string, accept: boolean) => {
    try {
      setError(null);
      await api.post(`/api/hr/shift-swaps/${uuid}/peer-decide/`, { accept });
      setSuccess(`Swap proposal ${accept ? "accepted and sent to manager" : "declined"}.`);
      loadTabData("swaps");
      loadSummary();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Failed to record response.");
    }
  };

  // Regularise attendance
  const handleRegularise = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!regModal) return;
    try {
      setError(null);
      await api.post(`/api/hr/attendance/${regModal}/regularise/`, {
        checked_in_at: regInTime || null,
        checked_out_at: regOutTime || null,
        reason: regReason,
      });
      setSuccess("Attendance regularisation request submitted to your manager.");
      setRegModal(null);
      setRegReason("");
      loadTabData("time");
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Failed to request regularisation.");
    }
  };

  // Manager Queue Actions
  const handleManagerAction = async (item: ManagerQueueItem, approve: boolean) => {
    try {
      setError(null);
      if (item.type === "leave") {
        await api.post(`/api/hr/leave/${item.reference}/decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "regularisation") {
        await api.post(`/api/hr/regularisations/${item.id}/decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "swap") {
        await api.post(`/api/hr/shift-swaps/${item.id}/manager-decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "correction") {
        await api.post(`/api/hr/profile-corrections/${item.id}/decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      }
      setSuccess(`${item.type_label} for ${item.employee_name} ${approve ? "approved" : "rejected"}.`);
      loadTabData("manager");
      loadSummary();
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  };

  // View payslip details
  const viewPayslip = async (reference: string) => {
    try {
      const doc = await api.get(`/api/payroll/payslips/${reference}/document/`);
      setPayslipModal(doc);
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Could not load payslip document.");
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error && !summary) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-4">
        <Alert variant="destructive">
          <AlertCircle className="h-5 w-5" />
          <AlertTitle>Self-Service Unavailable</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  const emp = summary?.employee;
  const todayAtt = summary?.attendance_today;

  return (
    <div className="space-y-6 pb-12">
      {/* Header Banner */}
      <div className="rounded-xl bg-gradient-to-r from-blue-700 via-indigo-700 to-slate-800 p-6 text-white shadow-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-blue-500/20 px-2 py-0.5 text-xs font-semibold text-blue-100 ring-1 ring-inset ring-blue-400/30">
                Staff Portal · §95
              </span>
              {emp?.department && (
                <span className="text-xs text-blue-200">· {emp.department}</span>
              )}
            </div>
            <h1 className="text-2xl font-bold tracking-tight mt-1">{emp?.full_name}</h1>
            <p className="text-sm text-blue-100/80">
              {emp?.position || "Staff"} ({emp?.code}) · Reports to {emp?.reports_to || "Medical Admin"}
            </p>
          </div>

          {/* Quick Punch Action Card */}
          <div className="flex items-center gap-3 bg-white/10 backdrop-blur-sm p-3 rounded-lg border border-white/20">
            <div className="text-right">
              <div className="text-xs text-blue-200">Today's Attendance</div>
              <div className="font-semibold capitalize text-sm">
                {todayAtt ? (
                  <span className="flex items-center gap-1.5 justify-end">
                    <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                    {todayAtt.status} ({todayAtt.worked_hours}h)
                  </span>
                ) : (
                  <span className="text-amber-300">Not checked in</span>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              {!todayAtt?.checked_in_at ? (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={clocking}
                  onClick={() => handlePunch("in")}
                  className="bg-emerald-500 hover:bg-emerald-600 text-white font-medium"
                >
                  <LogIn className="h-4 w-4 mr-1.5" /> Check In
                </Button>
              ) : !todayAtt.checked_out_at ? (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={clocking}
                  onClick={() => handlePunch("out")}
                  className="bg-amber-500 hover:bg-amber-600 text-white font-medium"
                >
                  <LogOut className="h-4 w-4 mr-1.5" /> Check Out
                </Button>
              ) : (
                <Badge variant="outline" className="border-emerald-300 text-emerald-100">
                  <CheckCircle2 className="h-3.5 w-3.5 mr-1 text-emerald-300" /> Completed
                </Badge>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Notifications / Feedback */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {success && (
        <Alert className="border-emerald-500 text-emerald-800 bg-emerald-50">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          <AlertTitle>Success</AlertTitle>
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      )}

      {/* Navigation Tabs */}
      <div className="flex border-b border-border overflow-x-auto gap-2 text-sm font-medium">
        <button
          onClick={() => setActiveTab("profile")}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap",
            activeTab === "profile"
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          <UserCheck className="h-4 w-4" /> My Profile
        </button>
        <button
          onClick={() => setActiveTab("time")}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap",
            activeTab === "time"
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          <Clock className="h-4 w-4" /> My Time
        </button>
        <button
          onClick={() => setActiveTab("swaps")}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap relative",
            activeTab === "swaps"
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          <ArrowRightLeft className="h-4 w-4" /> Shift Swaps
          {(summary?.pending_incoming_swaps ?? 0) > 0 && (
            <span className="ml-1 rounded-full bg-amber-500 text-white text-xs px-1.5 py-0.2">
              {summary?.pending_incoming_swaps}
            </span>
          )}
        </button>
        <button
          onClick={() => setActiveTab("leave")}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap",
            activeTab === "leave"
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          <Plane className="h-4 w-4" /> My Leave
        </button>
        <button
          onClick={() => setActiveTab("pay")}
          className={cn(
            "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap",
            activeTab === "pay"
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          <Wallet className="h-4 w-4" /> My Pay
        </button>

        {summary?.is_manager && (
          <button
            onClick={() => setActiveTab("manager")}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors whitespace-nowrap text-indigo-600",
              activeTab === "manager"
                ? "border-indigo-600 text-indigo-700 font-semibold"
                : "border-transparent hover:text-indigo-700"
            )}
          >
            <Users className="h-4 w-4" /> Team Approvals
            {(managerQueue?.summary.pending_total ?? 0) > 0 && (
              <span className="ml-1 rounded-full bg-indigo-600 text-white text-xs px-1.5 py-0.2">
                {managerQueue?.summary.pending_total}
              </span>
            )}
          </button>
        )}
      </div>

      {/* 1. My Profile Tab */}
      {activeTab === "profile" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Info */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <div>
                  <CardTitle>Personal & Employment Details</CardTitle>
                  <CardDescription>Verified staff record on file with HR</CardDescription>
                </div>
                <Button size="sm" variant="outline" onClick={() => setCorrectionModal(true)}>
                  <UserCog className="h-4 w-4 mr-1.5" /> Request Changes
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="text-muted-foreground">Phone Number</div>
                  <div className="font-medium">{emp?.phone || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Personal Email</div>
                  <div className="font-medium">{emp?.personal_email || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Residential Address</div>
                  <div className="font-medium">
                    {emp?.address ? `${emp.address}, ${emp.municipality || ""}, ${emp.district || ""}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Citizenship & PAN</div>
                  <div className="font-medium">
                    Citizenship: {emp?.citizenship_number || "—"} | PAN: {emp?.pan_number || "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Bank Account for Salary</div>
                  <div className="font-medium">
                    {emp?.bank_name ? `${emp.bank_name} (${emp.bank_account_number})` : "None configured"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Emergency Contact</div>
                  <div className="font-medium">
                    {emp?.emergency_contact_name
                      ? `${emp.emergency_contact_name} (${emp.emergency_contact_relation}) - ${emp.emergency_contact_phone}`
                      : "—"}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Profile Change Requests History */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Pending & Past Profile Correction Requests</CardTitle>
                <CardDescription>
                  Address, telephone, and bank details require HR review before updating payroll and tax records
                </CardDescription>
              </CardHeader>
              <CardContent>
                {corrections.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No profile change requests submitted.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Requested On</TableHead>
                        <TableHead>Proposed Changes</TableHead>
                        <TableHead>Reason</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {corrections.map((c) => (
                        <TableRow key={c.uuid}>
                          <TableCell className="text-xs text-muted-foreground">
                            {new Date(c.created_at).toLocaleDateString()}
                          </TableCell>
                          <TableCell className="text-xs font-mono">
                            {Object.entries(c.fields_payload).map(([k, v]) => (
                              <div key={k}>{k}: {v}</div>
                            ))}
                          </TableCell>
                          <TableCell className="text-xs">{c.reason}</TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                c.status === "approved"
                                  ? "default"
                                  : c.status === "pending"
                                  ? "outline"
                                  : "destructive"
                              }
                            >
                              {c.status}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Credentials Sidebar */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <FileCheck className="h-4 w-4 text-primary" /> Professional Licences & Council Registrations
                </CardTitle>
                <CardDescription>Lapsed licences immediately block prescribing and clinical practice</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {summary?.credentials && summary.credentials.length > 0 ? (
                  summary.credentials.map((cred) => (
                    <div
                      key={cred.uuid}
                      className={cn(
                        "p-3 rounded-lg border text-sm",
                        cred.status_tag === "expired"
                          ? "border-destructive bg-destructive/5 text-destructive"
                          : cred.status_tag === "expiring_soon"
                          ? "border-amber-400 bg-amber-50 text-amber-900"
                          : "border-border bg-card"
                      )}
                    >
                      <div className="flex items-center justify-between font-semibold">
                        <span>{cred.name}</span>
                        {cred.status_tag === "expired" ? (
                          <Badge variant="destructive">Expired</Badge>
                        ) : cred.status_tag === "expiring_soon" ? (
                          <Badge variant="outline" className="text-amber-700 border-amber-400">
                            Expiring in {cred.days_to_expiry}d
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-emerald-600 border-emerald-300">
                            Verified
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        Reg: {cred.registration_number || "—"} · {cred.issuing_body}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Expires on: {cred.expires_on || "Permanent"}
                      </div>
                      {cred.blocks_practice && cred.is_expired && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-destructive">
                          <ShieldAlert className="h-4 w-4" /> Clinical practice blocked until renewed.
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">No professional credentials registered.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* 2. My Time Tab */}
      {activeTab === "time" && (
        <div className="space-y-6">
          {/* Attendance History */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Attendance Log</CardTitle>
                <CardDescription>
                  Recorded clock events. If a mark was missed, raise a regularisation with your manager.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Check In</TableHead>
                    <TableHead>Check Out</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Late / Early</TableHead>
                    <TableHead>Hours</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {attendanceRecords.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground py-6">
                        No attendance records found for this period.
                      </TableCell>
                    </TableRow>
                  ) : (
                    attendanceRecords.map((rec) => (
                      <TableRow key={rec.uuid}>
                        <TableCell className="font-medium">{rec.date}</TableCell>
                        <TableCell>{rec.checked_in_at ? new Date(rec.checked_in_at).toLocaleTimeString() : "—"}</TableCell>
                        <TableCell>{rec.checked_out_at ? new Date(rec.checked_out_at).toLocaleTimeString() : "—"}</TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              rec.status === "present"
                                ? "default"
                                : rec.status === "late" || rec.status === "half_day"
                                ? "outline"
                                : "destructive"
                            }
                          >
                            {rec.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {rec.late_minutes > 0 ? `Late: ${rec.late_minutes}m ` : ""}
                          {rec.early_exit_minutes > 0 ? `Early: ${rec.early_exit_minutes}m` : ""}
                          {rec.late_minutes === 0 && rec.early_exit_minutes === 0 ? "On time" : ""}
                        </TableCell>
                        <TableCell className="text-xs">{rec.worked_hours}h</TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setRegModal(rec.uuid);
                              setRegInTime(rec.checked_in_at || "");
                              setRegOutTime(rec.checked_out_at || "");
                            }}
                          >
                            Regularise
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Upcoming Published Shifts */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Upcoming Roster Schedule (Next 14 Days)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                {summary?.upcoming_shifts && summary.upcoming_shifts.length > 0 ? (
                  summary.upcoming_shifts.map((s) => (
                    <div key={s.uuid} className="p-3 border rounded-lg bg-muted/20">
                      <div className="text-xs text-muted-foreground font-medium">{s.date}</div>
                      <div className="font-semibold text-sm mt-0.5">{s.shift_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {s.starts_at} - {s.ends_at}
                      </div>
                      {s.is_on_call && <Badge className="mt-1 text-[10px]" variant="outline">On Call</Badge>}
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground col-span-4">No published shifts for the upcoming fortnight.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 3. Shift Swaps Tab */}
      {activeTab === "swaps" && (
        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Colleague Shift Swaps</CardTitle>
                <CardDescription>
                  Mutual swaps require colleague acceptance first, followed by department manager sign-off.
                </CardDescription>
              </div>
              <Button onClick={() => setSwapModal(true)}>
                <ArrowRightLeft className="h-4 w-4 mr-1.5" /> Propose Swap
              </Button>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requester</TableHead>
                    <TableHead>Colleague</TableHead>
                    <TableHead>Shift To Swap</TableHead>
                    <TableHead>Target Shift / Cover</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {swaps.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground py-6">
                        No shift swap requests active.
                      </TableCell>
                    </TableRow>
                  ) : (
                    swaps.map((s) => {
                      const isIncoming = s.target_code === emp?.code;
                      return (
                        <TableRow key={s.uuid}>
                          <TableCell className="font-medium text-xs">
                            {s.requester_name} ({s.requester_code})
                          </TableCell>
                          <TableCell className="font-medium text-xs">
                            {s.target_name} ({s.target_code})
                          </TableCell>
                          <TableCell className="text-xs">
                            {s.requester_entry_date} ({s.requester_shift_name})
                          </TableCell>
                          <TableCell className="text-xs">
                            {s.target_entry_date
                              ? `${s.target_entry_date} (${s.target_shift_name})`
                              : "Shift Cover (1-way)"}
                          </TableCell>
                          <TableCell className="text-xs">{s.reason}</TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                s.status === "approved"
                                  ? "default"
                                  : s.status.includes("pending")
                                  ? "outline"
                                  : "destructive"
                              }
                            >
                              {s.status.replace("_", " ")}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            {isIncoming && s.status === "pending_peer" && (
                              <div className="flex gap-1.5 justify-end">
                                <Button
                                  size="sm"
                                  variant="default"
                                  onClick={() => handlePeerDecide(s.uuid, true)}
                                >
                                  Accept
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => handlePeerDecide(s.uuid, false)}
                                >
                                  Decline
                                </Button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 4. My Leave Tab */}
      {activeTab === "leave" && (
        <div className="space-y-6">
          {/* Balance Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {summary?.leave_balances.map((b) => (
              <Card key={b.code} className="border-t-4" style={{ borderTopColor: b.colour || "#3b82f6" }}>
                <CardHeader className="p-4 pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">{b.name}</CardTitle>
                </CardHeader>
                <CardContent className="p-4 pt-0">
                  <div className="text-2xl font-bold">{b.balance} <span className="text-xs text-muted-foreground font-normal">days</span></div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    Annual entitlement: {b.annual_entitlement} days
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>My Leave History</CardTitle>
                <CardDescription>Applications, working days calculated against holidays, and approval status.</CardDescription>
              </div>
              <Button onClick={() => setLeaveModal(true)}>
                <Plane className="h-4 w-4 mr-1.5" /> Apply for Leave
              </Button>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reference</TableHead>
                    <TableHead>Leave Type</TableHead>
                    <TableHead>Period</TableHead>
                    <TableHead>Working Days</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {leaveRequests.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                        No leave requests found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    leaveRequests.map((l) => (
                      <TableRow key={l.uuid}>
                        <TableCell className="font-mono text-xs">{l.reference}</TableCell>
                        <TableCell>{l.leave_type_name}</TableCell>
                        <TableCell className="text-xs">{l.starts_on} to {l.ends_on}</TableCell>
                        <TableCell className="text-xs">{l.working_days} days</TableCell>
                        <TableCell className="text-xs">{l.reason}</TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              l.status === "approved"
                                ? "default"
                                : l.status === "pending"
                                ? "outline"
                                : "destructive"
                            }
                          >
                            {l.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 5. My Pay Tab */}
      {activeTab === "pay" && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Approved Salary Payslips</CardTitle>
              <CardDescription>
                Only finalized and approved pay runs are visible here. Click any payslip to view line items or generate a printable document.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reference</TableHead>
                    <TableHead>Period</TableHead>
                    <TableHead>Gross Pay</TableHead>
                    <TableHead>Deductions</TableHead>
                    <TableHead>Tax / SSF</TableHead>
                    <TableHead>Net Pay</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payslips.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground py-6">
                        No approved payslips available yet.
                      </TableCell>
                    </TableRow>
                  ) : (
                    payslips.map((p) => (
                      <TableRow key={p.uuid}>
                        <TableCell className="font-mono text-xs">{p.reference}</TableCell>
                        <TableCell className="font-medium text-xs">{p.period_label}</TableCell>
                        <TableCell className="text-xs">NPR {p.gross}</TableCell>
                        <TableCell className="text-xs text-destructive">NPR {p.deductions}</TableCell>
                        <TableCell className="text-xs">NPR {p.tax}</TableCell>
                        <TableCell className="text-xs font-bold text-primary">NPR {p.net}</TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" variant="outline" onClick={() => viewPayslip(p.reference)}>
                            <Printer className="h-3.5 w-3.5 mr-1" /> View / Print
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 6. Manager Approval Hub Tab */}
      {activeTab === "manager" && summary?.is_manager && (
        <div className="space-y-6">
          {/* Summary counters */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground font-medium">Pending Approvals</div>
                <div className="text-2xl font-bold text-indigo-600 mt-1">{managerQueue?.summary.pending_total ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground font-medium">Leave Requests</div>
                <div className="text-2xl font-bold mt-1">{managerQueue?.summary.leave_count ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground font-medium">Regularisations</div>
                <div className="text-2xl font-bold mt-1">{managerQueue?.summary.regularisation_count ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground font-medium">Shift Swaps</div>
                <div className="text-2xl font-bold mt-1">{managerQueue?.summary.swap_count ?? 0}</div>
              </CardContent>
            </Card>
          </div>

          {/* Unified Worklist */}
          <Card>
            <CardHeader>
              <CardTitle>Team Requests Worklist</CardTitle>
              <CardDescription>
                One central queue holding every request from your team members rather than four separate screens.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {managerQueue?.items.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <CheckCircle2 className="h-8 w-8 mx-auto text-emerald-500 mb-2" />
                  All team requests cleared. Nothing pending review!
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Type</TableHead>
                      <TableHead>Team Member</TableHead>
                      <TableHead>Details</TableHead>
                      <TableHead>Reason</TableHead>
                      <TableHead>Submitted</TableHead>
                      <TableHead className="text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {managerQueue?.items.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>
                          <Badge variant="outline" style={{ borderColor: item.badge_colour, color: item.badge_colour }}>
                            {item.type_label}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium text-xs">
                          {item.employee_name} ({item.employee_code})
                        </TableCell>
                        <TableCell className="text-xs">
                          <div className="font-medium">{item.title}</div>
                          <div className="text-muted-foreground">{item.subtitle}</div>
                        </TableCell>
                        <TableCell className="text-xs max-w-[200px] truncate">{item.reason}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(item.submitted_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right space-x-1.5">
                          <Button size="sm" variant="default" onClick={() => handleManagerAction(item, true)}>
                            Approve
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => handleManagerAction(item, false)}>
                            Reject
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Modal: Request Profile Correction */}
      {correctionModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-lg bg-card p-6 space-y-4">
            <CardHeader className="p-0">
              <CardTitle>Request Profile / Bank Account Correction</CardTitle>
              <CardDescription>
                Updates to bank details, phone, or address require verification before taking effect.
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleCorrectionSubmit} className="space-y-3">
              <div>
                <Label>Phone Number</Label>
                <Input value={corrPhone} onChange={(e) => setCorrPhone(e.target.value)} required />
              </div>
              <div>
                <Label>Personal Email</Label>
                <Input value={corrEmail} onChange={(e) => setCorrEmail(e.target.value)} />
              </div>
              <div>
                <Label>Residential Address</Label>
                <Input value={corrAddress} onChange={(e) => setCorrAddress(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Bank Name</Label>
                  <Input value={corrBankName} onChange={(e) => setCorrBankName(e.target.value)} />
                </div>
                <div>
                  <Label>Bank Account Number</Label>
                  <Input value={corrAccountNo} onChange={(e) => setCorrAccountNo(e.target.value)} />
                </div>
              </div>
              <div>
                <Label>Reason for Update</Label>
                <Textarea
                  value={corrReason}
                  onChange={(e) => setCorrReason(e.target.value)}
                  placeholder="e.g. Switched payroll bank branch to New Road"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setCorrectionModal(false)}>
                  Cancel
                </Button>
                <Button type="submit">Submit Request</Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* Modal: Propose Shift Swap */}
      {swapModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-lg bg-card p-6 space-y-4">
            <CardHeader className="p-0">
              <CardTitle>Propose Shift Swap</CardTitle>
              <CardDescription>
                Select a published shift of yours and a target colleague to cover or swap.
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleSwapSubmit} className="space-y-3">
              <div>
                <Label>Your Shift to Swap</Label>
                <Select value={swapEntry} onChange={(e) => setSwapEntry(e.target.value)} required>
                  <option value="">Select your shift...</option>
                  {summary?.upcoming_shifts.map((s) => (
                    <option key={s.uuid} value={s.uuid}>
                      {s.date} — {s.shift_name} ({s.starts_at} - {s.ends_at})
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label>Colleague</Label>
                <Select value={swapTargetEmp} onChange={(e) => setSwapTargetEmp(e.target.value)} required>
                  <option value="">Select colleague...</option>
                  {colleagues
                    .filter((c) => c.code !== emp?.code)
                    .map((c) => (
                      <option key={c.uuid} value={c.uuid}>
                        {c.full_name} ({c.code})
                      </option>
                    ))}
                </Select>
              </div>
              <div>
                <Label>Reason</Label>
                <Textarea
                  value={swapReason}
                  onChange={(e) => setSwapReason(e.target.value)}
                  placeholder="e.g. Family emergency, will return cover next week"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setSwapModal(false)}>
                  Cancel
                </Button>
                <Button type="submit">Send Proposal</Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* Modal: Apply Leave */}
      {leaveModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-lg bg-card p-6 space-y-4">
            <CardHeader className="p-0">
              <CardTitle>Apply for Leave</CardTitle>
              <CardDescription>Working days are automatically computed factoring in Nepal's holidays.</CardDescription>
            </CardHeader>
            <form onSubmit={handleLeaveSubmit} className="space-y-3">
              <div>
                <Label>Leave Type</Label>
                <Select value={leaveType} onChange={(e) => setLeaveType(e.target.value)} required>
                  <option value="">Select leave type...</option>
                  {leaveTypes.map((t) => (
                    <option key={t.uuid} value={t.uuid}>
                      {t.name} (Annual: {t.annual_entitlement}d)
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Start Date</Label>
                  <Input type="date" value={leaveStarts} onChange={(e) => setLeaveStarts(e.target.value)} required />
                </div>
                <div>
                  <Label>End Date</Label>
                  <Input type="date" value={leaveEnds} onChange={(e) => setLeaveEnds(e.target.value)} required />
                </div>
              </div>
              <div>
                <Label>Reason</Label>
                <Textarea
                  value={leaveReason}
                  onChange={(e) => setLeaveReason(e.target.value)}
                  placeholder="State the reason for leave"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setLeaveModal(false)}>
                  Cancel
                </Button>
                <Button type="submit">Submit Application</Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* Modal: Regularise Attendance */}
      {regModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <Card className="w-full max-w-md bg-card p-6 space-y-4">
            <CardHeader className="p-0">
              <CardTitle>Request Clock Regularisation</CardTitle>
              <CardDescription>Provide corrected timestamps and an explanation for missed punches.</CardDescription>
            </CardHeader>
            <form onSubmit={handleRegularise} className="space-y-3">
              <div>
                <Label>Checked In At</Label>
                <Input
                  type="datetime-local"
                  value={regInTime ? regInTime.slice(0, 16) : ""}
                  onChange={(e) => setRegInTime(e.target.value)}
                />
              </div>
              <div>
                <Label>Checked Out At</Label>
                <Input
                  type="datetime-local"
                  value={regOutTime ? regOutTime.slice(0, 16) : ""}
                  onChange={(e) => setRegOutTime(e.target.value)}
                />
              </div>
              <div>
                <Label>Reason</Label>
                <Textarea
                  value={regReason}
                  onChange={(e) => setRegReason(e.target.value)}
                  placeholder="e.g. Card scanner offline during morning handover"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setRegModal(null)}>
                  Cancel
                </Button>
                <Button type="submit">Submit Regularisation</Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* Modal: Printable Payslip Document */}
      {payslipModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4 overflow-y-auto">
          <div className="w-full max-w-2xl bg-white text-slate-900 rounded-xl shadow-2xl p-8 space-y-6">
            <div className="flex items-center justify-between border-b pb-4">
              <div>
                <div className="text-xl font-bold text-blue-900">{payslipModal.organization_name}</div>
                <div className="text-xs text-slate-500">
                  {payslipModal.facility_name} · Salary Payslip ({payslipModal.period_label})
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    const printUrl = `/api/payroll/payslips/${payslipModal.reference}/document/?format=html`;
                    window.open(printUrl, "_blank");
                  }}
                >
                  <Printer className="h-4 w-4 mr-1.5" /> Print / PDF
                </Button>
                <Button size="sm" variant="outline" onClick={() => setPayslipModal(null)}>
                  Close
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs bg-slate-50 p-3 rounded-lg border">
              <div>
                <div><strong>Employee:</strong> {payslipModal.employee.name} ({payslipModal.employee.code})</div>
                <div><strong>Position:</strong> {payslipModal.employee.position}</div>
                <div><strong>Department:</strong> {payslipModal.employee.department}</div>
              </div>
              <div>
                <div><strong>PAN:</strong> {payslipModal.employee.pan_number || "—"}</div>
                <div><strong>Bank:</strong> {payslipModal.employee.bank_name} ({payslipModal.employee.bank_account_number || "—"})</div>
                <div><strong>Days Worked:</strong> {payslipModal.present_days} of {payslipModal.payable_days}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6 text-sm">
              <div>
                <div className="font-semibold text-xs uppercase tracking-wider text-slate-500 mb-2">Earnings</div>
                <div className="space-y-1.5 border-t pt-2">
                  {payslipModal.earnings.map((e: any) => (
                    <div key={e.name} className="flex justify-between text-xs">
                      <span>{e.name}</span>
                      <span>NPR {e.amount}</span>
                    </div>
                  ))}
                  <div className="flex justify-between font-bold pt-2 border-t text-xs">
                    <span>Gross Salary</span>
                    <span>NPR {payslipModal.gross_pay}</span>
                  </div>
                </div>
              </div>

              <div>
                <div className="font-semibold text-xs uppercase tracking-wider text-slate-500 mb-2">Deductions</div>
                <div className="space-y-1.5 border-t pt-2">
                  {payslipModal.deductions.map((d: any) => (
                    <div key={d.name} className="flex justify-between text-xs">
                      <span>{d.name}</span>
                      <span>NPR {d.amount}</span>
                    </div>
                  ))}
                  <div className="flex justify-between font-bold pt-2 border-t text-xs">
                    <span>Total Deductions</span>
                    <span>NPR {payslipModal.total_deductions}</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 flex justify-between items-center">
              <div>
                <div className="text-xs text-blue-700">Net Take-Home Pay</div>
                <div className="text-xs text-slate-500">Credited to registered bank account</div>
              </div>
              <div className="text-2xl font-bold text-blue-900">
                NPR {payslipModal.net_pay}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
