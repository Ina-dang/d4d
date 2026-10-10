"""fusion.py 결과(result.json) + 그 입력(docs: id·country·weight)을 Fusion 분석 화면용 sources.json으로 바꾼다.

사용: python docs/fusion-data/make_from_result.py ../result.json ../all-collected-verification-input-20261011.json
      python docs/fusion-data/make_from_result.py <결과> <입력> --topic india-pakistan --event "카슈미르 일대" 34.1 74.8 \n             --collection <collective_live.json>
출력: docs/fusion-data/<topic>.json (make_sources.py와 같은 형식 + 문서별 claims, 전체 summary·thresholds)

문서 하나 = 출처 하나. --collection(같은 실행의 수집 결과)을 주면 기관명·제목·URL·언어·게시일·원문을 채우고,
없으면 제목은 첫 주장 앞부분, 기관명은 비워 둔다.
  reliability = fusion.py가 계산한 문서 신뢰도(같은 문서의 claim은 값이 같다), weight = 입력의 출처 가중치
"""
import argparse
import json
from pathlib import Path

from make_sources import ROLE as CATEGORY_ROLE, TYPE as CATEGORY_TYPE, body, script, truthy

ROLE = {1: "제3국 관측기관", 2: "당사국 공식", 3: "언론"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("input")
    ap.add_argument("--event", nargs=3, metavar=("LABEL", "LAT", "LON"), default=["대만해협 일대", "24.5", "120.5"])
    ap.add_argument("--topic", default="taiwan-strait", help="출력 파일 이름 = 검색 화면의 주제 id")
    ap.add_argument("--collection", help="같은 실행의 collective_live.json (by_country 또는 all_documents)")
    a = ap.parse_args()
    result = json.loads(Path(a.result).read_text(encoding="utf-8-sig"))
    docs = {d["id"]: d for d in json.loads(Path(a.input).read_text(encoding="utf-8-sig"))["docs"]}
    meta = {}
    if a.collection:
        raw = json.loads(Path(a.collection).read_text(encoding="utf-8-sig"))
        raw = raw.get("output", raw)
        listed = [{**d, "country": d.get("country") or group} for group, ds in (raw.get("by_country") or {}).items() for d in ds]
        meta = {d["doc_id"]: d for d in listed or raw.get("all_documents") or []}

    by_doc = {}
    for c in result["claims"]:
        by_doc.setdefault(c["document_id"], []).append(c)
    sources = []
    for i, (doc_id, claims) in enumerate(by_doc.items(), 1):
        d, tier, m = docs.get(doc_id, {}), claims[0].get("tier"), meta.get(doc_id, {})
        first = claims[0]["translated_quote"]
        country = d.get("country") or m.get("country") or "INTL"
        category = m.get("source_category")
        sources.append({
            "id": f"S{i}", "doc_id": doc_id, "title": m.get("title") or first[:70] + ("…" if len(first) > 70 else ""),
            "url": m.get("url"), "agency": m.get("source_name"), "country": country,
            "role": CATEGORY_ROLE.get(category) or ROLE.get(tier), "type": CATEGORY_TYPE.get(category) or ROLE.get(tier),
            "script": script(m["language"], country) if m.get("language") else "한국어 번역", "language": m.get("language"),
            "tier": str(tier) if tier else None,
            "published_at": m.get("published_date") or claims[0].get("event_date"),
            "relation": "reprint" if truthy(m.get("is_reprint_likely")) else "event",
            "original_text": body(m) if m else None,
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
