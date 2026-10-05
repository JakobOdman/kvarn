"""
checks.py - the template's rules counted on an extraction, per document. Free and exact, no AI.

sum       the sum of a field = a field in another table (e.g. holdings against the total row), 0.5 % tolerance
count     the number of rows = a field in another table (e.g. "number of companies" in the report)
required  the field is filled in on every row
unique    no two rows have the same value

Amounts are text as written in the document; to_number turns them into numbers.
"""
import re

from api.templates import Rule, Template

TOLERANCE = 0.005


def to_number(text) -> float | None:
    """'12 500,5', '1,234.5', '(300)', '10.8%' -> float. None when empty, '-' or not a number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("−", "-").replace("–", "-")
    s = re.sub(r"[\s %]", "", s)
    if s in ("", "-") or not re.fullmatch(r"-?[\d.,]+", s):
        return None
    # Both comma and point: the last one is the decimal sign. Several of one: thousand separators.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(",") > 1 or s.count(".") > 1:
        s = s.replace(",", "").replace(".", "")
    elif "," in s and len(s.split(",")[1]) == 3:
        s = s.replace(",", "")  # 1,234 is a thousand separator
    else:
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def _fmt(x: float) -> str:
    text = f"{x:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


def describe(rule: Rule) -> str:
    """The rule in words, for the UI."""
    if rule.type == "sum":
        return f"Summan av {rule.table}.{rule.field} = {rule.target_table}.{rule.target_field}"
    if rule.type == "count":
        return f"Antal rader i {rule.table} = {rule.target_table}.{rule.target_field}"
    if rule.type == "required":
        return f"{rule.table}.{rule.field} är ifyllt"
    return f"{rule.table}.{rule.field} är unikt"


def _target(rule: Rule, tables: dict, document: str) -> float | None:
    """The first filled-in value of the target field in the document's rows."""
    for row in tables.get(rule.target_table, []):
        if row.get("dokument") == document:
            value = to_number(row.get(rule.target_field))
            if value is not None:
                return value
    return None


def _check(rule: Rule, tables: dict, document: str) -> dict:
    rows = [(i, r) for i, r in enumerate(tables.get(rule.table, [])) if r.get("dokument") == document]
    result = {"status": "ok", "message": "", "rows": []}

    if rule.type == "sum":
        total = _target(rule, tables, document)
        if total is None:
            return result | {"status": "unknown", "message": f"Inget värde i {rule.target_table}.{rule.target_field}."}
        values = [to_number(r.get(rule.field)) for _, r in rows]
        found = sum(v for v in values if v is not None)
        diff = found - total
        ok = abs(diff) <= TOLERANCE * abs(total) or (total == 0 and found == 0)
        message = f"Summa {_fmt(found)}, ska vara {_fmt(total)}" + ("" if diff == 0 else f" (diff {_fmt(diff)})")
        return result | {"status": "ok" if ok else "fail", "message": message}

    if rule.type == "count":
        expected = _target(rule, tables, document)
        if expected is None:
            return result | {"status": "unknown", "message": f"Inget värde i {rule.target_table}.{rule.target_field}."}
        ok = len(rows) == expected
        return result | {"status": "ok" if ok else "fail", "message": f"{len(rows)} rader, ska vara {_fmt(expected)}"}

    if rule.type == "required":
        empty = [i for i, r in rows if r.get(rule.field) in (None, "")]
        if empty:
            return result | {"status": "fail", "message": f"{len(empty)} av {len(rows)} rader saknar värde", "rows": empty}
        return result | {"message": f"Alla {len(rows)} rader ifyllda"}

    seen: dict[str, list[int]] = {}
    for i, r in rows:
        value = str(r.get(rule.field) or "").strip().lower()
        if value:
            seen.setdefault(value, []).append(i)
    duplicates = [i for indexes in seen.values() if len(indexes) > 1 for i in indexes]
    if duplicates:
        return result | {"status": "fail", "message": f"{len(duplicates)} rader har samma värde som någon annan",
                         "rows": duplicates}
    return result | {"message": f"Alla {len(rows)} värden unika"}


def run_checks(template: Template, extraction: dict) -> list[dict]:
    """[{rule (index), description, table, document, status ok|fail|unknown, message, rows (indexes in the table)}]"""
    documents = [d["name"] for d in extraction["documents"] if d["status"] == "done"]
    return [{"rule": n, "description": describe(rule), "table": rule.table, "document": doc,
             **_check(rule, extraction["tables"], doc)}
            for n, rule in enumerate(template.rules) for doc in documents]
