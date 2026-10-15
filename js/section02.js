/* ============================================================
   section02.js — Memory Archive 갤러리 10종 데이터 및
   카드 클릭 시 상세 모달(archiveDetailModal) 렌더링
   ============================================================ */

const memoryStories = [
  {
    title: "초여름 수국 골목",
    tag: "SPECIMEN NO. 01",
    viewBox: "90 104 282 282",
    story: "장마가 오기 직전, 비를 머금은 흙냄새를 맡으며 하굣길 돌담 밑에 활짝 피어난 수국 꽃송이를 가만히 쓰다듬던 축축하고 싱그럽던 오후.",
    hexes: ["#7CA5B8", "#B497D6", "#9BC495", "#C4D4BA"]
  },
  {
    title: "어린 시절 골목길 가로등",
    tag: "SPECIMEN NO. 02",
    viewBox: "485 104 282 282",
    story: "어둑해진 골목에서 숨바꼭질을 하다 멀리서 들려오는 엄마의 부름에 아쉽게 발걸음을 돌릴 때, 낡은 주황빛으로 우리를 비춰주던 가로등 불빛.",
    hexes: ["#FFB703", "#023047", "#FB8500"]
  },
  {
    title: "가을날 단풍 운동장",
    tag: "SPECIMEN NO. 03",
    viewBox: "880 104 282 282",
    story: "가을 운동회 날 만국기가 펄럭이던 높고 푸른 하늘 아래, 흙먼지 날리며 달리기를 마치고 플라타너스 붉은 낙엽을 모아 하늘 높이 던지던 날.",
    hexes: ["#C85D38", "#DAB049", "#4DA7E8", "#9B381E"]
  },
  {
    title: "여름 바닷가",
    tag: "SPECIMEN NO. 04",
    viewBox: "1275 104 282 282",
    story: "발가락 사이로 스며들던 따뜻한 모래와 귓가를 맴돌던 파도소리.",
    hexes: ["#E3C594", "#48CAE4", "#F8F9FA"]
  },
  {
    title: "비 오는 날 창밖",
    tag: "SPECIMEN NO. 05",
    viewBox: "1670 104 282 282",
    story: "유리창에 맺힌 빗방울을 손끝으로 가만히 잇다가, 라디오에서 흘러나오던 '비처럼 음악처럼' 을 듣던 비오는 어느 오후.",
    hexes: ["#6C757D", "#4682B4", "#8C7A6B", "#34495E"]
  },
  {
    title: "봄날 벚꽃길",
    tag: "SPECIMEN NO. 06",
    viewBox: "90 608 282 282",
    story: "새 학기 새 책가방을 메고 걷던 등굣길, 봄바람이 훅 불어올 때마다 눈처럼 머리 위로 쏟아져 내리던 연분홍 꽃잎을 두 손 모아 받아내던 설렘.",
    hexes: ["#FFC8DD", "#F8F9FA", "#D4A373", "#FFAFCC"]
  },
  {
    title: "겨울날 아침 햇살",
    tag: "SPECIMEN NO. 07",
    viewBox: "485 608 282 282",
    story: "유리창에 낀 성에를 하얗게 녹여 밖을 내다보고, 두꺼운 솜이불 속에서 발만 쏙 내민 채 거실 장판 위로 길게 쏟아져 들어오던 햇살을 쬐던 아침.",
    hexes: ["#FDF0D5", "#E9D8A6", "#EE9B00"]
  },
  {
    title: "노을 지는 제방길",
    tag: "SPECIMEN NO. 08",
    viewBox: "880 608 282 282",
    story: "동생 손을 꼭 잡고 자전거를 끌며 둑길을 걷다 마주친, 강물까지 온통 붉게 물들이며 세상을 따스하게 안아주던 장엄한 저녁노을.",
    hexes: ["#F4A261", "#E76F51", "#264653", "#E9C46A"]
  },
  {
    title: "할머니 댁 수박",
    tag: "SPECIMEN NO. 09",
    viewBox: "1275 608 282 282",
    story: "시골 할머니 댁 우물물에 차갑게 담가두었던 수박을 쪼개어, 마당에서 시원하게 등목을 하고 평상에 둘러앉아 씨를 뱉으며 깨어먹던 여름날.",
    hexes: ["#E63946", "#2A9D8F", "#A98467", "#1D3557"]
  },
  {
    title: "늦은 밤 독서실 스탠드",
    tag: "SPECIMEN NO. 10",
    viewBox: "1670 608 282 282",
    story: "칸막이 책상 위 조그만 초록색 스탠드 불빛 아래, 사각거리는 샤프 소리와 함께 차가운 새벽 공기를 마시며 미래를 꿈꾸던 고요한 밤.",
    hexes: ["#FFB703", "#212529", "#432818"]
  }
];

const archiveCards = document.querySelectorAll('.gallery-card');
const archiveDetailModal = document.getElementById('archiveDetailModal');
const archiveModalSvg = document.getElementById('archiveModalSvg');
const archiveModalTag = document.getElementById('archiveModalTag');
const archiveModalTitle = document.getElementById('archiveModalTitle');
const archiveModalMemoryText = document.getElementById('archiveModalMemoryText');
const archiveModalPaletteRow = document.getElementById('archiveModalPaletteRow');
const modalHangerBtn = document.getElementById('modalHangerBtn');

archiveCards.forEach(card => {
  card.addEventListener('mouseenter', () => playRecallChimeHover());

  card.addEventListener('click', () => {
    playMemoryRecallClick();

    const idx = parseInt(card.dataset.id, 10);
    const data = memoryStories[idx];
    if (!data) return;

    if (archiveModalSvg) archiveModalSvg.setAttribute('viewBox', data.viewBox);
    if (archiveModalTag) archiveModalTag.textContent = data.tag;
    if (archiveModalTitle) archiveModalTitle.textContent = data.title;
    if (archiveModalMemoryText) archiveModalMemoryText.textContent = data.story;

    if (archiveModalPaletteRow) {
      archiveModalPaletteRow.innerHTML = '';
      data.hexes.forEach(hex => {
        const chip = document.createElement('span');
        chip.className = 'badge-chip';
        chip.innerHTML = `<span class="dot" style="background-color: ${hex}"></span>${hex}`;
        archiveModalPaletteRow.appendChild(chip);
      });
    }

    if (archiveDetailModal) {
      archiveDetailModal.classList.add('is-active');
      archiveDetailModal.setAttribute('aria-hidden', 'false');
    }
  });
});

function closeArchiveDetailModal() {
  if (archiveDetailModal) {
    archiveDetailModal.classList.remove('is-active');
    archiveDetailModal.setAttribute('aria-hidden', 'true');
  }
}

if (modalHangerBtn) modalHangerBtn.addEventListener('click', closeArchiveDetailModal);
if (archiveDetailModal) {
  archiveDetailModal.addEventListener('click', (e) => {
    if (e.target === archiveDetailModal) closeArchiveDetailModal();
  });
}
