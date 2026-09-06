"""The one search box.

`GET /api/search/?q=ram` asks every source the caller is allowed to ask, and
returns what each found, grouped by source with a count that describes only what
the caller may see.

`?types=patient,invoice` narrows it. Given no types, every permitted source
runs -- which is the point of a global search, and also the reason the per-source
limit is small.

**Sources the caller cannot use are named in `refused`, not silently dropped.**
The same argument as the report library: somebody who cannot see a domain they
know exists concludes the system does not have it, while somebody told they lack
`employee.read` asks for it, which is the conversation that should happen. The
refusal names the permission and nothing else -- never a count, never whether
anything would have matched.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditSeverity
from apps.audit.services import record
from apps.common.permissions import get_authorization
from apps.rbac.permissions import Scope
from apps.search.sources import PER_SOURCE_LIMIT, all_sources, get_source

#: Below this, a search is a fishing trip rather than a lookup. Two characters
#: against a patient table is every patient whose name contains "ra".
MINIMUM_TERM = 2


class GlobalSearchView(APIView):
    """Search everything the caller is allowed to search."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        term = (request.query_params.get("q") or "").strip()
        if len(term) < MINIMUM_TERM:
            return Response(
                {
                    "error": {
                        "code": "search_term_too_short",
                        "message": f"Enter at least {MINIMUM_TERM} characters.",
                        "detail": {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        authorization = get_authorization(request)
        wanted = self._wanted(request)
        limit = self._limit(request)

        groups, refused, unknown = [], [], []
        for code in wanted:
            source = get_source(code)
            if source is None:
                unknown.append(code)
                continue
            # Held or the query is never issued. Running it and filtering
            # afterwards is not filtering: it produces a count that leaks and a
            # read that should not have happened.
            if not (authorization
                    and authorization.has(source.permission, Scope.OWN)):
                refused.append({
                    "type": source.code,
                    "label": source.label,
                    "needs": source.permission,
                })
                continue
            groups.append({
                "type": source.code,
                "label": source.label,
                "narrowed_to_your_patients": source.is_clinical,
                "results": source.find(term, request, limit),
            })

        found = sum(len(group["results"]) for group in groups)
        self._record(term, groups, found)
        return Response({
            "query": term,
            # The count of what this caller may see, full stop. "42 results, 3
            # shown" would tell them the other 39 exist, which is usually the
            # entire secret.
            "count": found,
            "groups": [group for group in groups if group["results"]],
            "searched": [group["type"] for group in groups],
            "refused": refused,
            "unknown_types": unknown,
        })

    def _wanted(self, request):
        raw = (request.query_params.get("types") or "").strip()
        if not raw:
            return [source.code for source in all_sources()]
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _limit(self, request):
        try:
            asked = int(request.query_params.get("limit", PER_SOURCE_LIMIT))
        except (TypeError, ValueError):
            return PER_SOURCE_LIMIT
        # Clamped rather than trusted. `?limit=100000` on eleven sources is a
        # denial of service written in a query string, and an export of the
        # patient index dressed as a search.
        return max(1, min(asked, PER_SOURCE_LIMIT * 2))

    def _record(self, term, groups, found):
        """One audit event for the search, not one per hit.

        A search touching twenty-five patients must not write twenty-five access
        rows; that drowns the log `record_patient_access` exists to keep
        readable. The term is recorded, because "who searched for that name the
        week the minister was admitted?" is a question hospitals have to answer.
        """
        touched_people = any(
            get_source(group["type"]).about_patients and group["results"]
            for group in groups
        )
        # Counted separately, because they are a different act. A hit reached
        # by naming a record exactly is a lookup somebody was handed; a hit
        # reached by browsing is one the relationship allowed. A row of
        # searches that are all lookups against records the searcher has no
        # relationship with is somebody walking the reference sequence, and
        # that pattern is only visible if the two are not added together.
        by_reference = sum(
            1
            for group in groups
            for hit in group["results"]
            if hit.get("by_reference")
        )
        record(
            action=(AuditAction.VIEW_SENSITIVE if touched_people
                    else AuditAction.VIEW),
            entity_type="search",
            entity_label=term,
            severity=(AuditSeverity.SENSITIVE if touched_people
                      else AuditSeverity.INFO),
            metadata={
                "term": term,
                "types": [group["type"] for group in groups],
                "hits": found,
                "by_reference": by_reference,
            },
        )


class SearchSourcesView(APIView):
    """What the box can look in, and which of those this caller may use."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        authorization = get_authorization(request)
        return Response({
            "sources": [
                {
                    "type": source.code,
                    "label": source.label,
                    "needs": source.permission,
                    "narrowed_to_your_patients": source.is_clinical,
                    "you_may_search_it": bool(
                        authorization
                        and authorization.has(source.permission, Scope.OWN)
                    ),
                }
                for source in all_sources()
            ],
            "minimum_characters": MINIMUM_TERM,
            "per_source_limit": PER_SOURCE_LIMIT,
        })
