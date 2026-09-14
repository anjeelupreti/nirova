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
        """
        from django.db.models.signals import post_delete, post_save

        from apps.inpatient.models import Bed, BedAssignment
        from apps.notifications.models import NotificationReceipt
        from apps.realtime.publish import ring
        from apps.scheduling.models import QueueToken

        def facility_uuid(facility_id) -> str:
            from apps.organization.models import Facility

            row = Facility.objects.filter(pk=facility_id).values_list("uuid", flat=True).first()
            return str(row) if row else ""

        def queue_changed(sender, instance, **kwargs):
            uuid = facility_uuid(instance.facility_id)
            if uuid:
                ring(f"queue.{uuid}")

        def bed_changed(sender, instance, **kwargs):
            ward = getattr(instance, "ward", None)
            uuid = facility_uuid(getattr(ward, "facility_id", None)) if ward else ""
            if uuid:
                ring(f"beds.{uuid}")

        def notification_arrived(sender, instance, **kwargs):
            ring("notifications", user_uuid=str(instance.recipient_id))

        for signal in (post_save, post_delete):
            signal.connect(queue_changed, sender=QueueToken, weak=False)
            signal.connect(bed_changed, sender=Bed, weak=False)
            signal.connect(bed_changed, sender=BedAssignment, weak=False)
        post_save.connect(notification_arrived, sender=NotificationReceipt, weak=False)
