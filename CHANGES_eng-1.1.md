# eng-1.1 — 기억 속 사물 색 반영

## 왜
eng-1.0은 감정·장소·시간 축에서만 색을 가져와서, "수박·옥수수" 같은 사물이 색에 나오지 않았고
주조색과 강조색 이름이 둘 다 "Peach Cream"으로 표시됐다.

## 바뀐 것
| 파일 | 내용 |
|---|---|
| core/objects.py (새 파일) | 사물 → 등급(색상 계열·밝기 1~9·채도 0~5) → OKLCH 표 → HEX → CIE LCh. 사전(color_lexicon) 우선 = 같은 낱말 같은 색. 등급이 범위 밖이면 버림 |
| core/synth.py | 강조색 ← 첫 번째 사물, 분위기색 ← 두 번째 사물(OBJECT_SLOTS=2). 사물 색엔 조화 당김 없음. 강조색이 주조색과 ΔE00 20 미만이면 채도→명도 순으로 벌림. 이름 중복 수정. 캐시 키에 사물 포함. ENGINE_VERSION=eng-1.1 |
| core/llm.py | objects를 {name, hue, lightness, chroma}로 받음(숫자 색값 자리 없음). 예전 문자열 목록도 받음. stub 모드는 사전 낱말로 사물 추출 |
| prompts/feature_prompt.py | 사물 등급 규칙·예시 추가 |
| core/pipeline.py | resolve_objects → synthesize 연결, 로그에 사물 등급 |
| oracle/lexicon_seed.json | 수박·옥수수·초원 추가 |
| tests/test_objects.py (새 파일) | 7개 — eng-1.0 색 유지 확인, 사물 배치, 사전 우선, 등급 게이트, 결정론·캐시 키, 대비 규칙, 예전 형식 |
| (프론트) src/components/Specimen.jsx | 근거 표시에 "사물 · 사전 등급/모델 등급 · 대비 보정" |

## 환경변수 (선택)
- OBJECT_SLOTS=2 (기본) — 사물 2개면 강조+분위기. 1이면 강조색만 사물, 분위기색은 시간 축 유지
- ACCENT_MIN_DE=20 (기본) — 강조색과 주조색의 최소 ΔE00

## 확인
- pytest 31개 통과 (기존 24 + 새 7)
- 사물이 없을 때는 eng-1.0과 같은 HEX (#F0C3AB · #B48865 · #EDDBBB · #E47570) — 이름만 "Peach Cream · 강조"로 바뀜
- 샘플 문장: 분위기 #EED059 옥수수 · 강조 #CD6057 수박, 검증 PASS (최대 ΔE00 0.41)
- 엔진 버전이 바뀌어 캐시 키가 달라지므로, 같은 문장도 새 표본으로 다시 계산된다
