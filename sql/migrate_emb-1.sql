-- 13) 검색 임베딩 테이블 (core/vector_store.py · emb-1, 2026-10-15) -----------------------------------------
--     KB 21항목·코퍼스 장면 문단의 임베딩. 서버가 지금 모델(oracle/similar.py)로 없으면 만들어 넣는다 → 레포 JSON 재생성 불필요.
--     행 키 = (kind, item_id, embedding_model). 모델이 다른 벡터끼리는 비교하지 않는다.
--     차원 1024 = SIMILAR_DIM (color_prompts.embedding 과 같다). 서버(service_role)만 접근 — 사용자 정책 없음.
create extension if not exists vector;
create table if not exists public.mac_embeddings (
  kind            text not null,               -- kb | corpus
  item_id         text not null,               -- KB 항목 id · 코퍼스 장면 문단 id
  embedding_model text not null,               -- 예: voyage:voyage-4:1024 · gemini:gemini-embedding-001:1024
  content_hash    text not null,               -- 임베딩한 문장의 sha256 앞 16자 (문장이 바뀌면 그 항목만 다시)
  embedding       vector(1024) not null,
  updated_at      timestamptz not null default now(),
  primary key (kind, item_id, embedding_model)
);
alter table public.mac_embeddings enable row level security;
