"""The report library: what exists, and running one.

Two endpoints and a deliberate absence.

**`GET /api/reports/`** lists what this system can tell you, grouped, with the
question each report answers rather than only its name. "Trial balance" means
nothing to the person who needs to know whether the books balance.

**`GET /api/reports/<code>/`** runs one, as JSON or as CSV with
`?export=csv`.

**There is no endpoint that runs arbitrary anything.** The registry is a fixed
list of functions somebody has checked, and the permission each declares is
enforced here. A reporting layer is exactly where somebody would look for a way
around the access controls — a report is a bulk read wearing a respectable hat
— so this one refuses on the same permissions as everything else.
"""

import csv
import io

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.exports import record_export
from apps.common.dates import as_date
from apps.common.permissions import get_authorization
from apps.rbac.permissions import Scope
from apps.reporting.registry import PARAMETERS, all_reports, call, get_report


class ReportLibraryView(APIView):
    """What this system can tell you, and what each report needs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        authorization = get_authorization(request)
        library = []
        for report in all_reports():
            # Reports the caller cannot run are listed but marked, rather than
            # hidden. Somebody who cannot see a report they have heard of asks
            # whether the system has it at all; somebody who sees it greyed out
            # asks for the permission, which is the conversation that should
            # happen.
            allowed = bool(
                authorization
                and authorization.has(report.permission, Scope.OWN)
            )
            library.append({
                "code": report.code,
                "name": report.name,
                "answers": report.answers,
                "group": report.group,
                "parameters": [
                    {
                        "name": name,
                        "description": PARAMETERS[name],
                        "required": name in report.requires,
                    }
                    for name in report.parameters
                ],
                "is_heavy": report.is_heavy,
                "permission": report.permission,
                "you_may_run_it": allowed,
            })
        return Response({"parameters": PARAMETERS, "reports": library})


class RunReportView(APIView):
    """Run one report. Permission enforced from the registry entry."""

    permission_classes = [IsAuthenticated]

    def get(self, request, code):
        report = get_report(code)
        if report is None:
            return Response(
                {"detail": f"No report called '{code}'."},
                status=status.HTTP_404_NOT_FOUND,
            )

        authorization = get_authorization(request)
        if authorization is None or not authorization.has(
            report.permission, Scope.OWN,
        ):
            return Response(
                {"detail": f"Running this report needs "
                           f"'{report.permission}'."},
                status=status.HTTP_403_FORBIDDEN,
            )

        given, missing = self._parameters(request, report)
        if missing:
            return Response(
                {
                    "detail": f"{report.name} needs {', '.join(missing)}.",
                    "parameters": [
                        {"name": name, "description": PARAMETERS[name]}
                        for name in report.parameters
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = call(report, given)

        # `export`, not `format`. DRF reserves `format` for content
        # negotiation, so `?format=csv` with no CSV renderer registered is a
        # 404 from the router before this method is ever reached -- a
        # not-found error for a resource that plainly exists, which is a
        # miserable thing to debug.
        if request.query_params.get("export") == "csv":
            return self._csv(
                report,
                result,
                request.query_params.get("section", ""),
                {key: str(value) for key, value in given.items()},
            )
        return Response({
            "report": report.code,
            "name": report.name,
            "answers": report.answers,
            "parameters": {key: str(value) for key, value in given.items()},
            # Which parts of this result are tables, computed here rather than
            # guessed by every reader. The screen needs it to render each
            # section as its own table instead of picking the first one, and
            # the export needs it to know whether `?section=` is required.
            "sections": sorted(self._tables_in(result)),
            "result": result,
        })

    def _parameters(self, request, report):
        """Read the declared parameters, parsed at the boundary.

        Dates are parsed here rather than passed through as strings: a service
        that does arithmetic on a query-string date raises rather than
        filtering, which this project has been bitten by once already.
        """
        from apps.organization.models import Facility

        given = {}
        params = request.query_params
        for name in report.parameters:
            raw = params.get(name)
            if raw in (None, ""):
                continue
            if name in ("since", "until"):
                given[name] = as_date(raw)
            elif name == "days":
                given[name] = int(raw)
            elif name == "facility":
                found = Facility.objects.filter(uuid=raw).first()
                if found is not None:
                    given[name] = found
        missing = [name for name in report.requires if name not in given]
        return given, missing

    def _tables_in(self, result):
        """Every part of a result that is genuinely a table.

        A list of dictionaries is one. A dictionary may hold several -- a
        balance sheet holds assets, liabilities and equity -- and that is the
        case this method exists for.
        """
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return {"": result}
        if not isinstance(result, dict):
            return {}
        return {
            key: value
            for key, value in result.items()
            if isinstance(value, list) and value and isinstance(value[0], dict)
        }

    def _csv(self, report, result, section="", parameters=None):
        """Flatten a report to CSV, or say plainly which part to ask for.

        A dict of dicts is not a table, and inventing a shape for one produces
        a spreadsheet whose columns mean different things further down the
        page.

        **The first draft took the first table it found and exported that.** On
        a balance sheet that is `assets` -- so `finance.balance_sheet.csv`
        would have contained the assets alone, under a filename that says
        balance sheet, with the liabilities silently absent. A spreadsheet that
        is half a balance sheet is worse than no spreadsheet, because it looks
        complete. So a result holding more than one table now refuses and names
        them, and `?section=` picks one.
        """
        tables = self._tables_in(result)
        if not tables:
            return Response(
                {
                    "detail": f"{report.name} is not a table, so it has no "
                              "CSV form. Ask for it as JSON.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if section:
            if section not in tables:
                return Response(
                    {
                        "detail": f"{report.name} has no section called "
                                  f"'{section}'.",
                        "sections": sorted(tables),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            rows = tables[section]
        elif len(tables) == 1:
            rows = next(iter(tables.values()))
            section = next(iter(tables))
        else:
            return Response(
                {
                    "detail": f"{report.name} has {len(tables)} tables in it, "
                              "and exporting one of them under this report's "
                              "name would look like the whole thing. Ask for "
                              "one with ?section=.",
                    "sections": sorted(tables),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=list(rows[0].keys()), extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        # The section is in the filename. Somebody with three files in a
        # downloads folder should be able to tell the liabilities from the
        # assets without opening them.
        name = f"{report.code}.{section}" if section else report.code
        response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        # Logged as an export, not as a view. A read shows one screen to one
        # person inside a system that can still refuse them tomorrow; an export
        # makes a copy that leaves, and after that no permission here governs
        # it. The row count and the parameters go in, so "what was in that
        # file?" is answerable a year later without keeping the file.
        record_export(
            report.code,
            label=f"{report.name}{f' ({section})' if section else ''}",
            rows=len(rows),
            parameters=parameters or {},
            entity_type="report",
        )
        return response
