from app.services.normalize import normalize_ref, normalize_supplier_name


def test_normalize_supplier_name_strips_accents_case_legal_form():
    assert normalize_supplier_name("SARL Dupont Frères") == "dupontfreres"
    assert normalize_supplier_name("Ets. Café du Port SAS") == "etscafeduport"


def test_normalize_supplier_name_same_result_for_variants():
    assert normalize_supplier_name("Boissons Caraïbes") == normalize_supplier_name(
        "BOISSONS CARAIBES"
    )


def test_normalize_ref_removes_spaces_and_hyphens_upcases():
    assert normalize_ref(" abc-123 ") == "ABC123"
    assert normalize_ref("ABC 123") == normalize_ref("abc-123")
