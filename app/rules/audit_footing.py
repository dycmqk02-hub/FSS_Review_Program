"""감사보고서 정밀 풋팅(Footing) 엔진.

PDF 단어 좌표(pdfplumber extract_words)로 행/열을 복원한 뒤 아래 검증을 수행한다.
  1) 재무제표 본문 풋팅 - 재무상태표(로마자 소계/총계/자본과부채총계), 포괄손익계산서(이익 체인·
     기타포괄·귀속), 현금흐름표(활동별 소계·증감·기말), 자본변동표(가로 합계/총계, 세로 기초→기말)
  2) 재무제표 간 대사 - 기말/기초 현금, 당기순이익, 자본변동표 기말↔재무상태표 자본항목, 전기말=당기초
  3) 주석 표 풋팅 - 세로 합계(소계·합계 계층, 후보식 중 최소차이 채택), 가로 합계(헤더 합계열),
     기초→기말 롤포워드(세로/가로), 동일 '기말' 행 2회 표시 일관성, 부호표시 추정
  4) 재무제표 ↔ 주석 금액 대사 - 주석번호 컬럼이 가리키는 주석 표에서 단위 환산(원/천원/백만원) 후 탐색
  5) 본문 서술 금액 대사 - 감사보고서 본문·주석1의 'xx백만원/천원' 금액 ↔ 재무제표(파생값 포함)
  6) 특수 검증 - 성격별 비용 합계=매출원가+판관비, 주식수 대사, 자본금/주식수, 자본변동표 기간표기

판정: 일치 / 단수차이(천원표시 |차이|<=max(2,구성항목수)) / 불일치 / 부호표시 확인 / 표기 확인 / 미발견.
원 단위 재무제표 본문은 1원 차이도 불일치로 본다. 휴리스틱이므로 예외 항목은 원문 대조가 필요하다.
"""
import json, math, re, sys

import pdfplumber


NUM_RE = re.compile(r'^\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?%?$|^\(?-?\d+(?:\.\d+)?\)?%?$')
DASH = {'-', '–', '—', '−'}


def parse_num(tok):
    """Return float value or None. '-' -> 0.0"""
    t = tok.strip()
    if t in DASH:
        return 0.0
    if not NUM_RE.match(t):
        return None
    if t.endswith('%'):
        return None  # percentages are handled separately (skipped)
    neg = t.startswith('(') and t.endswith(')')
    t = t.strip('()').replace(',', '')
    if t.startswith('-'):
        neg = not neg if neg else True
        t = t[1:]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def extract(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False,
                                       x_tolerance=1.5, y_tolerance=2)
            words.sort(key=lambda w: (round(w['top']), w['x0']))
            lines = []
            for w in words:
                if lines and abs(lines[-1]['top'] - w['top']) <= 2.5:
                    lines[-1]['words'].append(w)
                else:
                    lines.append({'top': w['top'], 'words': [w]})
            out = []
            for ln in lines:
                ws = sorted(ln['words'], key=lambda w: w['x0'])
                toks = [{'t': w['text'], 'x0': round(w['x0'], 1), 'x1': round(w['x1'], 1)} for w in ws]
                text = ' '.join(t['t'] for t in toks)
                out.append({'top': round(ln['top'], 1), 'text': text, 'toks': toks})
            pages.append({'page': pno, 'lines': out})
    return pages


"""(internal)
- 재무제표 본문 풋팅 (재무상태표/포괄손익계산서/자본변동표/현금흐름표)
- 재무제표 간 대사
- 주석 표 풋팅 (세로합계, 가로합계, 기초→기말 롤포워드)
- 재무제표 ↔ 주석 금액 대사
- 감사보고서/주석 본문 서술 금액 ↔ 재무제표 대사
"""

FOOTER = '전자공시시스템'
ROMAN = re.compile(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.\s*')
NOTE_HEAD = re.compile(r'^(\d{1,2})\.\s*([가-힣A-Za-z(].*)$')
SUB_HEAD = re.compile(r'^\((\d{1,2})\)\s*(.*)$')
SUBSUB_HEAD = re.compile(r'^(\d{1,2})\)\s*(.*)$')
MARK = re.compile(r'\(\*\d*\)|\(\*\)|\*\d+')


def norm(s):
    return MARK.sub('', s).replace(' ', '').replace('　', '').strip(':： ')


def is_num_tok(t):
    return parse_num(t) is not None


def is_pct_tok(t):
    return t.endswith('%') and NUM_RE.match(t) is not None


def status(diff, ncomp, exact=False):
    d = abs(diff)
    if d < 1e-6:
        return '일치'
    if exact:
        return '불일치'
    if d <= max(2, ncomp):
        return '단수차이'
    return '불일치'


class Report:
    def __init__(self, source, name=''):
        self.name = name
        if isinstance(source, list):
            self.pages = source
        elif str(source).lower().endswith('.json'):
            self.pages = json.load(open(source, encoding='utf-8'))
        else:
            self.pages = extract(source)
        self.fs_rows = {}        # stmt -> rows
        self.fs_checks = []
        self.cross_checks = []
        self.note_tables = []
        self.note_checks = []
        self.fs_note_checks = []
        self.text_checks = []
        self.skipped = []
        self.sections = {}

    # ------------------------------------------------------------ layout
    def locate_sections(self):
        fs_start = notes_start = notes_end = None
        for p in self.pages:
            texts = [l['text'] for l in p['lines'][:6]]
            joined = ' '.join(texts).replace(' ', '')
            if fs_start is None and any(re.fullmatch(r'(연결)?재무상태표', x.replace(' ', '')) for x in texts):
                fs_start = p['page']
            if fs_start and notes_start is None and texts and texts[0].strip() == '주석':
                notes_start = p['page']
            if notes_start and notes_end is None and p['page'] > notes_start and (
                    '내부회계관리제도' in joined[:40] or '외부감사실시내용' in joined[:40]):
                notes_end = p['page'] - 1
        if notes_end is None:
            notes_end = len(self.pages)
        self.sections = dict(fs_start=fs_start, notes_start=notes_start, notes_end=notes_end)
        return self.sections

    def lines(self, p_from, p_to):
        for p in self.pages[p_from - 1:p_to]:
            for l in p['lines']:
                if l['text'].startswith(FOOTER):
                    continue
                yield p['page'], l

    # ------------------------------------------------------------ statements
    def parse_statements(self):
        s = self.sections
        cur = None
        rows = {'BS': [], 'IS': [], 'SCE': [], 'CF': []}
        sce_lines = []
        for pg, l in self.lines(s['fs_start'], s['notes_start'] - 1):
            t = l['text'].replace(' ', '')
            if t.endswith('재무상태표'):
                cur = 'BS'; continue
            if t.endswith('손익계산서'):
                cur = 'IS'; continue
            if t.endswith('자본변동표'):
                cur = 'SCE'; continue
            if t.endswith('현금흐름표'):
                cur = 'CF'; continue
            if cur is None or t.startswith('"첨부된') or t.startswith('제4') or '(단위' in t:
                continue
            if cur == 'SCE':
                sce_lines.append((pg, l)); continue
            toks = l['toks']
            vals = [tk for tk in toks if tk['x1'] > 330 and is_num_tok(tk['t'])]
            label_toks = [tk for tk in toks if tk['x1'] <= 330 or not is_num_tok(tk['t'])]
            notes = [tk['t'] for tk in label_toks if re.fullmatch(r'[\d,]+', tk['t']) and tk['x0'] > 150]
            label = ' '.join(tk['t'] for tk in label_toks if tk['t'] not in notes).strip()
            if label.replace(' ', '').startswith('과목'):
                continue
            if len(vals) >= 2:
                cy, py = parse_num(vals[-2]['t']), parse_num(vals[-1]['t'])
            elif len(vals) == 1:
                continue
            else:
                cy = py = None
            rows[cur].append(dict(page=pg, label=label, n=norm(label), notes=','.join(notes), cy=cy, py=py))
        self.fs_rows = rows
        self.parse_sce(sce_lines)

    def _add_fs(self, stmt, item, formula, period, reported, calc, page, exact=True):
        diff = (reported or 0) - (calc or 0)
        self.fs_checks.append(dict(구분=stmt, 항목=item, 기간=period, 검증식=formula, 보고금액=reported,
                                   계산금액=calc, 차이=diff, 결과=status(diff, 0, exact), 페이지=page))

    def foot_bs(self):
        rows = self.fs_rows['BS']
        sec = None
        groups = []  # (header_row, [details])
        totals = {}
        sec_groups = {}
        for r in rows:
            n = r['n']
            if r['cy'] is None:
                if n in ('자산', '부채', '자본'):
                    sec = n; sec_groups[sec] = []
                continue
            if '총계' in n:
                totals[n] = r
                continue
            if ROMAN.match(r['label']) or n.endswith('귀속되는자본'):
                g = [r, []]; sec_groups.setdefault(sec, []).append(g)
            elif n == '비지배지분' or not sec_groups.get(sec):
                sec_groups.setdefault(sec, []).append([None, [r]])
            else:
                sec_groups[sec][-1][1].append(r)
        stmt = '재무상태표'
        sec_tot = {}
        for sec, gs in sec_groups.items():
            for hdr, det in gs:
                if hdr is None or not det:
                    continue
                for per in ('cy', 'py'):
                    calc = sum(d[per] for d in det)
                    self._add_fs(stmt, hdr['label'], f"{hdr['n']} = Σ하위 {len(det)}개 항목", per, hdr[per], calc, hdr['page'])
            # section total
            tot_key = [k for k in totals if k.startswith(sec) and k.endswith('총계') and '과' not in k]
            if tot_key:
                tr = totals[tot_key[0]]
                sec_tot[sec] = tr
                parts = [h if h is not None else None for h, _ in gs]
                for per in ('cy', 'py'):
                    calc = 0
                    for h, det in gs:
                        calc += h[per] if h is not None else sum(d[per] for d in det)
                    self._add_fs(stmt, tr['label'], f"{tr['n']} = Σ{sec} 구분합계", per, tr[per], calc, tr['page'])
        tl = [v for k, v in totals.items() if '자본과부채' in k or '부채와자본' in k]
        if tl and '부채' in sec_tot and '자본' in sec_tot:
            for per in ('cy', 'py'):
                self._add_fs(stmt, tl[0]['label'], '자본과부채총계 = 부채총계 + 자본총계', per, tl[0][per],
                             sec_tot['부채'][per] + sec_tot['자본'][per], tl[0]['page'])
                if '자산' in sec_tot:
                    self._add_fs(stmt, '자산총계', '자산총계 = 자본과부채총계', per, sec_tot['자산'][per], tl[0][per],
                                 tl[0]['page'])

    def foot_is(self):
        rows = [r for r in self.fs_rows['IS']]
        stmt = '포괄손익계산서'
        def get(key):
            for r in rows:
                if ROMAN.sub('', r['label']).replace(' ', '').startswith(key):
                    return r
            return next((r for r in rows if key in r['n']), None)

        def chk(target, comps, formula):
            t = get(target)
            cs = [(get(k), s) for k, s in comps]
            if t is None or any(c is None for c, _ in cs):
                return
            for per in ('cy', 'py'):
                calc = sum(s * c[per] for c, s in cs)
                self._add_fs(stmt, t['label'], formula, per, t[per], calc, t['page'])

        chk('매출총이익', [('매출액', 1), ('매출원가', -1)], '매출총이익 = 매출액 - 매출원가')
        chk('영업이익', [('매출총이익', 1), ('판매비와관리비', -1)], '영업이익 = 매출총이익 - 판관비')
        # 영업이익 ~ 차감전 사이 항목은 명칭으로 부호 결정
        idx_op = next((i for i, r in enumerate(rows) if '영업이익' in r['n']), None)
        idx_pt = next((i for i, r in enumerate(rows) if '차감전' in r['n']), None)
        if idx_op is not None and idx_pt is not None:
            mids = [r for r in rows[idx_op + 1:idx_pt] if r['cy'] is not None]
            t = rows[idx_pt]
            desc = []
            for per in ('cy', 'py'):
                calc = rows[idx_op][per]
                for r in mids:
                    sgn = -1 if ('비용' in r['n'] or r['n'].endswith('손실')) else 1
                    calc += sgn * r[per]
                    if per == 'cy':
                        desc.append(('-' if sgn < 0 else '+') + r['n'])
                self._add_fs(stmt, t['label'], '차감전순이익 = 영업이익 ' + ' '.join(desc), per, t[per], calc, t['page'])
        chk('당기순이익', [('법인세비용차감전', 1), ('법인세비용(', -1)], '당기순이익 = 차감전순이익 - 법인세비용')
        # 기타포괄손익
        i_oci = next((i for i, r in enumerate(rows) if '기타포괄손익' in r['n'] and ROMAN.match(r['label'])), None)
        i_tci = next((i for i, r in enumerate(rows) if '총포괄손익' in r['n'] and ROMAN.match(r['label'])), None)
        if i_oci is not None and i_tci is not None:
            subs = [r for r in rows[i_oci + 1:i_tci] if r['cy'] is not None]
            if subs:
                for per in ('cy', 'py'):
                    self._add_fs(stmt, rows[i_oci]['label'], f'기타포괄손익 = Σ세부항목 {len(subs)}개', per,
                                 rows[i_oci][per], sum(r[per] for r in subs), rows[i_oci]['page'])
            ni = get('당기순이익')
            for per in ('cy', 'py'):
                self._add_fs(stmt, rows[i_tci]['label'], '총포괄손익 = 당기순이익 + 기타포괄손익', per, rows[i_tci][per],
                             ni[per] + rows[i_oci][per], rows[i_tci]['page'])
        # 귀속
        for key, base in (('당기순이익(손실)의귀속', '당기순이익'), ('총포괄손익의귀속', '총포괄손익')):
            i = next((i for i, r in enumerate(rows) if key.replace('(손실)', '') in r['n'].replace('(손실)', '')), None)
            if i is None:
                continue
            subs = []
            for r in rows[i + 1:]:
                if ROMAN.match(r['label']):
                    break
                if r['cy'] is not None:
                    subs.append(r)
            b = next((r for r in rows if r['n'].replace(' ', '').endswith(base) or (base in r['n'] and ROMAN.match(r['label']) and '귀속' not in r['n'])), None)
            if subs and b:
                for per in ('cy', 'py'):
                    self._add_fs(stmt, rows[i]['label'], f'{base} = Σ귀속({len(subs)}개)', per, b[per],
                                 sum(r[per] for r in subs), rows[i]['page'])

    def foot_cf(self):
        rows = self.fs_rows['CF']
        stmt = '현금흐름표'
        romans = [(i, r) for i, r in enumerate(rows) if ROMAN.match(r['label'])]
        acts = {}
        for k, (i, r) in enumerate(romans):
            nxt = romans[k + 1][0] if k + 1 < len(romans) else len(rows)
            det = [d for d in rows[i + 1:nxt] if d['cy'] is not None]
            if det:
                acts[r['n']] = r
                for per in ('cy', 'py'):
                    self._add_fs(stmt, r['label'], f"{r['n']} = Σ세부 {len(det)}개", per, r[per],
                                 sum(d[per] for d in det), r['page'])
        inc = next((r for _, r in romans if '증가' in r['n'] and '현금' in r['n']), None)
        beg = next((r for _, r in romans if '기초' in r['n']), None)
        fx = next((r for _, r in romans if '환율' in r['n']), None)
        end = next((r for _, r in romans if '기말' in r['n']), None)
        if inc and len(acts) >= 3:
            for per in ('cy', 'py'):
                self._add_fs(stmt, inc['label'], '현금증감 = 영업 + 투자 + 재무', per, inc[per],
                             sum(a[per] for a in list(acts.values())[:3]), inc['page'])
        if inc and beg and end:
            for per in ('cy', 'py'):
                self._add_fs(stmt, end['label'], '기말현금 = 증감 + 기초 + 환율변동', per, end[per],
                             inc[per] + beg[per] + (fx[per] if fx else 0), end['page'])

    def parse_sce(self, lines):
        # 열 위치: 기초/기말 행의 숫자 x1 군집
        xs = []
        for pg, l in lines:
            if re.search(r'\d{4}\.\d{2}\.\d{2}', l['text']):
                xs += [tk['x1'] for tk in l['toks'] if is_num_tok(tk['t'])]
        cols = []
        for x in sorted(xs):
            if cols and abs(cols[-1][-1] - x) < 12:
                cols[-1].append(x)
            else:
                cols.append([x])
        cols = [sum(c) / len(c) for c in cols]
        # 헤더 단어 → 열 이름
        hdr_tokens = []
        for pg, l in lines:
            if not any(is_num_tok(tk['t']) for tk in l['toks'] if tk['t'] not in ('-',)) and l['top'] < 200:
                hdr_tokens += l['toks']
        merged = []
        i = 0
        while i < len(hdr_tokens):
            tk = hdr_tokens[i]
            if tk['t'] in ('합', '총', '소') and i + 1 < len(hdr_tokens) and hdr_tokens[i + 1]['t'] == '계':
                merged.append({'t': tk['t'] + '계', 'x0': tk['x0'], 'x1': hdr_tokens[i + 1]['x1']}); i += 2; continue
            merged.append(tk); i += 1
        names = [''] * len(cols)
        for tk in merged:
            if tk['t'] in ('과', '목', '주석', '과목'):
                continue
            c = (tk['x0'] + tk['x1']) / 2
            j = min(range(len(cols)), key=lambda k: abs(cols[k] - 30 - c)) if cols else None
            if j is not None and abs(cols[j] - 30 - c) < 70:
                names[j] += tk['t']
        rows = []
        for pg, l in lines:
            vals = [None] * len(cols)
            label_toks = []
            for tk in l['toks']:
                v = parse_num(tk['t'])
                if v is not None and cols:
                    j = min(range(len(cols)), key=lambda k: abs(cols[k] - tk['x1']))
                    if abs(cols[j] - tk['x1']) < 15:
                        vals[j] = v; continue
                label_toks.append(tk['t'])
            label = ' '.join(t for t in label_toks if not re.fullmatch(r'\d+', t))
            if all(v is None for v in vals):
                continue
            rows.append(dict(page=pg, label=label, n=norm(label), vals=vals))
        names = [re.sub(r'^(지배기업의?소유주에게)?(귀속되는자본)?', '', n) or n for n in names]
        self.sce = dict(cols=cols, names=names, rows=rows)

    def foot_sce(self):
        stmt = '자본변동표'
        names, rows = self.sce['names'], self.sce['rows']
        tot_idx = [i for i, nm in enumerate(names) if '합계' in nm or '총계' in nm]
        # 가로
        for r in rows:
            prev = None
            for t in tot_idx:
                comp = list(range((prev if prev is not None else -1) + 1, t))
                if prev is not None:
                    comp = [prev] + comp
                calc = sum((r['vals'][k] or 0) for k in comp)
                self._add_fs(stmt, r['label'], f"{names[t]} = Σ" + '+'.join(names[k] for k in comp), '가로', r['vals'][t] or 0,
                             calc, r['page'])
                prev = t
        # 세로 (기초 → 기말)
        start = None
        for i, r in enumerate(rows):
            if '초)' in r['label'] or r['n'].endswith('기초'):
                start = i
            elif ('말)' in r['label']) and start is not None:
                for j, nm in enumerate(names):
                    calc = sum((rr['vals'][j] or 0) for rr in rows[start:i])
                    self._add_fs(stmt, f"{r['label']} - {nm}", f'기말 = 기초 + Σ변동({i - start - 1}개)', '세로',
                                 r['vals'][j] or 0, calc, r['page'])
                start = None
        self.sce_names = names

    # ------------------------------------------------------------ cross statements
    def _add_x(self, item, a_desc, a, b_desc, b):
        diff = (a or 0) - (b or 0)
        self.cross_checks.append(dict(검증항목=item, 기준=a_desc, 기준금액=a, 대사=b_desc, 대사금액=b, 차이=diff,
                                      결과=status(diff, 0, True)))

    def cross_statements(self):
        bs, is_, cf = self.fs_rows['BS'], self.fs_rows['IS'], self.fs_rows['CF']
        f = lambda rows, key: next((r for r in rows if key in r['n']), None)
        cash = f(bs, '현금및현금성자산')
        cf_end = next((r for r in cf if '기말' in r['n'] and '현금' in r['n']), None)
        cf_beg = next((r for r in cf if '기초' in r['n'] and '현금' in r['n']), None)
        if cash and cf_end:
            self._add_x('기말 현금 (당기)', '재무상태표 현금및현금성자산', cash['cy'], '현금흐름표 기말현금', cf_end['cy'])
            self._add_x('기말 현금 (전기)', '재무상태표 현금및현금성자산(전기)', cash['py'], '현금흐름표 기말현금(전기)', cf_end['py'])
        if cash and cf_beg:
            self._add_x('기초 현금 (당기)', '재무상태표 전기말 현금', cash['py'], '현금흐름표 기초현금', cf_beg['cy'])
        rows, names = self.sce['rows'], self.sce_names
        ends = [r for r in rows if '말)' in r['label']]
        begs = [r for r in rows if '초)' in r['label']]
        ni = next((r for r in is_ if '당기순이익' in r['n'] and ROMAN.match(r['label'])), None)
        ni_sce = [r for r in rows if '당기순' in r['n']]
        tot_col = max((i for i, nm in enumerate(names) if '합계' in nm or '총계' in nm), default=len(names) - 1)
        if ni and len(ni_sce) >= 2:
            self._add_x('당기순이익 (전기)', '포괄손익계산서', ni['py'], '자본변동표', ni_sce[0]['vals'][tot_col])
            self._add_x('당기순이익 (당기)', '포괄손익계산서', ni['cy'], '자본변동표', ni_sce[1]['vals'][tot_col])
        if len(ends) >= 2 and len(begs) >= 2:
            for j, nm in enumerate(names):
                self._add_x(f'전기말=당기초 [{nm}]', '자본변동표 전기말', ends[0]['vals'][j], '자본변동표 당기초', begs[1]['vals'][j])
        # [연속성] 현금흐름표 당기 기초현금 = 현금흐름표 전기 기말현금
        if cf_beg and cf_end:
            self._add_x('[연속성] 현금흐름표 기초현금(당기) = 기말현금(전기)', '현금흐름표 당기 기초현금', cf_beg['cy'],
                        '현금흐름표 전기 기말현금', cf_end['py'])
        # [연속성] 자본변동표 당기초 = 재무상태표 전기말 자본항목
        keymap0 = [('자본금', '자본금'), ('주식발행초과금', '주식발행초과금'), ('기타자본', '기타자본'),
                   ('결손금', '이익잉여금'), ('이익잉여금', '이익잉여금'), ('비지배', '비지배지분')]
        tot_bs0 = next((r for r in bs if r['n'] == '자본총계'), None)
        if len(begs) >= 2:
            for j, nm in enumerate(names):
                tgt = None
                for k, b in keymap0:
                    if k in nm:
                        tgt = next((r for r in bs if r['n'].startswith(b)), None); break
                if ('합계' in nm or '총계' in nm) and j == tot_col:
                    tgt = tot_bs0
                if tgt is not None:
                    self._add_x(f'[연속성] 자본변동표 당기초 = 재무상태표 전기말 [{nm}]', f'자본변동표 당기초 {nm}', begs[1]['vals'][j],
                                f"재무상태표 전기말 {tgt['label']}", tgt['py'])
        # [연속성] 재무상태표 이익잉여금(결손금): 전기말 + 당기순이익 + 기타 변동(자본변동표) = 당기말
        re_bs = next((r for r in bs if r['n'].startswith('이익잉여금') or r['n'].startswith('결손금')), None)
        re_col = next((j for j, nm in enumerate(names) if '결손금' in nm or '이익잉여금' in nm), None)
        if re_bs and ni and re_col is not None and len(begs) >= 2 and len(ends) >= 2:
            i0 = rows.index(begs[1]); i1 = rows.index(ends[1])
            others = sum((r['vals'][re_col] or 0) for r in rows[i0 + 1:i1] if '당기순' not in r['n'])
            self._add_x('[연속성] 이익잉여금: 전기말 + 당기순이익 + 기타변동 = 당기말', '재무상태표 이익잉여금(당기말)', re_bs['cy'],
                        f'전기말 {re_bs["py"]:,.0f} + 순이익 {ni["cy"]:,.0f} + 기타 {others:,.0f}', re_bs['py'] + ni['cy'] + others)
        # 자본변동표 기말 ↔ 재무상태표 자본항목
        keymap = [('자본금', '자본금'), ('주식발행초과금', '주식발행초과금'), ('기타자본', '기타자본'),
                  ('결손금', '이익잉여금'), ('이익잉여금', '이익잉여금'), ('비지배', '비지배지분')]
        bs_eq = [r for r in bs]
        tot_bs = next((r for r in bs if r['n'] == '자본총계'), None)
        for j, nm in enumerate(names):
            target = None
            for k, b in keymap:
                if k in nm:
                    target = next((r for r in bs_eq if r['n'].startswith(b)), None); break
            if ('합계' in nm or '총계' in nm) and j == tot_col:
                target = tot_bs
            if target is None or len(ends) < 2:
                continue
            self._add_x(f'자본변동표 기말 ↔ 재무상태표 [{nm}] 당기', f'자본변동표 {nm}', ends[1]['vals'][j], f"재무상태표 {target['label']}", target['cy'])
            self._add_x(f'자본변동표 기말 ↔ 재무상태표 [{nm}] 전기', f'자본변동표 {nm}', ends[0]['vals'][j], f"재무상태표 {target['label']}", target['py'])

    # ------------------------------------------------------------ notes
    def parse_notes(self):
        s = self.sections
        note_no, note_title = 0, ''
        sub, subsub = '', ''
        tables = []
        cur = None

        def close():
            nonlocal cur
            if cur and any(r['nums'] for r in cur['rows']):
                tables.append(cur)
            cur = None

        self.note_text = {}
        for pg, l in self.lines(s['notes_start'], s['notes_end']):
            text = l['text'].strip()
            self.note_text.setdefault(note_no, []).append((pg, text))
            m = NOTE_HEAD.match(text)
            if m and note_no <= int(m.group(1)) <= note_no + 3 and not text.endswith('다.') and len(text) < 60:
                close(); note_no, note_title = int(m.group(1)), m.group(2).strip(); sub = subsub = ''; continue
            m = SUB_HEAD.match(text)
            if m and not text.startswith('(*'):
                close(); sub = text[:60]; subsub = ''; continue
            m = SUBSUB_HEAD.match(text)
            if m and len(text) < 40:
                close(); subsub = text; continue
            if '(단위' in text:
                close()
                unit = re.search(r'단위\s*[:：]?\s*([가-힣%]+)', text)
                cur = dict(note=note_no, note_title=note_title, sub=sub, subsub=subsub,
                           title=(sub + (' / ' + subsub if subsub else '')).strip(),
                           unit=unit.group(1) if unit else '', page=pg, rows=[], header=[])
                rest = [tk for tk in l['toks'] if '단위' not in tk['t'] and not tk['t'].endswith(')') and tk['t'] not in ('천원', '원', '백만원', '주')]
                if len(rest) >= 2:
                    cur['header'].append(rest)
                continue
            if cur is None:
                continue
            if text.startswith('(*') or text.startswith('*') or re.search(r'(니다|습니다)\.?\s*$', text) or text.startswith('(주석'):
                close(); continue
            # row
            toks = l['toks']
            nums, label, pct, pcts = [], [], False, []
            for k, tk in enumerate(toks):
                v = parse_num(tk['t'])
                if is_pct_tok(tk['t']):
                    pct = True
                    pv = parse_num(tk['t'][:-1])
                    if pv is not None:
                        pcts.append((pv / 100.0, tk['x1']))
                    continue
                if v is not None and not (k == 0 and tk['x0'] < 110 and tk['t'] not in ('-',)) and not (not nums and tk['x0'] < 110):
                    nums.append((v, tk['x1'], tk['t']))
                elif not nums:
                    label.append(tk['t'])
            row = dict(page=pg, label=' '.join(label), n=norm(' '.join(label)), nums=nums, pct=pct, pcts=pcts, toks=toks)
            if not nums and not any(x['nums'] for x in cur['rows']):
                cur['header'].append(toks)
            cur['rows'].append(row)
        close()
        for i, t in enumerate(tables):
            t['id'] = i + 1
            xs = sorted(x for r in t['rows'] for _, x, _ in r['nums'])
            cols = []
            for x in xs:
                if cols and x - cols[-1][-1] < 10:
                    cols[-1].append(x)
                else:
                    cols.append([x])
            t['cols'] = [max(c) for c in cols]
            t['colnames'] = self._colnames(t)
        self.note_tables = tables

    def _colnames(self, t):
        names = [''] * len(t['cols'])
        for hl in t['header']:
            for tk in self._merge_tot(hl):
                if parse_num(tk['t']) is not None:
                    continue
                cand = [j for j, cx in enumerate(t['cols']) if cx >= tk['x1'] - 12]
                if cand and tk['x0'] > 90:
                    j = cand[0]
                    names[j] = (names[j] + ' ' + tk['t']).strip()
        return names

    @staticmethod
    def _merge_tot(toks):
        toks = [dict(tk, t=MARK.sub('', tk['t'])) for tk in toks]
        out, i = [], 0
        while i < len(toks):
            tk = toks[i]
            if tk['t'] in ('합', '총', '소') and i + 1 < len(toks) and toks[i + 1]['t'] == '계':
                out.append({'t': tk['t'] + '계', 'x0': tk['x0'], 'x1': toks[i + 1]['x1']}); i += 2; continue
            out.append(tk); i += 1
        return out

    @staticmethod
    def _col_of(t, x):
        j = min(range(len(t['cols'])), key=lambda k: abs(t['cols'][k] - x))
        return j if abs(t['cols'][j] - x) <= 10 else None

    def _rowvec(self, t, r):
        v = {}
        for val, x, _ in r['nums']:
            j = self._col_of(t, x)
            if j is not None:
                v[j] = val
        return v

    TOTAL_EXACT = {'합계', '소계', '계', '총계', '합계금액', '순장부금액', '장부금액', '기말장부금액', '기말', '기말금액',
                   '기말잔액', '순액', '차감계', '기말순장부금액', '장부가액', '기말장부가액'}

    def is_total(self, n):
        return n in self.TOTAL_EXACT or n.endswith('합계') or n.endswith('소계') or n.endswith('총계')

    def _add_note(self, t, kind, row_label, col, reported, calc, ncomp, formula, override=None):
        diff = reported - calc
        unit_exact = t['unit'] in ('원',)
        res = override or status(diff, ncomp, unit_exact)
        self.note_checks.append(dict(주석=t['note'], 주석명=t['note_title'], 표=t['title'], 표ID=t['id'], 페이지=t['page'],
                                     단위=t['unit'], 유형=kind, 행=row_label, 열=col, 검증식=formula, 보고금액=reported,
                                     계산금액=calc, 차이=diff, 결과=res))

    def foot_notes(self):
        for t in self.note_tables:
            if not t['cols']:
                continue
            self._foot_vertical(t)
            self._foot_horizontal(t)
            self._dup_label(t)
            self._continuity_columns(t)
            self._formula_table(t)
        self._continuity_split_tables()
        self._tax_reconciliation()
        self._eps_check()

    # ---------------------------------------------------- 전기말 → 당기초 연속성
    def _col_idx(self, t, *names):
        for j, nm in enumerate(t['colnames']):
            if nm.replace(' ', '') in names:
                return j
        return None

    def _continuity_columns(self, t):
        """당기/전기 열이 나란한 세로 롤포워드 표: 당기열 '기초' = 전기열 '기말'."""
        jc, jp = self._col_idx(t, '당기'), self._col_idx(t, '전기')
        if jc is None or jp is None:
            return
        beg = next((r for r in t['rows'] if r['nums'] and r['n'].startswith('기초')), None)
        if beg is None:
            return
        idx = t['rows'].index(beg)
        end = next((r for r in t['rows'][idx + 1:] if r['nums'] and r['n'].startswith('기말')), None)
        if end is None:
            return
        b, e = self._rowvec(t, beg), self._rowvec(t, end)
        if jc in b and jp in e:
            self._add_note(t, '전기말→당기초', f"{beg['label']} vs {end['label']}", '당기 기초 / 전기 기말', b[jc], e[jp], 0,
                           '당기 기초 = 전기 기말 (같은 표의 당기열·전기열)', override=None if abs(b[jc] - e[jp]) > 0 else '일치')

    @staticmethod
    def period_tag(t):
        """'1) 당기' / '(2) 전기' / '1) 당기말' 처럼 표 제목이 기간만 나타내면 '당기'/'전기' 반환."""
        for txt in (t.get('subsub', ''), t.get('sub', '')):
            k = re.sub(r'^\(?\d+\)\s*', '', txt or '').replace(' ', '')
            if k in ('당기', '당기말'):
                return '당기'
            if k in ('전기', '전기말'):
                return '전기'
        return None

    def _continuity_split_tables(self):
        """'1) 당기' / '2) 전기'로 나뉜 변동표: 당기표 기초 = 전기표 기말 (세로형은 열별, 가로형은 행 라벨별)."""
        tabs = self.note_tables
        for i, cur in enumerate(tabs):
            if self.period_tag(cur) != '당기':
                continue
            pri = next((t for t in tabs[i + 1:i + 4] if t['note'] == cur['note'] and self.period_tag(t) == '전기'
                        and (t.get('sub') == cur.get('sub') or not cur.get('subsub'))), None)
            if pri is None or not cur['cols'] or not pri['cols']:
                continue
            beg = next((r for r in cur['rows'] if r['nums'] and r['n'].startswith('기초')), None)
            if beg is not None:          # 세로형 (예: 유형자산 변동표)
                end = next((r for r in pri['rows'] if r['nums'] and r['n'].startswith('기말')), None)
                if end is None:
                    continue
                b, e = self._rowvec(cur, beg), self._rowvec(pri, end)
                for j, v in b.items():
                    nm = cur['colnames'][j] if j < len(cur['colnames']) else ''
                    jp = pri['colnames'].index(nm) if nm and nm in pri['colnames'] else (j if len(pri['cols']) == len(cur['cols']) else None)
                    if jp is None or jp not in e:
                        continue
                    self._add_note(cur, '전기말→당기초', beg['label'], nm or f'열{j + 1}', v, e[jp], 0,
                                   f"당기표 '{beg['label']}' = 전기표 '{end['label']}' (p.{self.pg(pri['page'])})")
                continue
            jb = self._col_idx(cur, '기초', '기초잔액', '기초금액', '기초장부금액')
            je = self._col_idx(pri, '기말', '기말잔액', '기말금액', '기말장부금액')
            if jb is None or je is None:
                continue
            pmap = {r['n']: self._rowvec(pri, r) for r in pri['rows'] if r['nums']}
            for r in cur['rows']:
                if not r['nums'] or r['n'] not in pmap:
                    continue
                b = self._rowvec(cur, r)
                if jb in b and je in pmap[r['n']]:
                    self._add_note(cur, '전기말→당기초', r['label'], '기초 vs 전기 기말', b[jb], pmap[r['n']][je], 0,
                                   f"당기표 기초 = 전기표 기말 (p.{self.pg(pri['page'])})")

    # ---------------------------------------------------- 산식표 (곱셈/나눗셈)
    def _formula_table(self, t):
        hdr = ' '.join(tk['t'] for hl in t['header'] for tk in hl)
        names = [n.replace(' ', '') for n in t['colnames']]
        # (1) 지분법: 순자산(A) × 지분율(B) = 순자산지분금액, 순자산지분금액 + 내부거래 등 = 장부금액
        if '×' in hdr and '지분율' in hdr.replace(' ', ''):
            for r in t['rows']:
                if not r['nums'] or not r['pcts'] or self.is_total(r['n']):
                    continue
                v = self._rowvec(t, r)
                ks = sorted(v)
                if len(ks) < 2:
                    continue
                a, prod = v[ks[0]], v[ks[1]]
                rate = r['pcts'][0][0]
                calc = round(a * rate)
                tol = max(2, abs(a) * 0.00005)   # 지분율 표시 소수 2자리 반올림 허용
                diff = prod - calc
                res = '일치' if abs(diff) <= 1 else ('일치(반올림범위)' if abs(diff) <= tol else '불일치')
                self._add_note(t, '산식(곱셈)', r['label'], '순자산지분금액', prod, calc, 1,
                               f'순자산지분금액 = 기말순자산 {a:,.0f} × 지분율 {rate * 100:.2f}%', override=res)
                if len(ks) >= 4:
                    adj, book = v[ks[2]], v[ks[3]]
                    self._add_note(t, '가로합계', r['label'], '장부금액', book, prod + adj, 2, '장부금액 = 순자산지분금액 + 내부거래 등')
            tot = next((r for r in t['rows'] if self.is_total(r['n']) and r['nums']), None)
            if tot:
                tv = self._rowvec(t, tot)
                for j in tv:
                    body = [r for r in t['rows'] if r['nums'] and not self.is_total(r['n'])]
                    calc, cnt = self._sum_rows(t, body, j)
                    if cnt:
                        self._add_note(t, '세로합계', tot['label'], t['colnames'][j] or f'열{j + 1}', tv[j], calc, len(body),
                                       f'합계 = Σ회사별({len(body)}행)')
        # (2) 기대손실률 × 총장부금액 = 손실충당금 (손실충당금 내역표)
        rows = t['rows']
        for i, r in enumerate(rows):
            if not (r['pcts'] and '손실률' in r['n']):
                continue
            base = next((x for x in rows[i + 1:i + 3] if x['nums'] and '장부금액' in x['n']), None)
            allw = next((x for x in rows[i + 1:i + 4] if x['nums'] and '충당금' in x['n']), None)
            if not base or not allw:
                continue
            bv, av = self._rowvec(t, base), self._rowvec(t, allw)
            for rate, x in r['pcts']:
                j = self._col_of(t, x)
                if j is None or j not in bv or j not in av:
                    continue
                calc = bv[j] * rate
                tol = max(2, abs(bv[j]) * 0.00005)
                diff = av[j] - calc
                res = '일치' if abs(diff) <= 1 else ('일치(반올림범위)' if abs(diff) <= tol else '불일치')
                period = next((x['label'] for x in reversed(rows[:i]) if not x['nums'] and x['n'] in ('당기말', '전기말', '당기', '전기')), '')
                self._add_note(t, '산식(곱셈)', f"{allw['label']} ({period})" if period else allw['label'],
                               t['colnames'][j] or f'열{j + 1}', av[j], round(calc), 1,
                               f'손실충당금 = 총장부금액 {bv[j]:,.0f} × 기대손실률 {rate * 100:.2f}% (표시율 반올림 허용 ±{tol:,.0f})', override=res)

    def _tax_reconciliation(self):
        """법인세비용과 회계이익의 관계: 법인세비용 = 세율로 계산된 법인세 + Σ법인세효과, 그리고 손익계산서 법인세비용과 대사."""
        is_tax = next((r for r in self.fs_rows.get('IS', []) if ROMAN.sub('', r['label']).replace(' ', '').startswith('법인세비용(')), None)
        for t in self.note_tables:
            names = [r['n'] for r in t['rows'] if r['nums']]
            if not any('세율로계산된' in n for n in names) or not names or not names[-1].startswith('법인세비용'):
                continue
            rows = [r for r in t['rows'] if r['nums']]
            start = next(i for i, r in enumerate(rows) if '세율로계산된' in r['n'])
            last = rows[-1]
            body = rows[start:-1]
            for j, val in self._rowvec(t, last).items():
                calc, cnt = self._sum_rows(t, body, j)
                self._add_note(t, '세로합계', last['label'], t['colnames'][j] or f'열{j + 1}', val, calc, len(body),
                               f'법인세비용 = 세율로 계산된 법인세 + Σ법인세효과({len(body) - 1}행)')
            pre = rows[0] if rows[0]['n'].startswith('법인세비용차감전') else None
            if pre:
                calc_row = rows[start]
                pv, cv = self._rowvec(t, pre), self._rowvec(t, calc_row)
                for j in pv:
                    if j in cv and pv[j]:
                        rate = cv[j] / pv[j]
                        self.special.append(dict(검증항목=f"적용세율 역산 ({t['colnames'][j]})", 기준='세율로 계산된 법인세', 기준금액=cv[j],
                                                 대사='법인세비용차감전순손익', 대사금액=pv[j], 차이=None,
                                                 결과='일치' if 0.09 <= rate <= 0.27 else '확인필요',
                                                 비고=f"역산 세율 {rate * 100:.2f}% (법정세율 구간 9~24%+지방세 확인) 주석{t['note']} p.{self.pg(t['page'])}"))
            if is_tax:
                lv = self._rowvec(t, last)
                for k, (j, per) in enumerate(((0, 'cy'), (1, 'py'))):
                    keys = sorted(lv)
                    if k < len(keys):
                        v = lv[keys[k]]
                        diff = v - round(is_tax[per] / 1000)
                        self.special.append(dict(검증항목=f"법인세비용 주석 ↔ 손익계산서 ({'당기' if per == 'cy' else '전기'})",
                                                 기준='주석 법인세비용(천원)', 기준금액=v, 대사='손익계산서 법인세비용(천원 환산)',
                                                 대사금액=round(is_tax[per] / 1000), 차이=diff, 결과=status(diff, 1),
                                                 비고=f"주석{t['note']} p.{self.pg(t['page'])}"))
            break

    def _eps_check(self):
        """주당손익 = 귀속 당기순손익 ÷ 가중평균유통보통주식수 (원 미만 절사/반올림 허용), 손익계산서 EPS와 대사."""
        is_eps = next((r for r in self.fs_rows.get('IS', []) if r['n'].startswith('기본주당')), None)
        for t in self.note_tables:
            rows = [r for r in t['rows'] if r['nums']]
            eps = next((r for r in reversed(rows) if '주당' in r['n']), None)
            ni = next((r for r in rows if r is not eps and ('순이익' in r['n'] or '순손실' in r['n'] or '순손익' in r['n'])), None)
            sh = next((r for r in rows if '가중평균' in r['n']), None)
            if not (ni and sh and eps) or rows.index(eps) < rows.index(sh):
                continue
            nv, sv, ev = self._rowvec(t, ni), self._rowvec(t, sh), self._rowvec(t, eps)
            for k, j in enumerate(sorted(ev)):
                if j not in nv or j not in sv or not sv[j]:
                    continue
                raw = abs(nv[j]) / sv[j]
                ok = abs(abs(ev[j]) - raw) < 1.0
                self._add_note(t, '산식(나눗셈)', eps['label'], t['colnames'][j] or f'열{j + 1}', abs(ev[j]), round(raw, 2), 1,
                               f'주당손익 = {abs(nv[j]):,.0f} ÷ {sv[j]:,.0f}주 = {raw:,.2f}원', override='일치' if ok else '불일치')
                if is_eps:
                    per = 'cy' if k == 0 else 'py'
                    self.special.append(dict(검증항목=f"주당손익 주석 ↔ 손익계산서 ({'당기' if per == 'cy' else '전기'})",
                                             기준='주석 주당손익', 기준금액=abs(ev[j]), 대사='손익계산서 기본주당손익', 대사금액=abs(is_eps[per]),
                                             차이=abs(ev[j]) - abs(is_eps[per]), 결과=status(abs(ev[j]) - abs(is_eps[per]), 0, True),
                                             비고=f"주석{t['note']} p.{self.pg(t['page'])}"))
            break

    def _dup_label(self, t):
        seen = {}
        for r in t['rows']:
            if not r['nums'] or not r['n'].startswith('기말'):
                continue
            if r['n'] in seen:
                a, b = self._rowvec(t, seen[r['n']]), self._rowvec(t, r)
                for j in set(a) & set(b):
                    self._add_note(t, '동일항목 일관성', r['label'], t['colnames'][j] or f'열{j + 1}', b[j], a[j], 1,
                                   f"'{r['label']}' 행 2회 표시: 변동표 기말 vs 구성내역 기말")
            seen[r['n']] = r

    def _sum_rows(self, t, rows, j):
        s, cnt = 0.0, 0
        for r in rows:
            v = self._rowvec(t, r)
            if j in v:
                s += v[j]; cnt += 1
        return s, cnt

    def _best(self, t, j, val, cands):
        best = None
        for nm, rs in cands:
            if not rs:
                continue
            calc, cnt = self._sum_rows(t, rs, j)
            if cnt == 0:
                continue
            d = abs(val - calc)
            if best is None or d < best[0] - 1e-9:
                best = (d, nm, rs, calc)
        return best

    def _sign_infer(self, vals, target):
        """첫 항목(기초) 제외 부호 반전 조합으로 일치하는지 탐색"""
        import itertools
        n = len(vals)
        if n < 2 or n > 10:
            return None
        nz = [i for i in range(1, n) if vals[i] != 0]
        for k in range(1, len(nz) + 1):
            for combo in itertools.combinations(nz, k):
                s = sum(-v if i in combo else v for i, v in enumerate(vals))
                if abs(s - target) < 1e-6:
                    return combo
        return None

    def _foot_vertical(self, t):
        seg = []           # [{'r':row,'sub':bool,'cov':bool}]
        last_break = 0     # seg index after last subtotal
        last_hdr = 0       # seg index at last section header
        rf = None
        for idx, r in enumerate(t['rows']):
            if not r['nums']:
                if idx > 0 and r['label']:
                    last_hdr = len(seg)
                continue
            n = r['n']
            if n.startswith('기초'):
                rf = [r]; seg, last_break, last_hdr = [], 0, 0; continue
            if rf is not None and not self.is_total(n):
                rf.append(r); continue
            if self.is_total(n):
                vec = self._rowvec(t, r)
                if n.startswith('기말') and rf is not None:
                    for j, val in vec.items():
                        calc, cnt = self._sum_rows(t, rf, j)
                        vals = [self._rowvec(t, x).get(j, 0) for x in rf]
                        kind = '롤포워드(세로)'
                        formula = f'기말 = 기초 + Σ변동({len(rf) - 1}행)'
                        if abs(val - calc) > max(2, len(rf)):
                            combo = self._sign_infer(vals, val)
                            if combo:
                                self._add_note(t, kind, r['label'], t['colnames'][j] or f'열{j + 1}', val, calc, len(rf),
                                               formula + ' / 부호반전 시 일치: ' + ','.join(rf[i]['label'] for i in combo),
                                               override='부호표시 확인')
                                continue
                        self._add_note(t, kind, r['label'], t['colnames'][j] or f'열{j + 1}', val, calc, len(rf), formula)
                    rf = None; seg, last_break, last_hdr = [], 0, 0
                    continue
                is_sub = n.endswith('소계') or n == '계'
                if is_sub:
                    cands = [('Σ직전 항목', [e['r'] for e in seg[last_break:] if not e['cov']]),
                             ('Σ구분내 항목', [e['r'] for e in seg[last_hdr:] if not e['cov'] and not e['sub']])]
                else:
                    cands = [('Σ(소계+미포함 항목)', [e['r'] for e in seg if not e['cov']]),
                             ('Σ직전 소계 이후 항목', [e['r'] for e in seg[last_break:]]),
                             ('Σ전체 세부항목', [e['r'] for e in seg if not e['sub']]),
                             ('Σ직전 구분 항목', [e['r'] for e in seg[last_hdr:]])]
                used = None
                for j, val in vec.items():
                    best = self._best(t, j, val, cands)
                    if best is None:
                        continue
                    _, nm, rs, calc = best
                    used = rs if used is None else used
                    self._add_note(t, '세로합계', r['label'], t['colnames'][j] or f'열{j + 1}', val, calc, len(rs),
                                   f'{r["n"]} = {nm}({len(rs)}행)')
                if is_sub:
                    ids = set(id(x) for x in (used or []))
                    for e in seg:
                        if id(e['r']) in ids:
                            e['cov'] = True
                    seg.append({'r': r, 'sub': True, 'cov': False}); last_break = len(seg)
                else:
                    seg, last_break, last_hdr = [], 0, 0
            else:
                seg.append({'r': r, 'sub': False, 'cov': False})
        # 기초로 시작했지만 '기말' 라벨 없이 끝나는 표(예: 기초 발행주식수 → 가중평균유통보통주식수)는 마지막 행을 기말로 본다
        if rf is not None and len(rf) >= 3:
            last = rf[-1]
            body = rf[:-1]
            for j, val in self._rowvec(t, last).items():
                calc, cnt = self._sum_rows(t, body, j)
                self._add_note(t, '롤포워드(세로)', last['label'], t['colnames'][j] or f'열{j + 1}', val, calc, len(body),
                               f"{last['n']}(마지막 행) = 기초 + Σ변동({len(body) - 1}행)")

    TOT_HDR = {'합계', '총계', '장부금액', '기말', '순장부금액', '기말장부금액', '계', '소계', '기말잔액', '장부가액'}

    def _foot_horizontal(self, t):
        if not t['header']:
            return
        tot_cols = set()
        start_cols = set()
        hdr_words = [tk['t'] for hl in t['header'] for tk in self._merge_tot(hl)]
        strong = {'합계', '총계', '소계'} & set(hdr_words)
        keys = strong if strong else self.TOT_HDR
        for hl in t['header']:
            for tk in self._merge_tot(hl):
                if tk['t'] in keys or tk['t'] == '기초':
                    cand = [j for j, cx in enumerate(t['cols']) if cx >= tk['x1'] - 12]
                    if cand:
                        (start_cols if tk['t'] == '기초' else tot_cols).add(cand[0])
        if any('×' in w or w in ('(A)×(B)',) for w in hdr_words):
            self.skipped.append(dict(주석=t['note'], 표=t['title'], 페이지=t['page'], 사유='산식표 - 단순 가로합계 대신 산식(곱셈) 검증 적용'))
            return
        if not tot_cols:
            return
        tot_cols = sorted(tot_cols)
        for r in t['rows']:
            if not r['nums']:
                continue
            vec = self._rowvec(t, r)
            prev = -1
            for tc in tot_cols:
                comps = list(range(prev + 1, tc))
                sc = [s for s in start_cols if prev < s < tc]
                if sc:
                    comps = list(range(min(sc), tc))
                prev = tc
                if len(comps) < 2 or tc not in vec or not all(c in vec for c in comps):
                    continue
                calc = sum(vec.get(c, 0) for c in comps)
                val = vec[tc]
                formula = f"{t['colnames'][tc] or '합계열'} = Σ" + '+'.join(t['colnames'][c] or f'열{c + 1}' for c in comps)
                kind = '롤포워드(가로)' if sc else '가로합계'
                ov = None
                if abs(val - calc) > max(2, len(comps)):
                    combo = self._sign_infer([vec[c] for c in comps], val)
                    if combo:
                        ov = '부호표시 확인'
                        formula += ' / 부호반전 시 일치: ' + ','.join(t['colnames'][comps[i]] or f'열{comps[i] + 1}' for i in combo)
                self._add_note(t, kind, r['label'], t['colnames'][tc] or f'열{tc + 1}', val, calc, len(comps), formula, override=ov)

    # ------------------------------------------------------------ FS <-> notes
    def fs_vs_notes(self):
        stmap = {'BS': '재무상태표', 'IS': '포괄손익계산서', 'CF': '현금흐름표'}
        by_note = {}
        for t in self.note_tables:
            by_note.setdefault(t['note'], []).append(t)
        for st, rows in self.fs_rows.items():
            if st == 'SCE':
                continue
            for r in rows:
                if not r['notes'] or r['cy'] is None:
                    continue
                refs = [int(x) for x in r['notes'].split(',') if x.strip().isdigit()]
                for per, plabel in (('cy', '당기'), ('py', '전기')):
                    val = r[per]
                    if not val:
                        continue
                    hit = self._find_in_notes(by_note, refs, val)
                    if hit:
                        t, row, tv, d = hit
                        res = '일치' if d == 0 else '단수차이'
                        loc = f"주석{t['note']} {t['title'][:40]} / '{row['label']}' (p.{self.pg(row['page'])})"
                    else:
                        txt = self._find_in_note_text(refs, val)
                        if txt:
                            n, pg, line, tv = txt
                            res, loc = '일치(본문서술)', f"주석{n} 본문 p.{self.pg(pg)}: {line[:60]}"
                        else:
                            res, loc, tv = '미발견', '', None
                    self.fs_note_checks.append(dict(재무제표=stmap[st], 계정과목=r['label'], 주석번호=r['notes'], 기간=plabel,
                                                    재무제표금액_원=val, 주석금액=tv, 주석위치=loc, 결과=res))

    def note_rollforward_vs_bs(self):
        """주석 변동표 기말이 재무상태표 당기말과 맞으면, 같은 열/행의 기초가 재무상태표 전기말과 맞는지 확인."""
        bs = [r for r in self.fs_rows.get('BS', []) if r['notes'] and r['cy'] is not None and r['py'] is not None]
        seen = set()
        for t in self.note_tables:
            scale = {'천원': 1000, '백만원': 1e6, '원': 1}.get(t['unit'])
            if not scale or not t['cols']:
                continue
            cands = [r for r in bs if t['note'] in [int(x) for x in r['notes'].split(',') if x.strip().isdigit()]]
            if not cands or self.period_tag(t) == '전기':
                continue   # 전기 변동표는 기말이 당기말과 우연히 같을 수 있어 제외
            pairs = []   # (기초값, 기말값, 위치설명)
            rows = [r for r in t['rows'] if r['nums']]
            beg = next((r for r in rows if r['n'].startswith('기초')), None)
            end = next((r for r in rows[rows.index(beg) + 1:] if r['n'].startswith('기말')), None) if beg else None
            if beg and end:
                b, e = self._rowvec(t, beg), self._rowvec(t, end)
                for j in set(b) & set(e):
                    if '전기' in (t['colnames'][j] or ''):
                        continue
                    pairs.append((b[j], e[j], f"{t['colnames'][j] or f'열{j + 1}'} 열 기초/기말"))
            jb = self._col_idx(t, '기초', '기초잔액', '기초금액', '기초장부금액')
            je = self._col_idx(t, '기말', '기말잔액', '기말금액', '기말장부금액')
            if jb is not None and je is not None:
                for r in rows:
                    v = self._rowvec(t, r)
                    if jb in v and je in v:
                        pairs.append((v[jb], v[je], f"'{r['label']}' 행 기초/기말"))
            for bv, ev, where in pairs:
                for f in cands:
                    if abs(ev - f['cy'] / scale) <= 1 and ev != 0:
                        key = (f['label'], t['id'], where)
                        if key in seen:
                            continue
                        seen.add(key)
                        diff = bv - round(f['py'] / scale)
                        self.cross_checks.append(dict(
                            검증항목=f"[연속성] 주석{t['note']} 변동표 기초 = 재무상태표 전기말 [{f['label']}]",
                            기준=f"주석{t['note']} p.{self.pg(t['page'])} {where} (기말 {ev:,.0f}=당기말 확인)", 기준금액=bv,
                            대사=f"재무상태표 전기말 {f['label']} ({t['unit']} 환산)", 대사금액=round(f['py'] / scale),
                            차이=diff, 결과=status(diff, 1)))

    def _find_in_note_text(self, refs, val):
        """표에서 못 찾은 금액을 참조 주석의 서술문에서 탐색 (예: '자본금은 122,578,871천원입니다').
        기존 프로그램(pdf_note_check)의 '주석 안에 금액이 등장하는가' 방식을 보조 수단으로 결합."""
        rx = re.compile(r'([\d]{1,3}(?:,\d{3})+)\s*(천원|백만원|원)')
        for n in refs:
            for pg, line in getattr(self, 'note_text', {}).get(n, []):
                for m in rx.finditer(line):
                    num = float(m.group(1).replace(',', ''))
                    unit = {'천원': 1e3, '백만원': 1e6, '원': 1}[m.group(2)]
                    if abs(num - abs(val) / unit) < (0.5 + 1e-9 if unit > 1 else 1e-9) or num * unit == abs(val):
                        return n, pg, line, num
        return None

    def _find_in_notes(self, by_note, refs, val):
        prim = [n for n in refs if n not in (4, 5)] + [n for n in refs if n in (4, 5)]
        best = None
        for n in prim:
            for t in by_note.get(n, []):
                scale = {'천원': 1000, '백만원': 1e6, '원': 1}.get(t['unit'], 1000)
                target = val / scale
                for r in t['rows']:
                    for v, x, _ in r['nums']:
                        if v == 0:
                            continue
                        for cand in (v, -v):
                            d = abs(cand - target)
                            if d <= 1.0 or (scale == 1 and d < 1):
                                dd = 0 if abs(cand - round(target)) < 1e-6 or d < 0.5 + 1e-9 else round(d)
                                if best is None or dd < best[3]:
                                    best = (t, r, v, dd)
                if best and best[3] == 0:
                    return best
        return best

    # ------------------------------------------------------------ narrative
    def narrative(self):
        s = self.sections
        cands = []
        for st, rows in self.fs_rows.items():
            for r in rows:
                for per in ('cy', 'py'):
                    if r.get(per):
                        cands.append((f"{st}:{r['label']}({'당기' if per == 'cy' else '전기'})", abs(r[per])))
        bs = self.fs_rows['BS']
        ca = next((r for r in bs if '유동자산' in r['n'] and '비' not in r['n']), None)
        cl = next((r for r in bs if '유동부채' in r['n'] and '비' not in r['n']), None)
        if ca and cl:
            cands.append(('파생: 유동부채-유동자산(당기)', cl['cy'] - ca['cy']))
        rng = list(range(2, s['fs_start'])) + list(range(s['notes_start'], s['notes_start'] + 3))
        rx = re.compile(r'([\d]{1,3}(?:,\d{3})+|\d+)\s*(백만원|천원|억원)')
        for p in rng:
            for l in self.pages[p - 1]['lines']:
                for m in rx.finditer(l['text']):
                    num = float(m.group(1).replace(',', ''))
                    unit = {'백만원': 1e6, '천원': 1e3, '억원': 1e8}[m.group(2)]
                    if num * unit < 1e8:
                        continue
                    hits = [c for c in cands if abs(c[1] / unit - num) <= 1]
                    exact = [c for c in hits if abs(round(c[1] / unit) - num) < 1e-9]
                    self.text_checks.append(dict(페이지=p, 문장=l['text'][:120], 서술금액=m.group(0),
                                                 대응항목=', '.join(c[0] for c in (exact or hits)[:3]),
                                                 결과='일치' if exact else ('단수차이' if hits else '대응항목 미발견')))

    # ------------------------------------------------------------ special / inter-note
    def special_checks(self):
        def add(item, a_desc, a, b_desc, b, note=''):
            diff = (a or 0) - (b or 0)
            self.special.append(dict(검증항목=item, 기준=a_desc, 기준금액=a, 대사=b_desc, 대사금액=b, 차이=diff,
                                     결과=status(diff, 0, True) if a is not None and b is not None else '검증불가', 비고=note))
        is_ = self.fs_rows['IS']; bs = self.fs_rows['BS']
        f = lambda rows, key: next((r for r in rows if ROMAN.sub('', r['label']).replace(' ', '').startswith(key)), None)
        cogs, sga = f(is_, '매출원가'), f(is_, '판매비와관리비')
        nat = next((t for t in self.note_tables if '성격별' in t['note_title']), None)
        if cogs and sga and nat:
            tot = next((r for r in nat['rows'] if self.is_total(r['n']) and r['nums']), None)
            if tot:
                for k, per in enumerate(('cy', 'py')):
                    if k < len(tot['nums']):
                        add(f"비용의 성격별 분류 합계 ({'당기' if per == 'cy' else '전기'})", '주석 성격별비용 합계(천원)', tot['nums'][k][0],
                            '매출원가+판관비(천원 환산)', round((cogs[per] + sga[per]) / 1000), f"주석{nat['note']} p.{self.pg(nat['page'])}")
        # 성격별비용 합계가 일치하면 매출원가/판관비의 FS-주석 대사를 '합산 일치'로 갱신
        if cogs and sga and nat and all(c['결과'] == '일치' for c in self.special if '성격별' in c['검증항목']):
            for c in self.fs_note_checks:
                if c['결과'] == '미발견' and str(nat['note']) in c['주석번호'].split(',') and \
                        any(k in c['계정과목'] for k in ('매출원가', '판매비와관리비')):
                    c['결과'] = '일치(합산)'
                    c['주석위치'] = f"주석{nat['note']} 성격별비용 합계 = 매출원가+판관비 (특수검증 참조)"
        # 자본금 = 발행주식수 × 액면가
        par = None
        for p in self.pages[self.sections['notes_start'] - 1:self.sections['notes_end']]:
            for l in p['lines']:
                m = re.search(r'(?:1주당\s*)?액면(?:금액|가액|가)?\s*(?:은|:)?\s*([\d,]+)\s*원', l['text'])
                if m and par is None:
                    par = float(m.group(1).replace(',', ''))
        sh = next((t for t in self.note_tables if t['unit'] == '주' and any(r['n'].startswith('기말') for r in t['rows'])), None)
        cap = f(bs, '자본금')
        if sh and cap:
            end = next(r for r in sh['rows'] if r['n'].startswith('기말'))
            if not par and end['nums'] and end['nums'][0][0]:
                implied = cap['cy'] / end['nums'][0][0]
                self.special.append(dict(검증항목='자본금 ÷ 기말 발행주식수 (액면가 역산)', 기준='재무상태표 자본금(당기)', 기준금액=cap['cy'],
                                         대사=f"주식수 {end['nums'][0][0]:,.0f}주", 대사금액=end['nums'][0][0], 차이=None,
                                         결과='일치' if abs(implied - round(implied)) < 1e-9 else '확인필요',
                                         비고=f'주당 {implied:,.2f}원 (주석에 액면가 기재 없음 → 정수 여부만 확인)'))
            for k, per in enumerate(('cy', 'py')):
                if k < len(end['nums']) and par:
                    add(f"자본금 = 발행주식수 × 액면가 ({'당기' if per == 'cy' else '전기'})", '재무상태표 자본금', cap[per],
                        f'주식수 {end["nums"][k][0]:,.0f}주 × 액면 {par:,.0f}원', end['nums'][k][0] * par, f"주석{sh['note']} p.{self.pg(sh['page'])}")
            # 주주현황 주식수 합계
            holders = None
            for p in self.pages[self.sections['notes_start'] - 1:self.sections['notes_start'] + 2]:
                for l in p['lines']:
                    if re.match(r'^합\s*계', l['text'].strip()):
                        nums = [parse_num(tk['t']) for tk in l['toks'] if parse_num(tk['t']) is not None]
                        if nums and holders is None:
                            holders = nums[0]
            if holders:
                add('주석1 주주현황 주식수 합계 = 주석 자본금 기말 주식수', '주석1 주주현황 합계', holders, '자본금 주석 기말주식수',
                    end['nums'][0][0])
        # 자본변동표 기간 표기 점검
        rows = self.sce['rows']
        dated = [r for r in rows if re.search(r'\d{4}\.\d{2}\.\d{2}', r['label'])]
        if dated:
            years = sorted(set(re.search(r'(\d{4})\.', r['label']).group(1) for r in dated))
            cur_y = years[-1]
            for r in dated:
                y = re.search(r'(\d{4})\.', r['label']).group(1)
                lab = r['label']
                ok = ('당기' in lab) == (y == cur_y) or ('전기' in lab) == (y != cur_y) and ('당기' not in lab or y == cur_y)
                expected = '당기' if y == cur_y else '전기'
                good = expected in lab
                self.special.append(dict(검증항목='자본변동표 기간 표기', 기준=lab, 기준금액=None, 대사=f'{y}년 → {expected}초/{expected}말 표기 기대',
                                         대사금액=None, 차이=None, 결과='일치' if good else '표기 확인', 비고=f"p.{self.pg(r['page'])}"))

    def run(self):
        self.errors = []
        self.special = []
        self.sce = {'cols': [], 'names': [], 'rows': []}
        self.sce_names = []
        self.page_map = {}
        for p in self.pages:
            for l in p['lines'][::-1]:
                mm = re.search(r'Page\s+(\d+)\s*$', l['text'])
                if mm:
                    self.page_map[p['page']] = int(mm.group(1)); break
        self.locate_sections()
        if not self.sections.get('fs_start') or not self.sections.get('notes_start'):
            self.errors.append('재무제표/주석 시작 페이지를 찾지 못해 풋팅을 수행하지 못했습니다.')
            return self
        steps = [('재무제표 파싱', self.parse_statements), ('재무상태표', self.foot_bs), ('손익계산서', self.foot_is),
                 ('현금흐름표', self.foot_cf), ('자본변동표', self.foot_sce), ('재무제표간 대사', self.cross_statements),
                 ('주석 표 파싱', self.parse_notes), ('주석 풋팅', self.foot_notes), ('재무제표-주석 대사', self.fs_vs_notes),
                 ('주석 변동표-재무상태표 연속성', self.note_rollforward_vs_bs),
                 ('본문 서술금액', self.narrative), ('특수검증', self.special_checks)]
        for name, fn in steps:
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - 한 단계 실패가 전체 리뷰를 막지 않도록
                self.errors.append(f'{name} 단계 오류: {type(e).__name__}: {e}')
        return self

    def pg(self, p):
        return getattr(self, 'page_map', {}).get(p, p)




# ======================================================================================
# 기존 프로그램 결과 포맷 어댑터 (render_helpers / report_render 가 그대로 그릴 수 있도록)
# ======================================================================================
STMT_KEY = {'재무상태표': '재무상태표', '포괄손익계산서': '손익계산서', '자본변동표': '자본변동표', '현금흐름표': '현금흐름표'}
PERIOD = {'cy': '당기', 'py': '전기', '가로': '가로', '세로': '세로'}
OK = '일치'
OK_SET = ('일치', '일치(본문서술)', '일치(합산)', '일치(반올림범위)')


def to_calc_check(rep: Report) -> dict:
    out = {s: {'mismatches': [], 'skipped': [], 'note': None, 'checked': 0} for s in STMT_KEY.values()}
    for c in rep.fs_checks:
        d = out[STMT_KEY.get(c['구분'], c['구분'])]
        d['checked'] += 1
        if c['결과'] != OK:
            d['mismatches'].append({'parent': c['항목'], 'period': PERIOD.get(c['기간'], c['기간']), 'segment': None,
                                    'stated': c['보고금액'] or 0, 'computed': c['계산금액'] or 0, 'diff': c['차이'] or 0,
                                    'children': [c['검증식']], 'page': rep.pg(c['페이지']), 'result': c['결과']})
    for s, d in out.items():
        if d['checked'] == 0:
            d['note'] = '해당 재무제표를 인식하지 못해 검증하지 못했습니다(원문 확인 필요).'
    return out


def to_cross_check_fs(rep: Report) -> list:
    res = []
    for c in rep.cross_checks:
        if c['결과'] != OK:
            res.append({'item': c['검증항목'], 'diff': c['차이'], 'result': c['결과'],
                        'values': [{'source': '기준', 'label': c['기준'], 'value': c['기준금액'] or 0},
                                   {'source': '대사', 'label': c['대사'], 'value': c['대사금액'] or 0}]})
    return res


def to_note_check(rep: Report) -> dict:
    confirmed = sum(1 for c in rep.fs_note_checks if c['결과'] in OK_SET)
    unmatched = [{'stmt': c['재무제표'], 'label': f"{c['계정과목']} ({c['기간']}, {c['결과']})", 'value': c['재무제표금액_원'],
                  'notes': [f"주석 {c['주석번호']}" + (f" → {c['주석위치']}" if c['주석위치'] else '')]}
                 for c in rep.fs_note_checks if c['결과'] not in OK_SET]
    hier = [{'note': f"주석{c['주석']} p.{rep.pg(c['페이지'])}", 'parent': f"{c['행']} / {c['열']} [{c['유형']}·{c['결과']}]",
             'period': c['유형'], 'segment': None, 'stated': c['보고금액'], 'computed': c['계산금액'], 'diff': c['차이'],
             'children': [c['검증식']]} for c in rep.note_checks if c['결과'] not in OK_SET]
    return {'amount_tracing': {'confirmed': confirmed, 'unmatched': unmatched}, 'table_hierarchy': hier,
            'checked_tables': len({c['표ID'] for c in rep.note_checks}), 'total_tables': len(rep.note_tables),
            'checked_cells': len(rep.note_checks)}


def to_sum_check(rep: Report) -> list:
    """기존 '숫자 스크리닝' 탭 포맷 - 정밀 풋팅에서 일치하지 않은 항목만."""
    out = []
    for c in rep.fs_checks:
        if c['결과'] != OK:
            out.append({'page': rep.pg(c['페이지']), 'row_label': f"[{c['구분']}] {c['항목']}", 'column': PERIOD.get(c['기간'], c['기간']),
                        'stated': c['보고금액'] or 0, 'computed': c['계산금액'] or 0, 'diff': c['차이'] or 0, 'n_items': 0})
    for c in rep.note_checks:
        if c['결과'] not in OK_SET:
            out.append({'page': rep.pg(c['페이지']), 'row_label': f"[주석{c['주석']} {c['결과']}] {c['행']} / {c['열']}",
                        'column': c['유형'], 'stated': c['보고금액'], 'computed': c['계산금액'], 'diff': c['차이'], 'n_items': 0})
    return out


def to_variance_tables(rep: Report) -> dict:
    """재무제표 본문 행(헤더 제외)으로 증감분석 - 주석 표가 섞이지 않는다."""
    out = {}
    for code, stmt in (('BS', '재무상태표'), ('IS', '손익계산서'), ('CF', '현금흐름표')):
        rows = []
        for r in rep.fs_rows.get(code, []):
            if r['cy'] is None or r['py'] is None:
                continue
            diff = r['cy'] - r['py']
            rows.append({'label': r['label'], 'segment': None, 'current': r['cy'], 'prior': r['py'], 'diff': diff,
                         'pct': (diff / abs(r['py'])) if r['py'] else None})
        out[stmt] = {'rows': rows, 'note': None if rows else '재무제표를 인식하지 못했습니다.'}
    rows = []
    sce = rep.sce
    ends = [r for r in sce['rows'] if '말)' in r['label']]
    if len(ends) >= 2:
        for j, nm in enumerate(sce['names']):
            cur, pri = ends[-1]['vals'][j] or 0, ends[0]['vals'][j] or 0
            rows.append({'label': f'기말 {nm}', 'segment': None, 'current': cur, 'prior': pri, 'diff': cur - pri,
                         'pct': ((cur - pri) / abs(pri)) if pri else None})
    out['자본변동표'] = {'rows': rows, 'note': None if rows else '자본변동표 기말행을 인식하지 못했습니다.'}
    return out


def summary_counts(rep: Report) -> list:
    areas = [('재무제표 본문 풋팅', rep.fs_checks), ('재무제표 간 대사', rep.cross_checks), ('주석 풋팅', rep.note_checks),
             ('재무제표↔주석 대사', rep.fs_note_checks), ('본문 서술금액 대사', rep.text_checks),
             ('특수/주석간 검증', getattr(rep, 'special', []))]
    out = []
    for name, lst in areas:
        res = [c['결과'] for c in lst]
        res = ['일치' if x in OK_SET else x for x in res]
        out.append({'area': name, 'total': len(res), 'ok': res.count('일치'), 'rounding': res.count('단수차이'),
                    'mismatch': res.count('불일치'), 'other': len(res) - res.count('일치') - res.count('단수차이') - res.count('불일치')})
    return out


def exceptions(rep: Report) -> list:
    ex = []
    for c in rep.fs_checks:
        if c['결과'] != OK:
            ex.append(('재무제표풋팅', c['구분'], rep.pg(c['페이지']), c['항목'], c['검증식'], c['보고금액'], c['계산금액'], c['결과']))
    for c in rep.cross_checks:
        if c['결과'] != OK:
            ex.append(('재무제표간대사', '', '-', c['검증항목'], f"{c['기준']} vs {c['대사']}", c['기준금액'], c['대사금액'], c['결과']))
    for c in rep.note_checks:
        if c['결과'] not in OK_SET:
            ex.append(('주석풋팅', f"주석{c['주석']} {c['주석명']}", rep.pg(c['페이지']), f"{c['행']} / {c['열']}",
                       f"[{c['유형']}] {c['검증식']}", c['보고금액'], c['계산금액'], c['결과']))
    for c in rep.fs_note_checks:
        if c['결과'] not in OK_SET:
            ex.append(('재무제표-주석대사', c['재무제표'], '-', f"{c['계정과목']} ({c['기간']})", f"참조주석 {c['주석번호']} {c['주석위치']}".strip(),
                       c['재무제표금액_원'], c['주석금액'], c['결과']))
    for c in rep.text_checks:
        if c['결과'] != OK:
            ex.append(('본문수치대사', '', rep.pg(c['페이지']), c['서술금액'], c['문장'], None, None, c['결과']))
    for c in getattr(rep, 'special', []):
        if c['결과'] != OK:
            ex.append(('특수검증', '', str(c['비고']).replace('p.', ''), c['검증항목'], f"{c['기준']} / {c['대사']}", c['기준금액'], c['대사금액'], c['결과']))
    order = {'불일치': 0, '부호표시 확인': 1, '표기 확인': 2, '단수차이': 3}
    ex.sort(key=lambda e: order.get(e[7], 4))   # 심각도 순 (불일치 → 부호/표기 → 단수차이 → 미발견 등)
    return ex


def compare_consol_separate_amounts(con: Report, sep: Report) -> list:
    """연결 vs 별도 재무제표 본문 동일 계정 금액 비교 (차이는 오류가 아닌 검토포인트)."""
    def key(lbl):
        return re.sub(r'\s|\(.*?\)', '', ROMAN.sub('', lbl))
    out = []
    for code, stmt in (('BS', '재무상태표'), ('IS', '손익계산서'), ('CF', '현금흐름표')):
        smap = {}
        for r in sep.fs_rows.get(code, []):
            if r['cy'] is not None:
                smap.setdefault(key(r['label']), r)
        seen = set()
        for r in con.fs_rows.get(code, []):
            if r['cy'] is None:
                continue
            k = key(r['label'])
            if k in seen:
                continue
            seen.add(k)
            s = smap.get(k)
            if s is None:
                st = '별도에 없음'
            else:
                cy_same, py_same = r['cy'] == s['cy'], (r['py'] or 0) == (s['py'] or 0)
                st = '동일' if cy_same and py_same else ('당기 동일·전기 차이' if cy_same else ('당기 차이·전기 동일' if py_same else '당기·전기 차이'))
            out.append({'stmt': stmt, 'label': r['label'], 'consol_cy': r['cy'], 'sep_cy': s['cy'] if s else None,
                        'diff_cy': (r['cy'] - s['cy']) if s else None, 'consol_py': r['py'],
                        'sep_py': s['py'] if s else None, 'diff_py': ((r['py'] or 0) - (s['py'] or 0)) if s else None,
                        'status': st})
        ckeys = {key(r['label']) for r in con.fs_rows.get(code, []) if r['cy'] is not None}
        for k, s in smap.items():
            if k not in ckeys:
                out.append({'stmt': stmt, 'label': s['label'], 'consol_cy': None, 'sep_cy': s['cy'], 'diff_cy': None,
                            'consol_py': None, 'sep_py': s['py'], 'diff_py': None, 'status': '연결에 없음'})
    return out


# ------------------------------------------------------------------ Excel 시트
def add_excel_sheets(wb, label: str, rep: Report, prefix: str = '') -> None:
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.formatting.rule import CellIsRule, FormulaRule

    HDR_FILL = PatternFill('solid', start_color='1F3864')
    HDR_FONT = Font(name='Arial', bold=True, color='FFFFFF', size=10)
    BODY = Font(name='Arial', size=9)
    THIN = Side(style='thin', color='BFBFBF')
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    NUMFMT = '#,##0;(#,##0);-'
    RED, YEL, GRN = (PatternFill('solid', start_color=c) for c in ('F8CBAD', 'FFF2CC', 'E2EFDA'))
    pg = rep.pg

    def sheet(name, headers, rows, widths, num_cols=(), diff=None, result_col=None, wrap=()):
        ws = wb.create_sheet((prefix + name)[:31])
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill, c.border = HDR_FONT, HDR_FILL, BORDER
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        for i, r in enumerate(rows, start=2):
            vals = list(r)
            if diff:
                dcol, a, b = diff
                vals[dcol - 1] = f'=IF(OR({a}{i}="",{b}{i}=""),"",{a}{i}-{b}{i})'
            ws.append(vals)
            for j, c in enumerate(ws[i], start=1):
                c.font, c.border = BODY, BORDER
                c.alignment = Alignment(vertical='top', wrap_text=j in wrap)
                if j in num_cols:
                    c.number_format = NUMFMT
        for j, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        if result_col and rows:
            L = get_column_letter(result_col)
            rng = f'{L}2:{L}{len(rows) + 1}'
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"일치"'], fill=GRN))
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"불일치"'], fill=RED))
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"일치(본문서술)"'], fill=GRN))
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"일치(합산)"'], fill=GRN))
            ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"일치(반올림범위)"'], fill=GRN))
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f'AND({L}2<>"일치",{L}2<>"불일치",{L}2<>"일치(본문서술)",{L}2<>"일치(합산)",{L}2<>"일치(반올림범위)")'], fill=YEL))
        return ws

    ws = sheet('풋팅요약', ['검증영역', '검증건수', '일치', '단수차이', '불일치', '기타(확인필요)'],
               [(a['area'], a['total'], a['ok'], a['rounding'], a['mismatch'], a['other']) for a in summary_counts(rep)],
               [26, 12, 10, 10, 10, 14])
    n = ws.max_row
    ws.append(['합계'] + [f'=SUM({get_column_letter(j)}2:{get_column_letter(j)}{n})' for j in range(2, 7)])
    for c in ws[ws.max_row]:
        c.font = Font(name='Arial', bold=True, size=9); c.border = BORDER
    ws.append([])
    ws.append([f'대상: {label}   |   재무제표 p.{pg(rep.sections.get("fs_start"))}~  주석 p.{pg(rep.sections.get("notes_start"))}~p.{pg(rep.sections.get("notes_end"))}   |   추출 주석표 {len(rep.note_tables)}개'])
    for t in ['판정: 일치=차이0 / 단수차이=천원표시 |차이|<=max(2,구성항목수) / 불일치=허용범위 초과 / 부호표시 확인=부호반전 시 일치 / 표기 확인·미발견=참조·표기 점검 대상',
              '원 단위 재무제표 본문은 1원 차이도 불일치. 각 상세시트의 차이 열은 수식(보고-재계산)입니다.'] + [f'[오류] {e}' for e in getattr(rep, 'errors', [])]:
        ws.append([t])
        ws.cell(ws.max_row, 1).font = Font(name='Arial', size=9)

    sheet('풋팅예외', ['검증영역', '재무제표/주석', '페이지', '항목', '검증내용', '보고금액', '비교금액', '결과'], exceptions(rep),
          [16, 26, 7, 34, 60, 16, 16, 13], num_cols=(6, 7), result_col=8, wrap=(2, 4, 5))
    sheet('FS풋팅', ['재무제표', '페이지', '항목', '기간/방향', '검증식', '보고금액(원)', '재계산금액(원)', '차이', '결과'],
          [(c['구분'], pg(c['페이지']), c['항목'], PERIOD.get(c['기간'], c['기간']), c['검증식'], c['보고금액'], c['계산금액'], None, c['결과'])
           for c in rep.fs_checks], [14, 7, 34, 9, 46, 18, 18, 14, 10], num_cols=(6, 7, 8), diff=(8, 'F', 'G'), result_col=9, wrap=(3, 5))
    sheet('FS간대사', ['검증항목', '기준', '기준금액(원)', '대사대상', '대사금액(원)', '차이', '결과'],
          [(c['검증항목'], c['기준'], c['기준금액'], c['대사'], c['대사금액'], None, c['결과']) for c in rep.cross_checks],
          [36, 28, 18, 28, 18, 14, 10], num_cols=(3, 5, 6), diff=(6, 'C', 'E'), result_col=7, wrap=(1, 2, 4))
    sheet('주석풋팅', ['주석', '주석명', '표 제목', '표ID', '페이지', '단위', '검증유형', '행(항목)', '열', '검증식', '보고금액', '재계산금액', '차이', '결과'],
          [(c['주석'], c['주석명'], c['표'], c['표ID'], pg(c['페이지']), c['단위'], c['유형'], c['행'], c['열'], c['검증식'],
            c['보고금액'], c['계산금액'], None, c['결과']) for c in rep.note_checks],
          [6, 22, 40, 6, 7, 6, 13, 24, 18, 44, 15, 15, 12, 11], num_cols=(11, 12, 13), diff=(13, 'K', 'L'), result_col=14, wrap=(2, 3, 10))
    sheet('FS-주석대사', ['재무제표', '계정과목', '참조주석', '기간', '재무제표금액(원)', '주석금액(주석단위)', '주석 내 대응위치', '결과'],
          [(c['재무제표'], c['계정과목'], c['주석번호'], c['기간'], c['재무제표금액_원'], c['주석금액'], c['주석위치'], c['결과'])
           for c in rep.fs_note_checks], [14, 30, 14, 7, 19, 16, 60, 10], num_cols=(5, 6), result_col=8, wrap=(2, 7))
    sheet('본문수치대사', ['페이지', '문장', '서술금액', '대응 재무제표 항목', '결과'],
          [(pg(c['페이지']), c['문장'], c['서술금액'], c['대응항목'], c['결과']) for c in rep.text_checks],
          [7, 70, 16, 50, 14], result_col=5, wrap=(2, 4))
    sp = getattr(rep, 'special', [])
    ws = sheet('특수검증', ['검증항목', '기준', '기준금액', '대사대상', '대사금액', '차이', '결과', '비고'],
               [(c['검증항목'], c['기준'], c['기준금액'], c['대사'], c['대사금액'], '', c['결과'], c['비고']) for c in sp],
               [40, 26, 18, 36, 18, 12, 10, 40], num_cols=(3, 5, 6), result_col=7, wrap=(1, 2, 4, 8))
    for i, c in enumerate(sp, start=2):
        if c['차이'] is not None:
            ws.cell(i, 6).value = f'=C{i}-E{i}'
    chk = {}
    for c in rep.note_checks:
        chk.setdefault(c['표ID'], []).append(c['결과'])
    skipped = {(s['주석'], s['표']) for s in rep.skipped}
    rows = []
    for t in rep.note_tables:
        res = chk.get(t['id'], [])
        st = '검증제외(산식표)' if (t['note'], t['title']) in skipped else ('검증완료' if res else '합계/롤포워드 구조 없음')
        rows.append((t['id'], t['note'], t['note_title'], t['title'], pg(t['page']), t['unit'], len(t['rows']), len(t['cols']),
                     len(res), sum(1 for x in res if x != OK), st))
    sheet('추출표목록', ['표ID', '주석', '주석명', '표 제목', '페이지', '단위', '행수', '열수', '검증건수', '예외건수', '상태'], rows,
          [6, 6, 24, 54, 7, 6, 6, 6, 8, 8, 20], wrap=(3, 4))


def add_consol_sep_sheet(wb, rows: list) -> None:
    from openpyxl.styles import Font, PatternFill
    ws = wb.create_sheet('연결vs별도_금액비교')
    ws.append(['재무제표', '계정과목', '연결 당기', '별도 당기', '차이(당기)', '연결 전기', '별도 전기', '차이(전기)', '상태'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True, color='FFFFFF'); c.fill = PatternFill('solid', start_color='1F3864')
    for i, r in enumerate(rows, start=2):
        ws.append([r['stmt'], r['label'], r['consol_cy'], r['sep_cy'], f'=IF(OR(C{i}="",D{i}=""),"",C{i}-D{i})',
                   r['consol_py'], r['sep_py'], f'=IF(OR(F{i}="",G{i}=""),"",F{i}-G{i})', r['status']])
        for j in (3, 4, 5, 6, 7, 8):
            ws.cell(i, j).number_format = '#,##0;(#,##0);-'
        for c in ws[i]:
            c.font = Font(name='Arial', size=9)
    for j, w in enumerate([12, 34, 18, 18, 16, 18, 18, 16, 12], start=1):
        ws.column_dimensions[chr(64 + j)].width = w
    ws.freeze_panes = 'A2'


# ------------------------------------------------------------------ 전기 감사보고서 대사
def compare_prior_fs(cur: Report, prior: Report) -> list:
    """당기 보고서의 '전기' 열 = 전기 감사보고서의 '당기' 열 (재작성·재분류 탐지).
    재무상태표/손익계산서/현금흐름표 계정별 + 자본변동표 기말 열별."""
    def key(lbl):
        return re.sub(r'\s|\(.*?\)', '', ROMAN.sub('', lbl))
    out = []
    for code, stmt in (('BS', '재무상태표'), ('IS', '손익계산서'), ('CF', '현금흐름표')):
        pmap = {}
        for r in prior.fs_rows.get(code, []):
            if r['cy'] is not None:
                pmap.setdefault(key(r['label']), r)
        used = set()
        for r in cur.fs_rows.get(code, []):
            if r['py'] is None:
                continue
            k = key(r['label'])
            p = pmap.get(k)
            used.add(k)
            if p is None:
                res = '전기보고서에 없음(계정 신설·명칭변경·재분류 확인)'
            else:
                res = '일치' if p['cy'] == r['py'] else '불일치(재작성·재분류 확인)'
            out.append({'stmt': stmt, 'label': r['label'], 'cur_prior_col': r['py'], 'prior_report_cy': p['cy'] if p else None,
                        'result': res})
        for k, p in pmap.items():
            if k not in used:
                out.append({'stmt': stmt, 'label': p['label'], 'cur_prior_col': None, 'prior_report_cy': p['cy'],
                            'result': '당기보고서에 없음(계정 통합·명칭변경 확인)'})
    ce = [r for r in cur.sce['rows'] if '말)' in r['label']]
    pe = [r for r in prior.sce['rows'] if '말)' in r['label']]
    if ce and pe:
        for j, nm in enumerate(cur.sce['names']):
            pj = prior.sce['names'].index(nm) if nm in prior.sce['names'] else None
            pv = pe[-1]['vals'][pj] if pj is not None else None
            cv = ce[0]['vals'][j]
            out.append({'stmt': '자본변동표', 'label': f'전기말 {nm}', 'cur_prior_col': cv, 'prior_report_cy': pv,
                        'result': '일치' if pv is not None and pv == cv else ('전기보고서에 없음' if pv is None else '불일치(재작성 확인)')})
    return out


def add_prior_sheet(wb, name: str, rows: list) -> None:
    from openpyxl.styles import Font, PatternFill
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    ws = wb.create_sheet(name[:31])
    ws.append(['재무제표', '계정과목', '당기보고서 전기열', '전기보고서 당기열', '차이', '결과'])
    for c in ws[1]:
        c.font = Font(name='Arial', bold=True, color='FFFFFF'); c.fill = PatternFill('solid', start_color='1F3864')
    for i, r in enumerate(rows, start=2):
        ws.append([r['stmt'], r['label'], r['cur_prior_col'], r['prior_report_cy'],
                   f'=IF(OR(C{i}="",D{i}=""),"",C{i}-D{i})', r['result']])
        for j in (3, 4, 5):
            ws.cell(i, j).number_format = '#,##0;(#,##0);-'
        for c in ws[i]:
            c.font = Font(name='Arial', size=9)
    for col, w in zip('ABCDEF', (12, 34, 20, 20, 16, 34)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'A2'
    if rows:
        rng = f'F2:F{len(rows) + 1}'
        ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['"일치"'], fill=PatternFill('solid', start_color='E2EFDA')))
        ws.conditional_formatting.add(rng, FormulaRule(formula=['F2<>"일치"'], fill=PatternFill('solid', start_color='FFF2CC')))


# ------------------------------------------------------------------ 개요 시트 (요약 시트 대체)
NO_CHANGE_FLAG = {'period', 'report_date'}   # 매년 바뀌는 것이 정상인 항목은 음영 제외


def add_overview_sheet(wb, docs: list, sheet_name: str = '개요') -> None:
    """docs: [(label, overview_items, prior_items|None, prior_file|None)]. 전기≠당기면 연한 노란 음영."""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    ws = wb.create_sheet(sheet_name, 0)
    LIGHT_YEL = PatternFill('solid', start_color='FFF9C4')
    HDR = PatternFill('solid', start_color='1F3864')
    THIN = Side(style='thin', color='BFBFBF')
    B = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    ws['A1'] = '감사보고서 개요 - 전기 대비 당기'
    ws['A1'].font = Font(name='Arial', bold=True, size=13)
    ws['A2'] = '연한 노란 음영 = 전기 대비 변동 항목 (회계기간·감사보고서일은 매년 바뀌므로 제외)'
    ws['A2'].font = Font(name='Arial', size=9, color='595959')
    r = 4
    for label, cur, prior, prior_file in docs:
        ws.cell(r, 1, f'[{label}]').font = Font(name='Arial', bold=True, size=11)
        src = f'전기: {prior_file}' if prior_file else '전기 감사보고서 미제공 → 당기 보고서에 함께 기재된 전기값만 표시'
        ws.cell(r, 3, src).font = Font(name='Arial', size=9, color='595959')
        r += 1
        for j, h in enumerate(['항목', '전기', '당기', '전기 대비'], start=1):
            c = ws.cell(r, j, h)
            c.font, c.fill, c.border = Font(name='Arial', bold=True, color='FFFFFF', size=10), HDR, B
            c.alignment = Alignment(horizontal='center')
        r += 1
        pmap = {i['key']: i['value'] for i in (prior or [])}
        for it in cur:
            pv = pmap.get(it['key']) if prior else it.get('prior_in_report')
            if pv is None:
                pv_disp, chg = ('-' if prior else '전기 보고서 미제공'), ''
            else:
                pv_disp = pv
                if it['key'] in NO_CHANGE_FLAG:
                    chg = '기간 경과(정상)'
                else:
                    chg = '변동' if str(pv).strip() != str(it['value']).strip() else '동일'
            vals = [it['label'], pv_disp, it['value'], chg]
            for j, v in enumerate(vals, start=1):
                c = ws.cell(r, j, v)
                c.font, c.border = Font(name='Arial', size=10), B
                c.alignment = Alignment(wrap_text=True, vertical='top')
                if chg == '변동' and j >= 2:
                    c.fill = LIGHT_YEL
            r += 1
        r += 1
    for col, w in zip('ABCD', (34, 52, 52, 14)):
        ws.column_dimensions[col].width = w
