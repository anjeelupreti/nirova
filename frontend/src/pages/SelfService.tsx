/**
 * The employment half of "me": attendance, shifts, leave, pay, and a
 * manager's team requests. Rendered as sections of the profile hub
 * (`pages/Me.tsx`) rather than as a screen of its own.
 *
 * **It was a second profile.** This screen had its own banner, its own tab
 * strip and its own "My Profile", while My account had another -- two places
 * called "profile", styled nothing alike, and check-in, the one thing done
 * every day, three clicks deep. The hub owns the header, the tabs and the
 * check-in now; this file owns only what each section shows and does.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRightLeft,
  CheckCircle2,
  FileCheck,
  Plane,
  Printer,
  ShieldAlert,
  UserCog,
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
import { formatDate, formatTime } from "@/lib/dates";
import { ATTENDANCE_CHANGED } from "@/components/me/staff";
import { Modal, ModalColumns } from "@/components/ui/modal";

export type SelfServiceTab = "profile" | "time" | "swaps" | "leave" | "pay" | "manager";
type Tab = SelfServiceTab;

export function SelfServiceSection({
  section,
  summary,
  onSummaryChanged,
}: {
  section: SelfServiceTab;
  summary: ESSMeSummary;
  /** Ask the hub to re-read the summary it shares with its header. */
  onSummaryChanged: () => void;
}) {
  const activeTab: Tab = section;
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

  const loadSummary = onSummaryChanged;

  // The correction form starts from what HR holds now.
  useEffect(() => {
    const employee = summary.employee;
    if (!employee) return;
    setCorrPhone(employee.phone || "");
    setCorrEmail(employee.personal_email || "");
    setCorrAddress(employee.address || "");
    setCorrBankName(employee.bank_name || "");
    setCorrAccountNo(employee.bank_account_number || "");
  }, [summary]);

  // Load secondary tab data
  const loadTabData = useCallback(async (tab: Tab) => {
    try {
      if (tab === "time") {
        const attRes = await api.get<Paginated<AttendanceRecord>>("/hr/attendance/?mine=true");
        setAttendanceRecords(attRes.results || []);
      } else if (tab === "leave") {
        const [reqRes, typeRes] = await Promise.all([
          api.get<Paginated<LeaveRequest>>("/hr/leave/?mine=true"),
          api.get<Paginated<LeaveType>>("/hr/leave-types/"),
        ]);
        setLeaveRequests(reqRes.results || []);
        setLeaveTypes(typeRes.results || []);
      } else if (tab === "pay") {
        const payRes = await api.get<PayslipSummary[]>("/payroll/payslips/mine/");
        setPayslips(payRes || []);
      } else if (tab === "swaps") {
        const swapRes = await api.get<Paginated<ShiftSwapRow>>("/hr/shift-swaps/mine/");
        setSwaps(swapRes.results || []);
        // Peers, not the staff directory: `/hr/employees/` needs
        // `employee.read` and 403'd for every clinical role, so this dropdown
        // was empty for exactly the people who use it.
        const empRes = await api.get<Paginated<{ uuid: string; full_name: string; code: string }>>(
          "/hr/shift-swaps/peers/"
        );
        setColleagues(empRes.results || []);
      } else if (tab === "profile") {
        const corrRes = await api.get<Paginated<ProfileCorrectionRow>>("/hr/profile-corrections/");
        setCorrections(corrRes.results || []);
      } else if (tab === "manager") {
        const mgrRes = await api.get<ManagerQueueResponse>("/hr/manager-queue/");
        setManagerQueue(mgrRes);
      }
    } catch (err: any) {
      console.error("Tab load failed", err);
    }
  }, []);

  useEffect(() => {
    void loadTabData(activeTab);
    // Checking in from the header or from My day changes today's row here.
    const refresh = () => void loadTabData(activeTab);
    window.addEventListener(ATTENDANCE_CHANGED, refresh);
    return () => window.removeEventListener(ATTENDANCE_CHANGED, refresh);
  }, [activeTab, loadTabData]);

  // Submit Profile Correction
  const handleCorrectionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setError(null);
      await api.post("/hr/profile-corrections/", {
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
      await api.post("/hr/leave/", {
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
      await api.post("/hr/shift-swaps/", {
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
      await api.post(`/hr/shift-swaps/${uuid}/peer-decide/`, { accept });
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
      await api.post(`/hr/attendance/${regModal}/regularise/`, {
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
        await api.post(`/hr/leave/${item.reference}/decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "regularisation") {
        await api.post(`/hr/regularisations/${item.id}/decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "swap") {
        await api.post(`/hr/shift-swaps/${item.id}/manager-decide/`, {
          approve,
          notes: approve ? "Approved by manager" : "Declined by manager",
        });
      } else if (item.type === "correction") {
        await api.post(`/hr/profile-corrections/${item.id}/decide/`, {
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
      const doc = await api.get(`/payroll/payslips/${reference}/document/`);
      setPayslipModal(doc);
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : "Could not load payslip document.");
    }
  };

  const emp = summary?.employee;

  return (
    <div className="space-y-6">
      {/* Notifications / Feedback */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {success && (
        <Alert className="border-good/40 text-good bg-good-subtle">
          <CheckCircle2 className="h-4 w-4 text-good" />
          <AlertTitle>Success</AlertTitle>
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      )}

      {/* 1. My Profile Tab */}
      {activeTab === "profile" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Info */}
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <div>
                  <CardTitle>Employment record</CardTitle>
                  <CardDescription>What HR holds for you. Changes go through HR, because payroll and tax read it.</CardDescription>
                </div>
                <Button size="sm" variant="outline" onClick={() => setCorrectionModal(true)}>
                  <UserCog className="h-4 w-4 mr-1.5" /> Request a change
                </Button>
              </CardHeader>
              <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="text-muted-foreground">Phone</div>
                  <div className="font-medium">{emp?.phone || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Personal email</div>
                  <div className="font-medium">{emp?.personal_email || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Address</div>
                  <div className="font-medium">
                    {emp?.address ? `${emp.address}, ${emp.municipality || ""}, ${emp.district || ""}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Citizenship and PAN</div>
                  <div className="font-medium">
                    {emp?.citizenship_number || "—"} · PAN {emp?.pan_number || "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Salary account</div>
                  <div className="font-medium">
                    {emp?.bank_name ? `${emp.bank_name} (${emp.bank_account_number})` : "None configured"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Emergency contact</div>
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
                <CardTitle className="text-base">Change requests</CardTitle>
                <CardDescription>
                  Address, telephone and bank details are reviewed by HR before payroll uses them.
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
                            {formatDate(c.created_at)}
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
                              <span className="capitalize">{c.status.replace("_", " ")}</span>
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
                  <FileCheck className="h-4 w-4 text-primary" /> Licences and registrations
                </CardTitle>
                <CardDescription>A lapsed licence blocks prescribing until it is renewed.</CardDescription>
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
                          ? "border-warning/40 bg-warning-subtle text-warning"
                          : "border-border bg-card"
                      )}
                    >
                      <div className="flex items-center justify-between font-semibold">
                        <span>{cred.name}</span>
                        {cred.status_tag === "expired" ? (
                          <Badge variant="destructive">Expired</Badge>
                        ) : cred.status_tag === "expiring_soon" ? (
                          <Badge variant="outline" className="text-warning border-warning/40">
                            Expiring in {cred.days_to_expiry}d
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-good border-good/40">
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
                <CardTitle>Attendance</CardTitle>
                <CardDescription>
                  Your check-ins this month. Missed one? Ask your manager to correct it.
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
                        <TableCell>{rec.checked_in_at ? formatTime(rec.checked_in_at) : "—"}</TableCell>
                        <TableCell>{rec.checked_out_at ? formatTime(rec.checked_out_at) : "—"}</TableCell>
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
                            <span className="capitalize">{rec.status.replace("_", " ")}</span>
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
              <CardTitle className="text-base">Your shifts, next 14 days</CardTitle>
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
                <CardTitle>Shift swaps</CardTitle>
                <CardDescription>
                  Your colleague accepts first, then your manager signs it off.
                </CardDescription>
              </div>
              <Button onClick={() => setSwapModal(true)}>
                <ArrowRightLeft className="h-4 w-4 mr-1.5" /> Propose a swap
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
              <Card key={b.code} className="border-t-4" style={b.colour ? { borderTopColor: b.colour } : undefined}>
                <CardHeader className="p-4 pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">{b.name}</CardTitle>
                </CardHeader>
                <CardContent className="p-4 pt-0">
                  <div className="text-2xl font-bold tabular-nums">{Number(b.balance)} <span className="text-xs text-muted-foreground font-normal">days left</span></div>
                  <div className="text-[11px] text-muted-foreground mt-1">
                    of {Number(b.annual_entitlement)} a year
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>Leave applications</CardTitle>
                <CardDescription>Working days are counted against public holidays.</CardDescription>
              </div>
              <Button onClick={() => setLeaveModal(true)}>
                <Plane className="h-4 w-4 mr-1.5" /> Apply for leave
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
                            <span className="capitalize">{l.status.replace("_", " ")}</span>
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
              <CardTitle>Payslips</CardTitle>
              <CardDescription>
                Approved pay runs only. Open one to see every line, or print it.
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
                            <Printer className="h-3.5 w-3.5 mr-1" /> View
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
                <div className="text-2xl font-bold text-info mt-1">{managerQueue?.summary.pending_total ?? 0}</div>
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
              <CardTitle>Team requests</CardTitle>
              <CardDescription>
                Leave, corrections, shift swaps and attendance fixes from your team, in one list.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {managerQueue?.items.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <CheckCircle2 className="h-8 w-8 mx-auto text-good mb-2" />
                  Nothing from your team is waiting on you.
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
                          {formatDate(item.submitted_at)}
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
        <Modal
          open
          onClose={() => setCorrectionModal(false)}
          size="lg"
          title="Request a change to your record"
          description="Address, telephone and bank details are checked by HR before payroll uses them."
          footer={
            <>
              <Button type="button" variant="outline" onClick={() => setCorrectionModal(false)}>
                Cancel
              </Button>
              <Button type="submit" form="correction-form">
                Submit request
              </Button>
            </>
          }
        >
            <form id="correction-form" onSubmit={handleCorrectionSubmit} className="space-y-3">
              <ModalColumns>
                <div>
                  <Label>Phone</Label>
                  <Input value={corrPhone} onChange={(e) => setCorrPhone(e.target.value)} required />
                </div>
                <div>
                  <Label>Personal email</Label>
                  <Input value={corrEmail} onChange={(e) => setCorrEmail(e.target.value)} />
                </div>
                <div>
                  <Label>Bank name</Label>
                  <Input value={corrBankName} onChange={(e) => setCorrBankName(e.target.value)} />
                </div>
                <div>
                  <Label>Bank account number</Label>
                  <Input value={corrAccountNo} onChange={(e) => setCorrAccountNo(e.target.value)} />
                </div>
              </ModalColumns>
              <div>
                <Label>Address</Label>
                <Input value={corrAddress} onChange={(e) => setCorrAddress(e.target.value)} />
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
            </form>
        </Modal>
      )}

      {/* Modal: Propose Shift Swap */}
      {swapModal && (
        <Modal
          open
          onClose={() => setSwapModal(false)}
          size="lg"
          title="Propose a shift swap"
          description="Your colleague accepts first, then your manager signs it off."
          footer={
            <>
              <Button type="button" variant="outline" onClick={() => setSwapModal(false)}>
                Cancel
              </Button>
              <Button type="submit" form="swap-form">
                Send proposal
              </Button>
            </>
          }
        >
            <form id="swap-form" onSubmit={handleSwapSubmit} className="space-y-3">
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
            </form>
        </Modal>
      )}

      {/* Modal: Apply Leave */}
      {leaveModal && (
        <Modal
          open
          onClose={() => setLeaveModal(false)}
          size="lg"
          title="Apply for leave"
          description="Working days are counted against public holidays."
          footer={
            <>
              <Button type="button" variant="outline" onClick={() => setLeaveModal(false)}>
                Cancel
              </Button>
              <Button type="submit" form="leave-form">
                Submit application
              </Button>
            </>
          }
        >
            <form id="leave-form" onSubmit={handleLeaveSubmit} className="space-y-3">
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
              <ModalColumns>
                <div>
                  <Label>Start date</Label>
                  <Input type="date" value={leaveStarts} onChange={(e) => setLeaveStarts(e.target.value)} required />
                </div>
                <div>
                  <Label>End date</Label>
                  <Input type="date" value={leaveEnds} onChange={(e) => setLeaveEnds(e.target.value)} required />
                </div>
              </ModalColumns>
              <div>
                <Label>Reason</Label>
                <Textarea
                  value={leaveReason}
                  onChange={(e) => setLeaveReason(e.target.value)}
                  placeholder="State the reason for leave"
                  required
                />
              </div>
            </form>
        </Modal>
      )}

      {/* Modal: Regularise Attendance */}
      {regModal && (
        <Modal
          open
          onClose={() => setRegModal(null)}
          size="lg"
          title="Correct an attendance record"
          description="The corrected times and why the mark was missed. Your manager approves it."
          footer={
            <>
              <Button type="button" variant="outline" onClick={() => setRegModal(null)}>
                Cancel
              </Button>
              <Button type="submit" form="regularise-form">
                Submit correction
              </Button>
            </>
          }
        >
            <form id="regularise-form" onSubmit={handleRegularise} className="space-y-3">
              <ModalColumns>
                <div>
                  <Label>Checked in at</Label>
                  <Input
                    type="datetime-local"
                    value={regInTime ? regInTime.slice(0, 16) : ""}
                    onChange={(e) => setRegInTime(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Checked out at</Label>
                  <Input
                    type="datetime-local"
                    value={regOutTime ? regOutTime.slice(0, 16) : ""}
                    onChange={(e) => setRegOutTime(e.target.value)}
                  />
                </div>
              </ModalColumns>
              <div>
                <Label>Reason</Label>
                <Textarea
                  value={regReason}
                  onChange={(e) => setRegReason(e.target.value)}
                  placeholder="e.g. Card scanner offline during morning handover"
                  required
                />
              </div>
            </form>
        </Modal>
      )}

      {/* Modal: Printable Payslip Document */}
      {payslipModal && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4 overflow-y-auto">
          <div className="w-full max-w-2xl bg-white text-foreground rounded-xl shadow-2xl p-8 space-y-6">
            <div className="flex items-center justify-between border-b pb-4">
              <div>
                <div className="text-xl font-bold text-info">{payslipModal.organization_name}</div>
                <div className="text-xs text-muted-foreground">
                  {payslipModal.facility_name} · Salary Payslip ({payslipModal.period_label})
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    // `export=html`, not `format=html` -- DRF reserves
                    // `format`, so the old URL was a 404 -- and fetched with
                    // the token rather than navigated to, because a bare
                    // window.open arrives with no Authorization header.
                    void api
                      .openPrintable(
                        `/payroll/payslips/${payslipModal.reference}/document/?export=html`,
                      )
                      .catch((problem) =>
                        setError(
                          problem instanceof ApiError
                            ? problem.message
                            : "The payslip could not be produced.",
                        ),
                      );
                  }}
                >
                  <Printer className="h-4 w-4 mr-1.5" /> Print / PDF
                </Button>
                <Button size="sm" variant="outline" onClick={() => setPayslipModal(null)}>
                  Close
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs bg-muted p-3 rounded-lg border">
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
                <div className="font-semibold text-xs uppercase tracking-wider text-muted-foreground mb-2">Earnings</div>
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
                <div className="font-semibold text-xs uppercase tracking-wider text-muted-foreground mb-2">Deductions</div>
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

            <div className="rounded-lg bg-info-subtle border border-info/40 p-4 flex justify-between items-center">
              <div>
                <div className="text-xs text-info">Net Take-Home Pay</div>
                <div className="text-xs text-muted-foreground">Credited to registered bank account</div>
              </div>
              <div className="text-2xl font-bold text-info">
                NPR {payslipModal.net_pay}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
