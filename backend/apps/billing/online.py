"""Paying an invoice online: from a button to a receipt.

`start` opens an attempt and returns what the payer's browser needs — a URL
for Khalti, a signed form for eSewa. `confirm` asks the provider, server to
server, what became of it, and only a provider's "completed" for the right
amount becomes a `Payment` with a receipt number. The parameters on the
redirect back are never trusted: they travel through the payer's browser.

**Idempotent, because providers and people repeat themselves.** The return
page can be reloaded, the reconciler can run while the payer is returning,
a double-click can send two confirmations. The attempt row is locked while
it is confirmed, and one that already has its `Payment` is returned as it is.

**Money that cannot be applied is flagged, not lost.** If the invoice was
settled at the counter while the payer was in their wallet, the provider has
still taken the money. The attempt is marked paid with `needs_attention` set,
and the billing screen lists it for a refund from the provider's dashboard.
"""

import logging
import uuid as uuid_lib
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.billing import gateways
from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    OnlinePayment,
    OnlinePaymentStatus,
    OnlineProvider,
)
from apps.billing.services import BillingError, record_payment
from apps.tenancy.db import tenant_atomic

logger = logging.getLogger(__name__)

FINISHED = {
    OnlinePaymentStatus.COMPLETED, OnlinePaymentStatus.CANCELLED,
    OnlinePaymentStatus.EXPIRED, OnlinePaymentStatus.FAILED, OnlinePaymentStatus.REFUNDED,
}
#: An attempt nobody finished is given up after this long.
ABANDONED_AFTER = timedelta(hours=2)


class OnlinePaymentError(BillingError):
    code = "online_payment_failed"


def gateway_config() -> dict:
    """The tenant's gateway settings, with secrets unsealed for use here only."""
    from apps.common.sealing import unseal
    from apps.organization.config import config_value

    mode = config_value("payments", "gateway_mode", default="sandbox")
    mode = mode if mode in ("sandbox", "live") else "sandbox"
    khalti_key = unseal(config_value("payments", "khalti_secret_key", default=""))
    esewa_code = str(config_value("payments", "esewa_merchant_code", default="") or "")
    esewa_secret = unseal(config_value("payments", "esewa_secret_key", default=""))
    if mode == "sandbox" and not (esewa_code and esewa_secret):
        esewa_code, esewa_secret = gateways.ESEWA_TEST_MERCHANT
    return {
        "mode": mode,
        "khalti_key": khalti_key,
        "esewa_code": esewa_code,
        "esewa_secret": esewa_secret,
    }


def available_providers() -> list[dict]:
    """What a payer may choose, and whether it is the test system."""
    config = gateway_config()
    offered = []
    if config["esewa_code"] and config["esewa_secret"]:
        offered.append({"provider": OnlineProvider.ESEWA, "label": "eSewa"})
    if config["khalti_key"]:
        offered.append({"provider": OnlineProvider.KHALTI, "label": "Khalti"})
    return [{**row, "test_mode": config["mode"] == "sandbox"} for row in offered]


def start(invoice: Invoice, provider: str, *, return_to: str, channel: str = "portal",
          started_by: str = "", amount=None) -> dict:
    """Open an attempt. Returns `{uuid, provider, redirect_url}` or `{…, form}`.

    `return_to` is the page the payer comes back to; `?attempt=<uuid>` is
    appended so that page knows which attempt to confirm.
    """
    if provider not in OnlineProvider.values:
        raise OnlinePaymentError("Choose eSewa or Khalti.")
    if invoice.is_credit_note or invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED):
        raise OnlinePaymentError("This invoice cannot be paid online.")
    balance = invoice.balance_due
    amount = Decimal(str(amount)).quantize(Decimal("0.01")) if amount else balance
    if balance <= 0:
        raise OnlinePaymentError(f"{invoice.number} is already paid.", code="already_paid")
    if amount <= 0 or amount > balance:
        raise OnlinePaymentError(f"Pay up to the {balance} outstanding on {invoice.number}.")

    config = gateway_config()
    if provider == OnlineProvider.KHALTI and not config["khalti_key"]:
        raise OnlinePaymentError("Khalti is not set up for this hospital.", code="provider_unavailable")
    if provider == OnlineProvider.KHALTI and amount < gateways.KHALTI_MINIMUM:
        raise OnlinePaymentError("Khalti takes payments of NPR 10 or more.")

    attempt = OnlinePayment.objects.create(
        invoice=invoice, provider=provider, amount=amount, channel=channel,
        started_by_name=started_by[:255],
        # eSewa is told our id; Khalti tells us its `pidx`, set below.
        reference=uuid_lib.uuid4().hex,
    )
    separator = "&" if "?" in return_to else "?"
    back = f"{return_to}{separator}attempt={attempt.uuid}"

    try:
        if provider == OnlineProvider.KHALTI:
            answer = gateways.khalti_initiate(
                mode=config["mode"], secret_key=config["khalti_key"], amount=amount,
                order_id=str(attempt.uuid), order_name=f"Invoice {invoice.number}",
                return_url=back, website_url=return_to.split("?")[0],
            )
            attempt.reference = answer["pidx"]
            attempt.payment_url = answer["payment_url"]
            attempt.last_response = answer
            attempt.save(update_fields=["reference", "payment_url", "last_response", "updated_at"])
            result = {"redirect_url": attempt.payment_url}
        else:
            form = gateways.esewa_form(
                mode=config["mode"], product_code=config["esewa_code"], secret=config["esewa_secret"],
                amount=amount, transaction_uuid=attempt.reference,
                success_url=back, failure_url=f"{back}&failed=1",
            )
            result = {"form": form}
    except gateways.GatewayError as error:
        attempt.status = OnlinePaymentStatus.FAILED
        attempt.last_response = {"error": str(error)}
        attempt.save(update_fields=["status", "last_response", "updated_at"])
        raise OnlinePaymentError(str(error), code="provider_refused") from error

    record(
        AuditAction.CREATE,
        entity_type="billing.OnlinePayment",
        entity_id=attempt.uuid,
        entity_label=f"{attempt.get_provider_display()} {amount} for {invoice.number}",
        metadata={"channel": channel, "mode": config["mode"]},
    )
    return {
        "uuid": str(attempt.uuid),
        "provider": provider,
        "amount": str(amount),
        "test_mode": config["mode"] == "sandbox",
        **result,
    }


def confirm(attempt: OnlinePayment, *, callback: dict | None = None) -> OnlinePayment:
    """Ask the provider what became of an attempt, and act on the answer."""
    with tenant_atomic():
        attempt = OnlinePayment.objects.select_for_update().select_related("invoice").get(pk=attempt.pk)
        if attempt.status in FINISHED:
            return attempt

        config = gateway_config()
        try:
            if attempt.provider == OnlineProvider.KHALTI:
                answer = gateways.khalti_lookup(
                    mode=config["mode"], secret_key=config["khalti_key"], pidx=attempt.reference,
                )
            else:
                if callback and callback.get("data"):
                    signed = gateways.esewa_verify_callback(config["esewa_secret"], callback["data"])
                    attempt.last_response = {"callback_signature_valid": signed is not None}
                answer = gateways.esewa_status(
                    mode=config["mode"], product_code=config["esewa_code"],
                    amount=attempt.amount, transaction_uuid=attempt.reference,
                )
        except gateways.GatewayError as error:
            # Unreachable is not refused: leave it to be checked again.
            attempt.checked_at = timezone.now()
            attempt.last_response = {**attempt.last_response, "error": str(error)}
            attempt.save(update_fields=["checked_at", "last_response", "updated_at"])
            return attempt

        attempt.checked_at = timezone.now()
        attempt.last_response = {**attempt.last_response, **answer.raw}

        if answer.status == OnlinePaymentStatus.COMPLETED:
            if answer.amount is not None and answer.amount != attempt.amount:
                # Paid, but not what was asked. Never applied automatically.
                attempt.status = OnlinePaymentStatus.COMPLETED
                attempt.needs_attention = (
                    f"{attempt.get_provider_display()} reports {answer.amount}, "
                    f"not the {attempt.amount} requested. Check and apply by hand."
                )
            else:
                _apply(attempt, answer.transaction)
        elif answer.status in (OnlinePaymentStatus.INITIATED, OnlinePaymentStatus.PENDING):
            attempt.status = answer.status
            if timezone.now() - attempt.created_at > ABANDONED_AFTER:
                attempt.status = OnlinePaymentStatus.EXPIRED
        else:
            attempt.status = answer.status

        attempt.provider_transaction = answer.transaction or attempt.provider_transaction
        if attempt.status == OnlinePaymentStatus.COMPLETED and attempt.completed_at is None:
            attempt.completed_at = timezone.now()
        attempt.save()
        return attempt


def _apply(attempt: OnlinePayment, transaction: str) -> None:
    """Turn a confirmed attempt into a receipt, or flag why it cannot be."""
    attempt.status = OnlinePaymentStatus.COMPLETED
    invoice = Invoice.objects.select_for_update().get(pk=attempt.invoice_id)
    try:
        attempt.payment = record_payment(
            invoice, attempt.amount, attempt.provider,
            reference=f"{attempt.get_provider_display()} {transaction or attempt.reference}"[:128],
            counter="online",
            notes=f"Paid online ({attempt.channel})",
        )
    except BillingError as refused:
        attempt.needs_attention = (
            f"Paid through {attempt.get_provider_display()} but not applied: {refused.message} "
            "Refund it from the provider's dashboard."
        )[:255]
        logger.warning("Online payment %s could not be applied: %s", attempt.uuid, refused.message)


def reconcile(now=None) -> dict:
    """Check every attempt still open. For a scheduled task and a button."""
    now = now or timezone.now()
    counts = {"checked": 0, "completed": 0, "expired": 0}
    open_attempts = OnlinePayment.objects.filter(
        status__in=[OnlinePaymentStatus.INITIATED, OnlinePaymentStatus.PENDING],
        created_at__lte=now - timedelta(minutes=2),
        created_at__gte=now - timedelta(days=7),
    )
    for attempt in open_attempts[:200]:
        result = confirm(attempt)
        counts["checked"] += 1
        if result.status == OnlinePaymentStatus.COMPLETED:
            counts["completed"] += 1
        elif result.status == OnlinePaymentStatus.EXPIRED:
            counts["expired"] += 1
    return counts


def describe(attempt: OnlinePayment) -> dict:
    return {
        "uuid": str(attempt.uuid),
        "invoice": attempt.invoice.number,
        "provider": attempt.provider,
        "provider_label": attempt.get_provider_display(),
        "amount": str(attempt.amount),
        "status": attempt.status,
        "status_label": attempt.get_status_display(),
        "channel": attempt.channel,
        "started_by": attempt.started_by_name,
        "created_at": attempt.created_at,
        "completed_at": attempt.completed_at,
        "provider_transaction": attempt.provider_transaction,
        "receipt": attempt.payment.receipt_number if attempt.payment_id else "",
        "needs_attention": attempt.needs_attention,
        "balance_due": str(attempt.invoice.balance_due),
    }


def portal_return_url() -> str:
    return f"{settings.PORTAL_URL}/"


def console_return_url() -> str:
    return f"{settings.CONSOLE_URL}/billing/online-return"
