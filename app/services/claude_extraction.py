from typing import Any

import anthropic

from app.core.config import get_settings

TOOL_NAME = "extract_invoice"

CHARGE_KINDS = ["SHIPPING", "ECO_TAX", "DISCOUNT", "DEPOSIT", "OTHER"]

_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "line_type": {"type": "string", "enum": ["ARTICLE", "CHARGE"]},
        "charge_kind": {
            "type": ["string", "null"],
            "enum": CHARGE_KINDS + [None],
        },
        "supplier_ref": {"type": ["string", "null"]},
        "supplier_label": {"type": "string"},
        "size": {"type": ["string", "null"]},
        "quantity": {"type": ["number", "null"]},
        "unit_price_net": {"type": ["number", "null"]},
        "line_total_net": {"type": ["number", "null"]},
        "vat_rate": {"type": ["number", "null"]},
        "low_confidence": {"type": "boolean"},
    },
    "required": [
        "line_type",
        "charge_kind",
        "supplier_ref",
        "supplier_label",
        "size",
        "quantity",
        "unit_price_net",
        "line_total_net",
        "vat_rate",
        "low_confidence",
    ],
}

EXTRACT_INVOICE_TOOL = {
    "name": TOOL_NAME,
    "description": "Enregistre les données structurées extraites d'une facture ou d'un avoir fournisseur.",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_type": {"type": "string", "enum": ["INVOICE", "CREDIT_NOTE"]},
            "supplier_name": {"type": "string"},
            "invoice_number": {"type": ["string", "null"]},
            "invoice_date": {"type": ["string", "null"]},
            "currency": {"type": "string"},
            "total_ht": {"type": ["number", "null"]},
            "total_vat": {"type": ["number", "null"]},
            "total_ttc": {"type": ["number", "null"]},
            "lines": {"type": "array", "items": _LINE_SCHEMA},
            "page_count_documents": {"type": "integer"},
        },
        "required": [
            "document_type",
            "supplier_name",
            "invoice_number",
            "invoice_date",
            "currency",
            "total_ht",
            "total_vat",
            "total_ttc",
            "lines",
            "page_count_documents",
        ],
    },
}

_COMMON_RULES = """Tu extrais les données d'une facture ou d'un avoir fournisseur pour une application de suivi des achats.

Règles impératives :
- Réponds uniquement via l'outil `extract_invoice`, sans texte libre.
- Ne jamais inventer une valeur absente : mets `null`.
- Format français : "1 234,56" vaut 1234.56. Les espaces (y compris insécables) sont des séparateurs de milliers, la virgule est le séparateur décimal. Les dates JJ/MM/AAAA deviennent AAAA-MM-JJ.
- `unit_price_net` : prix unitaire net, remise de ligne déduite. Si la facture affiche un PU brut et un pourcentage de remise, calcule PU_brut × (1 − remise%) et ne renvoie que ce résultat. Ne renvoie jamais le PU brut.
- `line_type` : "ARTICLE" uniquement pour une marchandise physique achetée. Tout le reste est "CHARGE" : frais de port, participation aux frais, éco-participation/éco-contribution/DEEE, consigne/emballages consignés, remise globale de pied de facture, frais de dossier, escompte, arrondi. En cas de doute, choisis CHARGE.
- Avoirs : si le document est un avoir, une note de crédit ou un "credit note", alors document_type = "CREDIT_NOTE" et TOUTES les quantités, line_total_net et totaux sont NÉGATIFS, quelle que soit la façon dont ils sont imprimés sur le document.
- Une ligne de commentaire, un sous-total intermédiaire ou un rappel de commande ne sont pas des lignes : omets-les.
- `size` : taille de l'article (ex: "XS", "S", "M", "38", "40"...), uniquement si le document la précise. Si un article/couleur est décliné en plusieurs tailles avec une quantité par taille (tableau de type Size/PCS avec une colonne par taille), crée une ligne distincte par taille : même `supplier_ref` et même `supplier_label`, `size` renseigné avec le code de la taille, `quantity` = la quantité de cette seule taille, `unit_price_net` = le prix unitaire de la ligne (identique pour toutes les tailles du même article/couleur), `line_total_net` = quantité de cette taille × prix unitaire. N'ajoute aucune ligne pour une case vide ou à 0 du tableau de tailles. Si l'article n'est pas décliné en tailles, laisse `size` à `null`.
- total_ht, total_vat, total_ttc proviennent du pied de facture, pas d'un recalcul.
- Si un article apparaît sur plusieurs lignes (colisage détaillé), conserve les lignes séparées telles quelles.
- page_count_documents : nombre de factures distinctes détectées dans le document (vaut 1 dans l'immense majorité des cas)."""

_VISION_RULES = """
Règles spécifiques à ce document scanné :
- Le document peut être penché, taché, ou comporter des annotations manuscrites (tampon "payé", coche, mention marginale). Ignore toute annotation manuscrite et ne retiens que le contenu imprimé.
- Si un caractère est illisible dans une référence, renvoie la référence telle que lue en ajoutant "low_confidence": true sur la ligne concernée.
- Ne devine jamais un chiffre de montant ou de quantité : si le doute porte sur un nombre, mets `null` plutôt qu'une valeur approchée."""


def build_system_prompt(vision: bool) -> str:
    return _COMMON_RULES + (_VISION_RULES if vision else "")


class UnreliableExtractionError(Exception):
    pass


def _get_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _extract_tool_input(message: anthropic.types.Message) -> dict[str, Any]:
    for block in message.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise UnreliableExtractionError("Le modèle n'a pas utilisé l'outil extract_invoice.")


async def extract_text_mode(text_payload: str) -> dict[str, Any]:
    settings = get_settings()
    client = _get_client()
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=build_system_prompt(vision=False),
        tools=[EXTRACT_INVOICE_TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": text_payload}],
    )
    return _extract_tool_input(message)


async def extract_vision_mode(images_b64: list[str]) -> dict[str, Any]:
    settings = get_settings()
    client = _get_client()
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img},
        }
        for img in images_b64
    ]
    content.append(
        {
            "type": "text",
            "text": "Voici les pages de la facture, dans l'ordre. Extrais les données via l'outil.",
        }
    )
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=build_system_prompt(vision=True),
        tools=[EXTRACT_INVOICE_TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": content}],
    )
    return _extract_tool_input(message)


def total_mismatch(result: dict[str, Any], tolerance: float) -> float | None:
    lines = result.get("lines") or []
    total_ht = result.get("total_ht")
    if total_ht is None:
        return None
    line_sum = sum(
        (line.get("line_total_net") or 0.0) for line in lines if line.get("line_total_net") is not None
    )
    return abs(line_sum - total_ht)


def is_result_unreliable(result: dict[str, Any], tolerance: float) -> bool:
    lines = result.get("lines") or []
    if not lines:
        return True
    if result.get("total_ht") is None and not (
        result.get("invoice_number") or result.get("invoice_date")
    ):
        return True
    mismatch = total_mismatch(result, tolerance)
    if mismatch is not None and mismatch > tolerance:
        return True
    return False


def pick_best_result(
    result_a: dict[str, Any] | None, result_b: dict[str, Any] | None, tolerance: float
) -> tuple[dict[str, Any], str]:
    """Retourne (résultat, méthode) — préfère le plus petit écart, B à égalité."""
    if result_a is None:
        return result_b, "VISION_LLM"
    if result_b is None:
        return result_a, "NATIVE_LLM"

    mismatch_a = total_mismatch(result_a, tolerance)
    mismatch_b = total_mismatch(result_b, tolerance)
    mismatch_a = mismatch_a if mismatch_a is not None else float("inf")
    mismatch_b = mismatch_b if mismatch_b is not None else float("inf")

    if mismatch_a < mismatch_b:
        return result_a, "NATIVE_THEN_VISION"
    return result_b, "NATIVE_THEN_VISION"
