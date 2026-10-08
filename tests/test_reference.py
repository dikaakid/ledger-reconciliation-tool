from ledger_recon.config import ReconConfig
from ledger_recon.reference import ReferenceExtractor

REF = "8800112345678901"


def make():
    return ReferenceExtractor(ReconConfig())


def test_exact_length_does_not_over_consume_glued_digits():
    # A greedy \d{14,20} would swallow the glued "424242" and return a wrong reference.
    assert make().extract(f"INCOMING REF{REF}424242 MA:7") == REF


def test_shorter_reference_lengths_are_found():
    assert make().extract("TRF 880011234567890 FROM X") == "880011234567890"  # 15 digits
    assert make().extract("TRF 88001123456789 FROM X") == "88001123456789"  # 14 digits


def test_leading_channel_and_case_insensitive():
    assert make().extract(f"{REF}#PAYMENT") == REF
    assert make().extract(f"trf {REF} from x") == REF


def test_unknown_prefix_is_rejected_and_logged():
    ex = make()
    assert ex.extract("TRF9999900000000001 FROM UNKNOWN") is None
    assert ex.anomaly_summary()["9999900000000001"]["count"] == 1


def test_no_reference_returns_none():
    assert make().extract("MONTHLY ADMIN FEE") is None
    assert make().extract(None) is None
