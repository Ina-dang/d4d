import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from reliability import country_u, p_same, run, score  # noqa: E402

DOCS = [
    {"id": "d0", "country": "CN", "weight": 0.5, "sim": {"d1": 0.97, "d2": 0.62, "d3": 0.71}},
    {"id": "d1", "country": "CN", "weight": 0.4, "sim": {"d0": 0.97, "d2": 0.58, "d3": 0.66}},
    {"id": "d2", "country": "TW", "weight": 0.8, "sim": {"d0": 0.62, "d1": 0.58, "d3": 0.74}},
    {"id": "d3", "country": "US", "weight": 0.9, "sim": {"d0": 0.71, "d1": 0.66, "d2": 0.74}},
]


def test_country_u_discounts_same_country_copies():
    cu = country_u(DOCS)
    assert cu["US"]["u"] == 1.0
    assert 0 < cu["CN"]["u"] < 1


def test_score_range_and_monotonic_p_same():
    result = score({"docs": DOCS})
    assert all(0 <= r["reliability"] <= 1 for r in result["results"])
    assert p_same(0.4) < p_same(0.7) < p_same(0.95)


def test_missing_similarity_is_rejected():
    bad = [dict(DOCS[0], sim={"d1": 0.9}), *DOCS[1:]]
    with pytest.raises(ValueError):
        score({"docs": bad})


def test_run_attaches_document_reliability_to_claims():
    claims = [{"claim_id": "c1", "document_id": "d3"}, {"claim_id": "c2", "document_id": "zz"}]
    out = run({"docs": DOCS, "claims": claims})["claims"]
    expected = score({"docs": DOCS}, ["d3"])["results"][0]["reliability"]
    assert out[0] == {**claims[0], "reliability": expected}
    assert out[1]["reliability"] is None  # docs에 없는 문서
