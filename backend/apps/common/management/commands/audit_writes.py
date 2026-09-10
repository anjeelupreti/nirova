"""Which write endpoints take no more authority than reading them.

**Written after finding the queue.** `QueueViewSet` declared
`HasPermission.of("encounter.read", scope=Scope.OWN)` and nothing else, and
DRF's `@action(methods=["post"])` inherits the class's permission classes. So
`call-next`, `recall`, `start` and `complete` -- the four verbs that move a
waiting room -- were guarded by a *read* permission. A lab technician could
complete somebody's consultation. So could an **auditor**, a role whose entire
purpose is that it changes nothing.

`HasPermission.of(..., write=...)` exists precisely so that this is stated
rather than defaulted, and its docstring records a measurement that found 31
routes accepting writes from people who should not have one. That measurement
was a one-off script. This is the same question asked repeatably, which is the
difference between a bug that was fixed and a class of bug that stays fixed.

**Three ways a write can be authorised, and this looks for all three:**

1. `write=` on the declaring `HasPermission` -- the intended way.
2. A per-action `get_permissions()` -- resolved by *instantiating the view and
   setting `self.action`*, so a viewset that branches per action is read the
   way DRF reads it, not the way a regular expression guesses.
3. `authorization.require(...)` inside the handler -- found by parsing the
   function body, because a check written in the body is still a check.

Anything with none of the three, whose read code is a `.read` permission, is
reported. The read code is then the *whole* authority for the write, which is
the defect.

    manage.py audit_writes             # the findings, grouped by module
    manage.py audit_writes --all       # every write route and its authority
    manage.py audit_writes --roles     # name the seeded roles that get through
"""

import ast
import inspect
import textwrap
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.urls import get_resolver

# The scope ladder and the seeded role table, so `--roles` can answer "who
# actually gets through" rather than "which permission is missing". A finding
# nobody can put a name to does not get fixed.
from apps.rbac.permissions import Scope
from apps.rbac.services import SYSTEM_ROLES

#: Verbs that change something. `OPTIONS` and `HEAD` are not writes however
#: DRF routes them.
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

#: Where DRF's generic write actions actually do their work.
#:
#: `ModelViewSet.partial_update` calls `update`, which calls `perform_update`.
#: The hook DRF documents for "do something extra when saving" is the
#: `perform_*` one, so that is where a codebase puts its checks -- and a
#: reader looking only at the action name concludes there is no check.
DELEGATES = {
    "create": ("perform_create",),
    "update": ("perform_update",),
    "partial_update": ("update", "perform_update"),
    "destroy": ("perform_destroy",),
}

#: Endpoints whose write is open on purpose, keyed by the view class name.
#:
#: Written down rather than inferred. Signing in is a write -- it issues a
#: token -- that by definition cannot require a permission; dismissing your own
#: notification is a write whose subject and object are the same person, which
#: is the self-service principle the rest of the codebase already follows.
#: Every entry here is a claim somebody made on purpose, and the reason is the
#: point of the entry.
OPEN_BY_DESIGN = {
    "LoginView": "signing in cannot require a permission",
    "LogoutView": "signing out cannot require a permission",
    "RefreshView": "refreshing a token is the token's own authority",
    "SwitchOrganizationView": "the membership list is the authority",
    "PortalAuthView": "the patient portal's own sign-in",
    "ChangePasswordView": "your own password; the old one is the authority",
    "MeView": "your own account -- subject and object are the same person",
    "MyPreferencesView": "your own preferences",
    "PreferenceView": "your own notification preferences",
    "NotificationViewSet": "your own inbox; the receipt is the authority",
    "AttendanceViewSet": "clocking yourself in; scoped to the caller",
    "ProfileCorrectionViewSet": "asking for your own record to be corrected",
    "ShiftSwapViewSet": "asking to swap your own shift",
    "TokenRefreshView": "refreshing a token is the token's own authority",
    "BreakGlassView": (
        "break-glass is meant to be reachable by anybody with clinical "
        "access; the control is that it is recorded and reviewed, not that "
        "it is hard to press"
    ),
}

#: Reads that arrive as POSTs, keyed by `ViewClass.action`.
#:
#: A search with twenty filters, a duplicate check that takes a whole patient
#: record, a quotation that prices a basket, a preview of what a change would
#: do -- all of these are questions, not changes. They are POSTs because the
#: question does not fit in a query string, and requiring a *write* permission
#: for them would refuse the read to the people whose job is to ask.
#:
#: Named individually rather than pattern-matched on "preview" or "quote",
#: because a list of names is a list of decisions and a pattern is a loophole
#: waiting for somebody to name an endpoint `preview_and_apply`.
READ_SHAPED_POST = {
    "PatientViewSet.check_duplicates": "a search, not a merge",
    "PrescriptionViewSet.preview": "prices a prescription without writing one",
    "SaleViewSet.quote": "prices a basket without selling it",
    "FacilityChangeRequestViewSet.preview": (
        "shows what a change would do; the change itself is `decide`"
    ),
    "ExpenseViewSet.create": (
        "claiming an expense is not posting one -- deliberately `report.read`, "
        "so that anybody who can see the books can submit a taxi fare and "
        "only `finance.post` can approve it"
    ),
}


class Command(BaseCommand):
    help = "Report write endpoints guarded only by a read permission."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true",
            help="List every write route with the authority it takes.",
        )
        parser.add_argument(
            "--roles", action="store_true",
            help="Name the seeded roles that pass each finding's gate.",
        )
        parser.add_argument("--module", help="Only paths containing this.")

    def handle(self, *args, **options):
        findings, stated, excused = [], [], []

        for route in self._write_routes():
            if options.get("module") and options["module"] not in route["path"]:
                continue
            why = OPEN_BY_DESIGN.get(route["view"]) or READ_SHAPED_POST.get(
                f"{route['view']}.{route['action']}"
            )
            if why:
                excused.append((route, why))
            elif route["write_authority"]:
                stated.append(route)
            else:
                findings.append(route)

        if options["all"]:
            self._report_all(stated)

        by_module = defaultdict(list)
        for route in findings:
            parts = route["path"].strip("/").split("/")
            by_module[parts[1] if len(parts) > 1 else "?"].append(route)

        for module in sorted(by_module):
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(module))
            for route in sorted(by_module[module], key=lambda r: r["path"]):
                verbs = ",".join(sorted(route["methods"]))
                self.stdout.write(self.style.WARNING(
                    f"    {verbs:<18} {route['path']}"
                ))
                self.stdout.write(
                    f"    {'':<18} {route['view']}.{route['action']} "
                    f"-- guarded by {route['read_code'] or 'nothing'!r} only"
                )
                if options["roles"]:
                    who = self._roles_passing(route)
                    self.stdout.write(
                        f"    {'':<18} reachable by: "
                        f"{', '.join(who) or '(no seeded role)'}"
                    )

        self.stdout.write("")
        self.stdout.write(
            f"{len(findings)} write route(s) take no more authority than "
            f"reading, {len(stated)} state a write permission, "
            f"{len(excused)} open by design."
        )
        if findings:
            self.stdout.write("")
            self.stdout.write(
                "Each of these accepts a change from everybody who can see "
                "the screen. Declare the authority with "
                "`HasPermission.of(read, write=...)`, with a per-action "
                "`get_permissions()`, or add the view to OPEN_BY_DESIGN with "
                "the reason."
            )

    # -- internals --------------------------------------------------------

    def _report_all(self, stated):
        self.stdout.write(self.style.SUCCESS("Write routes with stated authority"))
        for route in sorted(stated, key=lambda r: r["path"]):
            self.stdout.write(
                f"    {route['path']:<58} {route['write_authority']}"
            )

    def _write_routes(self):
        """Every routed handler that accepts an unsafe verb, with its guard."""
        routes = []
        seen = set()

        def walk(patterns, prefix=""):
            for entry in patterns:
                pattern = prefix + str(entry.pattern)
                if hasattr(entry, "url_patterns"):
                    walk(entry.url_patterns, pattern)
                    continue
                # DRF's format-suffix routes are the same endpoint with
                # `.json` on the end; counting them doubles every router's
                # contribution and adds no finding.
                if "format" in pattern:
                    continue
                view = getattr(entry.callback, "cls", None)
                if view is None:
                    continue
                path = "/" + (
                    pattern.replace("\\.", ".").replace("^", "").replace("$", "")
                ).lstrip("/")
                if not path.startswith("/api/"):
                    continue

                # A router-generated viewset carries its verb->action map in
                # `initkwargs`; an APIView does not, and its unsafe verbs are
                # whichever handlers it defines.
                # `as_view(actions)` hangs the map on the *callback*, not in
                # `initkwargs`. Reading only `initkwargs` found nothing, every
                # viewset fell through to the APIView branch, and a viewset
                # has no `post` attribute -- so the first run of this command
                # reported 33 write routes out of several hundred and looked
                # reassuring. A tool that under-reports is worse than none.
                actions = getattr(entry.callback, "actions", None) or (
                    getattr(entry.callback, "initkwargs", {}).get("actions")
                )
                # **A router maps every verb; the view decides which it
                # answers.** `http_method_names` is how a viewset says "reads
                # and creates only", and DRF returns 405 for the rest before
                # any permission runs. Ignoring it made this command report
                # `EncounterViewSet.destroy` and a dozen like it as unguarded
                # writes -- routes that cannot be called at all. A finding
                # that cannot happen is worse than no finding, because
                # somebody spends an afternoon proving it cannot happen.
                answered = {
                    m.upper() for m in getattr(
                        view, "http_method_names",
                        [m.lower() for m in UNSAFE],
                    )
                }
                if actions:
                    by_action = defaultdict(set)
                    for method, action in actions.items():
                        if method.upper() in UNSAFE & answered:
                            by_action[action].add(method.upper())
                    pairs = list(by_action.items())
                else:
                    methods = {
                        m for m in UNSAFE & answered if hasattr(view, m.lower())
                    }
                    pairs = [(None, methods)] if methods else []

                for action, methods in pairs:
                    key = (view.__name__, action)
                    if key in seen:
                        continue
                    seen.add(key)
                    routes.append(self._describe(path, view, action, methods))

        walk(get_resolver().url_patterns)
        return routes

    def _describe(self, path, view, action, methods):
        """The authority one routed handler actually takes.

        `get_permissions()` is called on a real instance with `self.action`
        set, because that is how DRF decides. Reading the class attribute
        instead would miss every viewset that varies its guard per action --
        and those are exactly the ones somebody thought carefully about.
        """
        read_code = write_code = ""
        others = []
        try:
            instance = view()
            instance.action = action
            instance.request = None
            permissions = instance.get_permissions()
        except Exception:  # noqa: BLE001 -- a view we cannot build standalone
            permissions = [p() for p in getattr(view, "permission_classes", [])]

        for permission in permissions:
            code = getattr(permission, "permission_code", None)
            if code is None:
                others.append(type(permission).__name__)
                continue
            read_code = read_code or code
            write_code = write_code or getattr(permission, "write_code", "")

        in_body = self._body_requires(view, action)

        # The authority a *write* takes, as opposed to the authority a read
        # takes. An explicit `write=` states it; a `require()` in the body
        # states it; and a read code that is not a `.read` permission states
        # it too -- `HasPermission.of("stock.adjust")` on a POST is a write
        # permission written in the read slot, which is untidy but not a hole.
        authority = write_code or in_body
        if not authority and read_code and not read_code.endswith(".read"):
            authority = read_code
        # A view guarded by something other than `HasPermission` -- platform
        # staff, the portal's own token -- takes an authority this command
        # cannot name, and calling it unguarded would be false.
        named = sorted(set(others) - {"IsAuthenticated"})
        if not authority and not read_code and named:
            authority = "+".join(named)

        return {
            "path": path,
            "view": view.__name__,
            "action": action or "http verb",
            "methods": methods,
            "read_code": read_code,
            "write_authority": authority,
            "others": named,
        }

    def _body_requires(self, view, action):
        """A permission code asserted by `authorization.require(...)` inline.

        Parsed rather than executed: running the handler to find out what it
        checks would need a request, a tenant and a database, and the question
        is answerable from the source. Inherited handlers count, so the whole
        MRO is read rather than the leaf class.
        """
        found = []
        for klass in view.__mro__:
            try:
                source = inspect.getsource(klass)
            except (OSError, TypeError):
                continue
            # (parsed below; helper calls are followed one level, see
            # `_requires_in`)
            # `textwrap.dedent`, never `inspect.cleandoc`. `cleandoc`
            # computes its margin from the lines *after* the first, which for
            # a class is the body -- so it dedented every method to column
            # zero under a `class X:` line that stayed put, every parse raised
            # `SyntaxError`, and every inline `require()` in the codebase went
            # unseen. The command then reported guarded endpoints as
            # unguarded, which is the failure mode that wastes the most time:
            # a tool that cries wolf gets ignored, including when it is right.
            try:
                tree = ast.parse(textwrap.dedent(source))
            except SyntaxError:
                continue
            methods = {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
            }
            # **DRF's generic writes delegate, and the delegate is where the
            # check goes.** `partial_update` is almost never overridden;
            # `perform_update` is, and that is the documented hook. Reading
            # only the action name reported `EmployeeViewSet.partial_update`
            # as unguarded while `perform_update` five lines below required
            # `employee.manage`.
            delegates = DELEGATES.get(action, ())
            for name, node in methods.items():
                if action and name != action and name not in delegates:
                    continue
                if not action and name.upper() not in UNSAFE:
                    continue
                found.extend(self._requires_in(node, methods))
            if found:
                break
        return "+".join(sorted(set(found)))

    def _requires_in(self, node, methods, seen=None):
        """Codes asserted in this function, following `self.helper()` calls.

        **One level of indirection is the common case and had to be handled.**
        The blood bank, the ICU and the theatre all factor their check into a
        `_writable()` helper and call it from a dozen actions. Reading only
        the action body reported every one of those as unguarded -- forty-odd
        false findings, in the modules where a false finding is most expensive
        because they are the ones somebody would have to read carefully to
        disprove.

        Bounded by `seen` rather than by a depth counter: a helper that calls
        itself is a bug, but it is not this command's job to hang because of
        one.
        """
        seen = seen if seen is not None else set()
        if node.name in seen:
            return []
        seen.add(node.name)

        codes = []
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            target = ast.unparse(call.func)
            if target.endswith(".require") and call.args:
                try:
                    codes.append(ast.literal_eval(call.args[0]))
                except ValueError:
                    # A code built at runtime -- `f"{module}.read"`. Named
                    # rather than dropped: "there is a check here and it
                    # cannot be read statically" is a different answer from
                    # "there is no check here".
                    codes.append("(computed)")
            elif target.startswith("self.") and target.count(".") == 1:
                helper = methods.get(target.removeprefix("self."))
                if helper is not None:
                    codes.extend(self._requires_in(helper, methods, seen))
        return codes

    def _roles_passing(self, route):
        """Seeded roles whose permissions satisfy this gate.

        Exact membership, never substring: `"sale.return" in "sale.return_
        approve"` is `True`, and that mistake has already cost this codebase a
        test that proved nothing.
        """
        needed = route["read_code"]
        who = []
        for role in SYSTEM_ROLES:
            granted = set(role.get("permissions", ()))
            if needed and needed not in granted:
                continue
            if Scope.covers(role.get("max_scope", Scope.FACILITY), Scope.OWN):
                who.append(role["code"])
        return sorted(who)
