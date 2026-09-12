"""Sales over a period: the owner's view of the counter.

`sales_summary` answers "how did today go" for one facility. An owner asks
different questions — how is this month against last, which products carry
the margin, how much comes by eSewa, which till is short, when is the counter
busiest — and until now answered them by exporting days one at a time.

**The same rules as the daily summary**, so a one-day report and the counter's
own summary agree to the paisa: voided sales are excluded; returns are counted
on the day they completed; margin is computed on net revenue, with VAT taken
out (it was collected on the customer's behalf) and cost recovered only for
goods that went back on the shelf. A report that disagreed with the till's own
figure would be two numbers for one fact, and nobody would trust either.

Nothing is stored; everything is recomputed from sales, lines, returns and
payments, so the report cannot drift from the ledger.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.pos.models import (
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleReturnStatus,
    SaleStatus,
)

ZERO = Decimal("0.00")
#: A report longer than this is refused: a year at daily grain is 366 rows
#: and enough for any trend; beyond that it is an export job, not a screen.
MAX_DAYS = 366


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def sales_report(start, end, facility=None, facility_ids=None) -> dict:
    """Everything the sales screen and its Excel export show, for [start, end].

    `facility_ids` limits the report to the facilities a caller may see;
    `None` means all of them.
    """
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"Choose a period of at most {MAX_DAYS} days.")

    tz = timezone.get_current_timezone()
    since = timezone.make_aware(datetime.combine(start, time.min), tz)
    until = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)

    sales = Sale.objects.filter(sold_at__gte=since, sold_at__lt=until).exclude(status=SaleStatus.VOIDED)
    returns = SaleReturn.objects.filter(
        completed_at__gte=since, completed_at__lt=until, status=SaleReturnStatus.COMPLETED,
    )
    if facility is not None:
        sales = sales.filter(facility=facility)
        returns = returns.filter(sale__facility=facility)
    if facility_ids is not None:
        sales = sales.filter(facility_id__in=facility_ids)
        returns = returns.filter(sale__facility_id__in=facility_ids)

    lines = SaleLine.objects.filter(sale__in=sales)

    # -- headline ---------------------------------------------------------
    gross = _money(sales.aggregate(t=models.Sum("total"))["t"])
    tax = _money(sales.aggregate(t=models.Sum("tax_total"))["t"])
    discount = _money(sales.aggregate(t=models.Sum("discount_total"))["t"])
    count = sales.count()
    refunds = _money(returns.aggregate(t=models.Sum("refund_total"))["t"])

    gross_cost = sum((line.unit_cost * line.quantity for line in lines.only("unit_cost", "quantity")), ZERO)
    recovered = ZERO
    for row in SaleReturnLine.objects.filter(sale_return__in=returns).select_related("sale_return", "sale_line"):
        if row.sale_return.restock:
            recovered += row.sale_line.unit_cost * row.quantity
    net_revenue = _money(gross - refunds)
    net_cost = _money(gross_cost - recovered)
    margin = _money(net_revenue - tax - net_cost)

    # -- by day -----------------------------------------------------------------
    by_day = {start + timedelta(days=offset): {"sales": 0, "revenue": ZERO, "refunds": ZERO}
              for offset in range((end - start).days + 1)}
    for sale in sales.only("sold_at", "total"):
        day = timezone.localtime(sale.sold_at, tz).date()
        if day in by_day:
            by_day[day]["sales"] += 1
            by_day[day]["revenue"] += sale.total
    for refund in returns.only("completed_at", "refund_total"):
        day = timezone.localtime(refund.completed_at, tz).date()
        if day in by_day:
            by_day[day]["refunds"] += refund.refund_total

    # -- by hour of day -------------------------------------------------------------
    by_hour = defaultdict(lambda: {"sales": 0, "revenue": ZERO})
    for sale in sales.only("sold_at", "total"):
        hour = timezone.localtime(sale.sold_at, tz).hour
        by_hour[hour]["sales"] += 1
        by_hour[hour]["revenue"] += sale.total

    # -- by product ------------------------------------------------------------------
    products = (
        lines.values("product_name")
        .annotate(
            units=models.Sum("quantity"),
            revenue=models.Sum("total"),
            cost=models.Sum(models.F("unit_cost") * models.F("quantity"), output_field=models.DecimalField()),
            tax=models.Sum("tax_amount"),
            sales=models.Count("sale", distinct=True),
        )
        .order_by("-revenue")
    )

    # -- by payment method -----------------------------------------------------------------
    from apps.billing.models import Payment

    invoice_ids = [uuid for uuid in sales.values_list("invoice_uuid", flat=True) if uuid]
    tenders = defaultdict(lambda: {"count": 0, "amount": ZERO})
    labels = {}
    for payment in Payment.objects.filter(invoice__uuid__in=invoice_ids):
        tenders[payment.method]["count"] += 1
        tenders[payment.method]["amount"] += payment.amount
        labels[payment.method] = payment.get_method_display()

    # -- by cashier and till ----------------------------------------------------------------
    cashiers = (
        sales.values("sold_by_name", "session__counter")
        .annotate(sales=models.Count("id"), revenue=models.Sum("total"))
        .order_by("-revenue")
    )

    return {
        "start": start,
        "end": end,
        "facility": facility.name if facility else None,
        "totals": {
            "sales": count,
            "gross_revenue": gross,
            "discounts": discount,
            "refunds": refunds,
            "returns": returns.count(),
            "net_revenue": net_revenue,
            "tax": tax,
            "cost_of_goods": net_cost,
            "gross_margin": margin,
            "margin_percent": float(round(margin / (net_revenue - tax) * 100, 1)) if net_revenue - tax else 0.0,
            "average_sale": _money(gross / count) if count else ZERO,
            "return_rate_percent": float(round(refunds / gross * 100, 1)) if gross else 0.0,
        },
        "by_day": [
            {"date": day, "sales": row["sales"], "revenue": _money(row["revenue"]),
             "refunds": _money(row["refunds"]), "net": _money(row["revenue"] - row["refunds"])}
            for day, row in sorted(by_day.items())
        ],
        "by_hour": [
            {"hour": hour, "sales": by_hour[hour]["sales"], "revenue": _money(by_hour[hour]["revenue"])}
            for hour in range(24)
        ],
        "by_product": [
            {
                "product": row["product_name"],
                "quantity": row["units"],
                "sales": row["sales"],
                "revenue": _money(row["revenue"]),
                "cost": _money(row["cost"]),
                "margin": _money((row["revenue"] or ZERO) - (row["tax"] or ZERO) - (row["cost"] or ZERO)),
            }
            for row in products
        ],
        "by_tender": [
            {"method": method, "label": labels.get(method, method), "count": row["count"], "amount": _money(row["amount"])}
            for method, row in sorted(tenders.items(), key=lambda item: -item[1]["amount"])
        ],
        "by_cashier": [
            {"cashier": row["sold_by_name"], "till": row["session__counter"],
             "sales": row["sales"], "revenue": _money(row["revenue"])}
            for row in cashiers
        ],
    }
