"""당기 감사보고서 ↔ 전기 감사보고서 주석 비교.

1) 주석 목록 비교: 제목으로 짝을 지어 유지 / 번호변경 / 제목변경 / 당기 신설 / 당기 삭제 판정
2) 주석 숫자 대사: 당기 보고서 주석 표의 '전기' 금액 = 전기 보고서 같은 표의 '당기' 금액

표의 각 숫자 칸에 기간(당기/전기)을 붙이는 순서
  - 열 이름에 '당기'/'전기'가 있으면 그 열의 기간 (예: 당기말 | 전기말)
  - 아니면 표 안의 기간 머리행 (예: '당기말' 행 아래 ~ '전기말' 행 전까지)
  - 아니면 표 제목 '1) 당기' / '(2) 전기'
기간을 정할 수 없는 표(특정 시점 현황 등)는 대사 대상에서 제외한다.
짝짓기 키 = (주석, 표 제목[번호·기간어 제거], 구분 머리행, 행 라벨, 열 이름[기간어 제거], 같은 키 내 순번)
"""
import re
from difflib import SequenceMatcher

from .audit_footing import norm

PERIOD_WORDS = re.compile(r'(당기말|전기말|당기초|전기초|당기|전기|기말|기초)')
PERIOD_ROW = {'당기', '당기말', '전기', '전기말'}
# 계정명 안의 '당기/전기'(당기손익-공정가치, 당기법인세 등) - 열 기간 판단에서 제외
ACCT_PERIOD = re.compile(r'(당기|전기)(손익|순이익|순손실|순손익|법인세)')


def _clean_title(t: str) -> str:
    t = re.sub(r'^\(?\d+\)\s*', '', t or '')
    t = re.sub(r'[\s()\[\]<>:·ㆍ,\-]', '', t)
    return t


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def compare_note_lists(cur, prior) -> list:
    """returns [{'cur_no','cur_title','prior_no','prior_title','status'}]"""
    cl, pl = getattr(cur, 'note_index', []), getattr(prior, 'note_index', [])
    used, out = set(), []
    for c in cl:
        ck = _clean_title(c['title'])
        best, score = None, 0.0
        for i, p in enumerate(pl):
            if i in used:
                continue
            sc = 1.0 if _clean_title(p['title']) == ck else _sim(ck, _clean_title(p['title']))
            if sc > score:
                best, score = i, sc
        if best is not None and score >= 0.72:
            used.add(best)
            p = pl[best]
            if score < 1.0:
                st = '제목변경'
            elif p['no'] != c['no']:
                st = '번호변경'
            else:
                st = '유지'
            out.append({'cur_no': c['no'], 'cur_title': c['title'], 'prior_no': p['no'], 'prior_title': p['title'],
                        'status': st, 'cur_page': cur.pg(c['page']), 'prior_page': prior.pg(p['page'])})
        else:
            out.append({'cur_no': c['no'], 'cur_title': c['title'], 'prior_no': None, 'prior_title': '',
                        'status': '당기 신설', 'cur_page': cur.pg(c['page']), 'prior_page': None})
    for i, p in enumerate(pl):
        if i not in used:
            out.append({'cur_no': None, 'cur_title': '', 'prior_no': p['no'], 'prior_title': p['title'],
                        'status': '당기 삭제', 'cur_page': None, 'prior_page': prior.pg(p['page'])})
    out.sort(key=lambda r: (r['cur_no'] if r['cur_no'] is not None else 999, r['prior_no'] or 0))
    return out


def _cells(rep, want: str) -> dict:
    """{(note_title_key, table_key, section, row, col, occ): (value_in_won, info)} - 기간이 want 인 칸만."""
    out = {}
    for t in rep.note_tables:
        if not t['cols']:
            continue
        scale = {'천원': 1000, '백만원': 1e6, '원': 1}.get(t['unit'], 1)
        ttag = rep.period_tag(t)
        tkey = _clean_title(PERIOD_WORDS.sub('', t.get('sub', ''))) + '/' + _clean_title(PERIOD_WORDS.sub('', t.get('subsub', '')))
        nkey = _clean_title(t['note_title'])
        colp, colk = [], []
        for nm in t['colnames']:
            n = (nm or '').replace(' ', '')
            # '당기손익-공정가치', '당기법인세' 같은 계정명 속 '당기/전기'는 기간이 아님
            np_ = ACCT_PERIOD.sub('', n)
            p_ = '전기' if '전기' in np_ else ('당기' if '당기' in np_ else None)
            # 2단 머리글(당기말 → 유동|비유동): 앞 열이 '기간+하위항목'이면 기간어 없는 다음 열도 같은 기간
            if p_ is None and colp and colp[-1] and colk and colk[-1] != '금액':
                p_ = colp[-1]
            colp.append(p_)
            n2 = re.sub(r'^(구분|과목|항목|내역|계정)', '', PERIOD_WORDS.sub('', n))
            colk.append(n2 or '금액')
        row_period, section, seen = None, '', {}
        prev = None
        for r in t['rows']:
            if not r['nums']:
                lab = re.sub(r'[<>()\[\]]', '', r['n'])
                if lab in PERIOD_ROW:
                    row_period = '전기' if '전기' in lab else '당기'
                    section, seen = '', {}
                elif r['label'] and len(r['n']) <= 30 and not PERIOD_WORDS.search(r['n']) and \
                        not (prev is not None and prev['nums'] and not rep.is_total(prev['n'])):
                    # 기간어가 든 행(열 머리글)은 구분으로 보지 않음.
                    # 금액 행 바로 뒤의 빈 행(예: 금액 없이 이름만 있는 '단기금융상품')은 구분 머리글이 아니라 빈 항목
                    section = r['n']
                prev = r
                continue
            prev = r
            vec = rep._rowvec(t, r)
            for j, v in vec.items():
                per = colp[j] if j < len(colp) and colp[j] else (row_period or ttag)
                if per != want:
                    continue
                base = (nkey, tkey, section, r['n'], colk[j] if j < len(colk) else f'열{j + 1}')
                occ = seen.get(base, 0); seen[base] = occ + 1
                out[base + (occ,)] = (v * scale, {'note': t['note'], 'note_title': t['note_title'], 'table': t['title'],
                                                  'row': r['label'], 'col': t['colnames'][j] if j < len(t['colnames']) else '',
                                                  'page': rep.pg(r['page']), 'unit': t['unit'], 'raw': v})
    return out


def compare_note_numbers(cur, prior, note_pairs: list) -> list:
    """당기 보고서의 전기 칸 ↔ 전기 보고서의 당기 칸. note_pairs: compare_note_lists 결과(제목변경 주석 연결용)."""
    rename = {_clean_title(r['cur_title']): _clean_title(r['prior_title']) for r in note_pairs if r['cur_no'] and r['prior_no']}
    c_cells = _cells(cur, '전기')
    p_cells = _cells(prior, '당기')
    # 제목이 바뀐 주석은 전기 제목 키로 맞춤
    c_cells = {(rename.get(k[0], k[0]),) + k[1:]: v for k, v in c_cells.items()}
    # 표 제목이 조금 바뀐 경우: 같은 주석 안에서 표 키를 유사도로 연결
    p_tables = {}
    for k in p_cells:
        p_tables.setdefault(k[0], set()).add(k[1])
    tmap = {}
    for k in c_cells:
        if k[1] in p_tables.get(k[0], set()):
            continue
        cands = p_tables.get(k[0], set())
        best = max(cands, key=lambda x: _sim(k[1], x), default=None)
        if best is not None and _sim(k[1], best) >= 0.7:
            tmap[(k[0], k[1])] = best
    c_cells = {(k[0], tmap.get((k[0], k[1]), k[1])) + k[2:]: v for k, v in c_cells.items()}
    # 같은 (표, 구분, 행, 열)이 여러 번 나오는 경우(같은 이름의 차입처 등) 순번 대신 금액이 같은 칸끼리 먼저 짝짓기
    def regroup(cells):
        g = {}
        for k, v in cells.items():
            g.setdefault(k[:-1], []).append((k, v))
        return g
    cg, pg_ = regroup(c_cells), regroup(p_cells)
    pairs = {}
    for base, citems in cg.items():
        pitems = list(pg_.get(base, []))
        if len(citems) == 1 and len(pitems) == 1:
            pairs[citems[0][0]] = pitems[0][0]; continue
        free = list(pitems)
        rest = []
        for ck, (cv, ci) in citems:
            hit = next((pk for pk, (pv, pi) in free if abs(pv - cv) < 0.5), None)
            if hit is not None:
                pairs[ck] = hit; free = [x for x in free if x[0] != hit]
            else:
                rest.append(ck)
        if len(rest) == 1 and len(free) == 1 and len(citems) == 1:
            pairs[rest[0]] = free[0][0]   # 동일 이름 행이 여럿이면 금액이 다른 나머지는 순서로 억지로 짝짓지 않음(오탐 방지)
    # 2차: 표 제목이 달라 못 찾은 칸 → 같은 주석 안에서 (구분, 행, 열, 순번)이 양쪽 모두 유일하면 연결
    pk_used = set(pairs.values())
    def loose(k):
        return (k[0],) + k[2:]
    cl, pl = {}, {}
    for k in c_cells:
        if k not in pairs:
            cl.setdefault(loose(k), []).append(k)
    for k in p_cells:
        if k not in pk_used:
            pl.setdefault(loose(k), []).append(k)
    for lk, cks in cl.items():
        if len(cks) == 1 and len(pl.get(lk, [])) == 1:
            pairs[cks[0]] = pl[lk][0]
    # 3차: 같은 표 안에서 구분(섹션) 문맥만 달라 못 찾은 칸 → (주석, 표, 행, 열, 순번)이 양쪽 모두 유일하면 연결
    pk_used = set(pairs.values())
    def nosec(k):
        return k[:2] + k[3:]
    cl, pl = {}, {}
    for k in c_cells:
        if k not in pairs:
            cl.setdefault(nosec(k), []).append(k)
    for k in p_cells:
        if k not in pk_used:
            pl.setdefault(nosec(k), []).append(k)
    for lk, cks in cl.items():
        if len(cks) == 1 and len(pl.get(lk, [])) == 1:
            pairs[cks[0]] = pl[lk][0]
    # 4차·5차: 같은 주석·같은 표 안에서 금액이 같은 칸 연결 (양쪽 모두 유일할 때만)
    #   4차 = 행 이름(각주표시 (*1) 제거)이 같고 금액이 같음 → 열 머리글 문구·비율(%)만 다른 경우
    #   5차 = 열 이름이 같고 금액이 같음(0 제외) → 계정명 변경(장단기→장기), 회사명이 행에 붙은 경우 등
    foot = lambda s: re.sub(r'\(\*[^)]*\)|\*\d+', '', s)
    colk_ = lambda s: re.sub(r'-?\d+(\.\d+)?%', '', s)
    paren = lambda s: re.sub(r'\(.*?\)|\*\d+', '', s)   # 괄호 안 문구 전체 제거: '대손설정(환입)' = '대손설정'
    for keyf, nonzero in ((lambda k, v: (k[0], k[1], foot(k[3]), round(v)), False),
                          (lambda k, v: (k[0], k[1], colk_(k[4]), round(v)), True),
                          # 표 제목이 해마다 달라 표 키가 안 맞는 경우: 같은 주석 안 행 이름+금액
                          (lambda k, v: (k[0], paren(k[3]), round(v)), True),
                          # 주석 통합·분리(예: 전기 '8.선급금' → 당기 '9.기타자산'): 주석과 무관하게 행 이름+금액
                          (lambda k, v: (paren(k[3]), round(v)), True)):
        pk_used = set(pairs.values())
        cl, pl = {}, {}
        for k, (v, _) in c_cells.items():
            if k not in pairs and not (nonzero and round(v) == 0):
                cl.setdefault(keyf(k, v), []).append(k)
        for k, (v, _) in p_cells.items():
            if k not in pk_used and not (nonzero and round(v) == 0):
                pl.setdefault(keyf(k, v), []).append(k)
        for lk, cks in cl.items():
            if len(cks) == 1 and len(pl.get(lk, [])) == 1:
                pairs[cks[0]] = pl[lk][0]
    # 6차: 행 이름이 바뀐 행 - 이미 짝지어진 칸으로 '당기 행 ↔ 전기 행' 대응을 알면, 같은 행의 나머지 칸(0 포함)을 열 기준으로 연결
    alias, bad = {}, set()
    for ck, pk in pairs.items():
        a = (ck[0], ck[1], ck[3])
        if a in alias and alias[a] != pk[3]:
            bad.add(a)
        alias.setdefault(a, pk[3])
    pk_used = set(pairs.values())
    cl, pl = {}, {}
    for k in c_cells:
        a = (k[0], k[1], k[3])
        if k not in pairs and a in alias and a not in bad and alias[a] != k[3]:
            cl.setdefault((k[0], k[1], alias[a], k[4], k[5]), []).append(k)
    for k in p_cells:
        if k not in pk_used:
            pl.setdefault((k[0], k[1], k[3], k[4], k[5]), []).append(k)
    for lk, cks in cl.items():
        if len(cks) == 1 and len(pl.get(lk, [])) == 1:
            pairs[cks[0]] = pl[lk][0]
    out, used = [], set()
    for k, (cv, ci) in c_cells.items():
        pk = pairs.get(k)
        pv = p_cells.get(pk) if pk else None
        if pv is None:
            res, pval, pinfo = '전기보고서에 없음(신설·재분류·표 형식 변경 확인)', None, {}
        else:
            used.add(pk)
            pval, pinfo = pv
            tol = 1000 if ci['unit'] == '천원' or pinfo.get('unit') == '천원' else 1
            d = abs(cv - pval)
            res = '일치' if d == 0 else ('단수차이' if d <= tol else '불일치(재작성·재분류 확인)')
        out.append({'note': ci['note'], 'note_title': ci['note_title'], 'table': ci['table'], 'row': ci['row'],
                    'col': ci['col'], 'unit': ci['unit'], 'cur_prior': ci['raw'],
                    'prior_cur': pinfo.get('raw') if pv else None, 'cur_page': ci['page'],
                    'prior_page': pinfo.get('page') if pv else None,
                    'prior_note': pinfo.get('note') if pv else None, 'prior_row': pinfo.get('row') if pv else None,
                    'prior_note_title': pinfo.get('note_title') if pv else None,
                    'result': res})
    for k, (pv, pi) in p_cells.items():
        if k not in used:
            out.append({'note': None, 'note_title': pi['note_title'], 'table': pi['table'], 'row': pi['row'], 'col': pi['col'],
                        'unit': pi['unit'], 'cur_prior': None, 'prior_cur': pi['raw'], 'cur_page': None,
                        'prior_page': pi['page'], 'prior_note': pi['note'],
                        'result': '당기보고서에 없음(삭제·통합·표 형식 변경 확인)'})
    # 후처리: 여러 줄 셀 때문에 '구분' 문맥이 해마다 달라 잘못 짝지어진 불일치 → 같은 표·행·열에서 같은 금액이 있으면 일치로 정정
    by_loose = {}
    for k, (pv, pi) in p_cells.items():
        by_loose.setdefault((k[0], k[1], k[3], k[4]), []).append((k, pv))
    unpaired_prior = {id(r): r for r in out if r['cur_prior'] is None}
    ckey = {}
    for k, (cv, ci) in c_cells.items():
        ckey[(ci['note'], ci['table'], ci['row'], ci['col'], ci['raw'])] = k
    for r in out:
        if not r['result'].startswith('불일치'):
            continue
        k = ckey.get((r['note'], r['table'], r['row'], r['col'], r['cur_prior']))
        if not k:
            continue
        scale = {'천원': 1000, '백만원': 1e6, '원': 1}.get(r['unit'], 1)
        alt = [pv for pk, pv in by_loose.get((k[0], k[1], k[3], k[4]), []) if abs(pv - r['cur_prior'] * scale) < 0.5]
        if alt:
            r['result'] = '일치'
            r['prior_cur'] = r['cur_prior']
            for x in list(unpaired_prior.values()):
                if x['row'] == r['row'] and x['col'] == r['col'] and x['prior_cur'] == r['cur_prior']:
                    out.remove(x); unpaired_prior.pop(id(x)); break
    order = {'불일치(재작성·재분류 확인)': 0, '단수차이': 1}
    out.sort(key=lambda r: (order.get(r['result'], 3 if r['result'] == '일치' else 2), r['note'] or 999))
    return out


def summary(note_list: list, note_nums: list, fs_rows: list) -> dict:
    cnt = lambda lst, key, val: sum(1 for r in lst if r[key] == val)
    return {
        'fs_total': sum(1 for r in fs_rows if r['cur_prior_col'] is not None and r['prior_report_cy'] is not None),
        'fs_mismatch': sum(1 for r in fs_rows if r['result'].startswith('불일치')),
        'notes_new': [f"{r['cur_no']}. {r['cur_title']}" for r in note_list if r['status'] == '당기 신설'],
        'notes_removed': [f"{r['prior_no']}. {r['prior_title']}" for r in note_list if r['status'] == '당기 삭제'],
        'notes_renamed': [f"{r['prior_title']} → {r['cur_title']}" for r in note_list if r['status'] == '제목변경'],
        'num_total': sum(1 for r in note_nums if r['cur_prior'] is not None and r['prior_cur'] is not None),
        'num_ok': cnt(note_nums, 'result', '일치'), 'num_round': cnt(note_nums, 'result', '단수차이'),
        'num_mismatch': cnt(note_nums, 'result', '불일치(재작성·재분류 확인)'),
        'num_unpaired': sum(1 for r in note_nums if r['cur_prior'] is None or r['prior_cur'] is None),
    }


def _prior_row_note(r) -> str | None:
    """주석전기대사 시트 M열: 전기보고서의 짝 행 이름이 다르거나, 다른 제목의 주석(통합·분리)에서 짝을 찾았을 때만 표시."""
    if r.get('note') is None or not r.get('prior_row'):
        return None
    parts = []
    if r.get('prior_note_title') and _clean_title(r['prior_note_title']) != _clean_title(r.get('note_title') or ''):
        parts.append(f"전기 주석{r['prior_note']}")
    if norm(r['prior_row']) != norm(r['row'] or ''):
        parts.append(r['prior_row'])
    elif parts:
        parts.append(r['prior_row'])
    return ' '.join(parts) or None


def add_sheets(wb, prefix: str, note_list: list, note_nums: list) -> None:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    HDR = PatternFill('solid', start_color='1F3864')
    YEL = PatternFill('solid', start_color='FFF9C4')

    ws = wb.create_sheet(f'{prefix}주석목록비교'[:31])
    ws.append(['당기 주석번호', '당기 주석 제목', '당기 p.', '전기 주석번호', '전기 주석 제목', '전기 p.', '판정'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True, color='FFFFFF'); c.fill = HDR
    for r in note_list:
        ws.append([r['cur_no'], r['cur_title'], r['cur_page'], r['prior_no'], r['prior_title'], r['prior_page'], r['status']])
        for c in ws[ws.max_row]:
            c.font = Font(name='Arial', size=9)
            if r['status'] != '유지':
                c.fill = YEL
    for col, w in zip('ABCDEFG', (10, 40, 8, 10, 40, 8, 12)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'

    ws = wb.create_sheet(f'{prefix}주석전기대사'[:31])
    ws.append(['주석', '주석명', '표', '행', '열', '단위', '당기보고서 전기금액', '전기보고서 당기금액', '차이', '당기 p.',
               '전기 p.', '결과', '전기보고서 행(이름이 다를 때)'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True, color='FFFFFF'); c.fill = HDR
    for i, r in enumerate(note_nums, start=2):
        ws.append([r['note'] if r['note'] is not None else f"(전기 {r['prior_note']})", r['note_title'], r['table'], r['row'],
                   r['col'], r['unit'], r['cur_prior'], r['prior_cur'], f'=IF(OR(G{i}="",H{i}=""),"",G{i}-H{i})',
                   r['cur_page'], r['prior_page'], r['result'],
                   _prior_row_note(r)])
        for j in (7, 8, 9):
            ws.cell(i, j).number_format = '#,##0;(#,##0);-'
        for c in ws[i]:
            c.font = Font(name='Arial', size=9)
    for col, w in zip('ABCDEFGHIJKLM', (8, 22, 36, 26, 18, 6, 18, 18, 12, 7, 7, 34, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    n = len(note_nums) + 1
    if n > 1:
        ws.conditional_formatting.add(f'L2:L{n}', CellIsRule(operator='equal', formula=['"일치"'],
                                                             fill=PatternFill('solid', start_color='E2EFDA')))
        ws.conditional_formatting.add(f'L2:L{n}', FormulaRule(formula=['LEFT(L2,3)="불일치"'],
                                                              fill=PatternFill('solid', start_color='F8CBAD')))
        ws.conditional_formatting.add(f'L2:L{n}', FormulaRule(formula=['AND(L2<>"일치",LEFT(L2,3)<>"불일치")'],
                                                              fill=PatternFill('solid', start_color='FFF2CC')))
