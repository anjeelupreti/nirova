"""Turning what somebody typed in a spreadsheet into something a service accepts.

Every function here exists because real migration files contain the thing it
handles. None of it is defensive programming in the abstract sense: each case
below is a shape that arrives in practice and would otherwise either fail the
row or, worse, import the wrong value silently.

**The rule the whole module follows: never guess in a way that cannot be seen.**
A date that might be 3 March or 3rd of a month we cannot determine is an error,
not a coin flip. A phone number with spaces in it is cleaned, because there is
only one way to read it. The difference is whether a wrong answer is possible.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

#: Dates, most specific first. A spreadsheet exported from one system and
#: edited in Excel by two people will contain several of these in one column.
#:
#: **Day-first before month-first, and both before ambiguity is resolved.**
#: Nepal writes 2/3/2024 as 2 March. Accepting the American reading would move
#: a birthday by ten months without anything looking wrong, so a value that
#: parses either way is taken as day-first -- the local convention -- and a
#: value that *only* parses as month-first (13/2/2024 style in the other order)
#: is taken as such because there is then no ambiguity to get wrong.
DATE_FORMATS = (
    "%Y-%m-%d",      # ISO, what an export usually produces
    "%d/%m/%Y",      # Nepal and most of the world
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",      # only reached when day-first failed, so unambiguous
    "%Y/%m/%d",
    "%d %b %Y",      # 3 Mar 2024
    "%d %B %Y",      # 3 March 2024
    "%b %d, %Y",
)

#: Values people type to mean "I do not know". Treated as empty rather than as
#: text, because `date_of_birth = "N/A"` fails a row that has nothing wrong
#: with it and `blood_group = "-"` stores a dash forever.
BLANKS = {
    "", "-", "--", "n/a", "na", "nil", "none", "null", "unknown", "?",
    "not known", "not available", "#n/a", "#value!", "#ref!",
}

TRUE_WORDS = {"yes", "y", "true", "1", "t", "✓", "haas", "ha"}
FALSE_WORDS = {"no", "n", "false", "0", "f", "✗"}


class FieldError(ValueError):
    """A value that cannot be used, with a sentence a clerk can act on."""


def is_blank(value) -> bool:
    """Whether a cell means nothing, including the many ways people say so."""
    if value is None:
        return True
    return str(value).strip().lower() in BLANKS


def text(value, *, max_length: int | None = None, field: str = "") -> str:
    """A trimmed string, with the internal whitespace collapsed.

    Collapsing runs of spaces matters more than it looks: `"Ram  Bahadur"` and
    `"Ram Bahadur"` are the same person, and leaving them different defeats the
    exact-name duplicate check that is the main defence of this whole feature.
    """
    if is_blank(value):
        return ""
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if max_length and len(cleaned) > max_length:
        raise FieldError(
            f"is {len(cleaned)} characters; the longest this field holds is "
            f"{max_length}."
        )
    return cleaned


def phone(value) -> str:
    """Digits, a leading +, and nothing else.

    Spreadsheets hold phone numbers as `9841-234567`, `984 123 4567`,
    `+977 9841234567` and -- when Excel has decided the column is numeric --
    `9841234567.0`. All five are the same number, and a duplicate check on the
    raw strings would match none of them to each other.
    """
    if is_blank(value):
        return ""
    raw = str(value).strip()
    # Excel turns a long numeric-looking string into a float. Trailing `.0` is
    # Excel's, not the user's.
    if raw.endswith(".0"):
        raw = raw[:-2]
    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("+"):
        cleaned = "+" + re.sub(r"\D", "", cleaned[1:])
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7:
        raise FieldError(
            f"'{raw}' is too short to be a telephone number."
        )
    if len(digits) > 15:
        # E.164's limit. Usually two numbers in one cell.
        raise FieldError(
            f"'{raw}' has {len(digits)} digits, which is more than any "
            "telephone number; it may be two numbers in one cell."
        )
    return cleaned


def email(value) -> str:
    if is_blank(value):
        return ""
    cleaned = str(value).strip().lower()
    # Deliberately not a full RFC check. The point is to catch a name or a
    # phone number in the email column, not to adjudicate exotic addresses.
    if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
        raise FieldError(f"'{cleaned}' is not an email address.")
    return cleaned


def on_date(value, *, allow_future: bool = False, field: str = "") -> date | None:
    """A date, from whichever of nine formats the file happens to use.

    Returns None for a blank, because "we do not know this person's birthday"
    is a fact a migration has to be able to carry. A hospital's 2014
    spreadsheet has thousands of them.
    """
    if is_blank(value):
        return None

    # openpyxl hands back real datetimes for cells Excel stored as dates,
    # which is the one case with no ambiguity at all.
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        raw = str(value).strip()
        parsed = None
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise FieldError(
                f"'{raw}' is not a date this can read. Use 2024-03-02, or "
                "02/03/2024 for 2 March."
            )

    if not allow_future and parsed > date.today():
        raise FieldError(
            f"{parsed.isoformat()} is in the future."
        )
    return parsed


def decimal(value, *, minimum: Decimal | None = None, field: str = "") -> Decimal | None:
    """A number, with the thousands separators and currency symbols people type."""
    if is_blank(value):
        return None
    raw = str(value).strip()
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    try:
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise FieldError(f"'{raw}' is not a number.") from None
    if minimum is not None and number < minimum:
        raise FieldError(f"{number} is less than {minimum}.")
    return number


def integer(value, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if is_blank(value):
        return None
    number = decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise FieldError(f"'{value}' is not a whole number.")
    result = int(number)
    if minimum is not None and result < minimum:
        raise FieldError(f"{result} is below {minimum}.")
    if maximum is not None and result > maximum:
        raise FieldError(f"{result} is above {maximum}.")
    return result


def boolean(value, *, default: bool = False) -> bool:
    if is_blank(value):
        return default
    word = str(value).strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise FieldError(f"'{value}' is not a yes or a no.")


def choice(value, *, options: dict, field: str = "", default: str = "") -> str:
    """One of a fixed set, matched on how people actually write it.

    `options` maps a lowercased written form to the stored value, so several
    spellings can reach the same choice -- `"m"`, `"male"` and `"पुरुष"` all
    mean male. A value outside the set is an error rather than a default,
    because silently storing "other" for an unrecognised gender is a wrong
    answer presented as a right one.
    """
    if is_blank(value):
        return default
    word = re.sub(r"\s+", " ", str(value)).strip().lower()
    if word in options:
        return options[word]
    allowed = ", ".join(sorted(set(options.values())))
    raise FieldError(f"'{value}' is not recognised. Expected one of: {allowed}.")


#: Gender, in the forms that arrive. Nepal's official forms recognise a third
#: gender and so does the patient model, so the import must be able to carry it
#: rather than flattening it to male/female/other.
GENDERS = {
    "m": "male", "male": "male", "पुरुष": "male", "purush": "male",
    "f": "female", "female": "female", "महिला": "female", "mahila": "female",
    "o": "other", "other": "other", "third": "other", "third gender": "other",
    "अन्य": "other",
    "u": "unknown", "unknown": "unknown",
}

#: The ways a positive and a negative are written. `+ve` is near-universal in
#: Nepali and Indian records and is the spelling a naive parser always misses.
_SIGNS = {
    "+": ("+", "+ve", "pos", "positive"),
    "-": ("-", "-ve", "neg", "negative"),
}


def _blood_groups() -> dict:
    """`{written form: stored value}` for every blood group spelling seen.

    Built rather than typed out -- eight groups times eight spellings times two
    separators is 128 entries, and a hand-written table of that size acquires a
    typo that then silently rejects one group. Written as a loop rather than a
    comprehension because the comprehension that did this was unreadable and I
    could not tell by looking whether `A pos` was covered. It was not.
    """
    table = {}
    for letter in ("A", "B", "AB", "O"):
        for sign, words in _SIGNS.items():
            for word in words:
                stored = f"{letter}{sign}"
                # Both `a+ve` and `a +ve`: a space before the sign is common
                # and `choice()` only collapses runs of spaces, it does not
                # remove them.
                table[f"{letter.lower()}{word}"] = stored
                table[f"{letter.lower()} {word}"] = stored
    return table


#: Blood groups, including the `A positive` spelling and the Nepali `+ve` habit.
BLOOD_GROUPS = _blood_groups()

MARITAL_STATUSES = {
    "single": "single", "unmarried": "single",
    "married": "married",
    "widowed": "widowed", "widow": "widowed", "widower": "widowed",
    "divorced": "divorced", "separated": "separated",
}
