from io import BytesIO

from pypdf import PdfReader

from app.reporting.report_pdf import report_pdf


def test_pdf_preserves_multilingual_evidence_candidates_and_review_without_executing_markup():
    phrase = '한국어 주장과 台湾海峡 简体中文、日本語の発表 & <b>원문 태그</b>'
    report = {
        'question': '대만해협 발표 비교', 'status': 'draft', 'version': 3,
        'sections': {'key_judgment': [{'text': phrase * 100, 'claim_ids': ['d1-c1']} ]},
        'evidence': [{'claim_id': 'd1-c1', 'document_id': 'd1', 'source_name': '원출처',
                      'translated_quote': phrase, 'original_quote': '兩岸聲明 日本語 한국어',
                      'reliability': 0.321, 'url': 'javascript:alert(1)'}],
        'proposed_comparisons': [{'section': 'common_facts', 'text': '검토가 필요한 후보', 'claim_ids': ['d1-c1']}],
        'warnings': ['독립성 미확인'], 'audit': [],
    }
    reader = PdfReader(BytesIO(report_pdf(report)))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) > 2
    for expected in ['대만해협 발표 비교', '확인 대기', '검토가 필요한 후보', '[S1]',
                     '라벨 미제공', '<b>원문 태그</b>', '兩岸聲明 日本語 한국어', '台湾海峡 简体中文', '독립성 미확인']:
        assert expected in text
    assert '0.321' not in text
    assert 'javascript:' not in text
    assert all('/Font' in page['/Resources'] for page in reader.pages)
    # 열람 PC의 글꼴 설치 여부와 상관없이 한글이 표시되어야 한다.
    fonts = [font.get_object() for font in reader.pages[0]['/Resources']['/Font'].values()]
    assert any('/FontFile2' in font['/FontDescriptor'] for font in fonts if '/FontDescriptor' in font)
    assert report['status'] == 'draft' and not report['audit']


def test_pdf_keeps_korean_words_and_returned_labels_without_changing_scores():
    report = {
        'question': '중국과 대만의 대만해협 충돌에 관한 양측 발표와 주요 논쟁사항',
        'status': 'draft', 'evidence': [
            {'claim_id': f'd{i}-c1', 'document_id': f'd{i}', 'label': label,
             'reliability': score, 'translated_quote': '공식 발표의 주장입니다.',
             'original_quote': '無空白的中文原文' * 40,
             'url': 'https://example.com/' + 'long-path-' * 30}
            for i, (label, score) in enumerate([('값 일치', 0.7543), ('개연성 있음', 0.6543), ('판단 보류', 0.5543)])
        ],
    }
    reader = PdfReader(BytesIO(report_pdf(report)))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    for word in report['question'].split():
        assert word in reader.pages[0].extract_text(), f'단어 중간 줄바꿈: {word}'
    for claim in report['evidence']:
        assert claim['label'] in text
        assert str(claim['reliability']) not in text
    assert report['evidence'][0]['reliability'] == 0.7543
