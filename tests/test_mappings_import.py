import io
import re

import openpyxl


def _build_xlsx(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "reference_fournisseur",
        "fournisseur",
        "libelle_fournisseur",
        "notre_reference",
        "notre_libelle",
        "code_barre",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _extract_token(html: str) -> str:
    match = re.search(r'name="token" value="([a-f0-9]+)"', html)
    assert match, "token introuvable dans la page de compte-rendu"
    return match.group(1)


def test_import_creates_then_upserts_mapping(client):
    content = _build_xlsx(
        [
            {
                "reference_fournisseur": "ABC-123",
                "fournisseur": "Boissons Caraïbes SAS",
                "notre_reference": "INT-001",
                "notre_libelle": "Jus ananas 1L",
                "code_barre": "3456780000012",
            }
        ]
    )

    resp = client.post(
        "/referentiel/import/preview",
        files={"file": ("mapping.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert "Création" in resp.text
    token = _extract_token(resp.text)

    resp = client.post("/referentiel/import/apply", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 303

    listing = client.get("/referentiel")
    assert "INT-001" in listing.text
    assert "Jus ananas 1L" in listing.text
    assert "Boissons Caraïbes SAS" in listing.text

    # Deuxième import : même référence/fournisseur, libellé mis à jour -> upsert, pas de doublon
    content2 = _build_xlsx(
        [
            {
                "reference_fournisseur": "abc 123",  # variation d'écriture, doit matcher la même clé normalisée
                "fournisseur": "Boissons Caraïbes SAS",
                "notre_reference": "INT-001",
                "notre_libelle": "Jus ananas 1L (nouveau libellé)",
                "code_barre": "3456780000012",
            }
        ]
    )
    resp = client.post(
        "/referentiel/import/preview",
        files={"file": ("mapping2.xlsx", content2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert "Mise à jour" in resp.text
    token2 = _extract_token(resp.text)

    resp = client.post("/referentiel/import/apply", data={"token": token2}, follow_redirects=False)
    assert resp.status_code == 303

    listing2 = client.get("/referentiel")
    assert listing2.text.count("INT-001") == 1
    assert "Jus ananas 1L (nouveau libellé)" in listing2.text


def test_import_missing_required_column_is_reported(client):
    wb_bytes = io.BytesIO()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["colonne_inconnue"])
    ws.append(["valeur"])
    wb.save(wb_bytes)

    resp = client.post(
        "/referentiel/import/preview",
        files={"file": ("bad.xlsx", wb_bytes.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert "Colonnes obligatoires manquantes" in resp.text


def test_import_row_missing_required_field_is_ignored(client):
    content = _build_xlsx(
        [
            {
                "reference_fournisseur": "",
                "fournisseur": "Test",
                "notre_reference": "INT-002",
                "notre_libelle": "Article test",
            }
        ]
    )
    resp = client.post(
        "/referentiel/import/preview",
        files={"file": ("mapping.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert "Ignorée" in resp.text
