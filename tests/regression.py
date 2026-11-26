"""회귀 테스트: 샘플 감사보고서로 엔진을 돌려 검증 건수/결과가 기준값(expected.json)과 같은지 확인.

사용법
  python tests/regression.py            # 기준값과 비교 (다르면 차이 출력, 종료코드 1)
  python tests/regression.py --update   # 현재 결과로 기준값 갱신 (의도한 개선일 때만)

샘플 파일은 tests/samples/ 에 아래 이름으로 넣는다 (git에는 올리지 않음, .gitignore 처리).
  unison_consol.pdf, unison_separate.pdf, unison_xbrl.zip           (유니슨 제42기, 2026.03.19)
  unison_pri_consol.pdf, unison_pri_separate.pdf                    (유니슨 제41기, 2025.03.20)
  shinhan_cur_consol.pdf, shinhan_cur_separate.pdf                  (신한알파리츠 제16기, 2026.05.28)
  shinhan_pri_consol.pdf, shinhan_pri_separate.pdf                  (신한알파리츠 제15기, 2025.12.02)
없는 파일이 있는 케이스는 건너뛴다.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(ROOT, 'tests', 'samples')
EXPECTED = os.path.join(ROOT, 'tests', 'expected.json')

from app.rules import audit_footing as af            # noqa: E402
from app.rules import xbrl_pdf_tieout as xt           # noqa: E402
from app.rules import prior_note_compare as pnc       # noqa: E402

CASES = {
    'unison_consol': ('unison_consol.pdf', 'unison_pri_consol.pdf', ('unison_xbrl.zip', 'consolidated')),
    'unison_separate': ('unison_separate.pdf', 'unison_pri_separate.pdf', ('unison_xbrl.zip', 'separate')),
    'shinhan_consol': ('shinhan_cur_consol.pdf', 'shinhan_pri_consol.pdf', None),
    'shinhan_separate': ('shinhan_cur_separate.pdf', 'shinhan_pri_separate.pdf', None),
}


def run_case(cur, prior, xbrl):
    out = {}
    rep = af.Report(os.path.join(SAMPLES, cur)).run()
    out['errors'] = rep.errors
    out['footing'] = {a['area']: [a['total'], a['ok'], a['rounding'], a['mismatch'], a['other']] for a in af.summary_counts(rep)}
    out['exceptions'] = sorted(f"{e[7]}|{e[0]}|{e[3]}" for e in af.exceptions(rep) if e[7] in ('불일치', '부호표시 확인', '표기 확인'))
    if xbrl and os.path.exists(os.path.join(SAMPLES, xbrl[0])):
        t = xt.tieout(rep, os.path.join(SAMPLES, xbrl[0]), xbrl[1])
        s = xt.summary(t)
        out['xbrl'] = [s['total'], s['ok'], s['mismatch'], s['other']]
    if prior and os.path.exists(os.path.join(SAMPLES, prior)):
        prep = af.Report(os.path.join(SAMPLES, prior)).run()
        fs = af.compare_prior_fs(rep, prep)
        nl = pnc.compare_note_lists(rep, prep)
        nn = pnc.compare_note_numbers(rep, prep, nl)
        sm = pnc.summary(nl, nn, fs)
        out['prior'] = {k: sm[k] for k in ('fs_total', 'fs_mismatch', 'notes_new', 'notes_removed', 'notes_renamed',
                                           'num_total', 'num_ok', 'num_mismatch', 'num_unpaired')}
    return out


def main():
    update = '--update' in sys.argv
    expected = json.load(open(EXPECTED, encoding='utf-8')) if os.path.exists(EXPECTED) else {}
    current, failed = {}, False
    for name, (cur, prior, xbrl) in CASES.items():
        if not os.path.exists(os.path.join(SAMPLES, cur)):
            print(f'[SKIP] {name}: tests/samples/{cur} 없음')
            continue
        print(f'[RUN ] {name} ...', flush=True)
        current[name] = run_case(cur, prior, xbrl)
        if not update and name in expected and expected[name] != current[name]:
            failed = True
            print(f'[DIFF] {name}')
            for k in sorted(set(expected[name]) | set(current[name])):
                if expected[name].get(k) != current[name].get(k):
                    print(f'   - {k}\n       기준: {expected[name].get(k)}\n       현재: {current[name].get(k)}')
        elif not update:
            print(f'[ OK ] {name}')
    if update:
        expected.update(current)
        json.dump(expected, open(EXPECTED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('기준값 갱신 완료:', EXPECTED)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
