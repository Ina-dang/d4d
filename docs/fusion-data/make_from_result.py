"""fusion.py 결과(result.json) + 그 입력(docs: id·country·weight)을 Fusion 분석 화면용 sources.json으로 바꾼다.

사용: python docs/fusion-data/make_from_result.py ../result.json ../all-collected-verification-input-20261011.json
      python docs/fusion-data/make_from_result.py <결과> <입력> --topic india-pakistan --event "카슈미르 일대" 34.1 74.8
출력: docs/fusion-data/<topic>.json (make_sources.py와 같은 형식 + 문서별 claims, 전체 summary·thresholds)

문서 하나 = 출처 하나. 입력에 기관명·제목·URL이 없어 제목은 첫 주장 앞부분으로 대신한다.
  reliability = fusion.py가 계산한 문서 신뢰도(같은 문서의 claim은 값이 같다), weight = 입력의 출처 가중치
"""
import argparse
import json
from pathlib import Path

ROLE = {1: "제3국 관측기관", 2: "당사국 공식", 3: "언론"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("input")
    ap.add_argument("--event", nargs=3, metavar=("LABEL", "LAT", "LON"), default=["대만해협 일대", "24.5", "120.5"])
    ap.add_argument("--topic", default="taiwan-strait", help="출력 파일 이름 = 검색 화면의 주제 id")
    a = ap.parse_args()
    result = json.loads(Path(a.result).read_text(encoding="utf-8-sig"))
    docs = {d["id"]: d for d in json.loads(Path(a.input).read_text(encoding="utf-8-sig"))["docs"]}

    by_doc = {}
    for c in result["claims"]:
        by_doc.setdefault(c["document_id"], []).append(c)
    sources = []
    for i, (doc_id, claims) in enumerate(by_doc.items(), 1):
        d, tier = docs.get(doc_id, {}), claims[0].get("tier")
        first = claims[0]["translated_quote"]
        sources.append({
            "id": f"S{i}", "doc_id": doc_id, "title": first[:70] + ("…" if len(first) > 70 else ""),
            "agency": None, "country": d.get("country") or "INTL",
            "role": ROLE.get(tier), "type": ROLE.get(tier), "script": "한국어 번역", "tier": str(tier) if tier else None,
            "published_at": claims[0].get("event_date"), "relation": "event",
            "reliability": claims[0].get("reliability"), "weight": d.get("weight"),
            "claims": [{"id": c["claim_id"], "quote": c["translated_quote"], "label": c["label"],
                        "reliability": c.get("reliability")} for c in claims],
        })
    out = {"question": None,
           "event": {"id": "L1", "label": a.event[0], "lat": float(a.event[1]), "lon": float(a.event[2])},
           "summary": result.get("summary"), "sources": sources}
    dst = Path(__file__).with_name(f"{a.topic}.json")
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"{dst}: 문서 {len(sources)}건, 주장 {len(result['claims'])}건, {result.get('summary')}")


if __name__ == "__main__":
    main()
