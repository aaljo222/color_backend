-- MaC (Memory & Color) — Supabase 스키마 v1.0
-- 실행: Supabase SQL Editor 에 전체 붙여넣기. 원칙: 본인 행만(RLS), 원문·생년월일·연락처는 암호화 필드,
--       운영 로그는 서비스 키(서버)만. 서버는 service_role 로 접근하므로 RLS 는 '프론트 직접 접근' 방어선.

create extension if not exists vector;

-- 1) 프로필 + 크레딧 ------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text, name text, role text default 'user',
  credits int not null default 0 check (credits >= 0),
  free_credit_claimed boolean not null default false,
  updated_at timestamptz default now()
);

-- 1-1) 가입 시 프로필 자동 생성 (이메일·Google·카카오 모두) -----------------
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'name', new.raw_user_meta_data->>'full_name'))
  on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- 2) 표본 (팔레트·특징·검증 결과. 원문 없음) ----------------------------------
create table if not exists public.memory_specimens (
  id uuid primary key,
  user_id uuid references public.profiles(id) on delete cascade,
  specimen_hash text not null, cache_key text not null,
  palette jsonb not null, memory_summary text,
  kb_version text not null, engine_version text not null,
  verification jsonb, image_path text, thumb_path text,
  created_at timestamptz default now()
);
create index if not exists idx_specimens_user on public.memory_specimens(user_id, created_at desc);
create index if not exists idx_specimens_cache on public.memory_specimens(cache_key);

-- 3) 원문 (보관 동의 시만, AES-GCM 암호문) -----------------------------------
create table if not exists public.memory_texts (
  specimen_id uuid primary key references public.memory_specimens(id) on delete cascade,
  user_id uuid references public.profiles(id) on delete cascade,
  text_enc text not null, keep_consent boolean not null default true,
  created_at timestamptz default now()
);

-- 4) 운영 로그 (운영진 전용 — 사용자 정책 없음 = 접근 불가) ---------------------
create table if not exists public.generation_logs (
  id bigserial primary key,
  specimen_id uuid references public.memory_specimens(id) on delete cascade,
  features jsonb, verify_rows jsonb, masked_text_len int, kb_version text,
  created_at timestamptz default now()
);

-- 5) 컨시어지 / 6) Astral ---------------------------------------------------
create table if not exists public.concierge_requests (
  id uuid primary key, user_id uuid references public.profiles(id) on delete set null,
  client_name text, contact text, contact_enc text, request_type text, message text,
  status text default 'new', created_at timestamptz default now()
);
create table if not exists public.astral_results (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade,
  birth_date_enc text, guardian_colors jsonb, analysis_data jsonb,
  created_at timestamptz default now()
);

-- 7) Color KB (RAG) — 임베딩 768차원 (EMBED_DIM 과 일치) ------------------------
create table if not exists public.color_kb (
  id text primary key, axis text not null, name text, keywords text[], description text,
  lch real[], accent_lch real[], modifiers jsonb, source text, status text, kb_version text,
  embedding vector(768)
);
create or replace function public.match_color_kb(query_embedding vector(768), match_axis text, match_count int default 5)
returns table(id text, similarity float) language sql stable as $$
  select k.id, 1 - (k.embedding <=> query_embedding) as similarity
  from public.color_kb k where k.axis = match_axis and k.embedding is not null
  order by k.embedding <=> query_embedding limit match_count;
$$;

-- 8) 크레딧 RPC (원자적) -----------------------------------------------------
create or replace function public.consume_credit(p_user uuid) returns int language sql as $$
  update public.profiles set credits = credits - 1, updated_at = now()
  where id = p_user and credits > 0 returning credits;
$$;
create or replace function public.claim_free_credits(p_user uuid, p_amount int) returns int language sql as $$
  update public.profiles set credits = credits + p_amount, free_credit_claimed = true, updated_at = now()
  where id = p_user and free_credit_claimed = false returning credits;
$$;
revoke execute on function public.consume_credit(uuid) from anon, authenticated;
revoke execute on function public.claim_free_credits(uuid, int) from anon, authenticated;

-- 9) RLS ------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.memory_specimens enable row level security;
alter table public.memory_texts enable row level security;
alter table public.generation_logs enable row level security;
alter table public.concierge_requests enable row level security;
alter table public.astral_results enable row level security;
alter table public.color_kb enable row level security;

drop policy if exists "profiles: 본인 조회" on public.profiles;
create policy "profiles: 본인 조회" on public.profiles for select using (auth.uid() = id);
drop policy if exists "specimens: 본인 조회" on public.memory_specimens;
create policy "specimens: 본인 조회" on public.memory_specimens for select using (auth.uid() = user_id);
drop policy if exists "texts: 본인 조회" on public.memory_texts;
create policy "texts: 본인 조회" on public.memory_texts for select using (auth.uid() = user_id);
drop policy if exists "astral: 본인 조회" on public.astral_results;
create policy "astral: 본인 조회" on public.astral_results for select using (auth.uid() = user_id);
-- generation_logs · concierge_requests · color_kb : 사용자 정책 없음 → 프론트 직접 접근 불가 (서버만)

-- 10) Storage: 'specimens' 비공개 버킷 (대시보드 Storage → New bucket → Public 끔) ----
-- insert into storage.buckets (id, name, public) values ('specimens', 'specimens', false) on conflict do nothing;

-- 11) Color Oracle — 문장 → 팔레트 메타데이터 (routers/oracle_router.py · oracle/store.py) ----------
--     서버(service_role)만 접근. 사용자 정책 없음 = 프론트 직접 접근 불가.
create table if not exists public.color_prompts (
  key        text primary key,              -- 정규화한 문장
  prompt     text not null,                 -- 처음 입력한 원문
  result     jsonb not null,                -- 팔레트·등급·HEX·OKLCH·LCH·출처
  source     text,                          -- rule | lexicon | llm
  hits       integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists color_prompts_updated on public.color_prompts (updated_at desc);
create table if not exists public.color_lexicon (
  concept    text primary key,
  hue        text not null,
  lightness  smallint not null check (lightness between 1 and 9),
  chroma     smallint not null check (chroma between 0 and 5),
  source     text not null default 'llm',   -- seed | llm | manual
  created_at timestamptz not null default now()
);
alter table public.color_prompts enable row level security;
alter table public.color_lexicon enable row level security;

-- 11-1) 색 문장 '비슷한 문장 추천' (oracle/similar.py) — 임베딩을 쓸 때만 필요 -----------
--       같은 문장 = key(정규화 문장)로 찾고, 비슷한 문장 = 임베딩으로 후보만 보여 준다.
--       차원 1024 = SIMILAR_DIM (Voyage voyage-4 기본값). 제공자를 바꿔도 1024로 받는다.
--       embedding_model 이 다른 벡터끼리는 비교하지 않는다 (모델을 바꾸면 좌표가 전부 바뀐다).
alter table public.color_prompts add column if not exists embedding vector(1024);
alter table public.color_prompts add column if not exists embedding_model text;
create index if not exists color_prompts_embedding on public.color_prompts
  using hnsw (embedding vector_cosine_ops);
drop function if exists public.match_color_prompts(vector, int, float);
create or replace function public.match_color_prompts(query_embedding vector(1024), match_count int default 3,
                                                      min_similarity float default 0.8, model text default null)
returns table (key text, prompt text, source text, result jsonb, similarity float)
language sql stable as $$
  select p.key, p.prompt, p.source, p.result, 1 - (p.embedding <=> query_embedding) as similarity
  from public.color_prompts p
  where p.embedding is not null and coalesce(p.source, '') <> 'rule'
    and (model is null or p.embedding_model = model)
    and 1 - (p.embedding <=> query_embedding) >= min_similarity
  order by p.embedding <=> query_embedding
  limit match_count;
$$;
