"""PDF 재무제표 ↔ DART 원문 XBRL(zip) 대사.

감사보고서 PDF에서 읽은 재무상태표·손익계산서·현금흐름표의 계정별 당기/전기 금액을 같은
보고서의 XBRL 인스턴스 값과 대사한다. XBRL은 '연결/별도 구분 축 하나만 있는' context(본문
재무제표 값)만 사용한다. XBRL 재무상태표에는 전전기말(예: 2023-12-31) 값도 들어 있으므로
PDF만으로는 못 하는 '현금흐름표 전기 기초현금 = 전전기말 현금' 연속성도 함께 확인한다.

매칭 순서: (1) 정규화한 라벨이 같은 요소 → 금액 비교  (2) 라벨이 달라도 당기·전기 금액이 모두 같은
요소(부호 무시) → '일치(값 기준)'  (3) 없으면 'XBRL 미발견'.
"""
import re
from datetime import date

from .xbrl_loader import resolve_xbrl_source, validate_xbrl_files
from .xbrl_hierarchy import find_statement_roles, load_labels, role_elements, _is_structural
from .xbrl_facts import parse_contexts, parse_facts, CONSOLIDATED_MEMBER, SEPARATE_MEMBER

ROMAN = re.compile(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.\s*')
STMTS = (('BS', '재무상태표'), ('IS', '손익계산서'), ('CF', '현금흐름표'))

# 현금흐름표 지출(유출) 요소: XBRL은 지출액을 양수로 태깅하고 PDF는 (괄호) 음수로 표시하는 것이 관행.
# 이 요소들은 XBRL 값의 부호를 바꿔 PDF와 같은 기준으로 비교한다 (IncomeTaxesPaidRefund 도 '납부=양수' 정의).
OUTFLOW_RE = re.compile(r'(Payments?(Of|For|To)|PurchaseOf|RepaymentsOf|InterestPaid|IncomeTaxesPaid|DividendsPaid|'
                        r'CashAdvancesAndLoansMadeTo|AcquisitionOf)')


def sign_convention(code: str, name: str) -> int:
    return -1 if code == 'CF' and OUTFLOW_RE.search(name or '') else 1


def _key(label: str) -> str:
    s = ROMAN.sub('', label or '')
    s = re.sub(r'\[.*?\]|\(.*?\)', '', s)
    return re.sub(r'[\s·ㆍ,및\-]', '', s)


def load_statement_facts(source_path: str, kind: str):
    """returns ({stmt: [{"name","label","by_date":{date_str: value}}]}, dates_desc, error)"""
    try:
        files = resolve_xbrl_source(source_path)
    except Exception as e:  # noqa: BLE001
        return {}, [], f"XBRL 압축해제/탐색 실패: {e}"
    err = validate_xbrl_files(files)
    if err:
        return {}, [], err
    member = CONSOLIDATED_MEMBER if kind == 'consolidated' else SEPARATE_MEMBER
    try:
        roles = find_statement_roles(files['schema'])
        labels = load_labels(files['label_ko'])
        contexts = parse_contexts(files['instance'])
        facts = parse_facts(files['instance'])
    except Exception as e:  # noqa: BLE001
        return {}, [], f"XBRL 파싱 실패: {e}"
    out, dates = {}, set()
    for code, stmt in STMTS:
        role = roles.get((stmt, kind))
        if not role:
            out[code] = []
            continue
        rows = []
        for name in sorted(role_elements(files['presentation'], role)):
            if _is_structural(name) and not name.endswith('Abstract'):
                continue   # Abstract에 값을 태깅한 사례가 있어(태깅 오류) 값이 있으면 포함
            by_date = {}
            for cid, val in facts.get(name, []):
                ctx = contexts.get(cid)
                if not ctx or val is None or len(ctx['dims']) != 1 or next(iter(ctx['dims'].values())) != member:
                    continue
                try:
                    v = float(val)
                except ValueError:
                    continue
                if ctx['instant']:
                    d = ctx['instant']
                elif ctx['start'] and ctx['end']:
                    days = (date.fromisoformat(ctx['end']) - date.fromisoformat(ctx['start'])).days
                    if days < 300:          # 연간 감사보고서: 12개월 기간만
                        continue
                    d = ctx['end']
                else:
                    continue
                by_date[d] = v
                dates.add(d)
            if by_date:
                rows.append({'name': name, 'label': labels.get(name, name), 'by_date': by_date})
        out[code] = rows
    return out, sorted(dates, reverse=True), None


def tieout(rep, source_path: str, kind: str) -> dict:
    """rep: audit_footing.Report (run 완료). returns {"rows":[...], "continuity":[...], "error":str|None}"""
    xf, dates, err = load_statement_facts(source_path, kind)
    if err:
        return {'rows': [], 'continuity': [], 'error': err}
    if len(dates) < 2:
        return {'rows': [], 'continuity': [], 'error': 'XBRL에서 당기/전기 기간을 찾지 못했습니다.'}
    d_cur, d_pri = dates[0], dates[1]
    d_pp = dates[2] if len(dates) > 2 else None
    rows, used = [], set()
    for code, stmt in STMTS:
        elems = xf.get(code, [])
        by_key = {}
        for e in elems:
            by_key.setdefault(_key(e['label']), []).append(e)
        for r in rep.fs_rows.get(code, []):
            if r['cy'] is None or r['py'] is None:
                continue
            k = _key(r['label'])
            cand = by_key.get(k, [])

            def vmatch(e):
                sg = sign_convention(code, e['name'])
                c, p = e['by_date'].get(d_cur), e['by_date'].get(d_pri)
                c = c * sg if c is not None else None
                p = p * sg if p is not None else None
                if c is None or abs(abs(c) - abs(r['cy'])) >= 0.5:
                    return False
                return (p is not None and abs(abs(p) - abs(r['py'])) < 0.5) or (p is None and r['py'] == 0)

            hit, how = None, ''
            # 1) 라벨 + 금액 일치  2) 금액 일치(라벨 상이, 동명 계정이 유동/비유동에 중복되는 경우 포함)  3) 라벨만 일치
            hit = next((e for e in cand if vmatch(e)), None)
            if hit is not None:
                how = '라벨'
            elif r['cy'] or r['py']:
                pool = [e for e in elems if (code, e['name']) not in used] + [e for e in elems if (code, e['name']) in used]
                hit = next((e for e in pool if vmatch(e)), None)
                how = '값' if hit is not None else ''
            if hit is None:
                hit = next((e for e in cand if e['by_date'].get(d_cur) is not None), None)
                how = '라벨' if hit is not None else ''
            sg = sign_convention(code, hit['name']) if hit else 1
            for per, dt, pv in (('당기', d_cur, r['cy']), ('전기', d_pri, r['py'])):
                raw = hit['by_date'].get(dt) if hit else None
                if hit is not None and raw is None and pv == 0:
                    raw = 0.0
                xv = raw * sg if raw is not None else None
                if hit is None:
                    res = 'XBRL 미발견'
                elif xv is None:
                    res = 'XBRL 값 없음'
                elif abs(xv - pv) < 0.5:
                    res = '일치' if how == '라벨' else '일치(값 기준)'
                    if hit['name'].endswith('Abstract'):
                        res = '일치(값 기준·XBRL Abstract 요소에 값 태깅 - 태깅 확인)'
                elif abs(abs(xv) - abs(pv)) < 0.5:
                    res = '일치(부호표시 차이)'
                else:
                    res = '불일치'
                note = ''
                if hit is not None and sg == -1 and raw not in (None, 0):
                    note = f'지출항목 - XBRL 원값 {raw:,.0f}(지출=양수 태깅) 부호 변환 후 비교'
                rows.append({'stmt': stmt, 'label': r['label'], 'period': per, 'pdf': pv, 'xbrl': xv, 'xbrl_raw': raw,
                             'xbrl_label': f"{hit['label']} ({hit['name']})" if hit else '', 'result': res, 'note': note})
            if hit:
                used.add((code, hit['name']))
        for e in elems:
            if (code, e['name']) not in used and e['by_date'].get(d_cur) not in (None, 0.0):
                rows.append({'stmt': stmt, 'label': '-', 'period': '당기', 'pdf': None, 'xbrl': e['by_date'].get(d_cur),
                             'xbrl_raw': e['by_date'].get(d_cur), 'note': '',
                             'xbrl_label': f"{e['label']} ({e['name']})",
                             'result': 'PDF 본문에 없음(XBRL 세부태깅 - 참고)'})
    cont = []
    if d_pp:
        cash = next((e for e in xf.get('BS', []) if e['name'].endswith('CashAndCashEquivalents')), None)
        cf_beg = next((r for r in rep.fs_rows.get('CF', []) if '기초' in r['n'] and '현금' in r['n']), None)
        if cash and cf_beg and cash['by_date'].get(d_pp) is not None:
            a, b = cf_beg['py'], cash['by_date'][d_pp]
            cont.append({'item': f'[연속성] 현금흐름표 전기 기초현금 = 전전기말({d_pp}) 재무상태표 현금 (XBRL)',
                         'pdf': a, 'xbrl': b, 'result': '일치' if abs(a - b) < 0.5 else '불일치'})
        eq = next((e for e in xf.get('BS', []) if e['name'] in ('ifrs-full_Equity', 'Equity')), None)
        sce = rep.sce
        begs = [r for r in sce['rows'] if '초)' in r['label']]
        tot = max((i for i, nm in enumerate(sce['names']) if '합계' in nm or '총계' in nm), default=None)
        if eq and begs and tot is not None and eq['by_date'].get(d_pp) is not None:
            a, b = begs[0]['vals'][tot], eq['by_date'][d_pp]
            cont.append({'item': f'[연속성] 자본변동표 전기초 자본총계 = 전전기말({d_pp}) 재무상태표 자본총계 (XBRL)',
                         'pdf': a, 'xbrl': b, 'result': '일치' if a is not None and abs(a - b) < 0.5 else '불일치'})
    return {'rows': rows, 'continuity': cont, 'error': None, 'dates': [d_cur, d_pri, d_pp]}


def add_tieout_sheet(wb, name: str, data: dict) -> None:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    ws = wb.create_sheet(name[:31])
    ws.append(['재무제표', 'PDF 계정과목', '기간', 'PDF 금액', 'XBRL 금액(PDF 부호기준)', '차이', 'XBRL 요소(라벨)', '결과',
               'XBRL 원값', '비고'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True, color='FFFFFF'); c.fill = PatternFill('solid', start_color='1F3864')
    rows = data.get('rows', [])
    for r in data.get('continuity', []):
        rows = [{'stmt': '연속성', 'label': r['item'], 'period': '전기초', 'pdf': r['pdf'], 'xbrl': r['xbrl'],
                 'xbrl_label': '', 'result': r['result'], 'xbrl_raw': r['xbrl'], 'note': ''}] + rows
    if data.get('error'):
        ws.append([f"XBRL 대사 불가: {data['error']}"])
    for i, r in enumerate(rows, start=2):
        ws.append([r['stmt'], r['label'], r['period'], r['pdf'], r['xbrl'], f'=IF(OR(D{i}="",E{i}=""),"",D{i}-E{i})',
                   r['xbrl_label'], r['result'], r.get('xbrl_raw'), r.get('note', '')])
        for j in (4, 5, 6, 9):
            ws.cell(i, j).number_format = '#,##0;(#,##0);-'
        for c in ws[i]:
            c.font = Font(name='Arial', size=9)
    for col, w in zip('ABCDEFGHIJ', (12, 40, 7, 18, 20, 14, 56, 22, 18, 44)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    if rows:
        rng = f'H2:H{len(rows) + 1}'
        ws.conditional_formatting.add(rng, FormulaRule(formula=['LEFT(H2,2)="일치"'], fill=PatternFill('solid', start_color='E2EFDA')))
        ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"불일치"'], fill=PatternFill('solid', start_color='F8CBAD')))
        ws.conditional_formatting.add(rng, FormulaRule(formula=['AND(LEFT(H2,2)<>"일치",H2<>"불일치")'],
                                                       fill=PatternFill('solid', start_color='FFF2CC')))


def summary(data: dict) -> dict:
    res = [r['result'] for r in data.get('rows', []) if r['pdf'] is not None] + [r['result'] for r in data.get('continuity', [])]
    return {'area': 'PDF ↔ XBRL 대사', 'total': len(res), 'ok': sum(1 for x in res if x.startswith('일치')), 'rounding': 0,
            'mismatch': res.count('불일치'), 'other': sum(1 for x in res if not x.startswith('일치') and x != '불일치')}
