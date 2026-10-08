# MaC API — 기억의 색을, 매번 같은 색으로

MaC(Memory & Color) 백엔드 레퍼런스 구현. 멘토링 기술백서 v1.0의 대응방안을 코드로 옮겼다.
보안 계층(CORS·rate limit·UA 차단·Cloudflare 가드·Supabase JWT)은 운영 중인 elecai backend 패턴을 따른다.

```
기억 문장 → ①PII 마스킹 → ②특징 추출(LLM, 색 없음) → ③Color KB 해석(키워드→라벨→검색≥τ→기본톤)
         → ④결정론 LCh 합성(역할·면적비 고정) → ⑤그림 → ⑥K-Means·ΔE00 검증 → SPECIMEN
```

| 백서 진단 | 코드 |
|---|---|
| F1 HEX를 LLM이 생성 | `core/llm.py`는 특징만 추출(`Features`, Claude 강제 도구 호출), 색은 `core/synth.py`가 계산 |
| F2 기준표에 숫자 없음 | `data/color_kb.json` 항목마다 `lch`·`accent_lch`·`modifiers` |
| F3 합성식 | `core/synth.py` 보정식(명도 대비·채도 배율·색상각 조화·색역 클리핑) |
| F4 스키마 2개 | 단일 응답 스키마(아래). 면적비는 상수 |
| F5 RAG 아님 | `core/kb.py` Resolver + 검색기 3종(ngram / embedding / supabase pgvector) |
| F6 재현성 | `cache_key = hash(KB id 조합, KB 버전, 엔진 버전)` |
| F7 자기보고 confidence | `basis`(해석 경로·점수) + `verification`(측정 ΔE00)으로 대체 |

## 빠른 시작 (키 없이)

```bash
pip install -r requirements-dev.txt
cp .env.example .env            # 값은 비워 둬도 됨 → stub LLM + ngram 검색 + 메모리 저장소
uvicorn main:app --reload --port 8000
python -m pytest -q             # 20개 테스트 (MaC 14 + Color Oracle 6)
python scripts/eval_tau.py      # 골드셋으로 검색 임계값 τ 평가
```

> UA 차단이 켜져 있어 `curl` 기본 User-Agent 는 403 이다. 개발 중엔 `-H 'User-Agent: Mozilla/5.0 dev'` 를 붙이거나 `UA_BLOCK=0`.

## 실서비스 모드

1. **Claude**: `ANTHROPIC_API_KEY` 설정 → 특징 추출이 강제 도구 호출(`report_features`, 축별 라벨 enum)·`temperature=0` 으로 동작. 모델은 `CLAUDE_MODEL`.
2. **Supabase**: SQL Editor 에 `sql/schema.sql` 실행, Storage 에 비공개 버킷 `specimens` 생성, `.env` 에 URL·키 입력.
3. **임베딩 RAG (선택)**: Claude API에는 임베딩이 없어 `GEMINI_API_KEY`(+ `pip install google-genai`)가 따로 필요. `python scripts/build_kb_embeddings.py` → `RETRIEVER=embedding`
   (pgvector 사용 시 `--supabase` 후 `RETRIEVER=supabase`). **그다음 `scripts/eval_tau.py --retriever embedding` 으로 τ를 다시 정한다.**
4. **암호화**: `MEMORY_ENC_KEY` 생성(아래) — 원문 보관(`keep_text`)과 컨시어지 연락처에 사용.
   `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
5. **배포(Railway, Docker 불필요)**: `railway.json` 포함. Variables 에 `.env` 키 입력 후 `railway up`. `APP_ENV=prod`.
   현재 프론트는 Vercel 그대로 두고 API 만 분리하는 구성을 권장한다(scikit-learn·scipy 가 서버리스 용량 제한에 걸리기 쉬움).

## API

| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| POST | `/api/analyze` | 선택 | 기억 → SPECIMEN. 게스트=IP당 하루 2회·저장 안 함 / 로그인=크레딧 1, 보관함 저장 |
| GET | `/api/specimens` · `/api/specimens/{id}` | 필수 | 내 표본(본인 것만), 이미지는 만료되는 signed URL |
| GET · POST | `/api/me/credits` · `/api/me/credits/claim` | 필수 | 무료 크레딧은 **소셜 로그인·휴대폰 인증 계정만** 1회 지급 (Q1) |
| POST | `/api/concierge` | 선택 | 컨시어지 문의 (시간당 5회, 연락처 암호화) |
| POST | `/auth/signup` · `/auth/login` · GET/PATCH/DELETE `/auth/me` | - / 필수 | elecai 패턴 인증 라우터 |
| GET | `/health` | - | KB 버전·검색기·τ·LLM 모드·저장소 |
| GET · POST | `/api/oracle` | - | Color Oracle 결정론 변환 (hex2oklch·oklch2hex·hex2lch·lch2hex·scale·step·selfcheck·tools) |
| POST | `/api/palette` | 선택 | 문장 → 팔레트 (캐시 → 규칙 → 어휘사전 → 새 장면만 Claude 등급 1회). 게스트는 새 장면 LLM 하루 `ORACLE_LLM_DAILY`회 |
| GET | `/api/palette/gallery` · `/api/palette/thumb` | - | 저장된 문장 썸네일 |

응답 예 (`/api/analyze`):
```json
{
  "specimen_hash": "MaC-a858432c9fb9", "cache_key": "a858432c9fb9…", "kb_version": "kb-0.1-demo", "engine_version": "eng-1.0",
  "memory_summary": "…",
  "palette": [{"role": "dominant", "hex": "#9791AC", "area_ratio": 0.45, "color_name": "Dusk Lavender",
               "lch": [61.6, 15.4, 300.0], "basis": {"axis": "emotion", "kb_id": "longing_melancholy", "how": "keyword", "score": 1.0, "phrase": "그리움"}}, "…"],
  "verification": {"status": "PASS", "max_de00": 0.27, "max_ratio_err": 0.006, "attempts": 1, "renderer": "code"},
  "pii_masked": {"전화": 1, "이름": 1}, "cache_hit": false, "image_png_base64": "…", "email_sent": false
}
```

## 폴더

```
main.py                 보안 미들웨어 + 라우터 등록
oracle/ color_oracle.py  OKLCH·LCH·HEX 변환·색역 매핑·자가 검산 / color_abstraction.py 규칙·등급표·썸네일
        palette.py 문장→팔레트 / store.py 문장·낱말 메타데이터 / tools.py 디스패처
core/  color.py         sRGB↔Lab↔LCh, CIEDE2000, 색역 클리핑
       kb.py            Color KB 로드, Resolver(키워드→라벨→검색≥τ→기본톤), 검색기 3종
       llm.py           Gemini 특징 추출(구조화 출력) / stub / 임베딩
       pii.py           LLM 전송 전 마스킹 (서버 안에서)
       synth.py         결정론 LCh 합성 + cache_key
       render.py        무료 '코드 그림' (결정론, ΔE00≈0)
       verify.py        K-Means(Lab) + 헝가리안 매칭 + ΔE00 판정 + 수정 지시문
       pipeline.py      전체 흐름 + 생성→평가→재생성 루프(유료 이미지 생성기 자리)
       store.py         Supabase / 메모리 저장소, 크레딧, 게스트 한도
prompts/feature_prompt.py   색을 묻지 않는 특징 추출 프롬프트
data/color_kb.json      데모 KB (수치는 예시값 · status=demo)
data/goldset.jsonl      τ 평가용 골드셋 (팀이 계속 추가)
sql/schema.sql          테이블·RLS·pgvector·크레딧 RPC
scripts/                eval_tau.py · build_kb_embeddings.py · migrate_association.py
examples/frontend_fetch.js  MaC.html 에서 호출하는 예
```

## 팀이 채워야 할 것 (데모와 실서비스의 차이)

- **Color KB 수치** — `data/color_kb.json` 의 `lch`·계수는 구조 시연용 예시값이다. 코퍼스 팀원이 근거 자료(`source`)와 함께 확정하고 `status: confirmed` 로 바꾼다. 기존 기준표는 `python scripts/migrate_association.py prompts/color_association.py` 로 골격을 뽑을 수 있다.
- **τ·ΔE 기준** — 골드셋(`data/goldset.jsonl`)과 사용자 5명 테스트로 정한다. 현재 ngram 기본 τ=0.25 는 데모 골드셋에서 오연결 0 이 되는 최저값.
  ngram 정답률은 22% 수준이라(동의어를 못 잡음) 실서비스는 임베딩 검색이 필요하다.
- **유료 이미지 생성기** — `core/pipeline.py` 의 `ImageGenerator(palette, cache_key, feedback) -> PIL.Image` 를 구현해 `analyze(..., generator=)` 로 넘기면 검증 루프가 자동으로 붙는다. 실패가 이어지면 코드 그림으로 대체된다.
- **이름 마스킹** — `core/pii.py` 2단계는 휴리스틱(조사 앞 2~3음절 + 예외 목록)이다. 정확도가 필요하면 형태소 분석기 고유명사로 교체.
- **게스트 한도 카운터** — 지금은 프로세스 메모리. 인스턴스가 여러 개면 DB/Redis 로 옮긴다.
- **개인정보** — 기억 문장·이메일이 Anthropic(Claude)·Resend(해외 사업자)로 전달된다. 수집·이용 동의와 처리 위탁·국외 이전 고지 필요 여부를 오픈 전에 점검.
