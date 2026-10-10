"""원문 메뉴·목차·질문을 주장으로 내보내지 않는 최소 품질 검사."""

import re

MENU_START = re.compile(
    r'^(?:關鍵字\s*[:：]|关键词\s*[:：]|Keywords?\s*[:：]|跳到主要內容|網站導覽|'
    r'展開搜尋|調整頁面字體|分享至|複製連結|下載專區|下載檔案|Subscribe\b|'
    r'로그인\b|구독\s*안내)', re.I)
MENU_MARKERS = ('另開新視窗', '複製連結', '下載次數', '下載檔案', '調整頁面字體', '網站導覽')
TAIWAN_TERMS = re.compile(r'대만|台\s*[灣湾海]|臺\s*[灣海]|taiwan|formosa', re.I)


def claim_rejection_reason(text):
    visible = re.sub(r'\[\d{1,2}:\d{2}(?::\d{2})?\]', '', text).strip()
    if visible.rstrip('」』”"\'').endswith(('?', '？')):
        return 'question_without_assertion'
    if re.search(r'と(?:いう|言う)(?:と|のは)$', visible):
        return 'unfinished_introductory_clause'
    if re.search(r'何|どう|どっち', visible) and re.search(r'(?:これ|それ|あれ)です[。.]$', visible):
        return 'deictic_answer_without_assertion'
    if MENU_START.match(visible) or sum(marker in visible for marker in MENU_MARKERS) >= 2:
        return 'navigation_or_download_text'
    if (re.match(r'^第\s*\d+\s*[節章]\s', visible) and len(visible) < 120
            and not re.search(r'(?:ている|される|した|する|です|ます|である)[。.]', visible)):
        return 'section_heading'
    return None


def filter_claims(claims, question='', *, require_focus=False):
    accepted, excluded = [], []
    focus_docs = {claim['document_id'] for claim in claims
                  if not claim_rejection_reason(claim['original_quote'])
                  and TAIWAN_TERMS.search(claim['original_quote'])}
    for claim in claims:
        reason = claim_rejection_reason(claim['original_quote'])
        if not reason and require_focus and '대만' in question and claim['document_id'] not in focus_docs:
            reason = 'question_focus_missing'
        (excluded if reason else accepted).append({**claim, 'exclusion_reason': reason} if reason else claim)
    return accepted, excluded
