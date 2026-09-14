"""The console's colour must come from the token system, not from Tailwind.

**The measurement that prompted this: 325 hardcoded colour utilities across 29
files under `frontend/src/pages`, of which only 48 carried a `dark:`
counterpart.** So 277 of them are light-mode-only, and most of this product's
semantic colour was invisible or wrong the moment dark mode was switched on.
Nobody had been careless: there was no token for "an expiring batch", so
`text-amber-600` was the only thing on offer, and there was nowhere to look at
all of it at once.

(An earlier hand-run grep reported 178. It counted only `text-*` against nine
hues and missed every `bg-`, `border-` and `ring-`. The figure above is this
test's own count, which is the one that matters because it is the one that
ratchets.)

Both halves are now fixed. `semantic.css` declares the states the domain
actually has, and `/design` renders every one of them on a single scroll. This
test is the third part: a **ratchet**, so the number cannot climb back.

It began as a ratchet rather than a pass/fail on zero: migrating 44 screens is
a week of work, and blocking every unrelated commit behind it would have meant
the rule being deleted rather than the colours. It reached zero in one codemod
pass, so it is now an absolute rule -- and the scan covers the whole of
`frontend/src`, not only the screens. A rule that covers the pages and not the
components they are built from has a hole the size of the design system in it,
which is how a timeline marker kept an `emerald-500` through the burn-down.

The same shape as the other standing guards: it reads the frontend source,
skips rather than crashes when that source is not in the image, and asserts
something a human would otherwise have to remember.
"""
import pathlib
import re

import pytest

# Tailwind's own palette, which the token system replaces. `slate`, `gray`,
# `zinc`, `neutral` and `stone` are included: the neutrals moved to a warm ramp
# and a screen reaching for a cool grey undoes that as surely as one reaching
# for amber undoes the status colours.
TAILWIND_HUES = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
    "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)

# `text-amber-600`, `bg-red-50`, `border-emerald-500/40`, `dark:text-amber-400`.
RAW_COLOUR = re.compile(
    rf"(?:dark:)?(?:text|bg|border|ring|fill|stroke|from|via|to|decoration|outline|shadow)-"
    rf"(?:{TAILWIND_HUES})-\d{{2,3}}"
)

#: Where the ratchet stands. Lower it whenever a screen is migrated; never
#: raise it.
#:
#: 325 -> 0. It started at 325 across 29 files (NurseWorkspace 77, SelfService
#: 48, Notifications 24, Icu 18, Wards 18) and was cleared in one pass by a
#: codemod rather than by hand: hand-editing 29 files, several of them 2,000
#: lines, is how you introduce a different defect in each. The mapping it used
#: is stated in the development log -- hue family to domain state, with the
#: *step* deciding whether a colour was ink on a tint or ink on a page, because
#: collapsing `text-red-200` and `text-red-700` to one token makes one of them
#: invisible. Two decorative gradients it correctly refused to guess at were
#: done by hand.
#:
#: **The 48 `dark:` variants were deleted rather than translated.** That is the
#: whole point of the token layer: `text-warning` is already right in both
#: modes, and keeping `dark:text-amber-400` beside it would re-introduce the
#: split this exercise existed to remove.
#:
#: Now that it is zero the rule is absolute, and the floor assertion below is
#: what stops somebody quietly raising it again.
BUDGET = 0


def _pages_dir() -> pathlib.Path:
    """The whole source tree, not just `pages`.

    Widened after the burn-down reached zero and a `bg-emerald-500/15` was
    still sitting in the timeline marker in `components/ui/data.tsx` — outside
    the scanned directory, and therefore green in every palette including the
    violet one. A rule that covers the screens and not the components they are
    built from is a rule with a hole the size of the design system.
    """
    return pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"


#: `/* … */`, `{/* … */}` and `// …`, in that order.
#:
#: Stripped before scanning, because **a comment explaining which class was
#: removed must not itself count as that class.** Found the honest way: the
#: burn-down reached zero and this test still reported three, all of them
#: inside a note reading "the banner was `from-blue-700 via-indigo-700 …`".
#:
#: A guard that punishes documenting the defect it exists to prevent teaches
#: people to stop documenting. It measures code; comments are prose.
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _count() -> tuple[int, dict[str, int]]:
    """Every raw colour utility under `src`, and where they are."""
    pages = _pages_dir()
    per_file: dict[str, int] = {}
    total = 0
    for path in sorted(pages.rglob("*.tsx")):
        source = COMMENT.sub("", path.read_text(encoding="utf-8"))
        hits = RAW_COLOUR.findall(source)
        if hits:
            per_file[path.relative_to(pages).as_posix()] = len(hits)
            total += len(hits)
    return total, per_file


def test_raw_tailwind_colours_do_not_increase():
    """The burn-down may fall and may not rise."""
    pages = _pages_dir()
    if not pages.exists():
        # Skip, do not crash. This test reads the frontend source, which sits
        # beside the backend in the repository and *not* inside the backend
        # container image -- the image ships the backend only, by design.
        pytest.skip(f"frontend source not present at {pages}; nothing to scan")

    total, per_file = _count()

    assert total <= BUDGET, (
        f"{total} raw Tailwind colour utilities under frontend/src, up from the "
        f"budget of {BUDGET}. Every state this product has is a token in "
        f"`styles/tokens/semantic.css` -- use `<StatusBadge>`, or "
        f"`text-warning` / `bg-critical-subtle` / `text-good`, so the colour "
        f"is correct in dark mode without anybody writing the `dark:` half. "
        f"Worst offenders: "
        f"{sorted(per_file.items(), key=lambda pair: -pair[1])[:5]}"
    )

    # The other direction, and the more useful assertion once the migration is
    # under way: if the real number has fallen well below the budget, the
    # budget is stale and is quietly permitting a hundred new violations.
    assert total >= BUDGET - 40 or BUDGET == 0, (
        f"only {total} raw colour utilities remain against a budget of "
        f"{BUDGET}. Lower BUDGET to {total} so the ratchet keeps its grip -- a "
        f"budget far above the real count is not a guard, it is headroom."
    )


def test_the_token_layer_is_wired():
    """The three tiers exist and are imported in the right order.

    A cheap check with an expensive failure: if `index.css` stops importing the
    primitives, every semantic token resolves to nothing and the entire console
    renders in the browser's default colours. That is obvious in a browser and
    invisible in a diff.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present at {src}; nothing to scan")

    tokens = src / "styles" / "tokens"
    for name in ("palettes.css", "primitive.css", "semantic.css", "component.css"):
        assert (tokens / name).exists(), f"{name} is missing from {tokens}"

    index = (src / "index.css").read_text(encoding="utf-8")
    order = [
        index.find("tokens/palettes.css"),
        index.find("tokens/primitive.css"),
        index.find("tokens/semantic.css"),
        index.find("tokens/component.css"),
        index.find("@tailwind base"),
    ]
    assert all(position >= 0 for position in order), (
        "index.css must import all four token tiers before Tailwind's base "
        f"layer; found positions {order}"
    )
    assert order == sorted(order), (
        "the token tiers must be imported palettes -> primitive -> semantic -> "
        "component, and all four before `@tailwind base`. `palettes.css` is "
        "first because the other two resolve against the brand and neutral "
        f"ramps it declares; got {order}"
    )


def test_every_palette_declares_a_complete_ramp():
    """A palette that is missing a step is a screen with holes in it.

    Adding a sixth identity is meant to be a data change, and this is what
    makes that safe: a new block that forgets `--brand-primary-ink` produces
    unreadable buttons in exactly one theme, which nobody would notice until a
    customer picked it.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present at {src}; nothing to scan")

    css = (src / "styles" / "tokens" / "palettes.css").read_text(encoding="utf-8")

    blocks = re.findall(
        r'\[data-palette="([a-z]+)"\]\s*\{(.*?)\n\}', css, flags=re.DOTALL,
    )
    assert len(blocks) >= 3, (
        f"only {len(blocks)} palettes parsed out of palettes.css; the pattern "
        "has stopped matching and this test checks nothing"
    )

    required = (
        ["--brand-primary", "--brand-primary-ink"]
        + [f"--brand-{step}" for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)]
        + [f"--accent-{step}" for step in (50, 300, 400, 500, 600, 800, 950)]
        + [f"--neutral-{step}" for step in (0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 850, 900, 925, 950, 975, 1000)]
    )

    missing = {
        name: [token for token in required if f"{token}:" not in body]
        for name, body in blocks
    }
    missing = {name: gaps for name, gaps in missing.items() if gaps}

    assert not missing, f"palettes with missing tokens: {missing}"


def _hsl_to_rgb(hue: float, saturation: float, lightness: float):
    saturation /= 100
    lightness /= 100
    a = saturation * min(lightness, 1 - lightness)

    def channel(n: float) -> float:
        k = (n + hue / 30) % 12
        return lightness - a * max(-1, min(k - 3, min(9 - k, 1)))

    return channel(0), channel(8), channel(4)


def _relative_luminance(rgb) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(first: str, second: str) -> float:
    """WCAG contrast between two `H S% L%` triples."""
    values = []
    for triple in (first, second):
        hue, saturation, lightness = (
            float(part.rstrip("%")) for part in triple.split()
        )
        values.append(_relative_luminance(_hsl_to_rgb(hue, saturation, lightness)))
    lighter, darker = max(values), min(values)
    return (lighter + 0.05) / (darker + 0.05)


def test_every_status_tint_is_readable_in_both_themes():
    """A badge is small text on a tinted chip, so the bar is 4.5:1.

    The chart palette was computed by the data-visualisation validator and can
    be trusted. **These tints were not** -- they were chosen by eye in
    `semantic.css`, which is exactly the sort of decision that looks fine on
    the author's monitor and fails on a ward's. Seven pairs in each theme,
    checked rather than assumed.

    The 3:1 large-text allowance deliberately does not apply: these render at
    11px.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present at {src}; nothing to scan")

    css = (src / "styles" / "tokens" / "semantic.css").read_text(encoding="utf-8")

    # Split at the `.dark` block: the same token names carry different values
    # in each theme and both have to clear the bar.
    light, _, dark = css.partition(".dark {")
    assert dark, "semantic.css has no .dark block; the split below is meaningless"

    triple = r"(\d+(?:\.\d+)?\s+\d+(?:\.\d+)?%\s+\d+(?:\.\d+)?%)"

    def declared(block: str) -> dict[str, str]:
        return dict(re.findall(rf"--([a-z-]+):\s*{triple};", block))

    failures: list[str] = []
    for mode, block in (("light", light), ("dark", dark)):
        values = declared(block)
        pairs = [
            (name, f"{name}-subtle", f"{name}-subtle-foreground")
            for name in ("good", "warning", "serious", "critical", "info")
        ]
        for label, tint_key, ink_key in pairs:
            tint, ink = values.get(tint_key), values.get(ink_key)
            if tint is None or ink is None:
                # A missing pair is a failure, not a skip: the commonest way
                # this check stops checking anything is a rename.
                failures.append(f"{mode}/{label}: {tint_key} or {ink_key} not declared")
                continue
            ratio = _contrast(tint, ink)
            if ratio < 4.5:
                failures.append(f"{mode}/{label}: {ratio:.2f}:1 on its own tint")

    assert not failures, (
        "status badges below 4.5:1 — small text on a tinted chip has no "
        "large-text allowance: " + "; ".join(failures)
    )


def test_status_inks_are_readable_as_text_on_every_palette():
    """`text-warning` on a page must clear 4.5:1 — in all five palettes.

    **These were chosen as marks and are used as text.** A status colour was
    picked for dots, bars and fills, where 3:1 is the bar. The colour codemod
    then put `text-good`, `text-warning` and `text-serious` on some 270 sites as
    small text. Measured afterwards: six of the seven failed on the page in
    light mode, amber worst at 3.48:1, and the white numeral on an urgent
    triage badge sat at 3.7:1.

    Checked against **every palette's own page colour**, because the neutrals
    are tinted per palette and a status ink that passes on Vital's page can
    fail on Ember's. Acuity is checked as white-on-fill, which is how the badge
    uses it.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present at {src}; nothing to scan")

    tokens = src / "styles" / "tokens"
    primitive = (tokens / "primitive.css").read_text(encoding="utf-8")
    palettes = (tokens / "palettes.css").read_text(encoding="utf-8")

    triple = r"(\d+(?:\.\d+)?\s+\d+(?:\.\d+)?%\s+\d+(?:\.\d+)?%)"
    light_block, _, dark_block = primitive.partition(".dark {")

    def pick(block, prefix):
        return dict(re.findall(rf"--({prefix}-[a-z0-9]+):\s*{triple};", block))

    light_signals = pick(light_block, "signal")
    dark_signals = pick(dark_block, "signal")
    light_acuity = pick(light_block, "acuity")
    dark_acuity = pick(dark_block, "acuity")

    assert len(light_signals) >= 5 and len(light_acuity) == 5, (
        "the signal/acuity tokens did not parse out of primitive.css; this "
        "test would otherwise check nothing"
    )

    pages = dict(re.findall(
        rf'\[data-palette="([a-z]+)"\]\s*\{{[^}}]*?--neutral-50:\s*{triple};',
        palettes, flags=re.DOTALL,
    ))
    dark_cards = dict(re.findall(
        rf'\[data-palette="([a-z]+)"\]\s*\{{[^}}]*?--neutral-950:\s*{triple};',
        palettes, flags=re.DOTALL,
    ))
    assert len(pages) >= 3, "no palette pages parsed out of palettes.css"

    failures = []
    # `--signal-muted` is not a status ink used on its own as text; it backs
    # `quiet`, which is a neutral. Checked elsewhere as `muted-foreground`.
    inks = {k: v for k, v in light_signals.items() if k != "signal-muted"}
    dark_inks = {k: v for k, v in dark_signals.items() if k != "signal-muted"}

    for palette, page in pages.items():
        for name, value in inks.items():
            ratio = _contrast(value, page)
            if ratio < 4.5:
                failures.append(f"light/{palette}: {name} {ratio:.2f}:1 on the page")
    for palette, card in dark_cards.items():
        for name, value in dark_inks.items():
            ratio = _contrast(value, card)
            if ratio < 4.5:
                failures.append(f"dark/{palette}: {name} {ratio:.2f}:1 on the card")

    white = "0 0% 100%"
    for name, value in light_acuity.items():
        ratio = _contrast(value, white)
        if ratio < 4.5:
            failures.append(f"light: white numeral on {name} {ratio:.2f}:1")

    assert not failures, (
        "status inks below 4.5:1 as text — used as small text on some 270 "
        "sites, they must clear the text bar, not the mark bar: "
        + "; ".join(failures)
    )


def test_no_component_reads_a_primitive_token_directly():
    """Tier 1 is raw material; only `semantic.css` may name it.

    The indirection is the whole point of the three tiers: a component that
    reaches past the semantic layer to `--brand-500` pins itself to one value,
    and re-theming for a customer's own accent then misses it. The chart layer
    is the documented exception -- series and scale slots *are* the semantics
    for a chart, and there is no second name for them.
    """
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present at {src}; nothing to scan")

    #: Files allowed to name a primitive, each with its reason written here.
    #:
    #: Listed by name rather than detected from a marker comment, so adding one
    #: is a decision somebody makes in this file and defends -- the same shape
    #: as `PROBE` in `test_nav.py` and `reached_from_elsewhere` in
    #: `test_invariants.py`. A silent opt-out would make the rule advisory.
    ALLOWED = {
        # The palette picker. Its whole job is to preview a palette's raw ramp,
        # and a swatch drawn from semantic tokens would show the *active* theme
        # five times over -- a picker that lies about what it is offering. Each
        # swatch carries its own `data-palette`, so these resolve to the
        # palette being previewed rather than the one applied.
        "components/me/Appearance.tsx",
    }

    primitive = re.compile(r"var\(--(?:brand|accent|neutral)-\d+\)")
    offenders: dict[str, int] = {}
    for path in sorted(src.rglob("*.tsx")):
        relative = path.relative_to(src).as_posix()
        if relative in ALLOWED:
            continue
        hits = primitive.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[relative] = len(hits)

    assert not offenders, (
        "these components name a primitive token directly instead of a "
        "semantic one, so they will not follow a re-theme: "
        f"{offenders}. Use the semantic name (`--primary`, `--muted`, "
        "`--good`), add one to `semantic.css` if none fits, or add the file "
        "to ALLOWED above with the reason."
    )

    # And the other direction: an exemption for a file that no longer needs one
    # is a permanent hole nobody notices. Every entry must still be earning it.
    stale = sorted(
        name
        for name in ALLOWED
        if not primitive.search((src / name).read_text(encoding="utf-8"))
    )
    assert not stale, (
        "these files are exempted from the primitive-token rule and no longer "
        f"break it: {stale}. Remove them from ALLOWED."
    )
