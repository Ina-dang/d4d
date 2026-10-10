from copy import deepcopy

from app.claims.source_analysis_input import verification_input, verification_selection


def test_representative_export_uses_question_and_preserves_all_evidence():
    def claim(did, number, text):
        return {'claim_id': f'{did}-c{number}', 'document_id': did, 'tier': 2,
                'event_date': None, 'paragraph_id': f'{did}-snippet-p1',
                'translated_quote': text, 'original_quote': text, 'expression': '발표'}

    result = {'analysis_question': '중국 대만해협 충돌에 관한 양측 발표',
              'docs': [{'id': did, 'country': 'CN', 'weight': 0.5, 'sim': {}}
                       for did in ('a', 'b', 'empty')],
              'claims': [claim('b', 1, '중국 발표'), claim('a', 1, '연간 경제 목표'),
                         claim('a', 2, '중국이 대만해협 충돌에 관해 발표했다.'),
                         claim('b', 2, '중국 발표')]}
    original = deepcopy(result)
    output = verification_input(result)
    assert [c['claim_id'] for c in output['claims']] == ['a-c2', 'b-c1']
    assert len(output['docs']) == 3
    assert result == original
    assert all('original_quote' not in c for c in output['claims'])
    selection = verification_selection(result)
    assert selection['documents_without_claims'] == ['empty']
    assert selection['analyzed_claim_count'] == 4
    assert selection['exported_claim_count'] == 2


def test_empty_claims_do_not_create_a_placeholder():
    result = {'docs': [{'id': 'a', 'country': 'IN', 'weight': 0.75, 'sim': {}}],
              'claims': []}
    assert verification_input(result)['claims'] == []
    assert verification_selection(result)['documents_without_claims'] == ['a']
