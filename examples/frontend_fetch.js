// examples/frontend_fetch.js — MaC.html(Vanilla JS)에서 호출 예시
// 로그인은 프론트에서 Supabase(anon key)로 하고, access_token 만 백엔드로 보낸다. service_role 키는 절대 프론트에 두지 않는다.
const API = "https://api.mac.ai.kr";   // 배포 주소로 교체

async function analyzeMemory(memory, email, session /* supabase.auth.getSession() 결과 */) {
  const headers = { "Content-Type": "application/json" };
  if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
  const r = await fetch(`${API}/api/analyze`, {
    method: "POST", headers,
    body: JSON.stringify({ memory, email: email || null, keep_text: false, include_image: true }),
  });
  if (r.status === 429) throw new Error("오늘 체험 횟수를 다 썼어요. 로그인하면 더 만들 수 있어요.");
  if (r.status === 402) throw new Error("크레딧이 부족해요.");
  if (!r.ok) throw new Error((await r.json()).detail || "색채 표본 추출 실패");
  const d = await r.json();
  // d.palette[i] = { role, hex, area_ratio, color_name, lch, basis:{axis,kb_id,how,score,phrase} }
  // d.verification = { status, max_de00, ... }   d.image_png_base64 → <img src="data:image/png;base64,...">
  return d;
}
