from nbo.data import load_raw
from nbo.validation import validate_data


def test_raw_data_contract():
    customers, catalog, history = load_raw("dataset")
    report = validate_data(customers, catalog, history, {"expected_customers": 100000, "expected_offers": 22, "expected_history": 300112})
    assert report.valid, report.to_dict()
    assert not [issue for issue in report.issues if issue.level == "warning"]


def test_duplicate_primary_key_is_critical():
    customers, catalog, history = load_raw("dataset")
    broken = customers.iloc[:2].copy()
    broken.loc[broken.index[1], "cliente_id"] = broken.iloc[0]["cliente_id"]
    report = validate_data(broken, catalog, history.iloc[:0], {})
    assert not report.valid
    assert any(issue.check == "customers.pk" for issue in report.issues)

