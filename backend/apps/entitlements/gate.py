"""One gate for every module's API.

The console stopped showing screens a customer has not bought (§142), and a
hidden screen is a courtesy, not a control: the endpoints behind it were still
open, so an integration, a saved URL or anybody with a token could use a
module nobody had paid for.

Enforcement already existed **at the service layer** — `admit()` refuses
without the hospital module — which is right for the acts that matter and
leaves every read open. Rather than add a permission class to two hundred
viewsets and discover next year that three were missed, the gate is here: one
table from URL prefix to module, checked once per request, in the same shape
the navigation uses.

**What is deliberately not gated.** `/api/clinical/` — patients, the diary,
encounters and prescriptions are what every customer bought something to do.
`/api/me/` — it serves both the staff workspace and the patient portal, and a
prefix that means two things cannot gate on one module. `/api/billing/`,
`/api/notifications/`, `/api/org/`, `/api/auth/`, `/api/reports/`: core.

**A refusal says which module and what plan**, in the standard envelope, so
the console can offer the same "not included" screen a bookmarked route gets.
"""

import json
import logging
import time

from django.http import JsonResponse

from apps.catalog.keys import ModuleCode
from apps.common.exceptions import EntitlementError

logger = logging.getLogger("nirova.entitlements")

#: Longest prefix wins, so a more specific path can be exempted later.
GATED_PREFIXES = (
    ("/api/ipd/", ModuleCode.HOSPITAL),
    ("/api/ed/", ModuleCode.HOSPITAL),
    ("/api/ot/", ModuleCode.HOSPITAL),
    ("/api/icu/", ModuleCode.HOSPITAL),
    ("/api/diagnostics/", ModuleCode.LABORATORY),
    ("/api/blood/", ModuleCode.BLOOD_BANK),
    ("/api/pharmacy/", ModuleCode.PHARMACY),
    ("/api/pos/", ModuleCode.PHARMACY),
    ("/api/procurement/", ModuleCode.PROCUREMENT),
    ("/api/insurance/", ModuleCode.INSURANCE),
    ("/api/finance/", ModuleCode.FINANCE),
    ("/api/hr/", ModuleCode.HRMS),
    ("/api/payroll/", ModuleCode.PAYROLL),
    ("/api/portal/", ModuleCode.PATIENT_PORTAL),
    ("/api/import/", ModuleCode.API_ACCESS),
)


#: Seconds an organization's module list is remembered.
#:
#: The resolver is deliberately uncached — a support agent who grants headroom
#: expects the next click to show it — and this gate runs on *every* request to
#: a gated prefix, which the query-budget guard caught immediately: five extra
#: queries per request, on every ward page load, for an answer that changes
#: when somebody signs a contract. Half a minute, and every act that changes an
#: entitlement forgets it explicitly (`forget`), so a plan change is visible at
#: once and the steady state costs nothing.
CACHE_TTL = 30
_cache: dict[str, tuple[set, bool, float]] = {}


def forget(slug: str = "") -> None:
    """Drop a remembered answer — or all of them, when a plan changed."""
    if slug:
        _cache.pop(slug, None)
    else:
        _cache.clear()


def _modules_of(organization) -> tuple[set, bool]:
    key = organization.slug
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[2] < CACHE_TTL:
        return cached[0], cached[1]

    from apps.entitlements.resolver import resolve_entitlements

    entitlements = resolve_entitlements(organization)
    held = {code for code, on in entitlements.modules.items() if on}
    _cache[key] = (held, entitlements.is_entitled, now)
    return held, entitlements.is_entitled


def module_for_path(path: str) -> str:
    for prefix, module in GATED_PREFIXES:
        if path.startswith(prefix):
            return module
    return ""


class ModuleGateMiddleware:
    """Refuses an API a tenant's plan does not include.

    Placed after the tenant middleware, which is what binds
    `request.organization`. With no organization bound there is nothing to
    check — the platform console, sign-in, and the patient portal's own
    session all pass straight through.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        module = module_for_path(request.path)
        organization = getattr(request, "organization", None)
        if module and organization is not None and getattr(request, "tenant", None) is not None:
            refusal = self._check(organization, module, request)
            if refusal is not None:
                return refusal
        return self.get_response(request)

    def _check(self, organization, module: str, request=None):
        from apps.common.exceptions import SubscriptionInactive

        try:
            held, is_entitled = _modules_of(organization)
        except Exception:  # noqa: BLE001
            # **Fails open, loudly.** A resolver that cannot answer must not
            # take a hospital's laboratory offline; the service-layer guards
            # still refuse the acts that matter, and this is logged for the
            # platform team rather than swallowed.
            logger.exception("Could not resolve entitlements for %s", organization)
            return None

        if not is_entitled:
            refused = SubscriptionInactive(detail={"organization": str(organization.uuid)})
            return JsonResponse(refused.as_payload(), status=refused.status_code)
        if module not in held:
            refused = EntitlementError(
                f"The '{module}' module is not included in this subscription.",
                detail={"module": module},
            )
            return JsonResponse(refused.as_payload(), status=refused.status_code)
        return None


def gate_report() -> str:
    """Which API prefixes are gated, for the audit command and the tests."""
    return json.dumps(dict(GATED_PREFIXES), indent=2, sort_keys=True)
