"""frame 수집 결과(collected_live.json)를 Fusion 분석 화면의 지도·출처 근거용 sources.json으로 바꾼다.

사용: python docs/fusion-data/make_sources.py [frame/collected_live.json] [--event "대만해협 일대" 24.5 120.5]
출력: docs/fusion-data/<topic>.json  (docs/data/는 .gitignore의 data/ 규칙에 걸려 이 폴더를 쓴다)

변환 규칙
  source_name → agency, country → country
  source_category → role/type (party_official 당사국 공식, neutral_observer 제3국 관측기관, reputable_media 언론)
  language → script (zh는 TW·HK면 번체, 아니면 간체 / ja 일본어 / en 영문 / ko 한국어)
  credibility_weight → reliability, tier → tier
  is_reprint_likely가 참이면 relation = reprint, quoted_source가 다른 문서의 출처명과 맞으면 origin으로 잇고
  아니면 origin_label에 글자로만 남긴다 (수집기는 원출처를 기관명·인물명 같은 글자로 준다)
  본문: 정제된 문단(paragraphs.text)에서 마크다운 기호·중복 문단을 걷어 내고 앞부분만 (화면 표시용)
"""
import argparse
import json
import re
from pathlib import Path

ROLE = {"party_official": "당사국 공식", "neutral_observer": "제3국 관측기관", "reputable_media": "언론"}
TYPE = {"party_official": "당사국 공식 발표", "neutral_observer": "제3국 관측 자료", "reputable_media": "언론 보도"}
TEXT_LIMIT = 1600


def truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def script(lang: str, country: str) -> str:
    if lang == "zh":
        return "번체" if country in ("TW", "HK") else "간체"
    return {"ja": "일본어", "en": "영문", "ko": "한국어"}.get(lang, lang or "")


def plain(text: str) -> str:
    """수집 본문에 남은 마크다운 기호를 걷어 낸다: [글](링크) → 글, 이미지·강조·제목 기호 제거."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+|^#+\s*|^>\s*", "", text, flags=re.M)
    return re.sub(r"[ \t]+", " ", text).strip()


def body(doc: dict) -> str:
    paras = [plain(p.get("text") or p.get("raw_text") or "") for p in doc.get("paragraphs") or []]
    paras = list(dict.fromkeys(p for p in paras if len(p) > 1))  # 같은 문단 반복(제목 중복 등) 제거
    text = "\n".join(paras) or plain(doc.get("article_text") or "")
    return text[:TEXT_LIMIT] + ("…" if len(text) > TEXT_LIMIT else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="frame/collected_live.json")
    ap.add_argument("--event", nargs=3, metavar=("LABEL", "LAT", "LON"), default=["대만해협 일대", "24.5", "120.5"])
    ap.add_argument("--topic", default="taiwan-strait", help="출력 파일 이름 = 검색 화면의 주제 id")
    a = ap.parse_args()
    raw = json.loads(Path(a.src).read_text(encoding="utf-8"))
    docs = raw.get("all_documents", [])
    sources = []
    for i, d in enumerate(docs, 1):
        quoted = d.get("quoted_source")
        quoted = None if str(quoted) in ("None", "", "null") else quoted
        sources.append({
            "id": f"S{i}", "doc_id": d.get("doc_id"), "title": d.get("title") or "", "url": d.get("url"),
            "agency": d.get("source_name"), "country": d.get("country") or "INTL",
            "role": ROLE.get(d.get("source_category"), d.get("source_category")),
            "type": TYPE.get(d.get("source_category"), d.get("source_category")),
            "script": script(d.get("language"), d.get("country")), "language": d.get("language"),
            "tier": d.get("tier"), "published_at": d.get("published_date"),
            "relation": "reprint" if truthy(d.get("is_reprint_likely")) else "event",
            "origin_label": quoted, "reliability": d.get("credibility_weight"),
            "needs_review": bool((d.get("cleaning") or {}).get("needs_review")),
            "original_text": body(d),
        })
    by_agency = {s["agency"]: s["id"] for s in sources if s["relation"] == "event"}
    for s in sources:  # 원출처 글자가 다른 문서의 출처명과 같으면 그 문서로 잇는다
        if s["relation"] == "reprint" and s["origin_label"] in by_agency:
            s["origin"] = by_agency[s["origin_label"]]
    out = {"question": raw.get("korean_question"),
           "event": {"id": "L1", "label": a.event[0], "lat": float(a.event[1]), "lon": float(a.event[2]),
                     "date": raw.get("event_date")},
           "sources": sources}
    dst = Path(__file__).with_name(f"{a.topic}.json")
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"{dst}: 문서 {len(sources)}건, 재인용 추정 {sum(s['relation'] == 'reprint' for s in sources)}건")


if __name__ == "__main__":
    main()
