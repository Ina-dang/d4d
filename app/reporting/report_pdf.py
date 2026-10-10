"""저장된 보고서만 PDF로 렌더링한다. 모델 호출이나 검토 상태 변경은 없다."""

from functools import lru_cache
from io import BytesIO
from threading import Lock
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

from app.core.paths import STATIC
from app.reporting.reliability_report import SECTION_TITLES

FONT = 'GyeopnunSans'
FONT_PATH = STATIC / 'fonts' / 'NotoSansCJKkr-Regular.ttf'
FONT_LOCK = Lock()
STATUS = {'draft': '확인 대기', 'approved': '확인·저장 완료', 'held': '검토 보류'}
LABEL_COLORS = {
    '값 일치': ('#e3f0e6', '#35634a'),
    '개연성 있음': ('#f7f0d6', '#756020'),
    '판단 보류': ('#f8e7da', '#8a522e'),
}


class ReliabilityPill(Flowable):
    """숫자 대신 반환된 라벨을 색과 글자로 함께 표시한다."""

    def __init__(self, label):
        super().__init__()
        self.label = label or '라벨 미제공'
        self.background, self.foreground = LABEL_COLORS.get(self.label, ('#edf0f2', '#52616a'))
        self.width = pdfmetrics.stringWidth(self.label, FONT, 9) + 20
        self.height = 22
        self.spaceAfter = 8
        self.keepWithNext = True

    def draw(self):
        self.canv.setFillColor(colors.HexColor(self.background))
        self.canv.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        self.canv.setFillColor(colors.HexColor(self.foreground))
        self.canv.setFont(FONT, 9)
        self.canv.drawString(10, 7, self.label)


@lru_cache(maxsize=1)
def register_font():
    with FONT_LOCK:
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))


def report_pdf(report):
    register_font()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=23 * mm, bottomMargin=20 * mm,
        title=report['question'], author='겹눈', pageCompression=1,
    )
    # 띄어쓰기 단위로 줄을 바꾼다. 한 줄보다 긴 URL·무공백 원문만 나눠 넘침을 막는다.
    base = dict(fontName=FONT, fontSize=10, leading=16, wordWrap='LTR',
                textColor=colors.HexColor('#182c3b'), alignment=TA_LEFT, splitLongWords=True)
    body = ParagraphStyle('body', **base, spaceAfter=9)
    heading = ParagraphStyle('heading', parent=body, fontSize=14, leading=21,
                             spaceBefore=17, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle('title', parent=body, fontSize=20, leading=29, spaceAfter=16)
    small = ParagraphStyle('small', parent=body, fontSize=8.5, leading=13,
                           textColor=colors.HexColor('#526674'))
    candidate = ParagraphStyle('candidate', parent=body, leftIndent=10,
                               borderPadding=8, backColor=colors.HexColor('#f0f4f6'))
    source_title = ParagraphStyle('source-title', parent=heading, fontSize=11, leading=17)
    source_name = ParagraphStyle('source-name', parent=body, keepWithNext=True)
    source_meta = ParagraphStyle('source-meta', parent=small, keepWithNext=True)
    story = []

    def clean(value):
        # 원문은 마크업으로 실행하지 않고 텍스트로만 넣는다.
        text = ''.join(c for c in str(value or '') if ord(c) >= 32 or c in '\n\t')
        return escape(text).replace('\n', '<br/>')

    def add(value, style=body):
        story.append(Paragraph(clean(value), style))

    evidence = report.get('evidence', [])
    labels = {claim['claim_id']: f'S{i + 1}' for i, claim in enumerate(evidence)}

    def statement(item, style=body):
        refs = ' '.join(f'[{labels.get(cid, cid)}]' for cid in item.get('claim_ids', []))
        add(f"{item['text']} {refs}".rstrip(), style)

    status = STATUS.get(report.get('status'), report.get('status', '확인 대기'))
    add('겹눈  /  근거·신뢰도 보고서', small)
    add(report['question'], title)
    doc_count = len(report.get('docs', [])) or len({c['document_id'] for c in evidence})
    add(f"{status} · 버전 {report.get('version', 1)} · 문서 {doc_count}개 · 대표 주장 {len(evidence)}개", small)
    if report.get('status') != 'approved':
        add('사람의 확인을 마치지 않은 보고서입니다. 비교 후보와 인용 원문을 검토해 주세요.', small)
    for key, name in SECTION_TITLES.items():
        add(name, heading)
        items = report.get('sections', {}).get(key, [])
        proposed = [p for p in report.get('proposed_comparisons', []) if p['section'] == key]
        if not items and not proposed:
            add('같은 내용을 담은 주장 쌍을 찾지 못했습니다.' if key == 'common_facts'
                else '같은 대상·시점·조건에서 충돌하는 주장 쌍을 찾지 못했습니다.'
                if key == 'conflicting_candidates' else '판단할 근거가 충분하지 않습니다.')
        for item in items:
            statement(item)
        for item in proposed:
            add('검토할 공통 내용 후보 · 원문 대조 전' if key == 'common_facts'
                else '검토할 상충 후보 · 판단 보류', small)
            statement(item, candidate)

    story.append(PageBreak())
    add('근거 문장과 신뢰도', heading)
    add('라벨은 신뢰도 함수의 판정입니다. 내용의 사실 여부를 확정하지 않으며 원문과 함께 검토해야 합니다.', small)
    for claim in evidence:
        name = f"[{labels[claim['claim_id']]}] {claim.get('source_name') or claim['document_id']}"
        pill = ReliabilityPill(claim.get('label'))
        source_header = Table([[Paragraph(clean(name), source_title), pill]],
            colWidths=[document.width - 24 - pill.width, pill.width + 12],
            style=[('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                   ('LEFTPADDING', (0, 0), (-1, -1), 0), ('LEFTPADDING', (1, 0), (1, 0), 12),
                   ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                   ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)],
            spaceBefore=17, spaceAfter=9)
        source_header.keepWithNext = True
        story.append(source_header)
        add(claim.get('title') or claim['document_id'], source_name)
        add(f"주장 ID: {claim['claim_id']} · 문서 ID: {claim['document_id']}", source_meta)
        add('번역: ' + str(claim.get('translated_quote') or ''))
        add('원문: ' + str(claim.get('original_quote') or ''))
        url = str(claim.get('url') or '')
        if urlsplit(url).scheme.lower() in {'http', 'https'}:
            safe_url = escape(url, {'"': '&quot;', "'": '&apos;'})
            story.append(Paragraph(f'<link href="{safe_url}" color="#215e75">{clean(url)}</link>', small))
        story.append(Spacer(1, 5))

    if report.get('warnings'):
        add('처리 기록과 추가 한계', heading)
        for warning in report['warnings']:
            add(warning, small)
    if report.get('excluded_statements'):
        add('근거 검토에서 보류·제외한 문장', heading)
        for item in report['excluded_statements']:
            add(item['text'])
            add('보류·제외 이유: ' + item.get('reason', ''), small)
    add('검토 기록', heading)
    if not report.get('audit'):
        add('아직 사람의 검토 기록이 없습니다.', small)
    for item in report.get('audit', []):
        action = {'approve': '확인·저장', 'hold': '검토 보류', 'reopen': '재검토'}.get(item['action'], item['action'])
        add(f"{item['reviewer']} · {action} · {item.get('at', '')}", small)
        add(item.get('note', ''))

    def page_frame(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor('#526674'))
        canvas.drawString(20 * mm, A4[1] - 14 * mm, '겹눈 · 근거·신뢰도 보고서')
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 14 * mm, status)
        canvas.setStrokeColor(colors.HexColor('#d5dfe5'))
        canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        canvas.drawString(20 * mm, 11 * mm, f"버전 {report.get('version', 1)}")
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return buffer.getvalue()
