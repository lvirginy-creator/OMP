import io

import openpyxl


def _build_mapping_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["reference_fournisseur", "fournisseur", "notre_reference", "notre_libelle"])
    ws.append(["JREF-1", "Fournisseur Journal SAS", "INT-J1", "Article journal"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_journal_lists_mapping_import(client):
    content = _build_mapping_xlsx()
    resp = client.post(
        "/referentiel/import/preview",
        files={"file": ("journal_test.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    import re

    token = re.search(r'name="token" value="([a-f0-9]+)"', resp.text).group(1)
    client.post("/referentiel/import/apply", data={"token": token}, follow_redirects=False)

    journal = client.get("/journal")
    assert journal.status_code == 200
    assert "journal_test.xlsx" in journal.text
    assert "Référentiel mis à jour" in journal.text
