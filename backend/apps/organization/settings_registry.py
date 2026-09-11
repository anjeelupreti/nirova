"""The settings a customer may change about their own system.

`ConfigSetting` has existed since the organization app was written and has
**never had an endpoint**. Everything in it was written by a seed or by a
service call, which means two features shipped that nobody could reach:

* `privacy.require_care_relationship`, the switch that narrows clinical
  browsing to a clinician's own patients. Off by default and unturnonable
  except from a Django shell.
* the whole of `apps.organization.locale` -- timezone, fiscal calendar, tax
  rate -- added in logs 241 and 242.

**A declared registry, not a key/value endpoint.** An API that accepts any
namespace and key is a way to write arbitrary rows into a tenant's
configuration table, and every consumer of `config_value` then has to defend
itself against values it has never heard of. Declaring them here means the API
can validate a value before storing it, the screen can render the right
control without a hard-coded list of its own, and a setting nobody has
declared is simply not settable over HTTP.

The registry is code rather than data on purpose, the same argument as
`apps.rbac.permissions`: what a system *can* be configured to do is part of
the system, and a customer adding a row to a table should not be able to
invent a new one.
"""

from dataclasses import dataclass, field

from apps.organization.locale import (
    CURRENCY_KEY,
    FISCAL_CALENDAR_KEY,
    LOCALE_NAMESPACE,
    TAX_RATE_KEY,
    TIMEZONE_KEY,
    FiscalCalendar,
)


@dataclass(frozen=True)
class Setting:
    """One thing a customer may change, and what a valid answer looks like."""

    namespace: str
    key: str
    label: str
    #: What it does, in the words somebody choosing it would use. Shown under
    #: the control, because a setting whose effect you have to guess is one
    #: people leave alone.
    description: str
    #: "boolean" | "choice" | "decimal" | "string". Drives the control the
    #: screen renders and the validation the API applies.
    kind: str
    default: object
    #: For `kind="choice"`: (value, label) pairs.
    choices: list = field(default_factory=list)
    #: Whether a facility may hold its own value. False means the setting is
    #: organization-wide by nature -- a privacy policy is not something one
    #: branch opts out of quietly.
    per_facility: bool = False
    #: A warning shown before the value is changed. Present only where the
    #: change has consequences somebody should be told about first.
    caution: str = ""

    @property
    def code(self) -> str:
        return f"{self.namespace}.{self.key}"


#: Everything settable, grouped by the heading the screen puts it under.
SETTINGS = [
    Setting(
        namespace=LOCALE_NAMESPACE,
        key=TIMEZONE_KEY,
        label="Time zone",
        description=(
            "The clock this facility's staff read. Records are stored in UTC "
            "whatever this says; changing it changes how times are displayed, "
            "not what happened."
        ),
        kind="string",
        default="Asia/Kathmandu",
        per_facility=True,
    ),
    Setting(
        namespace=LOCALE_NAMESPACE,
        key=FISCAL_CALENDAR_KEY,
        label="Financial year",
        description=(
            "When this facility's financial year begins. Invoice numbering "
            "restarts at the beginning of each one."
        ),
        kind="choice",
        default=FiscalCalendar.NEPAL,
        choices=list(FiscalCalendar.CHOICES),
        per_facility=True,
        caution=(
            "Invoice numbers are gapless within a financial year. Changing "
            "this mid-year changes where the next sequence starts, so change "
            "it between years or not at all."
        ),
    ),
    Setting(
        namespace=LOCALE_NAMESPACE,
        key=CURRENCY_KEY,
        label="Currency",
        description="The three-letter code prices and invoices are held in.",
        kind="string",
        default="NPR",
        per_facility=True,
        caution=(
            "This does not convert anything. Existing prices keep their "
            "numbers and are simply relabelled, so change it only on a "
            "facility whose price list is being rebuilt."
        ),
    ),
    Setting(
        namespace=LOCALE_NAMESPACE,
        key=TAX_RATE_KEY,
        label="Standard tax rate",
        description=(
            "The percentage charged on standard-rated services that do not "
            "name a rate of their own. Exempt and zero-rated services are "
            "unaffected."
        ),
        kind="decimal",
        default="13.00",
        # Organization-wide, because the service catalogue is: a ServiceItem
        # has no facility, so a per-facility rate would have nothing to attach
        # to. See the comment on `ServiceItem.effective_tax_rate`.
        per_facility=False,
    ),
    Setting(
        namespace="privacy",
        key="require_care_relationship",
        label="Restrict browsing to your own patients",
        description=(
            "When on, clinicians browsing lists and search see only patients "
            "they have a care relationship with. Looking a record up by its "
            "reference still works, so a pharmacy handed a printed "
            "prescription can still dispense it."
        ),
        kind="boolean",
        default=False,
        # Deliberately organization-wide. A privacy policy that one branch can
        # switch off is not a policy.
        per_facility=False,
        caution=(
            "A single-site clinic gains little from this and pays the "
            "complexity. It is meant for groups where not everybody should "
            "see everybody."
        ),
    ),
    Setting(
        namespace="security",
        key="require_mfa",
        label="Require two-step sign-in for everyone",
        description=(
            "When on, every member signs in with a code from their phone as "
            "well as their password. Anybody who has not set it up is taken "
            "straight to setting it up, and can do nothing else until they "
            "have."
        ),
        kind="boolean",
        default=False,
        # Organization-wide: an account signs in once for every facility it
        # works at, so there is nowhere per-facility for this to live.
        per_facility=False,
        caution=(
            "Everybody without it set up — including you, if you have not — "
            "will be asked to set it up the next time they use the system. "
            "Make sure staff have a phone they can use for it, and that an "
            "administrator is on hand to reset it for anyone who loses theirs."
        ),
    ),
]

BY_CODE = {setting.code: setting for setting in SETTINGS}


def coerce(setting: Setting, raw):
    """Turn a submitted value into something safe to store, or raise.

    Validation lives here rather than in the serializer because the registry
    is what knows the shape of each setting, and a serializer that duplicated
    it would be a second definition to keep in step.
    """
    from decimal import Decimal, InvalidOperation

    if setting.kind == "boolean":
        if isinstance(raw, bool):
            return raw
        if str(raw).lower() in {"true", "1", "yes", "on"}:
            return True
        if str(raw).lower() in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{setting.label} is on or off.")

    if setting.kind == "choice":
        allowed = {value for value, _ in setting.choices}
        if raw not in allowed:
            raise ValueError(
                f"{setting.label} must be one of: {', '.join(sorted(allowed))}."
            )
        return raw

    if setting.kind == "decimal":
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{setting.label} must be a number.") from exc
        if value < 0 or value > 100:
            raise ValueError(f"{setting.label} is a percentage between 0 and 100.")
        # Stored as a string so it survives JSON without becoming a float --
        # the same reason the API renders money as strings.
        return f"{value:.2f}"

    text = str(raw).strip()
    if not text:
        raise ValueError(f"{setting.label} cannot be blank.")

    if setting.key == TIMEZONE_KEY:
        # Checked here rather than left to fail silently in middleware, where
        # a typo becomes a wrong clock nobody is told about.
        import zoneinfo

        try:
            zoneinfo.ZoneInfo(text)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"'{text}' is not a time zone. Use an IANA name such as "
                "Asia/Kathmandu or Asia/Dubai."
            ) from exc

    if setting.key == CURRENCY_KEY:
        if len(text) != 3 or not text.isalpha():
            raise ValueError("A currency is a three-letter code, such as NPR.")
        return text.upper()

    return text
