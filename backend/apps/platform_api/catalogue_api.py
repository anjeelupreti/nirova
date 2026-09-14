"""The catalogue, editable — and moving a customer between plans.

Until now `PlanViewSet` was read-only and the only way to price anything was
a seed and a deployment. These endpoints give the commercial side the two acts
they actually perform: **change what is for sale**, and **change what one
customer has bought** — the second with the consequences shown before it is
done, because a plan change silently removing Laboratory from a hospital is
the kind of support call that ends a contract.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.catalog import editing
from apps.catalog.models import Feature, Module, Plan
from apps.common.exceptions import DomainError
from apps.common.permissions import IsPlatformStaff
from apps.entitlements.resolver import resolve_entitlements
from apps.subscriptions.models import Subscription


def _audit(action, label, **metadata):
    """Platform acts are logged in the control plane's own trail.

    `record` writes to the *tenant* log and returns None with no tenant
    bound, which is correct for clinical work and wrong here — so platform
    edits carry the organization they affect in their metadata and are
    written wherever the caller is bound. The catalogue itself is global; the
    line that matters is who changed the price of what, and when.
    """
    record(
        action,
        entity_type="catalog.Plan",
        entity_label=label,
        metadata={"platform": True, **metadata},
    )


class CatalogueView(APIView):
    """`GET` — every module, feature, limit key and plan, in one payload.

    `POST` — create a plan.
    """

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        return Response(editing.catalogue())

    def post(self, request):
        plan = editing.create_plan(
            code=request.data.get("code", ""),
            name=request.data.get("name", ""),
            **{
                key: value for key, value in request.data.items()
                if key in editing.PLAN_FIELDS and key != "name"
            },
        )
        _audit(AuditAction.CREATE, f"Plan {plan.code} created")
        return Response(editing.plan_detail(plan), status=status.HTTP_201_CREATED)


class PlanEditView(APIView):
    """`PATCH` one plan's own fields; `GET` it with everything attached."""

    permission_classes = [IsPlatformStaff]

    def get(self, request, code):
        return Response(editing.plan_detail(get_object_or_404(Plan, code=code)))

    def patch(self, request, code):
        plan = get_object_or_404(Plan, code=code)
        before = {key: getattr(plan, key) for key in request.data if key in editing.PLAN_FIELDS}
        plan = editing.update_plan(plan, {
            key: value for key, value in request.data.items() if key in editing.PLAN_FIELDS
        })
        _audit(
            AuditAction.UPDATE, f"Plan {plan.code} changed",
            changes={key: {"from": str(value), "to": str(getattr(plan, key))}
                     for key, value in before.items()},
        )
        return Response(editing.plan_detail(plan))


class PlanCompositionView(APIView):
    """What a plan contains: `part` is `modules`, `features` or `limits`.

    `GET ?part=modules` returns the impact of *removing* nothing — that is,
    who is on the plan. `PUT` replaces that part of the plan; a change that
    takes something away is refused with the impact attached until the caller
    sends `confirm: true`.
    """

    permission_classes = [IsPlatformStaff]

    SETTERS = {
        "modules": editing.set_plan_modules,
        "features": editing.set_plan_features,
        "limits": editing.set_plan_limits,
    }

    def get(self, request, code, part):
        plan = get_object_or_404(Plan, code=code)
        if part not in self.SETTERS:
            raise DomainError(f"'{part}' is not part of a plan.")
        return Response(editing.impact_of(plan))

    def put(self, request, code, part):
        plan = get_object_or_404(Plan, code=code)
        setter = self.SETTERS.get(part)
        if setter is None:
            raise DomainError(f"'{part}' is not part of a plan.")
        wanted = request.data.get(part)
        if not isinstance(wanted, dict):
            raise DomainError(f"Send the whole set of {part} as an object.")
        impact = setter(plan, wanted, confirm=bool(request.data.get("confirm")))
        _audit(
            AuditAction.UPDATE, f"Plan {plan.code}: {part} changed",
            metadata={"platform": True, "part": part, "affected": impact["organizations"]},
        )
        return Response({"plan": editing.plan_detail(plan), "impact": impact})


class ModuleEditView(APIView):
    """A module's saleable metadata. Its *existence* comes from the code."""

    permission_classes = [IsPlatformStaff]

    def patch(self, request, code):
        module = get_object_or_404(Module, code=code)
        editing.update_module(module, dict(request.data))
        return Response(editing.catalogue()["modules"])


class FeatureEditView(APIView):
    permission_classes = [IsPlatformStaff]

    def patch(self, request, code):
        feature = get_object_or_404(Feature, code=code)
        editing.update_feature(feature, dict(request.data))
        return Response(editing.catalogue()["features"])


class PlanChangeView(APIView):
    """Move one customer to another plan.

    `GET ?plan=<code>` previews it: what they gain, what they lose, what it
    costs. `POST {plan, reason}` applies it. The preview is not a courtesy —
    it is how somebody notices that the "cheaper" plan they were about to
    move a hospital onto does not include the ward module it admits patients
    with.
    """

    permission_classes = [IsPlatformStaff]

    def _compare(self, subscription: Subscription, plan: Plan) -> dict:
        organization = subscription.organization
        before = resolve_entitlements(organization)
        after_modules = {
            row.module.code for row in plan.plan_modules.select_related("module")
            if row.is_included
        }
        after_features = {
            row.feature.code for row in plan.plan_features.select_related("feature")
            if row.is_enabled
        }
        held_modules = {code for code, on in before.modules.items() if on}
        held_features = {code for code, on in before.features.items() if on}
        limits = {}
        for row in plan.limits.all():
            current = before.limit(row.key)
            if current.value != row.value:
                limits[row.key] = {
                    "from": current.value, "to": row.value,
                    "tighter": row.value is not None and (
                        current.value is None or row.value < current.value
                    ),
                }
        return {
            "organization": organization.display_name,
            "from_plan": subscription.plan.code,
            "to_plan": plan.code,
            "gains_modules": sorted(after_modules - held_modules),
            "loses_modules": sorted(held_modules - after_modules),
            "gains_features": sorted(after_features - held_features),
            "loses_features": sorted(held_features - after_features),
            "limit_changes": limits,
            "price": {
                "from": str(subscription.contracted_price or subscription.plan.base_price),
                "to": str(plan.base_price),
                "currency": plan.currency,
            },
            "loses_something": bool(
                (held_modules - after_modules) or (held_features - after_features)
                or any(row["tighter"] for row in limits.values())
            ),
        }

    #: A subscription in one of these is history. Moving it between plans
    #: changes nothing for the customer and rewrites what they were on when
    #: it ended — found by previewing a change against a cancelled
    #: subscription and being shown a confident, meaningless diff.
    CLOSED = {"cancelled", "expired", "draft"}

    def _live(self, uuid) -> Subscription:
        subscription = get_object_or_404(Subscription, uuid=uuid)
        if subscription.status in self.CLOSED:
            raise DomainError(
                f"That subscription is {subscription.get_status_display().lower()}. "
                "Start a new one rather than moving a closed one between plans.",
                code="subscription_closed",
            )
        return subscription

    def get(self, request, uuid):
        subscription = self._live(uuid)
        plan = get_object_or_404(Plan, code=request.query_params.get("plan", ""))
        return Response(self._compare(subscription, plan))

    def post(self, request, uuid):
        subscription = self._live(uuid)
        plan = get_object_or_404(Plan, code=request.data.get("plan", ""))
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise DomainError("Say why this customer is moving plan.", code="reason_required")

        preview = self._compare(subscription, plan)
        if preview["loses_something"] and not request.data.get("confirm"):
            raise DomainError(
                "This plan takes capabilities away from a live customer. "
                "Confirm to continue.",
                code="needs_confirmation",
                detail={"preview": preview},
            )

        was = subscription.plan
        subscription.plan = plan
        subscription.contracted_price = plan.base_price
        subscription.billing_interval = plan.billing_interval
        subscription.save(update_fields=[
            "plan", "contracted_price", "billing_interval", "updated_at",
        ])
        record(
            AuditAction.UPDATE,
            entity_type="subscriptions.Subscription",
            entity_id=subscription.uuid,
            entity_label=f"{subscription.organization.display_name}: {was.code} → {plan.code}",
            reason=reason,
            metadata={"platform": True, "preview": preview},
        )
        return Response({"subscription": str(subscription.uuid), "applied": preview})
