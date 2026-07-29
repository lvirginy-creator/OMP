from sqlalchemy import select

from app.models.societe import Societe


def test_create_list_rename_toggle_societe(client):
    resp = client.post("/societes/create", data={"name": "OMP Martinique"}, follow_redirects=False)
    assert resp.status_code == 303

    listing = client.get("/societes")
    assert "OMP Martinique" in listing.text
    assert "Active" in listing.text


async def test_home_requires_active_societe_to_show_upload_form(client, db_session):
    home = client.get("/")
    assert "Aucune société active" in home.text

    from app.services.suppliers import now_iso

    db_session.add(Societe(name="OMP Guadeloupe", active=True, created_at=now_iso()))
    await db_session.commit()

    home2 = client.get("/")
    assert "OMP Guadeloupe" in home2.text
    assert 'name="societe_id"' in home2.text


async def test_upload_without_societe_is_rejected(client, db_session):
    from app.services.suppliers import now_iso

    db_session.add(Societe(name="OMP Test", active=True, created_at=now_iso()))
    await db_session.commit()

    from tests.fixtures.pdf_builder import simple_invoice_pdf

    resp = client.post(
        "/factures/upload",
        files={"files": ("f.pdf", simple_invoice_pdf(), "application/pdf")},
    )
    assert "Choisis une société" in resp.text


async def test_upload_with_societe_is_recorded_on_invoice(client, db_session):
    from app.services.suppliers import now_iso

    societe = Societe(name="OMP Recorded", active=True, created_at=now_iso())
    db_session.add(societe)
    await db_session.commit()
    societe_id = societe.id

    from tests.fixtures.pdf_builder import simple_invoice_pdf

    resp = client.post(
        "/factures/upload",
        data={"societe_id": str(societe_id)},
        files={"files": ("f.pdf", simple_invoice_pdf(), "application/pdf")},
    )
    assert "Importée" in resp.text

    listing = client.get("/factures")
    assert "OMP Recorded" in listing.text

    inactive_check = (
        await db_session.execute(select(Societe).where(Societe.id == societe_id))
    ).scalar_one()
    assert inactive_check.active is True
