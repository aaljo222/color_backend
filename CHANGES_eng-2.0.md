# eng-2.0 — 그림 먼저 (Image-first): 기억 → 색면추상화 → 그림에서 HEX 측정

## 왜
eng-1.x 는 팔레트를 KB 21항목에서 계산한 뒤 그 4색으로 그림을 그려, 그림이 늘 정확히 4색이었다.
팀장 피드백: "색면추상화를 바로 만들고, 만들어진 그림에서 HEX 를 뽑아야 한다."

## 켜는 법
- 서버 기본: `ENGINE_MODE=image_first` (기본은 palette = eng-1.2, 바뀐 것 없음)
- 요청마다: `POST /api/analyze` body 에 `"engine": "image_first"` (화면의 '엔진 (비교용)' 선택)
- 화가: `PAINTER=gemini | claude_scene | stub`
  - gemini: GEMINI_API_KEY + `pip install google-genai`, 모델 `GEMINI_IMAGE_MODEL`(기본 gemini-3.1-flash-lite-image)
  - claude_scene: ANTHROPIC_API_KEY 만으로 동작. Claude 가 색면 구성(JSON)을 내고 서버가 그림
  - stub: 키 없이 테스트용

## 흐름 (core/image_first.py)
1. 프롬프트: 기억 요약 + KB 검색 결과 설명 + 사물 + 정서 등급 (RAG 의 보강 단계)
2. 그리기 (화가)
3. 측정: Lab K-Means(k=6) → 면적 큰 3색 + 주조색과 가장 대비되는 1색 → 전체 픽셀 재배정(면적비)
   → 색 값은 군집 핵심 픽셀 40% 평균 (번진 경계 = 섞인 색 제외)
4. 심사: 4색 대표도 ≥ 80% (픽셀이 4색 중 하나와 ΔE00 ≤ 10) + 면적 가중 평균 채도·명도가 쾌·각성 범위 안
   → 실패하면 고칠 점을 프롬프트에 붙여 다시 그림 (IMAGE_MAX_ATTEMPTS=2)
5. 설명: 색마다 KB·사물 사전에서 가장 가까운 기준색 + ΔE00 (15 넘으면 '새 색')
6. 같은 기억 = 같은 그림: 프로세스 캐시 (재시작하면 사라짐 → 영구 캐시는 다음 단계)

## 실측 (기억 6개, 장면 JSON 은 Claude 가 claude_scene 화가 역할로 작성 — API 호출 아님)
| 지표 | eng-1.2 | eng-2.0 |
|---|---|---|
| 그림 속 서로 다른 색 수 (평균, 범위) | 3.7 (3~4) | 6.5 (4~11) |
| 주조색끼리 평균 ΔE00 | 28.4 | 39.1 |
| 24색 전체 평균 ΔE00 | 35.1 | 35.9 |
| 면적 가중 평균 채도 | 32.3 | 27.5 |
| 심사 통과 (첫 시도) | — | 3 / 6 |

## 한계
- 팔레트(4색) 다양성은 화가가 고르는 색에 달려 있다. 그림 자체가 풍부해지는 것이 핵심 이득
- 정서 범위·대표도 기준은 demo 값
- 실제 Gemini/Claude 호출 결과는 배포 후 같은 6문장으로 다시 재야 한다
- DB 스키마 변경 없음 (palette jsonb 안에 basis.nearest, generation_logs.features 안에 image_tries)
