"""What a person may set about their own view of the system.

Declared rather than free-form, for the same reason
`apps/organization/settings_registry.py` is: an endpoint that writes any key a
client sends is a way to put arbitrary JSON on a user row, and every reader
then has to defend itself against values it has never heard of.

**These are client preferences and nothing on the server branches on them.**
That is the line. `locale` and `timezone` are real columns on `User` because
the server formats dates with them; theme and density are here because only
the browser ever reads them. If something in this file ever starts affecting a
response, it belongs in a column instead.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Preference:
    key: str
    label: str
    description: str
    kind: str  # "choice" | "boolean"
    default: object
    choices: list = field(default_factory=list)


PREFERENCES = [
    Preference(
        key="theme",
        label="Appearance",
        description=(
            "Follow the system setting, or pick one. A ward at night and a "
            "billing desk under strip lights do not want the same screen."
        ),
        kind="choice",
        default="system",
        choices=[
            ("system", "Match my device"),
            ("light", "Light"),
            ("dark", "Dark"),
        ],
    ),
    Preference(
        key="palette",
        label="Colour",
        description=(
            "The whole interface, not just an accent. Each one is a complete "
            "identity with its own neutrals, and every combination in it has "
            "been checked for contrast in both light and dark."
        ),
        kind="choice",
        default="vital",
        choices=[
            ("vital", "Vital — luminous teal"),
            ("meridian", "Meridian — indigo and amber"),
            ("command", "Command — navy and cyan"),
            ("verdant", "Verdant — green and violet"),
            ("ember", "Ember — rose and teal"),
        ],
    ),
    Preference(
        key="density",
        label="Row height",
        description=(
            "Comfortable is easier to read; compact fits about a third more "
            "rows on screen, which is what a triage board wants."
        ),
        kind="choice",
        default="comfortable",
        choices=[
            ("comfortable", "Comfortable"),
            ("compact", "Compact"),
        ],
    ),
    Preference(
        key="landing",
        label="Open on",
        description=(
            "Which screen to land on after signing in. The default follows "
            "your role, which is usually right and occasionally is not."
        ),
        kind="choice",
        default="auto",
        choices=[
            ("auto", "Whatever suits my role"),
            ("/dashboard", "Dashboard"),
            ("/queue", "Queue"),
            ("/patients", "Patients"),
            ("/workspace", "My day"),
            ("/notifications", "Notifications"),
        ],
    ),
    Preference(
        key="calendar",
        label="Dates",
        description=(
            "Bikram Sambat is the calendar Nepal runs on: a patient asks for "
            "an appointment in Ashoj, and a ward round is recorded on a date "
            "somebody will later look up in BS. Both calendars are shown "
            "where a date is a legal record -- an invoice, a report -- "
            "because a date that reaches an insurer or a ministry has to be "
            "readable by both."
        ),
        kind="choice",
        default="gregorian",
        choices=[
            ("gregorian", "Gregorian (12 September 2026)"),
            ("bikram_sambat", "Bikram Sambat (२७ भाद्र २०८३)"),
        ],
    ),
    Preference(
        key="reduced_motion",
        label="Reduce motion",
        description=(
            "Turns off the sliding and fading. Your device may already ask "
            "for this; turning it on here applies it regardless."
        ),
        kind="boolean",
        default=False,
    ),
    Preference(
        key="notify_critical_results",
        label="Alert me to critical results",
        description=(
            "A red-flag laboratory value on a patient you are treating. "
            "Leaving this off does not stop the result being escalated to "
            "somebody -- it stops it being escalated to you."
        ),
        kind="boolean",
        default=True,
    ),
    Preference(
        key="notify_approvals",
        label="Alert me to approvals waiting",
        description="Purchase orders, leave, payroll runs and refunds.",
        kind="boolean",
        default=True,
    ),
]

BY_KEY = {preference.key: preference for preference in PREFERENCES}

DEFAULTS = {preference.key: preference.default for preference in PREFERENCES}


def resolved(stored: dict | None) -> dict:
    """Everything a client needs, defaults filled in.

    Returns every declared key whether or not it has been set, so the
    interface never has to decide what an absent value means -- and a
    preference added next release is simply present at its default rather
    than `undefined` in a component somewhere.
    """
    stored = stored or {}
    return {
        key: stored.get(key, default)
        for key, default in DEFAULTS.items()
    }


def coerce(key: str, raw):
    """Validate one submitted value, or raise `ValueError`."""
    preference = BY_KEY.get(key)
    if preference is None:
        raise ValueError(f"'{key}' is not a preference this system has.")

    if preference.kind == "boolean":
        if isinstance(raw, bool):
            return raw
        if str(raw).lower() in {"true", "1", "yes", "on"}:
            return True
        if str(raw).lower() in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{preference.label} is on or off.")

    allowed = {value for value, _ in preference.choices}
    if raw not in allowed:
        raise ValueError(
            f"{preference.label} must be one of: {', '.join(sorted(allowed))}."
        )
    return raw


def merge(stored: dict | None, submitted: dict) -> dict:
    """Apply a partial update, validating each key.

    Merged rather than replaced, so a client that knows about four
    preferences does not silently erase the two it has not been taught about
    yet -- which is what a PUT of the whole object would do the first time an
    old tab saved after a release.
    """
    updated = dict(stored or {})
    for key, value in submitted.items():
        updated[key] = coerce(key, value)
    return updated
