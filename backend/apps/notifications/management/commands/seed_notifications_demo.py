"""The notification centre, walked through the cases that decide its shape.

Runs the real service layer and prints what it expects beside what it got, so
a contradiction shows up in the output rather than needing to be looked for.

The cases that matter are the ones where a naive implementation is wrong: one
event told to several people is one row and several read states; read and
dismissed are different acts; an hourly sweep must not build a pile; a critical
alert cannot be switched off by a preference or swiped away without a word.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.identity.models import Membership, MembershipStatus
from apps.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationReceipt,
)
from apps.notifications.services import (
    NotificationError,
    dismiss,
    expire_stale,
    inbox,
    mark_all_read,
    mark_read,
    notify,
    preferences_for,
    resolve,
    resolve_by_key,
    set_preference,
    summary,
)
from apps.organization.models import Facility
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Organization


class Command(BaseCommand):
    help = "Demonstrate and verify the notification centre (§101)."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="manakamana")

    def handle(self, *args, **options):
        organization = Organization.objects.get(slug=options["organization"])
        with tenant_context(context_for_organization(organization)):
            self._run(organization)

    # -- helpers ---------------------------------------------------------

    def say(self, text=""):
        self.stdout.write(text)

    def expect(self, label, got, expected):
        """Print both numbers side by side and fail loudly if they differ."""
        ok = got == expected
        mark = "ok " if ok else "XX "
        line = f"   {mark}{label}: expected {expected}, got {got}"
        self.stdout.write(
            line if ok else self.style.ERROR(line)
        )
        if not ok:
            raise AssertionError(line)

    def _run(self, organization):
        self.say()
        self.say("--- §101 Notification centre ---")

        facility = Facility.objects.first()

        # A clean slate for this scenario only. The seed must be re-runnable:
        # four seeds in this project were found to work exactly once, and they
        # are the mechanism everything else is verified with.
        Notification.objects.filter(source="seed_demo").delete()

        people = [
            {"id": m.user.uuid,
             "name": getattr(m.user, "full_name", "") or m.user.email,
             "reason": "On the ward this shift"}
            for m in Membership.objects.filter(
                organization=organization, status=MembershipStatus.ACTIVE,
            ).select_related("user")[:3]
        ]
        if len(people) < 2:
            self.say("   needs at least two members; run seed_demo first")
            return
        first, second = people[0], people[1]
        self.say(f"   telling {len(people)} people, first is {first['name']}")

        # 1 -------------------------------------------------------------
        self.say()
        self.say("1. One event, several people")
        critical = notify(
            source="seed_demo", event="critical_value",
            category=NotificationCategory.CRITICAL,
            title="Potassium 6.8 mmol/L — bed 12",
            body="Above the critical threshold. Ring the ward.",
            link="/diagnostics", recipients=people, facility=facility,
            actor_name="Laboratory",
        )
        self.expect("notifications created", Notification.objects.filter(
            source="seed_demo", event="critical_value").count(), 1)
        self.expect("receipts created", critical.receipts.count(), len(people))
        self.say("   One fact, three read states. Storing it three times would make")
        self.say("   'how many were told' indistinguishable from 'it happened thrice',")
        self.say("   and the second is the question asked after somebody dies.")

        # 2 -------------------------------------------------------------
        self.say()
        self.say("2. Read is not dismissed")
        receipt = NotificationReceipt.objects.get(
            notification=critical, recipient_id=first["id"])
        mark_read(receipt)
        receipt.refresh_from_db()
        self.expect("read", receipt.read_at is not None, True)
        self.expect("still outstanding", receipt.dismissed_at is None, True)
        # Asserted against this scenario's own rows, not the global count.
        # The first version checked `summary()["critical"] == 1` and started
        # failing the moment the diagnostics module began raising real
        # critical notifications for the same person -- the assertion was
        # measuring the whole tenant while claiming to measure one event.
        outstanding = [
            row for row in inbox(first["id"], outstanding_only=True)
            if row.notification_id == critical.id
        ]
        self.expect("this notification still waiting on them", len(outstanding), 1)
        counts = summary(first["id"])
        self.say(f"   their critical count across the tenant: {counts['critical']}")
        self.say("   Read means seen. It is still on their list, because nothing")
        self.say("   has been done about it yet.")

        # 3 -------------------------------------------------------------
        self.say()
        self.say("3. A critical notification cannot be cleared without a word")
        try:
            dismiss(receipt, note="")
            raise AssertionError("dismissed a critical notification with no note")
        except NotificationError as exc:
            self.say(f"   refused: {exc.message}")
        dismiss(receipt, note="Rang Dr Sharma at 14:20, insulin-dextrose started.")
        receipt.refresh_from_db()
        self.expect("now dismissed", receipt.dismissed_at is not None, True)
        self.say("   An alert that can be swiped away silently is a record that")
        self.say("   somebody silenced it, which is worse than no record.")

        # 4 -------------------------------------------------------------
        self.say()
        self.say("4. Dismissing is one person's act, not everybody's")
        other = NotificationReceipt.objects.get(
            notification=critical, recipient_id=second["id"])
        self.expect("second person still outstanding", other.dismissed_at is None, True)
        self.expect("notification itself still open", critical.is_open, True)
        self.say("   One nurse acting does not clear the ward's list, and the")
        self.say("   underlying result is still abnormal either way.")

        # 5 -------------------------------------------------------------
        self.say()
        self.say("5. An hourly sweep must not build a pile")
        for _ in range(12):
            notify(
                source="seed_demo", event="licence_expiring",
                category=NotificationCategory.REMINDER,
                title="NMC registration expires in 21 days",
                recipients=[first], dedupe_key="seed:licence:EMP-0001",
            )
        self.expect("rows after twelve sweeps", Notification.objects.filter(
            source="seed_demo", event="licence_expiring").count(), 1)
        self.say("   Twelve runs, one notification. Without the key this is how a")
        self.say("   reminder becomes something people scroll past.")

        # 6 -------------------------------------------------------------
        self.say()
        self.say("6. The situation clearing is what removes it")
        resolve_by_key("seed:licence:EMP-0001", reason="Registration renewed")
        notify(
            source="seed_demo", event="licence_expiring",
            category=NotificationCategory.REMINDER,
            title="NMC registration expires in 21 days",
            recipients=[first], dedupe_key="seed:licence:EMP-0001",
        )
        self.expect("a new one may now be raised", Notification.objects.filter(
            source="seed_demo", event="licence_expiring").count(), 2)
        self.say("   The key is unique among *open* notifications, so the history")
        self.say("   of 'this fired every week for a month' stays countable.")

        # 7 -------------------------------------------------------------
        self.say()
        self.say("7. A preference quietens; it cannot silence a critical one")
        set_preference(second["id"], NotificationCategory.INFORMATION, enabled=False)
        notify(
            source="seed_demo", event="canteen", title="Canteen closes at 6 today",
            category=NotificationCategory.INFORMATION, recipients=[second],
        )
        info = Notification.objects.get(source="seed_demo", event="canteen")
        self.expect("receipts for someone who opted out", info.receipts.count(), 0)
        try:
            set_preference(second["id"], NotificationCategory.CRITICAL, enabled=False)
            raise AssertionError("stored a preference that would be ignored")
        except NotificationError as exc:
            self.say(f"   refused: {exc.message}")
        prefs = {p["category"]: p for p in preferences_for(second["id"])}
        self.expect("critical shown as unchangeable",
                   prefs[NotificationCategory.CRITICAL]["can_change"], False)
        self.say("   Storing an unenforceable preference is worse than refusing it:")
        self.say("   the screen would say something is off while it is on.")

        # 8 -------------------------------------------------------------
        self.say()
        self.say("8. Clearing the badge is not doing the work")
        notify(source="seed_demo", event="approval_waiting",
               category=NotificationCategory.APPROVAL,
               title="Purchase order PO-0042 needs approval",
               recipients=[first])
        before = summary(first["id"])
        mark_all_read(first["id"])
        after = summary(first["id"])
        self.expect("unread after mark-all-read", after["unread"], 0)
        self.expect("outstanding unchanged", after["outstanding"], before["outstanding"])
        self.say("   Catching up on a morning's notifications has not approved")
        self.say("   anything. A 'mark all read' that emptied the approvals queue")
        self.say("   would be a disaster dressed as a convenience.")

        # 9 -------------------------------------------------------------
        self.say()
        self.say("9. Ageing out the news, keeping the work")
        old = notify(source="seed_demo", event="stale_news",
                     category=NotificationCategory.INFORMATION,
                     title="Old notice", recipients=[first])
        Notification.objects.filter(pk=old.pk).update(
            raised_at=timezone.now() - timezone.timedelta(days=200))
        aged = expire_stale(older_than_days=90)
        self.say(f"   aged out: {aged}")
        approval = Notification.objects.get(
            source="seed_demo", event="approval_waiting")
        self.expect("the approval survived", approval.is_open, True)
        self.say("   An approval nobody has touched in ninety days is not stale —")
        self.say("   it is the most interesting thing in the system.")

        # 10 ------------------------------------------------------------
        self.say()
        self.say("10. What is waiting for me")
        counts = summary(first["id"])
        rows = inbox(first["id"], outstanding_only=True)
        self.say(f"   unread {counts['unread']} | outstanding {counts['outstanding']}"
                 f" | needs action {counts['needs_action']}")
        for row in rows:
            self.say(f"     [{row.notification.category}] {row.notification.title}")
        self.expect("outstanding count matches the list", counts["outstanding"], len(rows))
        self.say("   Counted from the receipts every time. A stored unread count is")
        self.say("   wrong the first time two requests race, and a badge showing 3")
        self.say("   when the answer is 4 looks exactly like a badge.")

        self.say()
        self.say(self.style.SUCCESS("Notification centre verified."))
