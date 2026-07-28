from app.services.claude_extraction import is_result_unreliable, pick_best_result, total_mismatch


def _result(total_ht=100.0, lines=None, invoice_number="F1", invoice_date="2026-01-01"):
    return {
        "document_type": "INVOICE",
        "supplier_name": "Test",
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "currency": "EUR",
        "total_ht": total_ht,
        "total_vat": 0.0,
        "total_ttc": total_ht,
        "lines": lines if lines is not None else [{"line_total_net": 100.0}],
        "page_count_documents": 1,
    }


def test_no_lines_is_unreliable():
    assert is_result_unreliable(_result(lines=[]), tolerance=0.02) is True


def test_missing_total_and_identifiers_is_unreliable():
    r = _result(total_ht=None, invoice_number=None, invoice_date=None)
    assert is_result_unreliable(r, tolerance=0.02) is True


def test_missing_total_but_identifiers_present_is_reliable():
    r = _result(total_ht=None, invoice_number="F1", invoice_date="2026-01-01")
    assert is_result_unreliable(r, tolerance=0.02) is False


def test_total_mismatch_beyond_tolerance_is_unreliable():
    r = _result(total_ht=100.0, lines=[{"line_total_net": 50.0}])
    assert is_result_unreliable(r, tolerance=0.02) is True


def test_total_within_tolerance_is_reliable():
    r = _result(total_ht=100.0, lines=[{"line_total_net": 99.99}])
    assert is_result_unreliable(r, tolerance=0.02) is False


def test_pick_best_result_prefers_smaller_mismatch():
    a = _result(total_ht=100.0, lines=[{"line_total_net": 50.0}])  # écart 50
    b = _result(total_ht=100.0, lines=[{"line_total_net": 99.0}])  # écart 1
    best, method = pick_best_result(a, b, tolerance=0.02)
    assert best is b
    assert method == "NATIVE_THEN_VISION"


def test_pick_best_result_prefers_b_on_tie():
    a = _result(total_ht=100.0, lines=[{"line_total_net": 90.0}])  # écart 10
    b = _result(total_ht=100.0, lines=[{"line_total_net": 90.0}])  # écart 10
    best, _ = pick_best_result(a, b, tolerance=0.02)
    assert best is b


def test_total_mismatch_none_when_total_ht_missing():
    assert total_mismatch(_result(total_ht=None), tolerance=0.02) is None
