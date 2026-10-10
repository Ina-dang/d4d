"""trend_analysis 결과(Wikipedia 조회수 스파이크 + 날짜별 기사 키워드)를 이슈 타임라인 페이지용 JSON 하나로 합친다.

사용: python docs/issues/make_issue_data.py <trend_analysis/data 폴더> <출력 json> [Wikipedia 문서 파일명] [timeline 이름]
  입력: wiki_<문서>_views.csv (일별 조회수), wiki_<문서>.json (z 구간), wiki_<문서>_jump.json (전후일 대비 급증일), timeline_<검색어>.json (키워드·관련 기사)
예:   python docs/issues/make_issue_data.py ../trend_analysis/data docs/issues/taiwan-strait.json
      python docs/issues/make_issue_data.py ../trend_analysis/data docs/issues/india-pakistan.json India_Pakistan_wars_and_conflicts 인도_파키스탄
"""
import json
import sys
from pathlib import Path



def main(src: str, dst: str, article: str = "Taiwan_Strait", timeline: str = "대만해협") -> None:
    src = Path(src)
    WIKI, JUMP, VIEWS = f"wiki_{article}.json", f"wiki_{article}_jump.json", f"wiki_{article}_views.csv"  # VIEWS: date,views 일별 조회수
    KEYWORDS = f"timeline_{timeline}.json"
    z = json.loads((src / WIKI).read_text(encoding="utf-8"))
    jump = json.loads((src / JUMP).read_text(encoding="utf-8"))
    kw = {d["date"]: d for d in json.loads((src / KEYWORDS).read_text(encoding="utf-8"))}
    out = {
        "topic": z["article"]["query"],
        "article": z["article"]["en_title"],
        "source": "영어 Wikipedia 일 조회수(사람, 봇 제외) · 키워드는 Google News 기사 제목",
        "range": {"start": z["range"][0], "end": z["range"][1]},
        "median_views": z["median_views"],
        "z_spikes": [{"start": s["start"], "end": s["end"], "peak": s["peak"], "views": s["peak_views"],
                      "z": s["z_max"]} for s in z["spikes"]],
        "jump_days": [{"date": s["peak"], "views": s["peak_views"], "jump": s["jump"], "ratio": s["ratio"],
                       "prev": s["prev_views"], "next": s["next_views"],
                       "keywords": [k["keyword"] for k in kw.get(s["peak"], {}).get("keywords", [])],
                       "articles": [{"title": a["title"], "url": a["url"], "source": a["source"], "lang": a["lang"]}
                                    for a in kw.get(s["peak"], {}).get("related", [])]}
                      for s in jump["spikes"]],
    }
    # 일별 조회수: range.start부터 하루 간격 정수 배열
    rows = dict(line.split(",") for line in (src / VIEWS).read_text(encoding="utf-8").splitlines()[1:] if line)
    days = sorted(d for d in rows if out["range"]["start"] <= d <= out["range"]["end"])
    assert days and days[0] == out["range"]["start"], "조회수 CSV 기간이 range와 맞지 않습니다"
    out["views"] = [int(float(rows[d])) for d in days]
    # 문서가 기간 중간에 생겼으면(그 전 조회수 0) 전체 중앙값이 0이 된다 → 문서가 있던 날만으로 평소 조회수를 잡는다
    if not out["median_views"]:
        live = sorted(v for v in out["views"] if v > 0)
        out["median_views"] = live[len(live) // 2] if live else 0
        out["views_since"] = days[next(i for i, v in enumerate(out["views"]) if v > 0)] if live else None
    # 급증일이 z 급증 구간 안에 있으면 그 구간을 함께 적는다 (며칠 이어진 이슈인지)
    for d in out["jump_days"]:
        d["period"] = next(({"start": z["start"], "end": z["end"], "z": z["z"]} for z in out["z_spikes"]
                            if z["start"] <= d["date"] <= z["end"]), None)
    Path(dst).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"{dst}: z 구간 {len(out['z_spikes'])}개, 급증일 {len(out['jump_days'])}개")


if __name__ == "__main__":
    main(*sys.argv[1:5])
