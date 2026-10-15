# emb-1 · 검색 임베딩을 Supabase 테이블에 (2026-10-15)

## 문제 (운영 확인)
- KB·코퍼스 검색 벡터가 레포 JSON 에만 있었다. `corpus_embeddings.json` 은 Gemini 로 만들어졌는데 서버에 `VOYAGE_API_KEY` 가 있으면
  질의는 Voyage → 모델 불일치 안전장치가 임베딩을 끄고 **ngram 으로 내려갔다** (VOYAGE 키를 넣고 실행해 로그로 재현).
- `color_prompts.embedding` 에 gemini 4행 · voyage 1행 · NULL 1행이 섞여, 서버 모델에 따라 '비슷한 문장'이 반쪽만 검색됐다.

## 바뀐 것
- `core/vector_store.py` (신규): 테이블 `mac_embeddings` 에 (kind, item_id, embedding_model) 별로 벡터 저장.
  지금 서버 모델(oracle/similar.py 하나로 결정)의 벡터가 없거나 문장이 바뀐 항목(content_hash)만 그 자리에서 임베딩해 저장한다.
  Supabase 가 없으면 프로세스 메모리. 실패하면 None → 예전처럼 파일 → ngram (서비스는 멈추지 않는다).
- `core/rag.py`: 코퍼스 검색 = ① 테이블 → ② 레포 파일(모델·버전 같을 때) → ③ ngram. 기본 auto 라 **배포하면 바로 켜진다.**
- `core/kb.py`: `RETRIEVER=embedding` = ① 테이블(`StoreRetriever`) → ② `kb_embeddings.json` → ③ ngram. 기본값은 그대로 ngram.
- `sql/migrate_emb-1.sql` (+ schema.sql 13절): 테이블 정의.
- `scripts/sync_embeddings.py`: 미리 채우기·상태 확인 (`--status`). color_prompts 도 지금 모델로 다시 채운다.
- main.py 는 바꾸지 않았다.

## 적용 순서
1. Supabase SQL Editor 에서 `sql/migrate_emb-1.sql` 실행
2. Railway·로컬 .env 의 임베딩 제공자를 같게: `EMBED_PROVIDER=voyage` (+ `VOYAGE_API_KEY`) 또는 `gemini`
3. 배포 → 첫 요청 때 KB 21 + 코퍼스 203 문장을 한 번 임베딩해 저장 (이후 0회)
4. (선택) KB 검색도 임베딩으로: `RETRIEVER=embedding` — τ(0.60)는 아직 실측 전이라 `scripts/eval_tau.py --retriever embedding` 으로 정한 뒤 켤 것

## 테스트
- `tests/test_vector_store.py` 6개 추가 (한 번만 임베딩·모델 변경 분리·문장 변경 그 항목만·키 없음/끔/장애 → None·KB 검색기·Supabase 왕복)
- 전체 209 통과 (stub). 실제 Supabase·Voyage·Gemini 호출은 이 환경에 키가 없어 돌리지 못함 → 배포 후 `python scripts/sync_embeddings.py --status` 로 확인
