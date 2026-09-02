"""Prescribing safety checks: allergies, duplicates and interactions.

Design position, stated plainly because it governs every function here:

**This module warns; it does not block.** A clinician may have a reason to
prescribe against a recorded allergy — a documented mild rash decades ago, a
drug with no alternative, a resuscitation. Software that refuses would be
overridden by writing the prescription on paper, which loses the record
entirely. So a warning is raised, the override is captured with a reason, and
both are stored on the prescription forever.

**It fails loud, not silent.** An unconfirmed allergy still warns (see
`PatientAllergy.blocks_prescribing`). The cost of a spurious warning is a
click; the cost of a missed one can be anaphylaxis.

The interaction data below is a **deliberately small, high-severity set**, not
a drug database. Shipping a partial interaction list dressed up as
comprehensive would be worse than shipping none, because clinicians would
trust the silence. Every entry here is a well-known, clinically serious pair;
the real answer is a licensed interaction database, wired in behind
`check_interactions()` when the pharmacy catalogue lands.
"""

import logging
import re

from apps.patients.models import AllergyStatus, PatientAllergy

logger = logging.getLogger("nirova.prescribing")


class Severity:
    """How loudly a warning should present."""

    INFO = "info"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"

    #: Warnings at or above this level require an explicit override reason.
    REQUIRES_OVERRIDE = {HIGH, CRITICAL}


# ---------------------------------------------------------------------------
# Allergy checking
# ---------------------------------------------------------------------------

#: Cross-sensitivity groups. A penicillin allergy is a warning against every
#: penicillin, not only the exact one recorded, and carries a real (if
#: overstated) cross-reactivity risk with cephalosporins.
#:
#: Keyed by the family name; values are substrings matched case-insensitively
#: against generic names. Substring matching is crude but suits generic
#: naming conventions, where the stem *is* the family (-cillin, -statin).
CROSS_SENSITIVITY = {
    "penicillin": [
        "penicillin", "amoxicillin", "ampicillin", "cloxacillin",
        "flucloxacillin", "piperacillin", "co-amoxiclav", "amoxiclav",
    ],
    "cephalosporin": [
        "cefixime", "ceftriaxone", "cefotaxime", "cefuroxime", "cephalexin",
        "cefazolin", "ceftazidime", "cefpodoxime",
    ],
    "sulfonamide": ["sulfamethoxazole", "cotrimoxazole", "sulfasalazine"],
    "nsaid": [
        "ibuprofen", "diclofenac", "naproxen", "aspirin", "ketorolac",
        "indomethacin", "mefenamic",
    ],
    "quinolone": [
        "ciprofloxacin", "levofloxacin", "ofloxacin", "moxifloxacin",
        "norfloxacin",
    ],
    "macrolide": ["azithromycin", "erythromycin", "clarithromycin"],
}

#: Families with meaningful cross-reactivity between them. Reported at a lower
#: severity than a direct match, because the risk is real but much smaller --
#: modern estimates put penicillin/cephalosporin cross-reactivity around 2%,
#: not the 10% once taught.
#:
#: Written in whatever order reads naturally; `_normalise_pairs` sorts the
#: keys at import. That is not tidiness -- the lookup sorts the pair it builds,
#: so an unsorted key here would simply never match and the warning would
#: silently never fire. A safety rule that depends on an author remembering
#: alphabetical order is a safety rule waiting to fail.
_CROSS_FAMILY_RISK_SOURCE = {
    ("penicillin", "cephalosporin"): Severity.MODERATE,
}

CROSS_FAMILY_RISK = {
    tuple(sorted(pair)): severity
    for pair, severity in _CROSS_FAMILY_RISK_SOURCE.items()
}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).strip()


def _families_for(drug_name: str) -> set:
    """Which cross-sensitivity families a drug belongs to."""
    name = _normalise(drug_name)
    return {
        family
        for family, members in CROSS_SENSITIVITY.items()
        if any(member in name for member in members)
    }


def check_allergies(patient, generic_name: str, brand_name: str = "") -> list:
    """Warnings raised by prescribing `generic_name` to `patient`.

    Three kinds of match, in decreasing confidence:

    1. The drug name contains the recorded substance, or vice versa.
    2. The drug is in the same family as the recorded substance.
    3. The drug is in a family with known cross-reactivity to that family.

    The patient is resolved through any merge chain first. A merged record
    keeps its identity but its allergies moved to the survivor, so checking
    the retired chart directly would return a clean result for a patient who
    is, in fact, allergic. Silence is the most dangerous possible answer here.
    """
    patient = patient.resolve()
    warnings = []
    candidate_names = [n for n in (generic_name, brand_name) if n]
    drug_families = set()
    for name in candidate_names:
        drug_families |= _families_for(name)

    allergies = PatientAllergy.objects.filter(patient=patient).exclude(
        status=AllergyStatus.REFUTED
    )

    for allergy in allergies:
        if not allergy.blocks_prescribing:
            continue

        substance = _normalise(allergy.substance)
        if not substance:
            continue

        matched = None
        severity = Severity.CRITICAL

        # 1. Direct name match, either direction. "Penicillin V" matches a
        #    recorded "penicillin"; a recorded "amoxicillin trihydrate"
        #    matches prescribed "amoxicillin".
        for name in candidate_names:
            normalised = _normalise(name)
            if substance in normalised or normalised in substance:
                matched = "direct"
                break

        # 2. Same family.
        if matched is None:
            allergy_families = _families_for(allergy.substance)
            shared = allergy_families & drug_families
            if shared:
                matched = f"same family ({', '.join(sorted(shared))})"
                severity = Severity.CRITICAL

            # 3. Related family.
            elif allergy_families and drug_families:
                for allergy_family in allergy_families:
                    for drug_family in drug_families:
                        pair = tuple(sorted((allergy_family, drug_family)))
                        if pair in CROSS_FAMILY_RISK:
                            matched = (
                                f"cross-reactivity between {allergy_family} "
                                f"and {drug_family}"
                            )
                            severity = CROSS_FAMILY_RISK[pair]
                            break
                    if matched:
                        break

        if matched is None:
            continue

        # A life-threatening reaction outranks the match confidence: even a
        # cross-family possibility is critical if the patient once had
        # anaphylaxis.
        if allergy.severity == "life_threatening":
            severity = Severity.CRITICAL

        warnings.append(
            {
                "type": "allergy",
                "severity": severity,
                "drug": generic_name,
                "substance": allergy.substance,
                "match": matched,
                "reaction": allergy.reaction,
                "allergy_severity": allergy.severity,
                "allergy_status": allergy.status,
                "message": (
                    f"{generic_name} — patient has a recorded "
                    f"{allergy.get_severity_display().lower()} allergy to "
                    f"{allergy.substance}"
                    + (f" ({allergy.reaction})" if allergy.reaction else "")
                    + (
                        f". Matched by {matched}."
                        if matched != "direct"
                        else "."
                    )
                    + (
                        " This allergy is unconfirmed."
                        if allergy.status == AllergyStatus.UNCONFIRMED
                        else ""
                    )
                ),
            }
        )

    return warnings


# ---------------------------------------------------------------------------
# Interaction checking
# ---------------------------------------------------------------------------

#: A small set of serious, well-established interactions. See the module
#: docstring on why this is not, and does not pretend to be, a drug database.
KNOWN_INTERACTIONS = [
    (["warfarin"], ["aspirin", "ibuprofen", "diclofenac", "naproxen"],
     Severity.CRITICAL, "Greatly increased bleeding risk."),
    (["warfarin"], ["ciprofloxacin", "metronidazole", "fluconazole"],
     Severity.HIGH, "Anticoagulant effect potentiated; INR may rise sharply."),
    (["methotrexate"], ["cotrimoxazole", "sulfamethoxazole", "trimethoprim"],
     Severity.CRITICAL, "Risk of severe bone-marrow suppression."),
    (["simvastatin", "atorvastatin"], ["clarithromycin", "erythromycin",
                                       "itraconazole", "ketoconazole"],
     Severity.HIGH, "Raised statin levels; risk of rhabdomyolysis."),
    (["ace inhibitor", "enalapril", "lisinopril", "ramipril"],
     ["spironolactone", "amiloride", "potassium"],
     Severity.HIGH, "Risk of hyperkalaemia."),
    (["metformin"], ["contrast", "iodinated contrast"],
     Severity.HIGH, "Risk of lactic acidosis; withhold around imaging."),
    (["tramadol", "fluoxetine", "sertraline", "amitriptyline"],
     ["tramadol", "fluoxetine", "sertraline", "amitriptyline", "linezolid"],
     Severity.HIGH, "Risk of serotonin syndrome."),
    (["digoxin"], ["amiodarone", "verapamil", "clarithromycin"],
     Severity.HIGH, "Digoxin levels raised; risk of toxicity."),
]


def check_interactions(lines: list) -> list:
    """Interactions between the medicines on one prescription.

    `lines` is a list of dicts or model instances carrying `generic_name`.
    Each pair is reported once, regardless of the order they were entered in.
    """
    warnings = []
    names = []
    for line in lines:
        name = (
            line.get("generic_name")
            if isinstance(line, dict)
            else getattr(line, "generic_name", "")
        )
        names.append(_normalise(name))

    seen_pairs = set()
    for i, first in enumerate(names):
        for j, second in enumerate(names):
            if i >= j or not first or not second:
                continue

            for group_a, group_b, severity, note in KNOWN_INTERACTIONS:
                a_first = any(drug in first for drug in group_a)
                b_second = any(drug in second for drug in group_b)
                a_second = any(drug in second for drug in group_a)
                b_first = any(drug in first for drug in group_b)

                if not ((a_first and b_second) or (a_second and b_first)):
                    continue

                # Self-pairs inside one group (the serotonin set lists the
                # same drugs on both sides) are only real if the two lines
                # are actually different medicines.
                if first == second:
                    continue

                pair = tuple(sorted((first, second)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                warnings.append(
                    {
                        "type": "interaction",
                        "severity": severity,
                        "drugs": list(pair),
                        "message": (
                            f"{pair[0].title()} + {pair[1].title()}: {note}"
                        ),
                    }
                )
    return warnings


def check_duplicates(lines: list) -> list:
    """The same medicine prescribed twice on one prescription.

    Usually a slip -- a brand and its generic entered separately, or a line
    added twice. Low severity, but worth catching before a patient doubles
    their dose.
    """
    warnings = []
    seen: dict[str, int] = {}
    for line in lines:
        name = (
            line.get("generic_name")
            if isinstance(line, dict)
            else getattr(line, "generic_name", "")
        )
        key = _normalise(name)
        if not key:
            continue
        seen[key] = seen.get(key, 0) + 1

    for name, count in seen.items():
        if count > 1:
            warnings.append(
                {
                    "type": "duplicate",
                    "severity": Severity.MODERATE,
                    "drug": name,
                    "message": (
                        f"{name.title()} appears {count} times on this "
                        "prescription."
                    ),
                }
            )
    return warnings


def run_safety_checks(patient, lines: list) -> dict:
    """Every check, for one proposed prescription.

    Returns the warnings plus whether an override reason will be required, so
    the client can present the right thing before the prescriber commits.

    Resolves the patient through any merge chain -- see `check_allergies`.
    """
    patient = patient.resolve()
    warnings = []
    for line in lines:
        generic = (
            line.get("generic_name")
            if isinstance(line, dict)
            else getattr(line, "generic_name", "")
        )
        brand = (
            line.get("brand_name", "")
            if isinstance(line, dict)
            else getattr(line, "brand_name", "")
        )
        warnings.extend(check_allergies(patient, generic, brand))

    warnings.extend(check_interactions(lines))
    warnings.extend(check_duplicates(lines))

    requires_override = any(
        warning["severity"] in Severity.REQUIRES_OVERRIDE for warning in warnings
    )
    by_severity: dict[str, int] = {}
    for warning in warnings:
        by_severity[warning["severity"]] = by_severity.get(warning["severity"], 0) + 1

    return {
        "warnings": warnings,
        "count": len(warnings),
        "by_severity": by_severity,
        "requires_override": requires_override,
        "has_critical": any(
            warning["severity"] == Severity.CRITICAL for warning in warnings
        ),
        #: Stated in the response so a client cannot mistake this for a gate.
        "is_blocking": False,
    }
