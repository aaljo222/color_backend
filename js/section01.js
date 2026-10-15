/* ============================================================
   section01.js — 히어로 배너 확대 모달, 색채 분석 입력 폼 제출(/api/analyze),
   분석 결과를 보여주는 지니 모달 렌더링
   * shared.js보다 먼저 로드되어도 되지만, 함수 호출은 DOM 삽입 이후에 일어납니다.
   ============================================================ */

/* -------------------- 1. 레퍼런스 원화 확대 모달 -------------------- */
const banner = document.getElementById('heroBanner');
const archModal = document.getElementById('archModal');
const modalCloseBtn = document.getElementById('modalCloseBtn');

if (banner) {
  banner.addEventListener('click', () => {
    playChime();
    archModal.classList.add('is-active');
  });
}

if (modalCloseBtn) {
  modalCloseBtn.addEventListener('click', () => {
    archModal.classList.remove('is-active');
  });
}

if (archModal) {
  archModal.addEventListener('click', (e) => {
    if (e.target === archModal) archModal.classList.remove('is-active');
  });
}

/* -------------------- 2. 분석 결과 지니 모달 열기/닫기 & 면적비 토글 -------------------- */
const modalBackdrop = document.getElementById("modalBackdrop");

function openDynamicModal() {
  playArchiveRevealSound();
  modalBackdrop.classList.remove("hidden");
}

function closeDynamicModal() {
  playArchiveCloseSound();
  modalBackdrop.classList.add("hidden");
}

if (modalBackdrop) {
  modalBackdrop.addEventListener("click", (e) => {
    if (e.target === modalBackdrop) closeDynamicModal();
  });
}

let showRatio = true;
function toggleRatio() {
  showRatio = !showRatio;
  playToggleSound(showRatio);

  const spectrum = document.getElementById('spectrumSection');
  const pills = document.querySelectorAll('.ratio-pill');

  if (showRatio) {
    spectrum.classList.remove('collapsed');
    pills.forEach(p => p.classList.remove('collapsed'));
  } else {
    spectrum.classList.add('collapsed');
    pills.forEach(p => p.classList.add('collapsed'));
  }
}

/* -------------------- 3. 입력 폼 인라인 알림 -------------------- */
const inlineTooltip = document.getElementById('formInlineTooltip');
const tooltipText = document.getElementById('tooltipText');

function showInlineNotice(message) {
  if (!inlineTooltip || !tooltipText) return;
  tooltipText.textContent = message;
  inlineTooltip.classList.add('is-active');
  inlineTooltip.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideInlineNotice() {
  if (!inlineTooltip) return;
  inlineTooltip.classList.remove('is-active');
}

const userMemoryEl = document.getElementById('userMemory');
const userEmailEl = document.getElementById('userEmail');
if (userMemoryEl) userMemoryEl.addEventListener('input', hideInlineNotice);
if (userEmailEl) userEmailEl.addEventListener('input', hideInlineNotice);

/* -------------------- 4. 백엔드 응답(/api/analyze) -> 지니 모달 렌더링 -------------------- */
function renderDynamicSpecimen(result) {
  const specimenHash = result.hash || result.specimen_code || "MaC-Archive";
  const summary = result.memory_summary || result.data?.memory_summary || "";
  const palette = result.palette || result.data?.palette || [];

  document.getElementById("specimenHash").textContent = specimenHash;
  document.getElementById("memorySummary").textContent = `"${summary}"`;

  document.getElementById("ratioLabel").textContent = palette.map(p => {
    const w = p.weight !== undefined ? p.weight : (p.area_ratio !== undefined ? p.area_ratio : 0.25);
    return `${Math.round(w * 100)}%`;
  }).join(" : ");

  document.getElementById("spectrumBar").innerHTML = palette.map(p => {
    const w = p.weight !== undefined ? p.weight : (p.area_ratio !== undefined ? p.area_ratio : 0.25);
    return `<div class="spectrum-segment" style="width: ${w * 100}%; background-color: ${p.hex};"></div>`;
  }).join("");

  document.getElementById("specimenList").innerHTML = palette.map(p => {
    const w = p.weight !== undefined ? p.weight : (p.area_ratio !== undefined ? p.area_ratio : 0.25);
    return `
      <div class="specimen-card">
        <div class="swatch" style="background-color: ${p.hex};"></div>
        <div class="specimen-info">
          <div class="info-top">
            <span class="color-name">${p.color_name || 'Color'}</span>
            <div>
              <span class="hex-code">${p.hex.toUpperCase()}</span>
              <span class="ratio-pill">${Math.round(w * 100)}%</span>
            </div>
          </div>
          <p class="reason-text">${p.reason || ''}</p>
        </div>
      </div>
    `;
  }).join("");

  openDynamicModal();
}

/* -------------------- 5. 폼 전송 이벤트 및 /api/analyze 호출 -------------------- */
const form = document.getElementById('colorArchForm');
const submitBtn = document.getElementById('submitBtn');

if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    getAudioContext();

    const memoryInputField = document.getElementById('userMemory');
    const emailInputField = document.getElementById('userEmail');
    const memoryInput = memoryInputField.value.trim();
    const emailInput = emailInputField.value.trim();

    if (memoryInput.length < 10) {
      showInlineNotice("장소, 시간, 계절, 행동, 기분 등의 그날의 뉘앙스가 느껴지는 기억을 채워주세요. 좀 더 구체적일수록 잘 보여드릴게요.");
      memoryInputField.focus();
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailInput || !emailRegex.test(emailInput)) {
      showInlineNotice("결과를 전송받으실 올바른 이메일 주소 형식을 입력해 주세요.");
      emailInputField.focus();
      return;
    }

    hideInlineNotice();
    submitBtn.disabled = true;
    submitBtn.textContent = 'Synthesizing...';

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory: memoryInput, email: emailInput })
      });

      const result = await response.json();

      if (!response.ok) {
        showInlineNotice(result.error || "색채 표본 추출에 실패했습니다. 문장을 조금 더 구체적으로 작성해 주세요.");
        return;
      }

      if (result.status === 'success' && result.palette && result.palette.length === 4) {
        renderDynamicSpecimen(result);
        form.reset();

        if (result.email_sent === false) {
          console.warn("[Resend Warning] 이메일 발송 로그:", result.email_error);
        }
      } else {
        showInlineNotice(result.error || '분석 결과 형식이 올바르지 않습니다. 다시 시도해 주세요.');
      }

    } catch (err) {
      showInlineNotice('서버와 통신할 수 없습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Synthesize Palette';
    }
  });
}
