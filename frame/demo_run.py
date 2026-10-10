"""
OSINT 수집기 로컬 검증 및 데모 스크립트
실행 방법: python demo_run.py
"""

import json
import os
import sys

# Windows 터미널 한글/특수문자 인코딩 대응
sys.stdout.reconfigure(encoding='utf-8')

from collector import OSINTCollector, TavilyClient

def main():
    print("=" * 65)
    print("🚀 [KoreanDefense/frame] 안보 OSINT 수집 엔진 테스트")
    print("   (7대 주요 안보 행위자: CN, TW, JP, KR, IN, PK, US)")
    print("=" * 65)

    collector = OSINTCollector()
    api_key = os.getenv("TAVILY_API_KEY")

    if TavilyClient is None or not api_key:
        if TavilyClient is None:
            print("[i] 'tavily-python' 패키지가 미설치 상태입니다.")
        if not api_key:
            print("[i] TAVILY_API_KEY 환경변수(.env)가 설정되지 않았습니다.")

        print("\n👉 [모의 데이터 검증 모드] 로직(언어 판별, 티어 분류, 재인용 감지, JSON 저장)을 테스트합니다.\n")

        mock_collector = OSINTCollector(api_key="mock_key")

        # 샘플: 일본 방위성(Tier 1, ja) 발표 (원문 인용 감지 포함)
        sample_url = "https://www.mod.go.jp/j/press/news/2026/10/10a.html"
        sample_text = (
            "According to Taiwan MND reports on earlier movements, the PLA increased presence.\n\n"
            "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。\n"
            "自衛隊は哨戒機及び護衛艦により所要の情報収集と警戒監視を実施した。"
        )

        tier_meta = mock_collector._resolve_tier_meta(sample_url)
        lang = mock_collector._detect_language(sample_url, sample_text)
        text_snippet = mock_collector._build_clean_5_sentence_snippet(sample_text, "中国海軍艦艇の動向について (防衛省)")

        mock_output = [
            {
                "doc_id": "doc_sample01",
                "url": sample_url,
                "title": "中国海軍艦艇の動向について (防衛省)",
                "score": 0.85,
                "score_notice": None,
                "language": lang,
                "tier": tier_meta["tier"],
                "source_name": tier_meta["name"],
                "country": tier_meta["country"],
                "source_category": tier_meta["category"],
                "credibility_weight": tier_meta["weight"],
                "published_date": "2026-10-10",
                "status": "success_full",
                "text_snippet": text_snippet,
                "article_text": sample_text,
            }
        ]

        print("✅ [테스트 결과 - 최종 규격 JSON]:")
        print(json.dumps(mock_output[0], indent=2, ensure_ascii=False))

        test_file = "sample_output.json"
        mock_collector.export_json(mock_output, test_file)
        print(f"[✓] export_json 테스트 성공: {test_file} 생성됨")

        print("\n" + "=" * 65)
        print("💡 안내: .env 파일에 TAVILY_API_KEY=tvly-... 를 설정하시면")
        print("   실제 웹 검색 및 7개국별 수집(국가당 최대 5건) 모드로 자동 동작합니다.")
        print("=" * 65)
        return

    # 실제 Tavily API 키가 있을 경우
    print("[+] TAVILY_API_KEY 감지 완료. 실제 웹 검색(한국어 질문 -> 7개국 자동 확장)을 진행합니다.\n")

    question = "대만해협 군사활동"
    event_date = "2026-10-01"

    # 🎯 각 국가별로 최대 20건씩 수집 (중화권 CN+HK+TW 합산 20건 캡 자동 적용)
    result = collector.collect_from_korean(
        question=question,
        event_date=event_date,
        max_docs_per_country=20,
        days_back=30
    )

    print("\n" + "=" * 65)
    print(f"📊 [최종 결과 요약] 총 {result['total_count']}건 수집 (국가당 최대 20건 제한, 중화권 합산 20건 캡):")
    for country_code, docs in result["by_country"].items():
        print(f"  - [{country_code}] {len(docs)}건")
        for d in docs[:2]:  # 국가당 상위 2건 미리보기
            print(f"    * [{d.get('tier')}티어] {d.get('source_name')} ({d.get('language')}) | {d.get('title')[:40]}")
        if len(docs) > 2:
            print(f"    * ... 외 {len(docs) - 2}건 추가 확보")

    collector.export_json(result, "collected_live.json")
    try:
        # 상위 루트 디렉토리(c:\KoreanDefense\collected_live.json) 동기화
        root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "collected_live.json"))
        with open(root_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"[💾] 루트 경로 동기화 완료: {root_path}")
    except Exception as e:
        print(f"[-] 루트 동기화 실패: {e}")

if __name__ == "__main__":
    main()
