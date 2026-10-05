"""The template's rules counted on the rows, per document."""
import pytest

from api.checks import run_checks, to_number
from api.templates import Template


@pytest.mark.parametrize("text, number", [
    ("12 500,5", 12500.5), ("1,234.5", 1234.5), ("1.234,5", 1234.5), ("1,234", 1234), ("10,5", 10.5),
    ("(300)", -300), ("−42", -42), ("10.8%", 10.8), ("1 234 567", 1234567), ("1.234.567", 1234567),
    (17, 17), ("-", None), ("", None), (None, None), ("ca 100", None),
])
def test_to_number(text, number):
    assert to_number(text) == number


def checks(rules, innehav, total, documents=("a.pdf",)):
    template = Template(name="T", prompt="p", rules=rules, tables=[
        {"name": "innehav", "fields": [{"name": "bolag"}, {"name": "varde"}]},
        {"name": "total", "fields": [{"name": "summa"}, {"name": "antal"}]}])
    extraction = {"documents": [{"name": d, "status": "done"} for d in documents],
                  "tables": {"innehav": innehav, "total": total}}
    return [(c["document"], c["status"], c["rows"]) for c in run_checks(template, extraction)]


def rows(*values, doc="a.pdf"):
    return [{"dokument": doc, "bolag": b, "varde": v} for b, v in values]


SUM = {"type": "sum", "table": "innehav", "field": "varde", "target_table": "total", "target_field": "summa"}
COUNT = {"type": "count", "table": "innehav", "target_table": "total", "target_field": "antal"}


@pytest.mark.parametrize("summa, status", [("300", "ok"), ("301", "ok"), ("310", "fail"), ("", "unknown")])
def test_sum_within_half_a_percent(summa, status):
    innehav = rows(("A", "100"), ("B", "200"), ("C", "-"))
    assert checks([SUM], innehav, [{"dokument": "a.pdf", "summa": summa}]) == [("a.pdf", status, [])]


def test_sum_and_count_are_per_document():
    innehav = rows(("A", "100"), ("B", "200")) + rows(("C", "50"), doc="b.pdf")
    total = [{"dokument": "a.pdf", "summa": "300", "antal": "2"}, {"dokument": "b.pdf", "summa": "999", "antal": "2"}]
    assert checks([SUM, COUNT], innehav, total, ("a.pdf", "b.pdf")) == [
        ("a.pdf", "ok", []), ("b.pdf", "fail", []), ("a.pdf", "ok", []), ("b.pdf", "fail", [])]


def test_required_marks_the_empty_rows():
    rule = {"type": "required", "table": "innehav", "field": "varde"}
    assert checks([rule], rows(("A", "100"), ("B", ""), ("C", None)), []) == [("a.pdf", "fail", [1, 2])]


def test_unique_ignores_case_and_spaces():
    rule = {"type": "unique", "table": "innehav", "field": "bolag"}
    assert checks([rule], rows(("Alfa AB", "1"), ("Beta", "2"), (" alfa ab", "3")), []) == [("a.pdf", "fail", [0, 2])]


def test_only_finished_documents_are_checked():
    rule = {"type": "required", "table": "innehav", "field": "bolag"}
    template = Template(name="T", prompt="p", rules=[rule],
                        tables=[{"name": "innehav", "fields": [{"name": "bolag"}]}])
    extraction = {"documents": [{"name": "a.pdf", "status": "done"}, {"name": "b.pdf", "status": "error"}],
                  "tables": {"innehav": []}}
    assert [c["document"] for c in run_checks(template, extraction)] == ["a.pdf"]


def test_a_rule_must_point_at_fields_that_exist():
    with pytest.raises(ValueError, match="finns inte"):
        Template(name="T", prompt="p", rules=[{**SUM, "target_field": "saknas"}],
                 tables=[{"name": "innehav", "fields": [{"name": "varde"}]},
                         {"name": "total", "fields": [{"name": "summa"}]}])
