from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    label = "realtime"

    def ready(self):
        """Ring the doorbell wherever a live screen's data changes.

        Signals rather than calls at each service, for the same reason the
        entitlement cache is invalidated by signal: the next place that moves
        a patient into a bed would forget to ring, and the board would be two
        minutes stale exactly when a bed matters.

        One topic per board, keyed the way the board is chosen on screen: the
        queue, beds, emergency department and lab by facility, an intensive
        care unit by ward, because that is what the ICU board is opened on.
        """
        from django.db.models.signals import post_delete, post_save

        from apps.diagnostics.models import CriticalValueAlert, DiagnosticOrder, DiagnosticResult
        from apps.emergency.models import Arrival, CriticalAlert, ResuscitationEvent, TriageAssessment
        from apps.icu import models as icu
        from apps.inpatient.models import Bed, BedAssignment
        from apps.notifications.models import NotificationReceipt
        from apps.organization.models import Facility
        from apps.realtime.publish import ring
        from apps.scheduling.models import QueueToken

        def facility_uuid(facility_id) -> str:
            if not facility_id:
                return ""
            row = Facility.objects.filter(pk=facility_id).values_list("uuid", flat=True).first()
            return str(row) if row else ""

        def on_facility(prefix, facility_id):
            uuid = facility_uuid(facility_id)
            if uuid:
                ring(f"{prefix}.{uuid}")

        def queue_changed(sender, instance, **kwargs):
            on_facility("queue", instance.facility_id)

        def bed_changed(sender, instance, **kwargs):
            ward = getattr(instance, "ward", None)
            if ward:
                on_facility("beds", ward.facility_id)

        def arrival_changed(sender, instance, **kwargs):
            on_facility("ed", instance.facility_id)

        def arrival_child_changed(sender, instance, **kwargs):
            facility_id = Arrival.objects.filter(pk=instance.arrival_id).values_list(
                "facility_id", flat=True,
            ).first()
            on_facility("ed", facility_id)

        def stay_ward(stay_id) -> str:
            row = icu.IcuStay.objects.filter(pk=stay_id).values_list("ward__uuid", flat=True).first()
            return str(row) if row else ""

        def stay_changed(sender, instance, **kwargs):
            ward = stay_ward(instance.pk)
            if ward:
                ring(f"icu.{ward}")

        def stay_child_changed(sender, instance, **kwargs):
            ward = stay_ward(instance.stay_id)
            if ward:
                ring(f"icu.{ward}")

        def rate_changed(sender, instance, **kwargs):
            stay_id = icu.Infusion.objects.filter(pk=instance.infusion_id).values_list(
                "stay_id", flat=True,
            ).first()
            ward = stay_ward(stay_id) if stay_id else ""
            if ward:
                ring(f"icu.{ward}")

        def order_changed(sender, instance, **kwargs):
            on_facility("lab", instance.facility_id)

        def result_changed(sender, instance, **kwargs):
            facility_id = DiagnosticOrder.objects.filter(pk=instance.order_id).values_list(
                "facility_id", flat=True,
            ).first()
            on_facility("lab", facility_id)

        def notification_arrived(sender, instance, **kwargs):
            ring("notifications", user_uuid=str(instance.recipient_id))

        watched = [
            (QueueToken, queue_changed),
            (Bed, bed_changed),
            (BedAssignment, bed_changed),
            (Arrival, arrival_changed),
            (TriageAssessment, arrival_child_changed),
            (CriticalAlert, arrival_child_changed),
            (ResuscitationEvent, arrival_child_changed),
            (icu.IcuStay, stay_changed),
            (icu.InfusionRate, rate_changed),
            (DiagnosticOrder, order_changed),
            (DiagnosticResult, result_changed),
            (CriticalValueAlert, result_changed),
        ]
        watched += [
            (model, stay_child_changed)
            for model in (
                icu.Observation, icu.FluidEntry, icu.Infusion, icu.VentilationRecord,
                icu.InvasiveDevice, icu.Round, icu.SofaScore, icu.Alert, icu.AlertThreshold,
            )
        ]
        for model, handler in watched:
            post_save.connect(handler, sender=model, weak=False)
            post_delete.connect(handler, sender=model, weak=False)
        post_save.connect(notification_arrived, sender=NotificationReceipt, weak=False)
