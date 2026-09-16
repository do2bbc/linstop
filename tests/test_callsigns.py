from linstop.callsigns import infer_german_license_class


def test_infer_class_e_from_do_call() -> None:
    assert infer_german_license_class("do2bbc") == "E"
    assert infer_german_license_class("da6abc") == "E"


def test_infer_class_n_from_dn9_call() -> None:
    assert infer_german_license_class("dn9abc") == "N"


def test_infer_class_a_from_db0_and_dl_calls() -> None:
    assert infer_german_license_class("da0abc") == "A"
    assert infer_german_license_class("da5abc") == "A"
    assert infer_german_license_class("db0abc") == "A"
    assert infer_german_license_class("dl1abc-9") == "A"


def test_infer_cb_call() -> None:
    assert infer_german_license_class("dbw400") == "CB-Funk"
    assert infer_german_license_class("abc123") == "CB-Funk"
    assert infer_german_license_class("13bb016") == "CB-Funk"


def test_infer_training_call() -> None:
    assert infer_german_license_class("dn1abc") == "Ausbildung"
    assert infer_german_license_class("dn8abc") == "Ausbildung"


def test_unknown_or_special_call_stays_empty() -> None:
    assert infer_german_license_class("not a call") == ""