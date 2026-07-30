from pydantic import BaseModel


class MappingRow(BaseModel):
    supplier_ref: str
    supplier_name: str | None = None
    supplier_label: str | None = None
    our_ref: str
    our_label: str
    ean: str | None = None


class MappingRowOutcome(BaseModel):
    row_number: int
    supplier_ref: str
    size: str | None = None
    supplier_name: str | None = None
    our_ref: str | None = None
    our_label: str | None = None
    action: str  # "create" | "update" | "ignore"
    reason: str | None = None
    old_our_ref: str | None = None
    old_our_label: str | None = None
    old_ean: str | None = None
