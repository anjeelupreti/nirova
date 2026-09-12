"""eSewa and Khalti: the two wallets most of Nepal pays with.

Thin clients for each provider's published merchant API, and nothing else —
what an attempt *means* for an invoice is `apps.billing.online`.

**Khalti — ePayment (KPG-2).** `initiate` returns a `pidx` and a
`payment_url`; the payer pays there and is sent back to our `return_url`;
`lookup` with the `pidx` is the only answer we act on. Amounts are in paisa.
    https://docs.khalti.com/khalti-epayment/

**eSewa — ePay v2.** The payer's browser posts a signed form to eSewa; eSewa
sends them back to `success_url` or `failure_url`; the transaction-status
endpoint, queried with our `transaction_uuid` and amount, is the only answer
we act on. The form's signature is HMAC-SHA256 over
`total_amount,transaction_uuid,product_code`, base64-encoded.
    https://developer.esewa.com.np/pages/Epay

Both are called with the standard library and a fifteen-second timeout; a
provider that does not answer leaves an attempt pending, to be checked again,
rather than failing it.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

TIMEOUT = 15

KHALTI_API = {
    "sandbox": "https://dev.khalti.com/api/v2/",
    "live": "https://khalti.com/api/v2/",
}
ESEWA_FORM = {
    "sandbox": "https://rc-epay.esewa.com.np/api/epay/main/v2/form",
    "live": "https://epay.esewa.com.np/api/epay/main/v2/form",
}
ESEWA_STATUS = {
    "sandbox": "https://rc.esewa.com.np/api/epay/transaction/status/",
    "live": "https://esewa.com.np/api/epay/transaction/status/",
}
#: eSewa's public test merchant, published in its developer documentation.
#: Used only in sandbox mode and only when the tenant has entered none.
ESEWA_TEST_MERCHANT = ("EPAYTEST", "8gBm/:&EnhH.1/q")

#: Khalti refuses less than NPR 10.
KHALTI_MINIMUM = Decimal("10.00")


class GatewayError(Exception):
    """The provider refused, or could not be reached."""


@dataclass(frozen=True)
class Answer:
    """A provider's view of one attempt, in our vocabulary."""

    #: One of `OnlinePaymentStatus`'s values.
    status: str
    amount: Decimal | None
    transaction: str
    raw: dict


def _call(url: str, *, body: dict | None = None, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 — fixed https hosts
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode() or "{}")
        except ValueError:
            detail = {}
        raise GatewayError(_explain(detail) or f"The provider refused ({error.code}).") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GatewayError("The payment provider could not be reached. Try again shortly.") from error


def _explain(detail: dict) -> str:
    """The first human sentence in a provider's error body."""
    if not isinstance(detail, dict):
        return ""
    for key in ("detail", "error_key", "message"):
        if isinstance(detail.get(key), str):
            return detail[key]
    for value in detail.values():
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0]
    return ""


# ---------------------------------------------------------------------------
# Khalti
# ---------------------------------------------------------------------------

KHALTI_STATUS = {
    "Completed": "completed",
    "Pending": "pending",
    "Initiated": "initiated",
    "Refunded": "refunded",
    "Partially Refunded": "refunded",
    "Expired": "expired",
    "User canceled": "cancelled",
}


def khalti_initiate(*, mode: str, secret_key: str, amount: Decimal, order_id: str,
                    order_name: str, return_url: str, website_url: str) -> dict:
    """Start a payment. Returns `{pidx, payment_url, expires_at}`.

    No customer details are sent. Khalti's `customer_info` is optional, and a
    patient's name and phone are not the wallet's business.
    """
    paisa = int((amount * 100).to_integral_value())
    answer = _call(
        KHALTI_API[mode] + "epayment/initiate/",
        body={
            "return_url": return_url,
            "website_url": website_url,
            "amount": paisa,
            "purchase_order_id": order_id,
            "purchase_order_name": order_name[:100],
        },
        headers={"Authorization": f"Key {secret_key}"},
    )
    if not answer.get("pidx") or not answer.get("payment_url"):
        raise GatewayError(_explain(answer) or "Khalti did not start the payment.")
    return answer


def khalti_lookup(*, mode: str, secret_key: str, pidx: str) -> Answer:
    raw = _call(
        KHALTI_API[mode] + "epayment/lookup/",
        body={"pidx": pidx},
        headers={"Authorization": f"Key {secret_key}"},
    )
    total = raw.get("total_amount")
    return Answer(
        status=KHALTI_STATUS.get(raw.get("status", ""), "pending"),
        amount=(Decimal(total) / 100).quantize(Decimal("0.01")) if total is not None else None,
        transaction=str(raw.get("transaction_id") or ""),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# eSewa
# ---------------------------------------------------------------------------

#: **`NOT_FOUND` is "not yet", not "never".** eSewa's status endpoint knows
#: nothing about a transaction until the payer completes it, so it answers
#: NOT_FOUND for one that is in progress — and the first version read that as
#: expired, settled the attempt seconds after it began, and would have stranded
#: the money of anybody who then went on to pay. Age decides expiry, in
#: `online.confirm`, not the provider's silence.
ESEWA_STATUS_MAP = {
    "COMPLETE": "completed",
    "PENDING": "pending",
    "AMBIGUOUS": "pending",
    "FULL_REFUND": "refunded",
    "PARTIAL_REFUND": "refunded",
    "CANCELED": "cancelled",
    "NOT_FOUND": "pending",
}


def esewa_amount(amount: Decimal) -> str:
    """eSewa's own notation: `1250` for whole rupees, `1250.5` otherwise.

    The signed message and the status query must spell the amount the same
    way every time, so there is exactly one place that spells it.
    """
    text = f"{amount.quantize(Decimal('0.01')):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def esewa_sign(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def esewa_form(*, mode: str, product_code: str, secret: str, amount: Decimal,
               transaction_uuid: str, success_url: str, failure_url: str) -> dict:
    """The form the payer's browser posts to eSewa: `{action, fields}`."""
    total = esewa_amount(amount)
    fields = {
        "amount": total,
        "tax_amount": "0",
        "total_amount": total,
        "transaction_uuid": transaction_uuid,
        "product_code": product_code,
        "product_service_charge": "0",
        "product_delivery_charge": "0",
        "success_url": success_url,
        "failure_url": failure_url,
        "signed_field_names": "total_amount,transaction_uuid,product_code",
    }
    fields["signature"] = esewa_sign(
        secret, f"total_amount={total},transaction_uuid={transaction_uuid},product_code={product_code}",
    )
    return {"action": ESEWA_FORM[mode], "fields": fields}


def esewa_verify_callback(secret: str, encoded: str) -> dict | None:
    """The data eSewa appended to `success_url`, if its signature is good.

    Kept for the record only: the status query decides. Numbers are parsed as
    their original text, because the signature is over the text eSewa wrote
    (`1000.0`), not over whatever a float prints as.
    """
    try:
        data = json.loads(base64.b64decode(encoded).decode(), parse_float=str, parse_int=str)
        names = data["signed_field_names"].split(",")
        message = ",".join(f"{name}={data[name]}" for name in names)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return data if hmac.compare_digest(esewa_sign(secret, message), str(data.get("signature", ""))) else None


def esewa_status(*, mode: str, product_code: str, amount: Decimal, transaction_uuid: str) -> Answer:
    query = urllib.parse.urlencode({
        "product_code": product_code,
        "total_amount": esewa_amount(amount),
        "transaction_uuid": transaction_uuid,
    })
    raw = _call(f"{ESEWA_STATUS[mode]}?{query}")
    total = raw.get("total_amount")
    return Answer(
        status=ESEWA_STATUS_MAP.get(str(raw.get("status", "")).upper(), "pending"),
        amount=Decimal(str(total)).quantize(Decimal("0.01")) if total not in (None, "") else None,
        transaction=str(raw.get("ref_id") or ""),
        raw=raw,
    )
