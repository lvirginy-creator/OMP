import re
import unicodedata

_LEGAL_FORMS = {
    "sas", "sasu", "sarl", "eurl", "sa", "sci", "snc", "ei", "eirl",
    "sc", "scop", "scic", "gie", "asso", "association",
}

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_supplier_name(name: str) -> str:
    """Minuscules, sans accents, sans ponctuation, sans forme juridique."""
    value = strip_accents(name).lower()
    tokens = [t for t in _PUNCT_RE.split(value) if t and t not in _LEGAL_FORMS]
    return "".join(tokens)


def normalize_ref(value: str) -> str:
    """Majuscules, espaces et tirets supprimés — cohérent avec la colonne générée SQL."""
    return re.sub(r"[ \-]+", "", value or "").upper()
