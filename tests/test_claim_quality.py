from app.claims.claim_quality import claim_rejection_reason, filter_claims


def test_navigation_heading_and_questions_are_not_claims_but_announcements_are():
    assert claim_rejection_reason('關鍵字： 臺海 中共 分享至 Facebook(另開新視窗) 複製連結 列印')
    assert claim_rejection_reason('第2節 中国 1 全般 1 中国軍の指導・指揮機関。')
    assert claim_rejection_reason('[0:00] どっちが本当なんですか?')
    assert claim_rejection_reason('[12:35] 台湾について何を持ち出すのという言うかというと')
    assert claim_rejection_reason('[12:35] 台湾について何を持ち出すかというと\n\n[12:43] これです。')
    assert claim_rejection_reason('迄0600時止，偵獲共艦8艘及公務船9艘，持續在臺海周邊活動。') is None
    assert claim_rejection_reason('Facebook announced a change to its Taiwan office.') is None


def test_existing_claim_ids_are_preserved_and_off_topic_snippet_requires_body_fallback():
    claims = [{'claim_id': 'a-c1', 'document_id': 'a', 'original_quote': '第2節 中国 1 全般。'},
              {'claim_id': 'a-c2', 'document_id': 'a', 'original_quote': '台湾周辺で活動している。'},
              {'claim_id': 'b-c1', 'document_id': 'b', 'original_quote': '外国の新聞は正しい。'}]
    accepted, excluded = filter_claims(claims, '대만해협 양측 발표', require_focus=True)
    assert [claim['claim_id'] for claim in accepted] == ['a-c2']
    assert [claim['exclusion_reason'] for claim in excluded] == ['section_heading', 'question_focus_missing']
