"""Domain services for ward nursing: assignments, NEWS2 deterioration scoring,
eMAR administration, SBAR handovers, and shift tasks.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.encounters.models import Encounter, VitalSigns
from apps.inpatient.models import (
    AdministrationStatus,
    Admission,
    Bed,
    CodeStatusChoice,
    MedicationAdministration,
    NurseAssignment,
    NurseRole,
    NursingHandover,
    NursingRound,
    NursingTask,
    ShiftChoice,
    TaskCategory,
    TaskStatus,
    Ward,
)
from apps.prescriptions.models import PrescriptionLine, PrescriptionLineStatus


# ---------------------------------------------------------------------------
# Shift helpers
# ---------------------------------------------------------------------------


def get_current_shift(now: Optional[datetime] = None) -> str:
    """Determine shift based on local hour (07:00-15:00 morning, 15:00-23:00 evening, 23:00-07:00 night)."""
    current_time = now or timezone.localtime(timezone.now())
    hour = current_time.hour
    if 7 <= hour < 15:
        return ShiftChoice.MORNING
    elif 15 <= hour < 23:
        return ShiftChoice.EVENING
    else:
        return ShiftChoice.NIGHT


# ---------------------------------------------------------------------------
# National Early Warning Score 2 (NEWS2) Calculator
# ---------------------------------------------------------------------------


def _numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_news2(vitals: Any) -> Dict[str, Any]:
    """Calculate the Royal College of Physicians NEWS2 score for a set of vitals.

    Parameters scored:
      1. Respiration rate (bpm)
      2. SpO2 scale 1 (%)
      3. Air or Oxygen (room air vs supplemental O2)
      4. Systolic blood pressure (mmHg)
      5. Pulse / Heart rate (bpm)
      6. Consciousness (Alert vs CVPU / GCS < 15)
      7. Temperature (°C)

    Returns score, risk level, triggers, and clinical recommendation.
    """
    if vitals is None:
        return {
            "score": 0,
            "risk_level": "low",
            "color": "green",
            "recommendation": "No observations recorded.",
            "triggers": [],
            "single_param_extreme": False,
        }

    # Extract values whether `vitals` is a VitalSigns model or a dict
    def get_val(name: str):
        if hasattr(vitals, name):
            return getattr(vitals, name)
        elif isinstance(vitals, dict):
            return vitals.get(name)
        return None

    triggers: List[Dict[str, Any]] = []
    total_score = 0
    single_param_extreme = False

    # 1. Respiration Rate
    rr = _numeric(get_val("respiratory_rate"))
    if rr is not None:
        pts = 0
        if rr <= 8:
            pts = 3
        elif 9 <= rr <= 11:
            pts = 1
        elif 12 <= rr <= 20:
            pts = 0
        elif 21 <= rr <= 24:
            pts = 2
        elif rr >= 25:
            pts = 3

        if pts > 0:
            total_score += pts
            if pts == 3:
                single_param_extreme = True
            triggers.append({"parameter": "Respiration rate", "score": pts, "value": f"{int(rr)} bpm"})

    # 2. Oxygen Saturation (SpO2 Scale 1)
    spo2 = _numeric(get_val("spo2_percent"))
    if spo2 is not None:
        pts = 0
        if spo2 <= 91:
            pts = 3
        elif 92 <= spo2 <= 93:
            pts = 2
        elif 94 <= spo2 <= 95:
            pts = 1
        elif spo2 >= 96:
            pts = 0

        if pts > 0:
            total_score += pts
            if pts == 3:
                single_param_extreme = True
            triggers.append({"parameter": "SpO2", "score": pts, "value": f"{int(spo2)}%"})

    # 3. Supplemental Oxygen
    on_room_air = get_val("on_room_air")
    oxygen_flow = _numeric(get_val("oxygen_flow_lpm"))
    is_supplemental = False
    if on_room_air is False or (oxygen_flow is not None and oxygen_flow > 0):
        is_supplemental = True

    if is_supplemental:
        total_score += 2
        triggers.append({"parameter": "Air or Oxygen", "score": 2, "value": "Supplemental O2"})

    # 4. Systolic Blood Pressure
    sbp = _numeric(get_val("systolic_bp"))
    if sbp is not None:
        pts = 0
        if sbp <= 90:
            pts = 3
        elif 91 <= sbp <= 100:
            pts = 2
        elif 101 <= sbp <= 110:
            pts = 1
        elif 111 <= sbp <= 219:
            pts = 0
        elif sbp >= 220:
            pts = 3

        if pts > 0:
            total_score += pts
            if pts == 3:
                single_param_extreme = True
            triggers.append({"parameter": "Systolic BP", "score": pts, "value": f"{int(sbp)} mmHg"})

    # 5. Pulse / Heart Rate
    hr = _numeric(get_val("pulse_bpm"))
    if hr is not None:
        pts = 0
        if hr <= 40:
            pts = 3
        elif 41 <= hr <= 50:
            pts = 1
        elif 51 <= hr <= 90:
            pts = 0
        elif 91 <= hr <= 110:
            pts = 1
        elif 111 <= hr <= 130:
            pts = 2
        elif hr >= 131:
            pts = 3

        if pts > 0:
            total_score += pts
            if pts == 3:
                single_param_extreme = True
            triggers.append({"parameter": "Pulse", "score": pts, "value": f"{int(hr)} bpm"})

    # 6. Consciousness (Alert vs CVPU / GCS)
    gcs = _numeric(get_val("gcs_total"))
    if gcs is not None and gcs < 15:
        total_score += 3
        single_param_extreme = True
        triggers.append({"parameter": "Consciousness", "score": 3, "value": f"GCS {int(gcs)} / CVPU"})

    # 7. Temperature
    temp = _numeric(get_val("temperature_c"))
    if temp is not None:
        pts = 0
        if temp <= 35.0:
            pts = 3
        elif 35.1 <= temp <= 36.0:
            pts = 1
        elif 36.1 <= temp <= 38.0:
            pts = 0
        elif 38.1 <= temp <= 39.0:
            pts = 1
        elif temp >= 39.1:
            pts = 2

        if pts > 0:
            total_score += pts
            if pts == 3:
                single_param_extreme = True
            triggers.append({"parameter": "Temperature", "score": pts, "value": f"{temp:.1f}°C"})

    # Risk category & Clinical Recommendation
    if total_score >= 7:
        risk_level = "high"
        color = "red"
        recommendation = "EMERGENCY: Immediate clinical / critical care review; continuous vital monitoring."
    elif total_score in (5, 6) or single_param_extreme:
        risk_level = "medium"
        color = "amber"
        recommendation = "URGENT: Clinician review within 1 hour; increase monitoring to minimum hourly."
    else:
        risk_level = "low"
        color = "green"
        recommendation = "Routine ward observation; monitor minimum every 4 to 6 hours."

    return {
        "score": total_score,
        "risk_level": risk_level,
        "color": color,
        "recommendation": recommendation,
        "triggers": triggers,
        "single_param_extreme": single_param_extreme,
    }


# ---------------------------------------------------------------------------
# Bedside Rounds & Vitals Recording
# ---------------------------------------------------------------------------


@transaction.atomic
def record_bedside_round(
    admission: Admission,
    actor: Any,
    temperature_c: Optional[Any] = None,
    pulse_bpm: Optional[int] = None,
    respiratory_rate: Optional[int] = None,
    systolic_bp: Optional[int] = None,
    diastolic_bp: Optional[int] = None,
    spo2_percent: Optional[int] = None,
    on_room_air: bool = True,
    oxygen_flow_lpm: Optional[Any] = None,
    blood_glucose_mmol: Optional[Any] = None,
    pain_score: Optional[int] = None,
    gcs_total: Optional[int] = None,
    intake_ml: int = 0,
    output_ml: int = 0,
    shift: str = "",
    observations: str = "",
    interventions: str = "",
    escalated: bool = False,
    escalation_reason: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Record a bedside vital sign set and nursing observation round together.

    Ensures the vital signs record is linked to the admission's encounter and
    computes the real-time NEWS2 score.
    """
    shift = shift or get_current_shift()
    encounter = admission.encounter

    # 1. Create VitalSigns on encounter if encounter exists
    vital_signs = None
    if encounter:
        vital_signs = VitalSigns.objects.create(
            encounter=encounter,
            recorded_at=timezone.now(),
            recorded_by_id=actor.uuid,
            recorded_by_name=getattr(actor, "full_name", str(actor)),
            temperature_c=temperature_c,
            pulse_bpm=pulse_bpm,
            respiratory_rate=respiratory_rate,
            systolic_bp=systolic_bp,
            diastolic_bp=diastolic_bp,
            spo2_percent=spo2_percent,
            on_room_air=on_room_air,
            oxygen_flow_lpm=oxygen_flow_lpm,
            blood_glucose_mmol=blood_glucose_mmol,
            pain_score=pain_score,
            gcs_total=gcs_total,
            notes=notes,
        )

    # 2. Compute NEWS2
    news2 = calculate_news2(vital_signs)
    if news2["risk_level"] == "high" and not escalated:
        # Prompt escalation notice if score is high
        escalated = True
        escalation_reason = escalation_reason or f"Auto-escalated: NEWS2 score {news2['score']} ({news2['risk_level'].upper()})"

    # 3. Create NursingRound
    round_obj = NursingRound.objects.create(
        admission=admission,
        recorded_at=timezone.now(),
        shift=shift,
        nurse_id=actor.uuid,
        nurse_name=getattr(actor, "full_name", str(actor)),
        intake_ml=intake_ml,
        output_ml=output_ml,
        pain_score=pain_score,
        observations=observations,
        interventions=interventions,
        escalated=escalated,
        escalation_reason=escalation_reason,
    )

    return {
        "round_uuid": str(round_obj.uuid),
        "recorded_at": round_obj.recorded_at.isoformat(),
        "shift": round_obj.shift,
        "nurse_name": round_obj.nurse_name,
        "intake_ml": round_obj.intake_ml,
        "output_ml": round_obj.output_ml,
        "balance_ml": round_obj.balance_ml,
        "pain_score": round_obj.pain_score,
        "escalated": round_obj.escalated,
        "escalation_reason": round_obj.escalation_reason,
        "news2": news2,
    }


# ---------------------------------------------------------------------------
# Nurse Assignment Services
# ---------------------------------------------------------------------------


def assign_nurse(
    ward: Ward,
    nurse_id: Any,
    nurse_name: str,
    assigned_date: date,
    shift: str,
    admission: Optional[Admission] = None,
    bed: Optional[Bed] = None,
    role: str = NurseRole.PRIMARY,
    notes: str = "",
    actor: Optional[Any] = None,
) -> NurseAssignment:
    """Assign a duty nurse to a ward bed/admission for a shift."""
    if not admission and not bed:
        raise ValidationError("Either an admission or a bed must be provided.")

    if not admission and bed and bed.current_assignment:
        admission = bed.current_assignment.admission

    if not bed and admission and admission.current_bed:
        bed = admission.current_bed

    # Deactivate existing active assignment for this specific admission/bed/shift/role
    filter_kwargs = {
        "ward": ward,
        "assigned_date": assigned_date,
        "shift": shift,
        "role": role,
        "is_active": True,
    }
    if admission:
        filter_kwargs["admission"] = admission
    elif bed:
        filter_kwargs["bed"] = bed

    NurseAssignment.objects.filter(**filter_kwargs).update(is_active=False)

    assignment = NurseAssignment.objects.create(
        ward=ward,
        admission=admission,
        bed=bed,
        nurse_id=nurse_id,
        nurse_name=nurse_name,
        assigned_date=assigned_date,
        shift=shift,
        role=role,
        notes=notes,
        assigned_by_id=actor.uuid if actor else None,
        assigned_by_name=getattr(actor, "full_name", str(actor)) if actor else "",
    )
    return assignment


# ---------------------------------------------------------------------------
# eMAR (Electronic Medication Administration Record)
# ---------------------------------------------------------------------------


def get_patient_emar(admission: Admission) -> Dict[str, Any]:
    """Retrieve the eMAR schedule and past administrations for an admission."""
    encounter = admission.encounter
    if not encounter:
        return {"active_lines": [], "administrations": []}

    # Fetch active prescription lines
    lines = (
        PrescriptionLine.objects.filter(
            prescription__encounter=encounter,
            status=PrescriptionLineStatus.ACTIVE,
        )
        .select_related("prescription")
        .order_by("display_order", "generic_name")
    )

    # Fetch administrations in the last 48 hours
    since = timezone.now() - timedelta(hours=48)
    administrations = (
        MedicationAdministration.objects.filter(
            admission=admission,
            administered_at__gte=since,
        )
        .select_related("prescription_line")
        .order_by("-administered_at")
    )

    administrations_data = [
        {
            "uuid": str(adm.uuid),
            "prescription_line": str(adm.prescription_line.uuid),
            "medicine_name": adm.medicine_name,
            "scheduled_time": adm.scheduled_time.isoformat(),
            "administered_at": adm.administered_at.isoformat(),
            "administered_by_name": adm.administered_by_name,
            "dose_given": adm.dose_given,
            "route": adm.route,
            "status": adm.status,
            "reason": adm.reason,
            "injection_site": adm.injection_site,
            "witness_by_name": adm.witness_by_name,
            "notes": adm.notes,
        }
        for adm in administrations
    ]

    lines_data = []
    for line in lines:
        line_adms = [a for a in administrations_data if a["prescription_line"] == str(line.uuid)]
        last_adm = line_adms[0] if line_adms else None

        lines_data.append(
            {
                "uuid": str(line.uuid),
                "generic_name": line.generic_name,
                "brand_name": line.brand_name,
                "display_name": line.display_name,
                "dose": line.dose,
                "route": line.route,
                "route_display": line.get_route_display(),
                "frequency": line.frequency,
                "frequency_display": line.get_frequency_display(),
                "instructions": line.instructions,
                "is_prn": line.is_prn,
                "prn_indication": line.prn_indication,
                "max_doses_per_day": line.max_doses_per_day,
                "start_date": line.start_date.isoformat() if line.start_date else None,
                "end_date": line.end_date.isoformat() if line.end_date else None,
                "last_administered": last_adm,
                "history": line_adms,
            }
        )

    return {
        "admission_reference": admission.reference,
        "patient_name": admission.patient.full_name,
        "lines": lines_data,
        "administrations": administrations_data,
    }


@transaction.atomic
def administer_medication(
    prescription_line: PrescriptionLine,
    admission: Admission,
    actor: Any,
    status: str = AdministrationStatus.GIVEN,
    dose_given: str = "",
    route: str = "",
    scheduled_time: Optional[datetime] = None,
    reason: str = "",
    injection_site: str = "",
    witness_id: Optional[Any] = None,
    witness_name: str = "",
    notes: str = "",
) -> MedicationAdministration:
    """Record administration, withholding, or refusal of a medication."""
    if status in (AdministrationStatus.HELD, AdministrationStatus.REFUSED, AdministrationStatus.OMITTED):
        if not reason.strip():
            raise ValidationError(f"A mandatory clinical reason is required when status is '{status}'.")

    scheduled = scheduled_time or timezone.now()
    dose = dose_given.strip() or prescription_line.dose
    r = route.strip() or prescription_line.route

    admin = MedicationAdministration.objects.create(
        admission=admission,
        encounter=admission.encounter,
        prescription_line=prescription_line,
        medicine_name=prescription_line.display_name,
        scheduled_time=scheduled,
        administered_at=timezone.now(),
        administered_by_id=actor.uuid,
        administered_by_name=getattr(actor, "full_name", str(actor)),
        dose_given=dose,
        route=r,
        status=status,
        reason=reason.strip(),
        injection_site=injection_site.strip(),
        witness_by_id=witness_id,
        witness_by_name=witness_name.strip(),
        notes=notes.strip(),
    )
    return admin


# ---------------------------------------------------------------------------
# SBAR Shift Handover Services
# ---------------------------------------------------------------------------


def create_sbar_handover(
    admission: Admission,
    outgoing_nurse: Any,
    situation: str,
    assessment: str,
    recommendation: str,
    background: str = "",
    shift: str = "",
    shift_date: Optional[date] = None,
    code_status: str = CodeStatusChoice.FULL_CODE,
) -> NursingHandover:
    """Create a structured SBAR shift handover note."""
    shift = shift or get_current_shift()
    s_date = shift_date or timezone.localdate()
    ward = admission.current_bed.ward if admission.current_bed else admission.facility.wards.first()
    if not ward:
        raise ValidationError("Admission has no assigned ward.")

    handover = NursingHandover.objects.create(
        admission=admission,
        ward=ward,
        shift_date=s_date,
        shift=shift,
        outgoing_nurse_id=outgoing_nurse.uuid,
        outgoing_nurse_name=getattr(outgoing_nurse, "full_name", str(outgoing_nurse)),
        code_status=code_status,
        situation=situation.strip(),
        background=background.strip(),
        assessment=assessment.strip(),
        recommendation=recommendation.strip(),
    )
    return handover


def acknowledge_handover(
    handover: NursingHandover,
    incoming_nurse: Any,
) -> NursingHandover:
    """Sign-off and acknowledge handover by the incoming duty nurse."""
    handover.is_acknowledged = True
    handover.incoming_nurse_id = incoming_nurse.uuid
    handover.incoming_nurse_name = getattr(incoming_nurse, "full_name", str(incoming_nurse))
    handover.acknowledged_at = timezone.now()
    handover.save(update_fields=["is_acknowledged", "incoming_nurse_id", "incoming_nurse_name", "acknowledged_at", "updated_at"])
    return handover


# ---------------------------------------------------------------------------
# Nursing Tasks Services
# ---------------------------------------------------------------------------


def create_nursing_task(
    admission: Admission,
    title: str,
    category: str = TaskCategory.GENERAL,
    shift: str = "",
    due_at: Optional[datetime] = None,
    notes: str = "",
) -> NursingTask:
    ward = admission.current_bed.ward if admission.current_bed else admission.facility.wards.first()
    if not ward:
        raise ValidationError("Admission has no assigned ward.")

    task = NursingTask.objects.create(
        admission=admission,
        ward=ward,
        title=title.strip(),
        category=category,
        shift=shift,
        due_at=due_at,
        notes=notes.strip(),
    )
    return task


def complete_nursing_task(
    task: NursingTask,
    actor: Any,
    notes: str = "",
) -> NursingTask:
    task.status = TaskStatus.COMPLETED
    task.completed_at = timezone.now()
    task.completed_by_id = actor.uuid
    task.completed_by_name = getattr(actor, "full_name", str(actor))
    if notes:
        task.notes = f"{task.notes}\n{notes}".strip()
    task.save(update_fields=["status", "completed_at", "completed_by_id", "completed_by_name", "notes", "updated_at"])
    return task


# ---------------------------------------------------------------------------
# Nurse Workspace Aggregator
# ---------------------------------------------------------------------------


def get_nurse_workspace_summary(
    actor: Any,
    facility: Any,
    ward_id: Optional[str] = None,
    target_date: Optional[date] = None,
    target_shift: Optional[str] = None,
    scope: str = "mine",
) -> Dict[str, Any]:
    """Aggregate live clinical census, NEWS2 alerts, medications due, and tasks

    for the signed-in nurse.
    """
    shift = target_shift or get_current_shift()
    s_date = target_date or timezone.localdate()

    # Query in-house admissions
    admissions_qs = (
        Admission.objects.filter(
            facility=facility,
            status__in=["admitted", "discharge_initiated"],
        )
        .select_related("patient", "encounter")
        .prefetch_related("bed_assignments__bed__ward", "rounds")
    )

    if ward_id:
        admissions_qs = admissions_qs.filter(
            bed_assignments__vacated_at__isnull=True,
            bed_assignments__ward__uuid=ward_id,
        )

    # Check nurse assignments
    nurse_uuid = getattr(actor, "uuid", None)
    my_assignments = {}
    if nurse_uuid:
        assignments = NurseAssignment.objects.filter(
            nurse_id=nurse_uuid,
            assigned_date=s_date,
            shift=shift,
            is_active=True,
        ).select_related("admission", "bed")
        for a in assignments:
            if a.admission_id:
                my_assignments[a.admission_id] = a
            elif a.bed_id and a.bed.current_assignment:
                my_assignments[a.bed.current_assignment.admission_id] = a

    patients_list = []
    admissions = list(admissions_qs.order_by("admitted_at"))

    for adm in admissions:
        bed = adm.current_bed
        ward = bed.ward if bed else None
        is_mine = adm.id in my_assignments

        if scope == "mine" and my_assignments and not is_mine:
            # If user filtered to 'mine' and has assignments, skip unassigned
            continue

        # 1. Latest Vitals & NEWS2
        latest_vital = None
        if adm.encounter:
            latest_vital = adm.encounter.vitals.order_by("-recorded_at").first()

        news2 = calculate_news2(latest_vital)

        # 2. 24-hour Fluid Balance
        recent_rounds = [
            r for r in adm.rounds.all()
            if r.recorded_at >= timezone.now() - timedelta(hours=24)
        ]
        intake_24h = sum(r.intake_ml for r in recent_rounds)
        output_24h = sum(r.output_ml for r in recent_rounds)
        fluid_balance_24h = intake_24h - output_24h

        # 3. Active Prescriptions / eMAR Count
        active_rx_count = 0
        if adm.encounter:
            active_rx_count = PrescriptionLine.objects.filter(
                prescription__encounter=adm.encounter,
                status=PrescriptionLineStatus.ACTIVE,
            ).count()

        # Administrations today
        adms_today_count = adm.medication_administrations.filter(
            administered_at__date=s_date
        ).count()

        # 4. Nursing Tasks for shift
        tasks = adm.nursing_tasks.filter(
            status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS]
        ).order_by("due_at")
        pending_tasks_count = tasks.count()

        # 5. Latest Handover
        latest_handover = adm.handovers.order_by("-created_at").first()
        handover_data = None
        if latest_handover:
            handover_data = {
                "uuid": str(latest_handover.uuid),
                "shift": latest_handover.shift,
                "shift_date": latest_handover.shift_date.isoformat(),
                "outgoing_nurse_name": latest_handover.outgoing_nurse_name,
                "code_status": latest_handover.code_status,
                "is_acknowledged": latest_handover.is_acknowledged,
                "incoming_nurse_name": latest_handover.incoming_nurse_name,
                "situation": latest_handover.situation,
                "recommendation": latest_handover.recommendation,
            }

        # Format latest vitals snippet
        vitals_snippet = None
        if latest_vital:
            vitals_snippet = {
                "recorded_at": latest_vital.recorded_at.isoformat(),
                "bp": latest_vital.blood_pressure,
                "pulse": latest_vital.pulse_bpm,
                "rr": latest_vital.respiratory_rate,
                "spo2": latest_vital.spo2_percent,
                "temp": float(latest_vital.temperature_c) if latest_vital.temperature_c else None,
                "pain": latest_vital.pain_score,
                "flags": latest_vital.abnormal_flags(),
            }

        patients_list.append(
            {
                "admission_uuid": str(adm.uuid),
                "admission_reference": adm.reference,
                "patient_uuid": str(adm.patient.uuid),
                "patient_name": adm.patient.full_name,
                "patient_mrn": adm.patient.mrn,
                "patient_age": adm.patient.age_display if hasattr(adm.patient, "age_display") else "",
                "patient_gender": adm.patient.gender,
                "admitted_at": adm.admitted_at.isoformat(),
                "length_of_stay_days": adm.length_of_stay_days,
                "admitting_diagnosis": adm.admitting_diagnosis,
                "consultant_name": adm.consultant_name,
                "bed_code": str(bed) if bed else "No bed",
                "ward_name": ward.name if ward else "Unassigned",
                "ward_uuid": str(ward.uuid) if ward else None,
                "is_mine": is_mine,
                "assigned_nurse_role": my_assignments[adm.id].role if is_mine else None,
                "news2": news2,
                "vitals": vitals_snippet,
                "fluid_balance_24h": {
                    "intake_ml": intake_24h,
                    "output_ml": output_24h,
                    "net_ml": fluid_balance_24h,
                },
                "emar": {
                    "active_medicines": active_rx_count,
                    "administrations_today": adms_today_count,
                },
                "tasks": {
                    "pending_count": pending_tasks_count,
                },
                "handover": handover_data,
            }
        )

    # Summary statistics for the nurse's shift
    total_patients = len(patients_list)
    high_risk_count = sum(1 for p in patients_list if p["news2"]["risk_level"] == "high")
    medium_risk_count = sum(1 for p in patients_list if p["news2"]["risk_level"] == "medium")
    total_tasks_pending = sum(p["tasks"]["pending_count"] for p in patients_list)

    return {
        "shift": shift,
        "date": s_date.isoformat(),
        "scope": scope,
        "facility_name": getattr(facility, "name", ""),
        "total_patients": total_patients,
        "high_risk_count": high_risk_count,
        "medium_risk_count": medium_risk_count,
        "total_tasks_pending": total_tasks_pending,
        "patients": patients_list,
    }
