"""Nepal's statutory payroll rules.

Everything here is *policy*, and policy changes with the budget speech. So the
numbers live in `TaxSlab` and `ContributionScheme` rows and this module holds
only the **shape** of the calculation — the order the rules apply in, what is
capped against what, and which exemption displaces which. That shape is far
more stable than the rates: the slabs move most years, the structure has not
changed in a decade.

The calculation, in the order it must happen:

1. **Annualise.** A progressive rate applied to one month's pay puts everybody
   in the wrong band twelve times over. Payroll works monthly and the tax is
   computed on the projected year.
2. **Deduct retirement contributions**, capped by the lower of a fixed ceiling
   and one third of assessable income.
3. **Deduct insurance premiums**, each capped separately.
4. **Apply remote-area and disability allowances**, which reduce taxable
   income further.
5. **Run the slabs**, band by band.
6. **Waive the 1% social security tax** for anybody contributing to the SSF —
   the contribution replaces it.
7. **Divide by twelve** for the month's deduction.

Every step records what it did, because "why is my tax 4,200?" has to be
answerable from the payslip rather than by somebody re-deriving it.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.payroll.models import ContributionScheme, TaxRegime, TaxSlab

ZERO = Decimal("0.00")
PAISA = Decimal("0.01")
MONTHS = Decimal("12")

#: A third of assessable income is the ceiling Nepal places on the retirement
#: contribution deduction, alongside a flat rupee cap. Both apply; the lower
#: wins. Named rather than inlined because it is the part of the rule people
#: forget.
RETIREMENT_DEDUCTION_FRACTION = Decimal("1") / Decimal("3")

#: Caps on deductible insurance premiums, annual, in rupees. These are rates
#: rather than structure and would ideally be rows too; they are here as
#: named constants because they change far less often than the slabs and
#: giving them a table of their own would be more machinery than they earn.
#: When one changes, this is the single place to edit.
LIFE_INSURANCE_CAP = Decimal("40000.00")
HEALTH_INSURANCE_CAP = Decimal("20000.00")

#: Remote-area allowance against taxable income, by category. Category A is
#: the most remote.
REMOTE_AREA_ALLOWANCE = {
    "A": Decimal("50000.00"),
    "B": Decimal("40000.00"),
    "C": Decimal("30000.00"),
    "D": Decimal("20000.00"),
    "E": Decimal("10000.00"),
}

#: Additional exemption for an employee with a disability, expressed as a
#: multiple of the first tax band's width — which is how the Nepali rule is
#: written, so that it moves with the band rather than needing its own edit.
DISABILITY_EXEMPTION_MULTIPLE = Decimal("0.50")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP)


def jsonable(value):
    """Recursively turn `Decimal` into a string for storage in a JSON field.

    `Decimal` is not JSON-serialisable and `float` would defeat the point of
    using it. The tax workings are stored so a payslip can explain itself, and
    an explanation whose numbers drifted in serialisation explains nothing.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def slabs_for(fiscal_year: str, regime: str = TaxRegime.INDIVIDUAL) -> list:
    """The bands in force, lowest first.

    Falls back to the most recent year on file rather than returning nothing.
    A payroll that silently computed zero tax because nobody loaded this
    year's slabs would be far worse than one computed on last year's — the
    first is invisible, the second is obvious on the payslip and correctable
    with a supplementary run.
    """
    bands = list(
        TaxSlab.objects.filter(fiscal_year=fiscal_year, regime=regime)
        .order_by("sequence")
    )
    if bands:
        return bands

    latest = (
        TaxSlab.objects.filter(regime=regime)
        .order_by("-fiscal_year")
        .values_list("fiscal_year", flat=True)
        .first()
    )
    if latest is None:
        return []
    return list(
        TaxSlab.objects.filter(fiscal_year=latest, regime=regime)
        .order_by("sequence")
    )


def scheme_for(code: str, fiscal_year: str) -> ContributionScheme | None:
    """A contribution scheme in force, falling back to the latest on file."""
    scheme = ContributionScheme.objects.filter(
        code=code, fiscal_year=fiscal_year, is_active=True
    ).first()
    if scheme:
        return scheme
    return (
        ContributionScheme.objects.filter(code=code, is_active=True)
        .order_by("-fiscal_year")
        .first()
    )


def retirement_deduction(
    annual_contribution: Decimal,
    assessable_income: Decimal,
    ceiling: Decimal,
) -> dict:
    """How much of a retirement contribution is deductible.

    Two caps, and the **lower** wins: a flat rupee ceiling, and one third of
    assessable income. Applying only the flat cap over-deducts for anybody on
    a low salary making a large voluntary contribution, which is exactly the
    case the fraction exists to catch.
    """
    fraction_cap = (assessable_income * RETIREMENT_DEDUCTION_FRACTION).quantize(
        PAISA, rounding=ROUND_HALF_UP
    )
    allowed = min(annual_contribution, ceiling, fraction_cap)
    return {
        "contributed": money(annual_contribution),
        "flat_ceiling": money(ceiling),
        "one_third_of_income": fraction_cap,
        "deductible": money(max(allowed, ZERO)),
        "binding_cap": (
            "contribution" if allowed == annual_contribution
            else "flat ceiling" if allowed == ceiling
            else "one third of assessable income"
        ),
    }


def insurance_deduction(life_premium, health_premium) -> dict:
    """Deductible insurance premiums, each capped separately.

    Separately, not jointly: somebody paying 60,000 in life premiums and
    nothing for health may deduct 40,000, not 60,000 against a combined cap.
    """
    life = min(money(life_premium), LIFE_INSURANCE_CAP)
    health = min(money(health_premium), HEALTH_INSURANCE_CAP)
    return {
        "life_premium": money(life_premium),
        "life_deductible": life,
        "life_cap": LIFE_INSURANCE_CAP,
        "health_premium": money(health_premium),
        "health_deductible": health,
        "health_cap": HEALTH_INSURANCE_CAP,
        "total": life + health,
    }


def apply_slabs(taxable_income: Decimal, bands: list, ssf_contributor: bool) -> dict:
    """Run the progressive bands and show the working.

    Each band taxes only the part of income that falls inside it — the whole
    point of a progressive table, and the thing most often got wrong by
    applying the top rate to everything.

    The 1% first band is Nepal's social security tax. An employee contributing
    to the SSF does not pay it: the contribution replaces it. Skipping it
    rather than deleting the band keeps the table honest for everybody else.
    """
    remaining = max(taxable_income, ZERO)
    total = ZERO
    workings = []

    for band in bands:
        if remaining <= ZERO:
            break

        width = (
            band.upper_bound - band.lower_bound
            if band.upper_bound is not None
            else remaining
        )
        taxed_here = min(remaining, width)
        if taxed_here <= ZERO:
            continue

        waived = band.waived_for_ssf_contributors and ssf_contributor
        amount = (
            ZERO if waived
            else (taxed_here * band.rate_percent / Decimal("100")).quantize(
                PAISA, rounding=ROUND_HALF_UP
            )
        )
        total += amount
        workings.append(
            {
                "band": band.label or f"{band.lower_bound}–{band.upper_bound or '∞'}",
                "lower": str(band.lower_bound),
                "upper": str(band.upper_bound) if band.upper_bound else None,
                "rate_percent": str(band.rate_percent),
                "amount_taxed": str(taxed_here),
                "tax": str(amount),
                "waived": waived,
                "waiver_reason": (
                    "Contributing to the Social Security Fund, which replaces "
                    "the social security tax." if waived else ""
                ),
            }
        )
        remaining -= taxed_here

    return {"annual_tax": money(total), "bands": workings}


def compute_tax(
    *,
    fiscal_year: str,
    monthly_taxable_gross: Decimal,
    regime: str = TaxRegime.INDIVIDUAL,
    monthly_retirement_contribution: Decimal = ZERO,
    annual_cit_contribution: Decimal = ZERO,
    retirement_ceiling: Decimal = Decimal("500000.00"),
    life_insurance_premium: Decimal = ZERO,
    health_insurance_premium: Decimal = ZERO,
    remote_area_category: str = "",
    is_disabled: bool = False,
    ssf_contributor: bool = False,
    months_remaining: Decimal = MONTHS,
) -> dict:
    """Monthly income tax, with the whole derivation attached.

    `months_remaining` exists for somebody who joins in the middle of a year:
    their annual projection is what they will actually earn, not twelve months
    of a salary they will be paid for seven. Projecting the full year would
    push a mid-year joiner into a band they never reach and over-deduct every
    month until somebody noticed at year end.
    """
    monthly_taxable_gross = money(monthly_taxable_gross)
    months = max(Decimal(str(months_remaining)), Decimal("1"))

    annual_gross = money(monthly_taxable_gross * months)
    annual_retirement = money(
        Decimal(str(monthly_retirement_contribution)) * months
        + Decimal(str(annual_cit_contribution))
    )

    retirement = retirement_deduction(
        annual_retirement, annual_gross, Decimal(str(retirement_ceiling))
    )
    insurance = insurance_deduction(
        life_insurance_premium, health_insurance_premium
    )

    bands = slabs_for(fiscal_year, regime)
    remote_allowance = REMOTE_AREA_ALLOWANCE.get(
        (remote_area_category or "").upper(), ZERO
    )

    disability_allowance = ZERO
    if is_disabled and bands:
        first = bands[0]
        width = (
            first.upper_bound - first.lower_bound
            if first.upper_bound is not None else ZERO
        )
        disability_allowance = money(width * DISABILITY_EXEMPTION_MULTIPLE)

    taxable = max(
        annual_gross
        - retirement["deductible"]
        - insurance["total"]
        - remote_allowance
        - disability_allowance,
        ZERO,
    )

    slab_result = apply_slabs(taxable, bands, ssf_contributor)
    monthly_tax = (slab_result["annual_tax"] / months).quantize(
        PAISA, rounding=ROUND_HALF_UP
    )

    return {
        "fiscal_year": fiscal_year,
        "regime": regime,
        "months_projected": str(months),
        "monthly_taxable_gross": str(monthly_taxable_gross),
        "annual_gross": str(annual_gross),
        "retirement": retirement,
        "insurance": insurance,
        "remote_area_allowance": str(remote_allowance),
        "disability_allowance": str(disability_allowance),
        "taxable_income": str(taxable),
        "ssf_contributor": ssf_contributor,
        "bands": slab_result["bands"],
        "annual_tax": str(slab_result["annual_tax"]),
        "monthly_tax": monthly_tax,
        "slabs_missing": not bands,
    }


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
#
# The rates below are the shape the tables take, loaded by
# `seed_nepal_tax`. They are *starting* data for a new tenant, not a source of
# truth: an organization edits the rows when the budget changes, and the code
# never reads these constants at runtime.

#: (sequence, lower, upper, rate, waived for SSF contributors, label)
INDIVIDUAL_SLABS = [
    (1, "0", "500000", "1", True, "First 500,000 — social security tax"),
    (2, "500000", "700000", "10", False, "Next 200,000"),
    (3, "700000", "1000000", "20", False, "Next 300,000"),
    (4, "1000000", "2000000", "30", False, "Next 1,000,000"),
    (5, "2000000", None, "36", False, "Above 2,000,000"),
]

#: A married couple assessed jointly gets a wider first band.
COUPLE_SLABS = [
    (1, "0", "600000", "1", True, "First 600,000 — social security tax"),
    (2, "600000", "800000", "10", False, "Next 200,000"),
    (3, "800000", "1100000", "20", False, "Next 300,000"),
    (4, "1100000", "2000000", "30", False, "Next 900,000"),
    (5, "2000000", None, "36", False, "Above 2,000,000"),
]

#: (code, name, employee %, employer %, deductible, ceiling, replaces SST)
CONTRIBUTION_SCHEMES = [
    (
        "ssf", "Social Security Fund",
        "11.000", "20.000", True, "500000", True,
    ),
    (
        "pf", "Provident Fund",
        "10.000", "10.000", True, "500000", False,
    ),
    (
        "cit", "Citizen Investment Trust",
        "0.000", "0.000", True, "500000", False,
    ),
]
