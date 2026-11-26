# CLAUDE.md - FSS_Review_Program 작업 인수인계

이 파일은 Claude Code가 이 저장소에서 작업할 때 자동으로 읽는 맥락 문서다.
(2026-11-24~25 claude.ai 세션에서 진행한 개발 내용을 정리)

## 목적
감사인 품질관리용 **감사보고서(및 분·반기 검토보고서) 리뷰·풋팅 데스크톱 프로그램**.
DART에서 받은 보고서 PDF를 올리면 재무제표·주석 숫자 풋팅, 대사, 전기 대비 비교를 자동 수행하고
결과를 화면 탭 + Excel(다운로드 폴더 자동 저장)로 보여준다.
- 사용자는 한국어로 소통한다. 결과물·UI 문구·커밋 메시지도 한국어.
- 입력은 **PDF만으로 실행**되어야 한다(전기 PDF, XBRL ZIP은 선택). 외부 전송·AI 호출 없음.

## 실행
- Windows: `run.bat` 더블클릭 (최초 .venv 생성 + 패키지 설치). EXE: `build_exe.bat` → `dist\FSS_ReviewProgram.exe`
- 직접: `pip install -r requirements.txt` → `python main.py` (Python 3.10+, tkinter 필요)
- **`.bat` 파일은 ASCII(영어)만 + CRLF로 저장**할 것. UTF-8 한글/LF면 cmd가 명령을 조각내 실행함
  (`.gitattributes`의 `*.bat -text`로 CRLF 그대로 보관). pip 업그레이드는 `python -m pip`로, 실패해도 계속 진행.
- `dist\FSS_ReviewProgram.exe`는 **구버전 빌드** - 기능 반영하려면 재빌드 필요.

## 회귀 테스트 (코드 수정 후 반드시 실행)
```
python tests/regression.py            # 기준값(tests/expected.json)과 비교
python tests/regression.py --update   # 의도한 개선으로 결과가 바뀐 경우에만 기준값 갱신
```
샘플 PDF는 `tests/samples/`(git 제외)에 둔다 - 파일명은 tests/regression.py 상단 주석 참고.
- 유니슨 제42기(2025.12.31) 연결/별도 + 원문XBRL ZIP + 제41기(전기, 2025.03.20) 연결/별도(unison_pri_*.pdf)
- 신한알파리츠 제16기(2025.10~2026.03, **6개월 결산**) 연결/별도 + 제15기(전기) 연결/별도
서식이 다른 두 회사이므로, 한쪽만 맞추고 다른 쪽을 깨뜨리지 않도록 항상 둘 다 돌린다.

## 구조 (감사보고서 경로 중심)
```
main.py → app/ui.py (customtkinter)  ── 보고서종류 ① 분반기 / 감사
app/review_engine.py   보고서종류별 분기
app/audit_engine.py    감사보고서 파이프라인 (결과 포맷은 semiannual_engine 과 동일 → 기존 탭 재사용)
                       `order_current_prior`: 당기·전기 파일이 바뀌어 와도 재무제표 표지('제 42 기 … 부터 … 까지 / 제 41 기 …')의
                       기수 → 종료일이 큰 쪽을 당기로 (파일명은 쓰지 않음, 바꿔 처리하면 개요 시트에 표시)
app/rules/audit_footing.py      ★ 정밀 풋팅 엔진 (pdfplumber 단어 좌표로 행/열 복원)
app/rules/audit_opinion.py      감사의견/KAM/계속기업/내부회계/개요(build_overview)
app/rules/audit_checklist.py    감사기준서 700·701·570·706 필수 기재사항
app/rules/prior_note_compare.py 전기 보고서 대비 주석 목록(신설/삭제/제목변경) + 주석 표 숫자 대사
                                (짝짓기: 정확키 → 표제목 무시 → 구분 무시 → 행이름(각주 제거)+금액 → 열+금액(0 제외) → 행 별칭.
                                 → 같은 주석 행이름+금액 → 주석 무관 행이름(괄호 제거)+금액(주석 통합·분리 대응).
                                 열 기간 판단 시 '당기손익-공정가치' 등 계정명 속 당기/전기 제외, 2단 머리글(당기말→유동|비유동) 기간 이어받기,
                                 금액 행 사이 빈 행은 구분 머리글 아님.
                                 당기보고서 기준 제외: 당기보고서 전기금액 0('-') & 전기보고서 0 또는 짝 없음 → 대사 대상 아님)
                                재무제표 전기대사 `_detect_reclass`: 불일치 차이 = 한쪽에만 있는 계정 1~3개 합이면 '재분류(…통합/분리 시 일치)'
app/rules/xbrl_pdf_tieout.py    PDF 재무제표 ↔ XBRL 계정별 대사 (CF 지출요소 부호 관행 반영)
app/variance_export.py          Excel 출력 (감사: 첫 시트 '개요', 풋팅 시트들, 전기대사 시트들)
app/render_helpers.py           탭 렌더링 (render_footing, render_overview 등)
app/semiannual_engine.py        분·반기 경로(기존 로직, 정밀 풋팅 미적용)
tests/regression.py             회귀 테스트
```

### audit_footing.Report 처리 단계 (run())
1. `locate_sections` 재무제표/주석 시작·끝 페이지
2. `parse_statements` 재무제표 행 파싱 - 금액 열은 **'주석' 머리글 x좌표 기준**(고정 좌표 금지), 여러 줄 계정명 병합
3. `foot_bs / foot_is / foot_cf / foot_sce` 본문 풋팅 (CF는 I.>1.>(1)>항목 계층. '현금유출액' 머리행은 하위 양수표시면 재계산금액=-(Σ하위)로 차이 계산.
   CF 행은 'VI. 기말의 현금' 행에서 잘라냄(뒤에 섞인 주석 행 제거), IV.증감/V.기초/VI.기말/환율 행은 Σ하위 검증 제외)
4. `cross_statements` + `_cross_more` 재무제표 간 대사 + 연속성(CF 기초=전기 기말, CF 기말=BS 현금, SCE 당기초=BS 전기말, 이익잉여금 등),
   당기순이익 IS↔SCE↔CF, (연결) 지배/비지배 귀속↔SCE, 총포괄손익, CF 배당금지급·유상증자↔SCE·CF 조정↔IS 동일계정(차이 시 '참고').
   결과는 FS간대사 시트와 **FS풋팅 시트 하단('재무제표 간 대사')**에 함께 출력
5. `parse_notes` 주석 표 추출 (`(단위` 줄에서 표 시작, `(n)`/`n)`/①②/가. 소제목, 표 기간태그 `period_tag`)
6. `foot_notes` 세로합계(후보식 중 최소차이), 가로합계, 롤포워드, 전기말→당기초, 산식(지분율·기대손실률·EPS·적수·법인세 관계; 가중평균주식수 표에 기간 열(시작일~종료일)이 있으면 날짜로 일수 재계산 → 적수·가중평균 검증, 일수 열 합산 안 함)
7. `fs_vs_notes` → `fs_note_pair_sums` → `note_rollforward_vs_bs` 재무제표↔주석 대사
8. `narrative` 본문 서술금액(백만원/천원) ↔ 재무제표/주석 금액, `special_checks`
- 판정: 일치 / 일치(…변형) / 단수차이(천원표시 |차이|≤max(2,구성항목수)) / 불일치 / 부호표시 확인 / 표기 확인 / 미발견 / 참고
- 원 단위 재무제표 본문은 1원 차이도 불일치.

## 지금까지의 주요 결정
- 원본 저장소의 감사 경로는 스텁이었음 → 정밀 풋팅 엔진을 이식해 구현.
- 사용자 요청으로 **제거**: 공시사항점검표 8400 대사, Excel 정밀검증(옵션⑧), AI 심층리뷰(Claude/Gemini), 커스텀 체크리스트,
  resources/review_standard.txt. (8400 대사는 "따로 고민"하기로 보류)
- XBRL은 선택 입력으로 유지: DART '원문XBRL' ZIP 1개만 받으면 됨(뷰어 Excel 2종은 불필요).
- 감사보고서 Excel의 첫 시트는 '개요'(전기 대비 당기, 변동 행 연한 노랑 FFF9C4)만. 텍스트 요약 시트 제거.
- XBRL 현금흐름표 지출요소(Payments/PurchaseOf/RepaymentsOf/InterestPaid/IncomeTaxesPaid…)는 부호 변환 후 비교.

## 검증 결과 메모 (실제 발견한 사항)
- 유니슨 연결 주석14 유형자산 기말 합계 136,007,192 vs 195천원, 별도 자본변동표 2024년 행 '당기초/당기말' 오표기,
  이연법인세 미인식 만기표 합계만 있고 만기별 '-', 공사계약 잔액 변동표 당기/전기 부호표시 불일치.
- 신한알파 연결 주석8(2) 전기 감가상각비: 당기보고서 8,265,501 vs 전기보고서 8,291,214천원(타 주석·CF는 8,291,215).
  업무수행이사 김영중→김기민 변경, 주석 '28. 보고기간 후 사건' 신설.
- 유니슨 제42기 vs 제41기: 전기보고서 자본변동표 결손금 (58,887,620,841) vs 같은 보고서 BS (…842) 1원 불일치(당기보고서에서 842로 정정),
  선급금 → 기타유동/비유동자산 통합, 기타유동부채 분리(재분류), 리스 이자비용 142,065 vs 141,400, 경영진 보상 전기 반올림 표시 → 정밀 금액.

## 남은 과제 (백로그)
1. 전기 비교 '짝 없음' 칸 축소 - 여러 줄 셀 표(차입금 차입처·담보 표), 종속기업 현황 표(행 라벨 공란) 파싱 개선
2. 분·반기 경로에도 정밀 풋팅 적용 (3개월/누적 4열 손익계산서 처리 필요)
3. 공시사항점검표 8400 대사 재설계 (보류 중)
4. 전기 XBRL을 계층 템플릿으로 써서 당기 PDF 매핑 (당기 XBRL 없는 경우 대비)
5. GitHub 반영: 브랜치 `feature/audit-footing` (커밋 8개) - 원격에 아직 push 안 됨
6. Windows 실제 GUI 확인 (claude.ai 세션에서는 tkinter가 없어 위젯 트리를 HTML로 그려 확인만 함)

## 작업 규칙
- 수정 후 `python tests/regression.py` 통과 확인. 결과가 바뀌면 원문 PDF로 진위 확인 후에만 `--update`.
- 새 서식 대응은 고정 좌표·회사별 하드코딩 대신 머리글/구조 기반으로 일반화.
- 오탐(실제 차이 아닌 '불일치')을 줄이는 것이 우선 - 불확실하면 '불일치' 대신 '참고/확인필요/짝 없음'으로 분류.
