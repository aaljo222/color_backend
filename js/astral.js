const form = document.getElementById('astralForm');
const calendarRadios = document.querySelectorAll('input[name="calendarType"]');
const leapMonthGroup = document.getElementById('leapMonthGroup');
const birthMonth = document.getElementById('birthMonth');
const birthDay = document.getElementById('birthDay');
const birthTime = document.getElementById('birthTime');
const timeUnknown = document.getElementById('timeUnknown');
const formError = document.getElementById('formError');
const submitButton = document.getElementById('submitButton');
const loadingResult = document.getElementById('loadingResult');
const paidReport = document.getElementById('reportContent');
const bojagiContent = document.getElementById('bojagiContent');
const birthOverseas = document.getElementById('birthOverseas');
const birthCityInput = document.getElementById('birthCity');
const birthCountry = document.getElementById('birthCountry');
const countrySearch = document.getElementById('countrySearch');
let countryOptions = [], validCityNames = new Set();
const locationsReady = fetch('/assets/birth-locations.json').then(response => {
  if (!response.ok) throw Error('지역 목록을 불러오지 못했습니다. 새로고침해 주세요.');
  return response.json();
}).then(data => {
  const suggestions = document.getElementById('koreanCitySuggestions');
  suggestions.replaceChildren();
  Object.entries(data.regions).forEach(([province, cities]) => {
    if (!province.endsWith('도')) {
      const short = province.replace('특별자치시', '').replace('특별시', '').replace('광역시', '');
      [province, short, short + '시'].forEach(name => validCityNames.add(name));
    }
    cities.forEach(city => {
      validCityNames.add(city); validCityNames.add(province + ' ' + city);
    });
    (province.endsWith('도') ? cities.map(city => province + ' ' + city) : [province, ...cities.map(city => province + ' ' + city)]).forEach(name => {
      const option = document.createElement('option'); option.value = name; suggestions.append(option);
    });
  });
  Object.entries(data.province_aliases).forEach(([old, current]) => {
    data.regions[current].forEach(city => validCityNames.add(old + ' ' + city));
  });
  const names = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['ko'], {type:'region'}) : null;
  countryOptions = data.country_codes.filter(code => code !== 'KR').map(code => ({code, name:names ? names.of(code) : code})).sort((a,b) => a.name.localeCompare(b.name, 'ko'));
  renderCountryOptions();
  return true;
}).catch(() => false);
function renderCountryOptions() {
  const selected = birthCountry.value;
  birthCountry.replaceChildren();
  const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = '국가·지역을 선택해 주세요'; birthCountry.append(placeholder);
  const query = countrySearch.value.trim().toLocaleLowerCase();
  countryOptions.filter(item => item.name.includes(query) || item.code.toLowerCase().includes(query)).forEach(item => {
    const option = document.createElement('option'); option.value = item.code; option.textContent = item.name; birthCountry.append(option);
  });
  if ([...birthCountry.options].some(option => option.value === selected)) birthCountry.value = selected;
}
birthOverseas.addEventListener('change', () => {
  document.getElementById('birthRegionLabel').htmlFor = birthOverseas.checked ? 'birthCountry' : 'birthCity';
  document.getElementById('birthRegionDetail').textContent = birthOverseas.checked ? '(국가·지역)' : '(시·군)';
  document.getElementById('domesticBirthGroup').hidden = birthOverseas.checked;
  document.getElementById('overseasBirthGroup').hidden = !birthOverseas.checked;
  birthCityInput.disabled = birthOverseas.checked;
  birthCityInput.required = !birthOverseas.checked;
  birthCountry.disabled = countrySearch.disabled = !birthOverseas.checked;
  birthCountry.required = birthOverseas.checked;
});
countrySearch.addEventListener('input', renderCountryOptions);
let latestReport = null;
let latestDisplayName = '';
let artRequest = null, artObjectUrl = null, artGeneration = 0;
let requestId = 0;
let activeRequest = null;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const sound = AstralSound.createSound(window.AudioContext || window.webkitAudioContext);
// Browsers permit audio only after a user gesture; no separate sound toggle.
async function activateSound(event) {
  if (!event.isTrusted || sound.enabled) return;
  if (await sound.enable()) sound.play('select');
}
document.addEventListener('pointerdown', activateSound);
document.addEventListener('keydown', activateSound);
document.addEventListener('visibilitychange', () => { if (document.hidden) sound.disable(); });
const sensoryCards = '.pillar-card, .styling-card, .paid-color-grid article';
function handleCardHover(event) {
  if (event.pointerType !== 'mouse') return;
  const card = event.target.closest(sensoryCards);
  if (card && !card.contains(event.relatedTarget)) sound.play('hover');
}
function handleCardFocus(event) {
  const card = event.target.closest(sensoryCards);
  if (card && !card.contains(event.relatedTarget)) sound.play('hover');
}
[paidReport].forEach(container => {
  container.addEventListener('pointerover', handleCardHover);
  container.addEventListener('focusin', handleCardFocus);
});
const revealTargets = new Set();
const revealObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
  const visible = entries.filter((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.45);
  visible.forEach(({ target }, index) => {
    revealObserver.unobserve(target);
    revealTargets.delete(target);
    revealResult(target, Math.min(index, 3) * 150);
  });
}, { threshold: 0.45 }) : null;
const closingDialogs = new WeakMap();

// Each card unfolds when nearly half of it is visible, including on mobile.
// Content remains readable if animation or IntersectionObserver is unavailable.
function revealResult(target, delay = 0) {
  if (reducedMotion.matches || !target.animate || target.hidden) return;
  target.getAnimations().forEach((animation) => animation.cancel());
  target.animate([
    { opacity: 0, transform: 'perspective(900px) translateY(36px) rotateX(7deg) scale(.96)' },
    { opacity: 1, transform: 'perspective(900px) translateY(0) rotateX(0deg) scale(1)' },
  ], { duration: 1000, delay, easing: 'cubic-bezier(.22, .7, .2, 1)', fill: 'backwards' });
}

document.querySelectorAll('[data-replay]').forEach((button) => button.addEventListener('click', () => {
  const container = document.getElementById(button.dataset.replay);
  clearReveals(container);
  [...container.children].forEach((card) => revealWhenVisible(card));
  sound.play('select');
}));

function revealWhenVisible(target) {
  if (!revealObserver) return revealResult(target);
  revealTargets.add(target);
  revealObserver.observe(target);
}

function clearReveals(container) {
  for (const target of revealTargets) {
    if (target === container || container.contains(target)) {
      revealObserver.unobserve(target);
      revealTargets.delete(target);
    }
  }
  container.getAnimations({ subtree: true }).forEach((animation) => animation.cancel());
}

function scrollToResult(target) {
  target.scrollIntoView({ behavior: reducedMotion.matches ? 'instant' : 'smooth', block: 'start' });
}

function closeAnimatedDialog(dialog) {
  if (closingDialogs.has(dialog)) return closingDialogs.get(dialog);
  if (!dialog.open) return Promise.resolve();
  dialog.getAnimations().forEach((animation) => animation.cancel());
  dialog.classList.add('is-closing');
  const exit = !reducedMotion.matches && dialog.animate
    ? dialog.animate([
      { opacity: 1, transform: 'translateY(0) scale(1)' },
      { opacity: 0, transform: 'translateY(-18px) scale(.92, .86)' },
    ], { duration: 220, easing: 'cubic-bezier(.55, .055, .675, .19)', fill: 'forwards' })
    : null;
  const closing = (async () => {
    try {
      if (exit) await exit.finished;
    } catch (_) {
      // Cancellation (including reduced-motion changes) must still close the dialog.
    } finally {
      dialog.close();
      exit?.cancel();
      dialog.classList.remove('is-closing');
    }
  })().finally(() => { closingDialogs.delete(dialog); });
  closingDialogs.set(dialog, closing);
  return closing;
}

function openAnimatedDialog(dialog) {
  dialog.showModal();
  sound.play('open');
  if (!reducedMotion.matches && dialog.animate) {
    dialog.animate([
      { opacity: 0, transform: 'translateY(20px) scale(.94, .9)' },
      { opacity: 1, transform: 'translateY(0) scale(1)' },
    ], { duration: 380, easing: 'cubic-bezier(.34, 1.3, .64, 1)' });
  }
}

const artworkView = AstralArtworkView.createArtworkView({
  document, motion:reducedMotion, sound, openDialog:openAnimatedDialog, closeDialog:closeAnimatedDialog,
});

reducedMotion.addEventListener('change', () => {
  if (reducedMotion.matches) clearReveals(paidReport);
});

// NOTE: 월/일 select 는 index.html 인라인 스크립트가 채웁니다.

calendarRadios.forEach((radio) => {
  radio.addEventListener('change', () => {
    const isLunar = document.querySelector('input[name="calendarType"]:checked').value === 'lunar';
    leapMonthGroup.hidden = !isLunar;
  });
});

timeUnknown.addEventListener('change', () => {
  birthTime.disabled = timeUnknown.checked;
  birthTime.required = !timeUnknown.checked;
});

function setLoading(busy) {
  loadingResult.hidden = !busy;
  submitButton.disabled = busy;
  submitButton.setAttribute('aria-busy', String(busy));
  submitButton.querySelector('span').textContent = busy ? '나의 사주와 색을 분석하고 있어요…' : '나의 사주와 색 확인하기';
}

function showError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function clearError() {
  formError.hidden = true;
  formError.textContent = '';
}

async function postJson(url, payload, signal) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '결과를 불러오지 못했습니다.');
      return result;
    } catch (error) {
      lastError = error;
      if (!(error instanceof TypeError) || attempt === 1) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 800));
    }
  }
  throw lastError;
}

function buildPayload() {
  const year = document.getElementById('birthYear').value.padStart(4, '0');
  const month = birthMonth.value.padStart(2, '0');
  const day = birthDay.value.padStart(2, '0');
  const calendarType = document.querySelector('input[name="calendarType"]:checked').value;
  const selectedGender = document.querySelector('input[name="gender"]:checked');
  return {
    calendar_type: calendarType,
    birth_date: `${year}-${month}-${day}`,
    is_leap_month: calendarType === 'lunar' && document.querySelector('input[name="leapMonth"]:checked').value === 'true',
    birth_time: timeUnknown.checked ? '' : birthTime.value,
    time_unknown: timeUnknown.checked,
    birth_city: document.getElementById('birthCity').value,
    birth_overseas: birthOverseas.checked,
    birth_country: birthOverseas.checked ? birthCountry.value : 'KR',
    gender: selectedGender ? selectedGender.value : '',
  };
}

function renderNotices(notices) {
  const container = document.getElementById('noticeList');
  container.innerHTML = '';
  notices.forEach((notice) => {
    const paragraph = document.createElement('p');
    paragraph.textContent = notice;
    container.appendChild(paragraph);
  });
  container.hidden = notices.length === 0;
}

function renderCandidates(candidates) {
  const card = document.getElementById('boundaryCard');
  const container = document.getElementById('boundaryCandidates');
  container.innerHTML = '';
  candidates.forEach((candidate) => {
    const row = document.createElement('div');
    row.className = 'candidate-row';
    const label = document.createElement('span');
    label.textContent = candidate.label;
    const pillars = document.createElement('span');
    pillars.className = 'candidate-pillars';
    pillars.textContent = [candidate.pillars.year, candidate.pillars.month, candidate.pillars.day, candidate.pillars.hour]
      .filter(Boolean).join(' · ');
    row.append(label, pillars);
    container.appendChild(row);
  });
  card.hidden = candidates.length < 2;
}

function mixHex(source, target, amount) {
  const parse = (value) => [1, 3, 5].map((start) => Number.parseInt(value.slice(start, start + 2), 16));
  const [sr, sg, sb] = parse(source);
  const [tr, tg, tb] = parse(target);
  const channel = (from, to) => Math.round(from + (to - from) * amount).toString(16).padStart(2, '0');
  return `#${channel(sr, tr)}${channel(sg, tg)}${channel(sb, tb)}`;
}

function hexAlpha(hex, alpha) {
  const red = Number.parseInt(hex.slice(1, 3), 16);
  const green = Number.parseInt(hex.slice(3, 5), 16);
  const blue = Number.parseInt(hex.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function renderArtBrief(report) {
  const art = report.artwork;
  document.getElementById('patternFamily').textContent = art ? [art.spec.style, art.spec.mood, art.spec.art_direction?.label].filter(Boolean).join(' · ') : '';
  document.getElementById('artStatus').textContent = art?.configured ? '나의 여덟 색이 한 폭의 전통화로 이어집니다.' : (art?.message || '사주 결과를 먼저 확인해 주세요.');
  const button = document.getElementById('generateArtButton');
  button.disabled = !art?.configured;
  button.textContent = '나의 전통화 생성하기';
  const tones = document.getElementById('patternToneLegend');
  tones.replaceChildren();
  (art?.spec.palette || []).forEach(color => {
    const item = document.createElement('div'), dot = document.createElement('i');
    const name = document.createElement('strong'), hex = document.createElement('code');
    item.className = 'art-palette-chip';
    item.setAttribute('role','listitem');
    item.setAttribute('aria-label',color.name + ' ' + color.hex);
    dot.style.backgroundColor = color.hex;
    dot.setAttribute('aria-hidden','true');
    name.textContent = color.name;
    hex.textContent = color.hex;
    item.append(dot, name, hex);
    tones.appendChild(item);
  });
}
function clearArtwork() {
  artworkView.reset();
  artGeneration += 1;
  artRequest?.abort(); artRequest = null;
  if (artObjectUrl) URL.revokeObjectURL(artObjectUrl);
  artObjectUrl = null;
  const image = document.getElementById('traditionalArtwork');
  image.hidden = true; image.removeAttribute('src');
  document.getElementById('artExplanation').hidden = true;
  document.getElementById('artExplanationObjects').replaceChildren();
  document.getElementById('artError').hidden = true;
  document.getElementById('generateArtButton').disabled = true;
}
function renderArtExplanation(explanation) {
  const section = document.getElementById('artExplanation');
  section.hidden = true;
  if (!explanation) return;
  document.getElementById('artExplanationTitle').textContent = AstralReportUI.artworkStoryTitle(latestDisplayName);
  document.getElementById('artExplanationSummary').textContent = explanation.summary;
  document.getElementById('artExplanationStyle').textContent = explanation.style;
  document.getElementById('artExplanationNote').textContent = explanation.note;
  const objects = document.getElementById('artExplanationObjects');
  objects.replaceChildren();
  explanation.objects.forEach(item => {
    const card = document.createElement('article');
    const name = document.createElement('h4'), meaning = document.createElement('p');
    name.textContent = item.object === '고서' ? '책' : item.object;
    meaning.textContent = item.meaning;
    card.append(name, meaning); objects.appendChild(card);
  });
  section.hidden = false;
}
async function generateArtwork() {
  if (!latestReport?.artwork?.configured || artRequest || artObjectUrl) return;
  const report = latestReport, generation = ++artGeneration;
  const controller = new AbortController();
  artRequest = controller;
  const button = document.getElementById('generateArtButton');
  const status = document.getElementById('artStatus'), errorBox = document.getElementById('artError');
  button.disabled = true; button.textContent = '전통화를 그리고 있어요…';
  errorBox.hidden = true;
  status.textContent = '선정된 여덟 색으로 한국 전통 채색화를 제작하고 있습니다. 생성에는 시간이 걸릴 수 있어요.';
  try {
    // Paid generation is deliberately NOT retried by postJson.
    const response = await fetch('/api/astral_art', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticket:report.artwork.ticket}), signal:controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '전통화 생성에 실패했습니다.');
    if (generation !== artGeneration || report !== latestReport) return;
    if (result.mime_type !== 'image/png') throw Error('작품 이미지 형식을 확인해 주세요.');
    const binary = atob(result.image_base64);
    const bytes = Uint8Array.from(binary, letter => letter.charCodeAt(0));
    // The shared ivory scroll is frontend decoration, never baked into the PNG.
    // Ignore legacy gender/palette side-mat hints; retain the provider's native pixels.
    const artworkBlob = new Blob([AstralReportUI.artworkPngWithPalette(
      bytes, report)], {type:'image/png'});
    if (generation !== artGeneration || report !== latestReport) return;
    artObjectUrl = URL.createObjectURL(artworkBlob);
    const image = document.getElementById('traditionalArtwork');
    image.src = artObjectUrl;
    await image.decode();
    if (generation !== artGeneration || report !== latestReport) return;
    artworkView.reveal(artObjectUrl);
    renderArtExplanation(result.explanation);
    status.textContent = result.cached ? '이미 완성한 나의 전통화를 불러왔어요.' : '나만의 전통화가 완성되었어요. 그림에 담긴 이야기를 함께 만나보세요.';
    document.getElementById('downloadPatternButton').disabled = false;
    button.textContent = '전통화 생성 완료';
  } catch (error) {
    if (generation !== artGeneration || error.name === 'AbortError') return;
    if (artObjectUrl) { URL.revokeObjectURL(artObjectUrl); artObjectUrl = null; }
    artworkView.reset();
    document.getElementById('traditionalArtwork').removeAttribute('src');
    document.getElementById('artExplanation').hidden = true;
    errorBox.textContent = error.message || '전통화 생성 서버에 연결하지 못했습니다.';
    errorBox.hidden = false;
    status.textContent = '사주 결과와 팔레트는 그대로 유지됩니다. 다시 생성하면 추가 비용이 발생할 수 있습니다.';
    button.disabled = false; button.textContent = '전통화 생성 다시 요청하기';
  } finally {
    if (generation === artGeneration) artRequest = null;
  }
}
document.getElementById('generateArtButton').addEventListener('click', generateArtwork);

function renderPillars(report) {
  const container = document.getElementById('reportPillars');
  container.innerHTML = '';
  AstralReportUI.pillarModels(report.pillars).forEach((pillar) => {
    const item = document.createElement('article');
    item.className = `pillar-card${pillar.key === 'day' ? ' pillar-day' : ''}`;
    item.tabIndex = 0;
    item.setAttribute('role', 'group');
    const name = document.createElement('h4');
    name.textContent = pillar.label;
    item.appendChild(name);
    const concepts = {
      hour: '시주 · 태어난 시간의 두 글자입니다. 개인적인 표현과 세부 활동을 살피는 보조 관점이며, 시간을 모르면 만들지 않아요.',
      day: '일주 · 태어난 날의 두 글자입니다. 위 글자인 일간을 나의 기준으로 삼고, 아래 글자인 일지는 가까운 관계의 주제로 읽어요.',
      month: '월주 · 절기에 따라 정한 달의 두 글자입니다. 태어난 계절의 조건과 일상·사회 활동의 배경을 함께 살펴요.',
      year: '연주 · 입춘을 기준으로 정한 해의 두 글자입니다. 성장 환경과 넓은 관계의 배경을 살피는 관점이에요.',
    };
    const tooltip = document.createElement('p');
    tooltip.className = 'pillar-tooltip';
    tooltip.id = 'pillar-tip-' + pillar.key;
    tooltip.setAttribute('role', 'tooltip');
    tooltip.textContent = concepts[pillar.key];
    item.setAttribute('aria-describedby', tooltip.id);
    item.appendChild(tooltip);
    item.setAttribute('aria-label', `${pillar.label} ${pillar.value || '시간 미상'}`);
    if (!pillar.value) {
      const unknown = document.createElement('p');
      unknown.className = 'pillar-unknown';
      unknown.textContent = '시간 미상';
      const note = document.createElement('small');
      note.textContent = '시주는 만들지 않아요';
      item.append(unknown, note);
    } else {
      [pillar.stem, pillar.branch].forEach((letter, index) => {
        const row = document.createElement('div');
        row.className = 'pillar-letter';
        row.style.setProperty('--pillar-ink', AstralReportUI.ELEMENT_INK[letter.element]);
        row.style.setProperty('--pillar-color', report.element_profile.element_colors[letter.element]);
        const label = document.createElement('small');
        label.textContent = index === 0 ? '천간' : '지지';
        const glyph = document.createElement('strong');
        glyph.textContent = `${letter.text}(${letter.hanja})`;
        const element = document.createElement('span');
        element.className = 'pillar-element';
        element.textContent = letter.element;
        row.append(label, glyph, element);
        item.appendChild(row);
      });
      if (pillar.key === 'day') {
        const marker = document.createElement('small');
        marker.className = 'pillar-day-label';
        marker.textContent = '일간 = 나의 기준';
        item.appendChild(marker);
      }
    }
    container.appendChild(item);
  });
}

function renderReading(report, container) {
  container.innerHTML = '';
  report.reading.forEach((section, index) => {
    const accent = AstralReportUI.readingAccent(section, report);
    const article = document.createElement('article');
    const header = document.createElement('header');
    const chip = document.createElement('div');
    const heading = document.createElement('div');
    const role = document.createElement('span');
    const number = document.createElement('span');
    const title = document.createElement('h4');
    const colorName = document.createElement('p');
    const possibility = document.createElement('p');
    const facts = document.createElement('div');
    const action = document.createElement('p');
    article.style.setProperty('--section-color', accent.hex);
    header.className = 'reading-color-header';
    chip.className = 'reading-color-chip';
    chip.setAttribute('aria-label', `${accent.name} ${accent.hex}`);
    role.className = 'reading-role';
    role.textContent = AstralReportUI.displayRole(accent);
    number.className = 'reading-number';
    number.textContent = String(index + 1).padStart(2, '0');
    title.textContent = section.title;
    colorName.className = 'reading-color-name';
    colorName.textContent = `${accent.name} · ${accent.hex}`;
    chip.appendChild(number);
    heading.append(role, title, colorName);
    header.append(chip, heading);
    possibility.className = 'reading-possibility';
    possibility.innerHTML = '<strong>해석 가능성</strong>';
    possibility.append(document.createTextNode(section.possibility));
    facts.className = 'reading-facts';
    [['활용할 강점', section.strength], ['확인할 지점', section.watch]].forEach(([label, text]) => {
      const box = document.createElement('p');
      const caption = document.createElement('strong');
      caption.textContent = label;
      box.append(caption, document.createTextNode(text));
      facts.appendChild(box);
    });
    action.className = 'reading-action';
    action.innerHTML = '<strong>오늘 해볼 작은 행동</strong>';
    action.append(document.createTextNode(section.action.replaceAll('균형색', '보완색')));
    article.append(header, possibility, facts, action);
    container.appendChild(article);
  });
}

function renderElementProfile(profile) {
  const model = AstralReportUI.spectrumModel(profile);
  const container = document.getElementById('elementSpectrum');
  container.innerHTML = '';
  const svgNode = (name, attributes, parent) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (parent) parent.appendChild(node);
    return node;
  };
  const points = (items) => items.map(point => `${point.x},${point.y}`).join(' ');
  const svg = svgNode('svg', { viewBox: '0 0 360 340', role: 'img', 'aria-labelledby': 'spectrumTitle spectrumDesc' }, container);
  svgNode('title', { id: 'spectrumTitle' }, svg).textContent = '오각형 오행 컬러 스펙트럼';
  svgNode('desc', { id: 'spectrumDesc' }, svg).textContent = model.axes.map(axis => `${axis.element} ${axis.count}칸 ${axis.percent}%`).join(', ') + `. 바깥 눈금은 가장 많은 항목의 ${model.maximum}칸이며 다섯 축에 같은 눈금을 적용했습니다. 사주의 강약이 아닌 이미지용 구성입니다.`;
  model.rings.forEach((ring, index) => svgNode('polygon', { points: points(ring), fill: 'none', stroke: '#e1dbcf', 'stroke-width': index === model.rings.length - 1 ? 1.4 : .8 }, svg));
  model.axes.forEach(axis => svgNode('line', { x1: model.center.x, y1: model.center.y, x2: axis.outer.x, y2: axis.outer.y, stroke: '#e6dfd3' }, svg));
  // Each colored wedge is clipped by the measured polygon, not an invented score.
  const defs = svgNode('defs', {}, svg);
  const clip = svgNode('clipPath', { id: 'spectrumAreaClip' }, defs);
  svgNode('polygon', { points: points(model.axes.map(axis => axis.value)) }, clip);
  const fill = svgNode('g', { 'clip-path': 'url(#spectrumAreaClip)' }, svg);
  model.axes.forEach((axis, index) => {
    const prev = model.axes[(index + 4) % 5].outer;
    const next = model.axes[(index + 1) % 5].outer;
    const start = { x: (prev.x + axis.outer.x) / 2, y: (prev.y + axis.outer.y) / 2 };
    const end = { x: (next.x + axis.outer.x) / 2, y: (next.y + axis.outer.y) / 2 };
    svgNode('polygon', { points: points([model.center, start, axis.outer, end]), fill: axis.color, 'fill-opacity': .85 }, fill);
  });
  svgNode('polygon', { class: 'spectrum-data', points: points(model.axes.map(axis => axis.value)), fill: 'none', stroke: '#8b6e43', 'stroke-width': 2.2, 'stroke-linejoin': 'round' }, svg);
  model.axes.forEach(axis => {
    if (axis.count > 0) svgNode('circle', { cx: axis.value.x, cy: axis.value.y, r: 4.8, fill: axis.ink, stroke: '#fffdf8', 'stroke-width': 1.7 }, svg);
    const text = svgNode('text', { x: axis.label.x, y: axis.label.y, 'text-anchor': 'middle', fill: axis.ink, class: 'spectrum-axis' }, svg);
    svgNode('tspan', { x: axis.label.x, dy: 0 }, text).textContent = `${axis.element} ${axis.english}`;
    svgNode('tspan', { x: axis.label.x, dy: 18, class: 'spectrum-axis-value' }, text).textContent = `${axis.count}칸 · ${axis.percent}%`;
  });
  document.getElementById('spectrumScale').textContent = `확대 눈금 · 중심 0칸 → 바깥선 ${model.maximum}칸 · 8단계로 표시합니다. 비율(%)은 전체 ${profile.slot_count}칸 기준입니다.`;
}

// ---------- 대표색 카드: 인라인 아코디언 ----------
function buildStylingPanel(model, id) {
  const panel = document.createElement('div');
  const inner = document.createElement('div');
  panel.className = 'styling-panel';
  panel.id = id;
  panel.inert = true; // 접힌 상태에서는 탭 포커스가 들어가지 않게
  inner.className = 'styling-panel-inner';

  const intro = document.createElement('p');
  intro.className = 'styling-dialog-intro';
  intro.textContent = model.color.selection_reason || model.reason;

  const colors = document.createElement('div');
  colors.className = 'paid-color-grid styling-dialog-colors';
  renderPaidColors([model.color, model.companion].filter(Boolean), colors);
  [...colors.children].forEach((card, index) => {
    card.querySelector('details').remove();
    const use = document.createElement('p');
    use.className = 'styling-pair-use';
    use.textContent = index === 0 ? model.tips[0] : model.companion.guide.use;
    card.appendChild(use);
  });

  const tipsTitle = document.createElement('h3');
  tipsTitle.className = 'styling-tips-title';
  tipsTitle.textContent = '일상에서 이렇게 함께 써보세요';
  const tips = document.createElement('ul');
  tips.className = 'styling-dialog-tips';
  model.tips.forEach(tip => {
    const li = document.createElement('li');
    li.textContent = tip;
    tips.appendChild(li);
  });

  const frequency = document.createElement('p');
  frequency.className = 'styling-dialog-frequency';
  frequency.textContent = `이렇게 시작해요 · ${model.frequency}${model.moment ? ` · ${model.moment}` : ''}`;

  inner.append(intro, colors, tipsTitle, tips, frequency);
  panel.appendChild(inner);
  return panel;
}

function setStylingOpen(card, open) {
  const trigger = card.querySelector('.styling-trigger');
  const panel = card.querySelector('.styling-panel');
  card.classList.toggle('is-open', open);
  trigger.setAttribute('aria-expanded', String(open));
  trigger.querySelector('.styling-trigger-more').textContent =
    open ? '접기 ↑' : '두 색의 의미와 활용법 보기 ↓';
  panel.inert = !open;
}

function renderStyling(report) {
  const container = document.getElementById('stylingGrid');
  container.innerHTML = '';
  const order = report.colors.map(color => color.role);
  AstralReportUI.stylingModels(report)
    .sort((a, b) => order.indexOf(a.color.role) - order.indexOf(b.color.role))
    .forEach(model => {
      const card = document.createElement('article');
      card.className = `styling-card styling-${model.key}`;
      card.style.setProperty('--styling-color', model.color.hex);

      const panelId = `styling-panel-${model.key}`;
      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'styling-trigger';
      trigger.setAttribute('aria-expanded', 'false');
      trigger.setAttribute('aria-controls', panelId);
      trigger.setAttribute('aria-label', `${model.title}, ${model.color.name}, 두 색 활용법 펼치기`);

      const header = document.createElement('span');
      header.className = 'styling-trigger-header';
      const swatch = document.createElement('span');
      swatch.className = 'styling-swatch';
      swatch.setAttribute('aria-label', model.color.hex);
      const heading = document.createElement('span');
      const label = document.createElement('span');
      label.className = 'styling-purpose';
      label.textContent = `${model.title} · ${AstralReportUI.displayRole(model.color)}`;
      const name = document.createElement('strong');
      name.className = 'styling-trigger-name';
      name.textContent = model.color.name;
      const hex = document.createElement('code');
      hex.textContent = model.color.hex;
      heading.append(label, name, hex);
      header.append(swatch, heading);

      const tagline = document.createElement('span');
      tagline.className = 'styling-tagline';
      tagline.textContent = model.tagline;
      const more = document.createElement('span');
      more.className = 'styling-trigger-more';
      more.textContent = '두 색의 의미와 활용법 보기 ↓';
      trigger.append(header, tagline, more);

      card.append(trigger, buildStylingPanel({ ...model, report }, panelId));

      trigger.addEventListener('click', () => {
        const willOpen = !card.classList.contains('is-open');
        // 한 번에 하나만 열기 (여러 개 열고 싶으면 아래 3줄 삭제)
        container.querySelectorAll('.styling-card.is-open').forEach(other => {
          if (other !== card) setStylingOpen(other, false);
        });
        setStylingOpen(card, willOpen);
        sound.play(willOpen ? 'open' : 'close');
        if (willOpen) {
          card.scrollIntoView({ behavior: reducedMotion.matches ? 'instant' : 'smooth', block: 'nearest' });
        }
      });
      container.appendChild(card);
    });
}

function renderPaidColors(colors, container = document.getElementById('paidColorGrid')) {
  const descriptions = {
    고유색: '일간을 기준으로 정한 중심 색',
    재능색: '천간의 십신을 가중해 고른 활동 주제',
    관계색: '일지 본기의 십신으로 읽는 관계 주제',
    균형색: '이미지 구성에서 적은 오행을 채우는 시각화 색',
  };
  container.innerHTML = '';
  colors.forEach((color) => {
    const card = document.createElement('article');
    const swatch = document.createElement('button');
    card.style.setProperty('--card-tint', color.hex);
    const copyLabel = document.createElement('span');
    const role = document.createElement('p');
    const name = document.createElement('h4');
    const basis = document.createElement('p');
    const guide = document.createElement('p');
    const caution = document.createElement('p');
    const hex = document.createElement('code');
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    swatch.className = 'paid-color-swatch';
    swatch.type = 'button';
    swatch.setAttribute('aria-label', `${color.name} ${color.hex} HEX 복사`);
    swatch.style.backgroundColor = color.hex;
    copyLabel.className = 'swatch-copy-label';
    copyLabel.textContent = 'HEX 복사';
    swatch.appendChild(copyLabel);
    swatch.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(color.hex);
        sound.play('select');
        copyLabel.textContent = '복사 완료';
        window.setTimeout(() => { copyLabel.textContent = 'HEX 복사'; }, 1400);
      } catch (_) {
        copyLabel.textContent = color.hex;
      }
    });
    role.className = 'color-role';
    role.textContent = color.name;
    name.textContent = color.name;
    basis.textContent = `${descriptions[color.role]} · 기준 ${color.basis}`;
    const description = document.createElement('p');
    description.className = 'pair-description';
    description.textContent = color.description || `${AstralReportUI.displayRole(color)}의 기준이 되는 대표색입니다.`;
    guide.className = 'color-guide';
    guide.textContent = `이렇게 사용해 보세요 · ${color.guide.use}`;
    caution.className = 'color-caution';
    caution.textContent = color.guide.avoid;
    hex.textContent = color.hex;
    details.className = 'color-chip-details';
    summary.textContent = '색의 기준과 활용법';
    details.append(summary, basis, guide, caution);
    card.append(role, swatch, name, hex, description, details);
    container.appendChild(card);
  });
}

function renderFortune(fortune) {
  document.getElementById('fortuneScore').textContent = fortune.score;
  document.getElementById('fortuneBrief').textContent = `${fortune.theme} · ${fortune.recommended_action}`;
  const date = document.getElementById('fortuneDate');
  date.textContent = fortune.date_kst;
  date.dateTime = fortune.date_kst;
}

function renderReport(report) {
  latestReport = report;
  const genderName = report.profile.gender === 'male' ? '남성' : '여성';
  const timeLabel = report.profile.time_unknown ? '시간 미상' : '출생시간 반영';
  document.getElementById('reportMeta').textContent = `${report.profile.solar_date} · ${report.profile.birth_city} · ${genderName} · ${timeLabel}`;
  document.getElementById('overviewHeadline').textContent = report.overview.headline;
  renderPillars(report);
  renderElementProfile(report.element_profile);
  renderStyling(report);
  renderNotices(report.notices || []);
  renderCandidates(report.boundary_candidates || []);
  clearArtwork();
  renderArtBrief(report);
  renderFortune(report.today_fortune);
  document.getElementById('paidDisclaimer').textContent = report.disclaimer;
  paidReport.hidden = false;
  bojagiContent.hidden = false;
  document.getElementById('resultPlaceholder').hidden = true;
  document.getElementById('bojagiPlaceholder').hidden = true;
  document.getElementById('downloadPatternButton').disabled = true;
  paidReport.querySelectorAll('.report-summary, .pillar-card, .styling-card').forEach(target => revealWhenVisible(target));
}

function invalidateCalculatedResults() {
  clearArtwork();
  requestId += 1;
  activeRequest?.abort();
  activeRequest = null;
  setLoading(false);
  clearReveals(paidReport);
  clearReveals(bojagiContent);
  paidReport.hidden = true;
  bojagiContent.hidden = true;
  latestReport = null;
  latestDisplayName = '';
  showView('birthSection', false);
  document.getElementById('resultPlaceholder').hidden = false;
  document.getElementById('bojagiPlaceholder').hidden = false;
  document.getElementById('reportMeta').textContent = '';
  document.getElementById('patternFamily').textContent = '';
  document.getElementById('downloadPatternButton').disabled = true;
  clearError();
}

// ---------- 결과 스튜디오(풀스크린 오버레이) ----------
const studio = document.getElementById('astralStudio');
const studioScroll = document.getElementById('studioScroll');
const navLinks = [...document.querySelectorAll('.section-nav a')];
const viewIds = ['birthSection', 'resultSection', 'bojagiSection'];

// birthSection: 스튜디오 닫힘(입력 모달이 보임)
// resultSection / bojagiSection: 스튜디오 열림 + 해당 섹션 표시
function showView(requested, scroll = true) {
  const id = viewIds.includes(requested) && (requested === 'birthSection' || latestReport)
    ? requested : 'birthSection';
  const open = id !== 'birthSection';
  const wasOpen = studio.classList.contains('is-active');
  ['resultSection', 'bojagiSection'].forEach(view => {
    document.getElementById(view).hidden = view !== id;
  });
  studio.classList.toggle('is-active', open);
  studio.setAttribute('aria-hidden', String(!open));
  studio.inert = !open;
  document.body.classList.toggle('studio-open', open);
  artworkView.setVisible(id === 'bojagiSection');
  navLinks.forEach(link => {
    const locked = link.hash !== '#birthSection' && !latestReport;
    link.setAttribute('aria-disabled', String(locked));
    if (link.hash === '#' + id) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (open && scroll) {
    studioScroll.scrollTo({ top: 0, behavior: wasOpen && !reducedMotion.matches ? 'smooth' : 'instant' });
  }
}

form.addEventListener('input', invalidateCalculatedResults);
form.addEventListener('change', invalidateCalculatedResults);
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitButton.disabled) return;
  // 입력이 그대로(= latestReport 가 남아 있음)면 API 재호출 없이 스튜디오만 다시 연다.
  if (latestReport) {
    showView('resultSection');
    document.getElementById('report-title').focus({ preventScroll: true });
    return;
  }
  clearError();
  if (!await locationsReady) return showError('지역 목록을 불러오지 못했습니다. 새로고침한 뒤 다시 시도해 주세요.');
  if (submitButton.disabled) return;
  const payload = buildPayload();
  if (payload.birth_overseas) {
    if (!payload.birth_country) return showError('목록에서 해외 출생 국가를 선택해 주세요.');
    return showError('해외 출생 계산은 준비 중입니다. 도시별 과거 시간대 검증 후 지원할 예정이며, 현재는 국내 출생만 계산할 수 있습니다.');
  }
  payload.birth_city = payload.birth_city.trim().replace(/\s+/g, ' ');
  if (!validCityNames.has(payload.birth_city)) return showError('국내 출생 지역은 목록에 있는 시·군을 선택해 주세요. 해외 출생이면 해외를 체크해 주세요.');
  if (!payload.gender) return showError('성별을 선택해 주세요.');
  if (!payload.birth_city) return showError('대한민국 내 출생 시·군을 입력해 주세요.');
  if (!payload.time_unknown && !payload.birth_time) return showError('출생 시각을 입력하거나 시간 모름을 선택해 주세요.');
  invalidateCalculatedResults();
  const id = ++requestId;
  const controller = new AbortController();
  activeRequest = controller;
  setLoading(true);
  try {
    const report = await postJson('/api/astral_report', payload, controller.signal);
    if (id !== requestId) return;
    latestDisplayName = document.getElementById('birthName').value.trim();
    renderReport(report);
    sound.play('reveal');
    showView('resultSection');
    document.getElementById('report-title').focus({ preventScroll: true });
  } catch (error) {
    if (id !== requestId || error.name === 'AbortError') return;
    showError(error instanceof TypeError && /fetch/i.test(error.message)
      ? '계산 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
      : error.message || '잠시 후 다시 시도해 주세요.');
  } finally {
    if (id === requestId) { activeRequest = null; setLoading(false); }
  }
});

document.getElementById('resetButton').addEventListener('click', () => {
  invalidateCalculatedResults();
  showView('birthSection');
  document.getElementById('birthYear').focus({ preventScroll: true });
});

navLinks.forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  if (link.getAttribute('aria-disabled') === 'true') return;
  showView(link.hash.slice(1));
  sound.play('select');
}));
document.getElementById('resultToArtworkButton').addEventListener('click', () => {
  if (!latestReport) return;
  showView('bojagiSection');
  document.getElementById('bojagi-title').focus({preventScroll:true});
  sound.play('select');
  void generateArtwork();
});

// 스튜디오 닫기(Close) → 출생정보 입력 모달로 복귀. 결과(latestReport)는 유지됩니다.
document.getElementById('studioCloseBtn').addEventListener('click', () => {
  showView('birthSection', false);
  sound.play('close');
});
// Escape: 다이얼로그(전통화 크게 보기)가 열려 있으면 다이얼로그가 처리하고,
// 아니면 스튜디오를 닫습니다. (index.html 의 Escape 핸들러는 studio-open 중 동작하지 않음)
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (document.querySelector('dialog[open]')) return;
  if (studio.classList.contains('is-active')) {
    showView('birthSection', false);
    sound.play('close');
  }
});

showView('birthSection', false);

document.getElementById('downloadPatternButton').addEventListener('click', (event) => {
  if (!latestReport || !artObjectUrl) return;
  const link = document.createElement('a');
  link.href = artObjectUrl;
  link.download = `astral-traditional-${latestReport.pattern_seed}.png`;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  const button = event.currentTarget;
  button.textContent = '다운로드 시작됨';
  window.setTimeout(() => { button.textContent = 'PNG 다운로드'; }, 1400);
});