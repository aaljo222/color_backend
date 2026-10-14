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
| F5 RAG 아님 | `core/kb.py` Resolver + 검색기 3종(ngram / embedding / supabase pgvector) · **eng-2.2 코퍼스 RAG** `core/corpus.py`·`core/rag.py` (`data/corpus/`) |
| F6 재현성 | `cache_key = hash(KB id 조합, KB 버전, 엔진 버전)` |
| F7 자기보고 confidence | `basis`(해석 경로·점수) + `verification`(측정 ΔE00)으로 대체 |

## 빠른 시작 (키 없이)

```bash
pip install -r requirements-dev.txt
cp .env.example .env            # 값은 비워 둬도 됨 → stub LLM + ngram 검색 + 메모리 저장소
uvicorn main:app --reload --port 8000
python -m pytest -q             # 20개 테스트 (MaC 14 + Color Oracle 6)
python scripts/eval_tau.py      # 골드셋으로 검색 임계값 τ 평가
python scripts/eval_rag.py --sweep   # 코퍼스 RAG: KB만 vs 코퍼스 정답률, τc 정하기 (eng-2.2)
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
| POST | `/api/chat/ask` | 선택(정책 미확정) | 색채 챗봇 작업 생성 (`{"text":"..."}`) |
| GET | `/api/chat/result/{job_id}` | - | 색채 챗봇 작업 상태·결과 조회 |
| POST | `/auth/signup` · `/auth/login` · GET/PATCH/DELETE `/auth/me` | - / 필수 | elecai 패턴 인증 라우터 |
| GET | `/health` | - | KB 버전·검색기·τ·LLM 모드·저장소 |
| GET · POST | `/api/oracle` | - | Color Oracle 결정론 변환 (hex2oklch·oklch2hex·hex2lch·lch2hex·scale·step·selfcheck·tools) |
| POST | `/api/palette` | 선택 | 문장 → 팔레트 (캐시 → 규칙 → 어휘사전 → 새 장면만 Claude 등급 1회). 게스트는 새 장면 LLM 하루 `ORACLE_LLM_DAILY`회 |
| GET | `/api/palette/gallery` · `/api/palette/thumb` | - | 저장된 문장 썸네일 |

색채 챗봇은 `data/chat_kb.json`을 첫 검색 시 읽습니다. 작업은 프로세스 내 메모리에서 최대 500개, 생성 후 30분까지 보관하며, 여러 worker 프로세스에서는 job 조회가 공유되지 않습니다. 현재 원본 응답을 유지하므로 중간 상태는 `queued`/`running`이고 결과에는 입력 `text`가 포함됩니다. `ChatData`에도 `note`와 citation의 `paper`/`text`가 추가로 들어갈 수 있습니다. 임시 인증은 선택적 Supabase JWT이며 정책은 미확정입니다. 논문 검색 임계값은 `TAU`(기본값 0.12), 웹 검색 기본 제공자는 Google 검색 결과를 전달하는 SerpAPI입니다. `CHAT_WEB=serpapi`와 `SERPAPI_API_KEY`를 설정하며, 키 누락이나 API 실패 시 경고 로그를 남기고 웹 인용 없이 `source=none`으로 처리합니다. 일시적으로 기존 위키백과 검색을 유지하려면 `CHAT_WEB=wikipedia`, 웹 검색을 끄려면 `CHAT_WEB=off`로 설정합니다. 웹 citation에는 하위 호환 필드와 함께 `url`, `kind="web"`가 추가됩니다.

### 챗봇 검색 평가 및 strict 모드

`CHAT_RETRIEVAL`은 기본 `strict`입니다. Strict는 기존 TF-IDF 검색 결과에 상대 점수·동일 논문 제한, 인용 위치의 원문 keyword 대조, 2차 자료 기사 후순위 처리를 적용합니다. 의미 검색을 함께 사용하려면 Gemini 또는 OpenAI 임베딩 키를 설정하고 `python scripts/build_chat_embeddings.py`로 `data/chat_kb_embeddings.json`을 만든 뒤 `CHAT_RETRIEVAL=hybrid`를 설정합니다. 빌드 스크립트는 먼저 `data/papers/`의 PDF/TXT/이미지를 추출하고, 페이지·절 위치가 포함된 문서 청크와 검수 KB 카드 벡터를 한 인덱스에 생성합니다. Hybrid는 strict가 citation을 찾지 못한 질문에만 임베딩 검색으로 보완하고, 검수 KB 후보에는 기존 원문 근거 검증과 기사 후순위도 적용합니다. 추출 원문 후보는 `CHAT_OCR_TAU`(기본 0.72) 이상에서만 인용되며 출처 파일·페이지/절을 표시합니다. 카드 의미 점수 기준은 `CHAT_EMBEDDING_TAU`(기본 0.70; 평가셋에서 가장 높은 범위 밖 의미점수 0.666과 정답 보완 후보 0.726 사이에서 보수적으로 설정)이며 제공자/데이터가 바뀌면 재평가해야 합니다. 인덱스가 없거나 낡았거나 질의 임베딩이 실패하면 경고 로그를 남기고 strict TF-IDF 결과로 계속 동작합니다. 기존 키워드 검색을 임시 복귀하려면 `CHAT_RETRIEVAL=legacy`를 지정하세요. 응답 계약과 외부 검색 경로는 바뀌지 않습니다. PDF OCR에는 PyMuPDF와 시스템 Tesseract의 `kor`·`eng` 언어 데이터가 필요합니다.

`TAU` 기본값은 `0.12`입니다. 평가셋에서 지식베이스 밖 질문의 최고점은 `0.093`, 정답 카드 점수의 최저는 `0.058`이어서 양쪽을 완전히 분리하는 단일 임계값은 없습니다. Strict는 밖 질문 누출을 억제하면서 이 기존 임계값을 유지합니다.

오프라인 평가(웹 요청 없음):

```powershell
python scripts/eval_chat.py --mode legacy --output data/eval/baseline_current_legacy.md
python scripts/eval_chat.py --mode strict --stage secondary --output data/eval/strict.md
python scripts/eval_chat.py --mode hybrid --output data/eval/hybrid.md
python -m pytest -q
```

카드를 추가하거나 수정할 때는 `python scripts/verify_kb.py`와 두 모드 평가를 다시 실행하고, A 적중률·B 거절률·C 오답 근거 채택률·정밀도가 기준 보고서보다 악화되지 않았는지 확인한 뒤 변경을 승인하세요. `tests/test_chat_retrieval.py`는 평가셋에서 고정한 적중·거절·혼동 문항을 회귀 검사합니다.

### 챗봇 논문 원문 추출·검수

`data/papers/`의 PDF·TXT 원문에서 위치를 보존한 텍스트를 생성하고 기존 카드와 대조하려면 개발 환경에서 실행합니다.

```powershell
python -m pip install -r requirements-dev.txt
python scripts/extract_papers.py
python scripts/verify_kb.py
```

추출 결과는 `data/papers_text/<원본 파일명>.json`에 저장합니다. 입력 파일 해시가 같으면 건너뛰며, 다시 추출할 때는 `--force`를 사용합니다. PDF는 페이지별 텍스트와 인쇄 쪽 번호를 저장합니다. 텍스트가 거의 없는 PDF 쪽만 OCR하며 이 경우 Tesseract와 `kor`, `eng` 언어 데이터가 필요합니다. TXT는 UTF-8(BOM 포함)을 먼저 시도하고 실패하면 CP949를 사용합니다. 쪽 구분이 없으면 문단 경계 기준 약 1,500자 절로 분할합니다. 선택적인 TXT 서지 메타데이터는 `data/papers/<파일명>.meta.json`의 `paper`, `cite_prefix` 값으로 둡니다.

`data/kb_audit.md`는 사람이 원문과 대조한 기존 카드 감사 보고서입니다. `scripts/verify_kb.py`는 구조·ID·길이·인용 범위와 문자열 힌트만 검사하고 의미를 판정하지 않습니다. `scripts/prepare_kb_draft.py`는 추출 JSON의 특정 위치와 원문 발췌를 지정해 `data/kb_pending.json`에 검토 초안을 추가합니다. 초안 절차는 `chat_kb.json`을 수정하지 않으며, 병합은 검토·승인 후 별도로 진행해야 합니다.

TXT 초안은 예를 들어 `--source a.txt.json --cite "Neuroscience News, 2013, 본문 §2"`처럼 절 번호를 포함해야 합니다. PDF는 `--cite "저자, 연도, pp.123–124"` 형식을 사용합니다. 두 경우 모두 `--evidence`에는 해당 위치의 발췌를 지정하며, 이 발췌는 검수 메모로 pending 카드에 보존됩니다.

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
data/chat_kb.json       색채 챗봇 논문 지식베이스
data/goldset.jsonl      τ 평가용 골드셋 (팀이 계속 추가)
data/corpus/            코퍼스 (eng-2.2): scenes.jsonl 장면 문단→KB 항목 · objects.jsonl 사물 등급 · research.jsonl 연구 근거
data/goldset_rag.jsonl  코퍼스 RAG 평가용 추가 골드셋 (작성자 편향 있음 — 사용자 문장으로 교체할 것)
core/corpus.py · rag.py 코퍼스 로드·검증 / 검색(ngram·임베딩)·근거 묶음(grounding)
sql/schema.sql          테이블·RLS·pgvector·크레딧 RPC
scripts/                eval·임베딩 작업 / 논문 원문 extract_papers.py · verify_kb.py · prepare_kb_draft.py
examples/frontend_fetch.js  MaC.html 에서 호출하는 예
```

## 팀이 채워야 할 것 (데모와 실서비스의 차이)

- **코퍼스 초안 검토 (eng-2.2)** — `data/corpus/scenes.jsonl`·`objects.jsonl` 은 `status: draft`(작성: 개발 초안). 코퍼스 팀원이 문단과 등급을 보고 `confirmed` 로 바꾼다. 문단을 고치면 코퍼스 버전이 자동으로 바뀌고, 그 뒤 새로 고정되는 문장부터 반영된다. `research.jsonl` 은 출처를 확인한 연구만 `confirmed` 로 넣는다(검증 게이트가 url 없는 문단을 막는다).

- **Color KB 수치** — `data/color_kb.json` 의 `lch`·계수는 구조 시연용 예시값이다. 코퍼스 팀원이 근거 자료(`source`)와 함께 확정하고 `status: confirmed` 로 바꾼다. 기존 기준표는 `python scripts/migrate_association.py prompts/color_association.py` 로 골격을 뽑을 수 있다.
- **τ·ΔE 기준** — 골드셋(`data/goldset.jsonl`)과 사용자 5명 테스트로 정한다. 현재 ngram 기본 τ=0.25 는 데모 골드셋에서 오연결 0 이 되는 최저값.
  ngram 정답률은 22% 수준이라(동의어를 못 잡음) 실서비스는 임베딩 검색이 필요하다.
- **유료 이미지 생성기** — `core/pipeline.py` 의 `ImageGenerator(palette, cache_key, feedback) -> PIL.Image` 를 구현해 `analyze(..., generator=)` 로 넘기면 검증 루프가 자동으로 붙는다. 실패가 이어지면 코드 그림으로 대체된다.
- **이름 마스킹** — `core/pii.py` 2단계는 휴리스틱(조사 앞 2~3음절 + 예외 목록)이다. 정확도가 필요하면 형태소 분석기 고유명사로 교체.
- **게스트 한도 카운터** — 지금은 프로세스 메모리. 인스턴스가 여러 개면 DB/Redis 로 옮긴다.
- **개인정보** — 기억 문장·이메일이 Anthropic(Claude)·Resend(해외 사업자)로 전달된다. 수집·이용 동의와 처리 위탁·국외 이전 고지 필요 여부를 오픈 전에 점검.
