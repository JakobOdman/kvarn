"""
templates.py - an extraction template: the prompt and the tables the AI fills in.

Stored in the database, one per user (db.py). The engine adds document and page to every row,
so a template never lists them.
"""
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, model_validator

from api import db

RESERVED = {"dokument", "sida"}  # columns the engine adds to every row


class Field(BaseModel):
    name: str
    description: str = ""
    type: Literal["text", "integer", "choice"] = "text"
    choices: list[str] = []  # only for type "choice"


class Table(BaseModel):
    name: str
    description: str = ""
    fields: list[Field]


class Rule(BaseModel):
    """A check that can be counted after the extraction, per document. See checks.py."""
    type: Literal["sum", "count", "required", "unique"]
    table: str
    field: str = ""  # not used by count
    target_table: str = ""  # sum and count: what the rows are compared with
    target_field: str = ""


class Template(BaseModel):
    id: str = ""  # a random id, set when first saved
    name: str
    prompt: str
    tables: list[Table]
    page_selection: bool = False  # later: a cheap model picks the relevant pages first
    rules: list[Rule] = []

    @model_validator(mode="after")
    def check_names(self):
        table_names = [t.name for t in self.tables]
        if len(set(table_names)) != len(table_names):
            raise ValueError("Två tabeller har samma namn.")
        for table in self.tables:
            names = [f.name for f in table.fields]
            if len(set(names)) != len(names):
                raise ValueError(f"Två fält i {table.name} har samma namn.")
            if RESERVED & set(names):
                raise ValueError(f"{', '.join(sorted(RESERVED))} läggs till automatiskt och kan inte vara fält.")
            for f in table.fields:
                if f.type == "choice" and not f.choices:
                    raise ValueError(f"{table.name}.{f.name} är ett val utan värden.")
        fields = {t.name: {f.name for f in t.fields} for t in self.tables}
        for i, rule in enumerate(self.rules, 1):
            wanted = [(rule.table, rule.field if rule.type != "count" else None)]
            if rule.type in ("sum", "count"):
                wanted.append((rule.target_table, rule.target_field))
            for table, field in wanted:
                if table not in fields:
                    raise ValueError(f"Kontroll {i}: tabellen {table or '(ingen)'} finns inte.")
                if field is not None and field not in fields[table]:
                    raise ValueError(f"Kontroll {i}: fältet {table}.{field or '(inget)'} finns inte.")
        return self


def list_templates(user_id: str) -> list[Template]:
    """The user's templates, sorted by name."""
    return [Template.model_validate(t) for t in db.list_templates(user_id)]


def load_template(template_id: str, user_id: str) -> Template | None:
    """One of the user's templates, or None (also when it is someone else's)."""
    template = db.get_template(template_id, user_id)
    return Template.model_validate(template) if template else None


def save_template(template: Template, user_id: str) -> Template | None:
    """Create (a new template gets a random id) or update. None if the id is someone else's."""
    if not template.name.strip():
        raise ValueError("Mallen behöver ett namn.")
    if not template.id:
        template.id = uuid4().hex
    if not db.save_template(template.id, user_id, template.name, template.model_dump()):
        return None
    return template


def delete_template(template_id: str, user_id: str) -> bool:
    return db.delete_template(template_id, user_id)


def _field_schema(field: Field) -> dict:
    if field.type == "integer":
        schema = {"type": ["integer", "null"]}
    elif field.type == "choice":
        schema = {"type": "string", "enum": field.choices + [""]}  # "" when the document does not say
    else:
        schema = {"type": "string"}
    if field.description:
        schema["description"] = field.description
    return schema


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def schema_for(template: Template) -> dict:
    """Strict JSON schema for the answer: one array of rows per table, plus the page on every row."""
    tables = {}
    for table in template.tables:
        row = {f.name: _field_schema(f) for f in table.fields}
        row["sida"] = {"type": "integer", "description": "N ur raden '=== Sida N ===' där raden står"}
        tables[table.name] = {"type": "array", "items": _object(row)}
        if table.description:
            tables[table.name]["description"] = table.description
    return _object(tables)
