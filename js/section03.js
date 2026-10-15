/* ============================================================
   section03.js — Color Concierge 문의 폼: 유효성 검사,
   실제 메일 발송 API 호출, 상태 안내 바 처리
   ============================================================ */

const selectElem = document.getElementById('inquirySubject');
const updateOptionsByDevice = () => {
  if (!selectElem) return;
  const isSmallScreen = window.innerWidth <= 768;
  Array.from(selectElem.options).forEach(opt => {
    if (opt.dataset && (opt.dataset.short || opt.dataset.full)) {
      opt.text = isSmallScreen ? (opt.dataset.short || opt.text) : (opt.dataset.full || opt.text);
    }
  });
};
updateOptionsByDevice();
window.addEventListener('resize', updateOptionsByDevice);

const conciergeForm = document.getElementById('conciergeForm');
const conciergeSubmitBtn = document.getElementById('conciergeSubmitBtn');
const btnNotifyBar = document.getElementById('btnNotifyBar');
const btnNotifyText = document.getElementById('btnNotifyText');

let tooltipTimer = null;
let notifyBarTimer = null;

function resetFormUIFeedback() {
  document.querySelectorAll('.field-tooltip-bubble').forEach(t => t.classList.remove('is-visible'));
  document.querySelectorAll('.field-input, .field-select, .field-textarea').forEach(i => i.classList.remove('field-invalid'));
}

function hideButtonNotification() {
  if (!btnNotifyBar) return;
  btnNotifyBar.classList.remove('is-active', 'status-connecting', 'status-failed');
}

function showButtonNotification(message, status = 'connecting') {
  if (!btnNotifyBar || !btnNotifyText) return;
  if (notifyBarTimer) clearTimeout(notifyBarTimer);

  btnNotifyBar.className = 'btn-notify-bar is-active';
  btnNotifyBar.classList.add(status === 'failed' ? 'status-failed' : 'status-connecting');
  btnNotifyText.textContent = message;
}

if (conciergeForm) {
  const formInputs = conciergeForm.querySelectorAll('.field-input, .field-select, .field-textarea');
  formInputs.forEach(input => {
    input.addEventListener('input', resetFormUIFeedback);
    input.addEventListener('change', resetFormUIFeedback);
  });

  conciergeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    resetFormUIFeedback();

    if (conciergeSubmitBtn && conciergeSubmitBtn.disabled) return;

    const nameElem = document.getElementById('clientName');
    const contactElem = document.getElementById('clientContact');
    const subjectElem = document.getElementById('inquirySubject');
    const messageElem = document.getElementById('clientMessage');

    const name = nameElem ? nameElem.value.trim() : '';
    const contact = contactElem ? contactElem.value.trim() : '';
    const subjectVal = subjectElem ? subjectElem.value : '';
    const message = messageElem ? messageElem.value.trim() : '';

    let firstEmptyField = null;
    let targetTooltip = null;

    if (!name && nameElem) {
      firstEmptyField = nameElem;
      targetTooltip = document.getElementById('nameTooltip');
    } else if (!contact && contactElem) {
      firstEmptyField = contactElem;
      targetTooltip = document.getElementById('contactTooltip');
    } else if (!subjectVal && subjectElem) {
      firstEmptyField = subjectElem;
      targetTooltip = document.getElementById('subjectTooltip');
    } else if (!message && messageElem) {
      firstEmptyField = messageElem;
      targetTooltip = document.getElementById('messageTooltip');
    }

    if (firstEmptyField && targetTooltip) {
      playWarningChime();
      firstEmptyField.classList.add('field-invalid');
      targetTooltip.classList.add('is-visible');
      firstEmptyField.focus();
      hideButtonNotification();

      if (tooltipTimer) clearTimeout(tooltipTimer);
      tooltipTimer = setTimeout(() => {
        targetTooltip.classList.remove('is-visible');
      }, 3200);
      return;
    }

    playWarningChime();
    if (conciergeSubmitBtn) {
      conciergeSubmitBtn.disabled = true;
      conciergeSubmitBtn.textContent = 'CONNECTING DESK...';
    }

    showButtonNotification('MaC 컨시어지 데스크로 전송 중입니다...', 'connecting');

    const payload = {
      client_name: name,
      client_contact: contact,
      subject: subjectVal,
      message: message
    };

    const startTime = Date.now();
    let isSuccess = false;

    try {
      // 실제 메일 발송 백엔드: /api/contact (concierge@mac.ai.kr 로 발송)
      const response = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const result = await response.json();
      if (response.ok && result.status === 'success') {
        isSuccess = true;
      }
    } catch (err) {
      isSuccess = false;
    }

    // 고객이 안내 문구를 여유롭게 인지하도록 최소 4000ms 유지
    const elapsedTime = Date.now() - startTime;
    const minimumNoticeTime = 4000;
    if (elapsedTime < minimumNoticeTime) {
      await new Promise(resolve => setTimeout(resolve, minimumNoticeTime - elapsedTime));
    }

    playWarningChime();

    if (isSuccess) {
      showButtonNotification('전송이 완료되었습니다. 곧 연락드리겠습니다.', 'connecting');
      conciergeForm.reset();
    } else {
      showButtonNotification('일시적인 통신 지연이 발생했습니다.\n잠시 후 다시 시도해 주시기 바랍니다.', 'failed');
    }

    if (conciergeSubmitBtn) {
      conciergeSubmitBtn.disabled = false;
      conciergeSubmitBtn.textContent = 'SUBMIT PRIVATE REQUEST';
    }

    notifyBarTimer = setTimeout(() => {
      hideButtonNotification();
    }, 5000);
  });
}
