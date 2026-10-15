![놀이공원](./images/reference.png)
# MaC
### [ Memory and Color | My and Color ] 

*당신의 추억을 한 줄로 남겨주세요.  
당신의 기억을,  
색으로 돌려드립니다.*  
<br><br> 

---
### Key ideas:   
Cognitive Externalization  
Synesthetic Visualization  
Chromatic Cryptography / Color Encoding  
Memory Coordinate Mapping  
MaC SPECIMEN code (Standardization)  
<br><br>
## Introduction
> ** *What color is your memory?* **  
> 언어로 표현된 개인의 기억을 AI로 해석하여 4색의 디지털 색채 표본(MaC SPECIMEN)과 정량적 HEX 데이터로 환원하는 웹 서비스.
MaC는 보이지 않는 내면의 감각과 기억을 관찰 가능한 색채로 변환하는 시각화 서비스 입니다. 

- **주관적 다의성의 보존**: 타인에게는 단순한 추상 색면이지만, 본인에게는 기억의 공감각적 온도를 복원하는 고유한 암호로 작동합니다.
- **정서의 외재화(Externalization)**: "내가 곧 감정"인 상태에서 벗어나, 내면의 기억을 `#FFB7C5`와 같은 구체적인 데이터 덩어리로 변환하여 객관적으로 마주합니다.
- **MaC SPECIMEN 체계**: 국제 공식 표준이 아닌, MaC 프로젝트만의 독립적인 디지털 기억색 표본 규격으로 상표권 침해 없이 안전하게 결과물을 영구 보존합니다.

---
<br><br>
## Tech Stack

| 계층 | 사용 기술 | 설명 |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript | 의존성 없는 가벼운 반응형 웹 UI, CSS 그리드 기반 모달 |
| **Backend** | Python 3.12+, Serverless Function (`api/analyze.py`) | Vercel Serverless 기반 API 핸들러 및 템플릿 렌더러 |
| **AI Engine** | Google Gemini 2.5 Flash(가변)| `temperature=0.0` 제어로 동일 입력 재현성 가능 |
| **Email** | Resend API | 도메인(`mac.ai.kr`) 인증 기반 트랜잭션 이메일 자동 발송 |
| **Data/Color**| JSON, HEX (`#RRGGBB`), sRGB,  MaC 색표본(기억 기반 도출 색표본) | 웹 표준 규격 데이터 인터체인지 |

---
<br><br>
## Deployment URLs

- **Production Service**: `https://mac.ai.kr` (또는 Vercel 배포 도메인)
- **GitHub Repository**: `https://github.com/OZ-Codessey/MaC.git`

---
<br><br>
## ⚙️ Environment Setup

터미널(Terminal) 환경에서 아래 명령어를 순서대로 실행하여 로컬 개발 환경을 구축합니다.

```bash
# 1. 저장소 복제 및 디렉토리 이동
cd Desktop
git clone [https://github.com/OZ-Codessey/MaC.git](https://github.com/OZ-Codessey/MaC.git)
cd MaC

# 2. 가상환경 생성 및 활성화 (macOS/Linux)
python3 -m venv venv
source venv/bin/activate

# 3. 백엔드 의존성 패키지 설치
pip3 install -r requirements.txt  

```
<br>  

>##  🔐 Environment Variables  

보안을 위해 모든 API Secret Key는 소스 코드에 커밋하지 않으며, 배포 플랫폼(Vercel) 및 로컬 환경 변수(.env)를 통해 격리 관리합니다.  
채워 넣을 수 있습니다.
| 구분 | 항목 / 변수명 | 상세 설명 | 비고 / 발급처 |
| :--- | :--- | :--- | :--- |
| **필수 환경 변수** | `GEMINI_API_KEY` | 기억 서사 분석 및 4색 팔레트 추출을 위한 AI Key | [Google AI Studio](https://aistudio.google.com/) |
| **필수 환경 변수** | `RESEND_API_KEY` | 분석 결과표 및 컨시어지 의뢰 메일 발송용 Key | [Resend](https://resend.com/) |
| **로컬 환경 설정** | `.env` 생성 | 프로젝트 루트 디렉토리에 생성 후 발급받은 키 입력 (`.env.example` 활용) | `.gitignore`에 등록되어 GitHub에 노출되지 않음 |
| 📌 **Tip** | `cp .env.example .env` | 로컬 환경 구성 시 터미널에서 템플릿을 복사하여 즉시 환경 변수를 설정할 수 있습니다. | CLI 명령어 |  

<br> <br>

# 🌐 How to Run  

###  **Option A. Vercel CLI 로컬 구동 (권장)**
프론트엔드와 Python 서버리스 함수(api/analyze.py)를 프로덕션 환경과 동일하게 로컬에서 통합 실행합니다.  
```  
# Vercel CLI 설치 (최초 1회)
npm install -g vercel

# 로컬 통합 개발 서버 구동
vercel dev
```  

### **Option B. 단독 백엔드 스크립트 실행** 
서버리스 함수와 별개로 로컬 파이썬 메인 로직만 단독으로 테스트할 경우 실행합니다.  
```
python3 main.py
```  
<br>  

## ☁️ Production Deployment (Vercel) 

Vercel 클라우드 환경에서 서버리스 함수가 안전하게 동작하도록 대시보드 설정을 완료합니다.  
1. Vercel Dashboard 접속 후 MaC 프로젝트 선택  
2. Settings → Environment Variables 탭 이동  
3. Type: Secret 상태로 환경 변수 등록 후 Save:  
>- GEMINI_API_KEY
>- RESEND_API_KEY  
4. Deployments 탭에서 최신 배포 항목의 Redeploy를 실행하여 키를 반영합니다.  
<br>

### 👮🏼‍♂️ Compliance & Security Notice 
```
1. 독자적 표본 체계: 본 서비스의 색채 표본 체계는 독자적인 MaC SPECIMEN을 기반으로 작동하며, PANTONE®을 포함한 타사 상표권을 침해하지 않습니다.  

2. 보안 격리: 모든 API Key와 인증 토큰은 환경 변수로 암호화 관리되며 클라이언트 번들에 노출되지 않습니다.  
```
<br><br>

## 🔍 Commit Log  


| No. | Commit Hash | Commit Message |  기능 및 주요 작업 내역 |
| :---: | :---: | :--- | :--- |
| **1** | `817f381` | feat: Initialize MaC project skeleton and environment settings | MaC 프로젝트 기본 뼈대 구조 생성 및 개발 환경 초기 세팅 |
| **2** | `e35f938` | WIP | 기본 기능 구현 진행 중 임시 작업 내역 저장 (Work In Progress) |
| **3** | `d392dde` | feat: Memory Archive 갤러리 기본 UI 구현 | 10종 큐레이션 작품 배치를 위한 메모리 아카이브 갤러리 기본 그리드 UI 제작 |
| **4** | `fd0876a` | feat: build private contact form with responsive 2-way inquiry options | 디바이스 규격에 따라 축약/전체 텍스트가 전환되는 프라이빗 컨시어지 폼 구축 |
| **5** | `90704e1` | chore: update .gitignore | 로컬 환경 변수(`.env`) 및 불필요한 설정 파일의 원격 저장소 누출 방지 처리 |
| **6** | `4a7f8d7` | feat(ux): implement multi-sensory micro-interactions with Web Audio API, dynamic lighting, and modal zoom viewer | **[보너스 과제 2: UX 고도화]** Web Audio API 기반 어쿠스틱 사운드 피드백, 갤러리 카드 호버 라이팅, 작품 줌 뷰어 등 감각적 마이크로 인터랙션 구현 |
| **7** | `db2ca84` | feat(concierge): build inline validation speech tooltips and anchored async notification system | **[보너스 과제 2: UX 고도화]** 브라우저 기본 alert를 대체하는 필드별 유효성 말풍선 툴팁 및 버튼 상단 고정 비동기 상태 알림 시스템 구축 |
| **8** | `b1b42a3` | chore: finalize .gitignore settings | 프로젝트 전반의 Git 추적 제외 대상 목록 최종 점검 및 고도화 |
| **9** | `6141d79` | Add files via upload | 프로젝트에 사용되는 필수 레퍼런스 원화 및 그래픽 이미지 에셋 추가 |
| **10** | `e6cd446` | feat: build architectural 2-column hero layout and integrate synthesized chime audio | **[보너스 과제 2: UX 고도화]** 2열 히어로 레이아웃 배치 및 튜닝포크 어쿠스틱 차임벨 청각 인터랙션 연동 |
| **11** | `92cb756` | feat: implement reference artwork lightbox modal with easel halo ambient lighting | **[보너스 과제 2: UX 고도화]** 이젤 후광 조명(Halo) 연출을 적용한 원화 라이트박스 팝업 모달 인터랙션 구현 |
| **12** | `8983f1a` | feat: add Astral color service-readiness modal with birth date input field | 생년월일 입력 기반 사주 오행 수호색 서비스 준비 중 안내용 모달 컴포넌트 추가 |
| **13** | `9b87d69` | style: polish editorial typography flow and add full-screen mobile navigation drawer | **[보너스 과제 2: UX 고도화]** 모바일 전용 풀스크린 네비게이션 드로어 메뉴 및 가변 에디토리얼 타이포그래피 구현 |
| **14** | `54012c3` | style: match social button background tone precisely with About Color typography | 소셜 링크 버튼의 웜 골드 배경색을 메인 텍스트 톤앤매너와 정밀 일치화 |
| **15** | `926dd62` | Refactor: Modularize chromatic pipeline and automate email delivery | **[보너스 과제 1: 운영 자동화]** CIELAB 색채 연산 엔진 모듈화 및 Resend API를 연동하여 AI 분석 결과표 이메일 자동 발송 파이프라인 구축 |
| **16** | `7339952` | Feat: Build interactive specimen modal prototype featuring genie motion and acoustic cues | **[보너스 과제 2: UX 고도화]** 지니 흡입 인터랙션 애니메이션 및 음향 큐가 적용된 색채 표본 인터랙티브 모달 제작 |
| **17** | `62ae657` | fix: improve layered error handling and UX | **[보너스 과제 2: UX 고도화]** 계층별 예외 처리(400 유효성, 502 재시도) 기준 수립 및 사용자 입력 오류 피드백 UX 개선 |
| **18** | `ac9a47e` | feat: connect dynamic specimen modal to API and restore navigation modals | 동적 색채 모달과 백엔드 API 간 실시간 통신 연동 및 상단 네비게이션 모달 복원 |
| **19** | `7ae15b7` | Merge branch 'main' of https://github.com/OZ-Codessey/MaC | 원격 저장소의 최신 브랜치 변경 내역 동기화 및 병합 (Merge) |
| **20** | `b9ae977` | feat(concierge): integrate resilient inquiry dispatch, dynamic fluid typography, and bespoke salon notification UX | **[보너스 과제 1 & 2 복합 적용]**<br>1. **운영 자동화**: 컨시어지 폼 입력을 Resend 트랜잭션 엔진을 통해 운영자 사서함(`Concierge@mac.ai.kr`)으로 실시간 전달하는 운영 알림 파이프라인 구축<br>2. **UX 고도화**: 모바일 가변 폰트, 전송 인지 시간 확보 및 5초 자동 소멸 피드백 안내 바 UX 연동 |  


<br><br><br>

 
<details>
<summary><b>🌲 Directory Structure (클릭하여 펼치기)</b></summary>

```text
MaC/
├── MaC.html                    # [Entry Point] 프론트엔드 단일 통합 실행 파일
├── emailTemplate.html          # Resend 발송용 색채 표본 HTML 서식
├── favi.html                   # 파비콘 및 브라우저 메타 태그 컴포넌트
├── requirements.txt            # Python 의존성 라이브러리 목록 (resend 등)
├── vercel.json                 # Vercel 배포 및 라우팅 제어 설정
├── .env                        # 로컬 보안 환경 변수 (API Keys)
├── .gitignore                  # Git 추적 제외 설정
├── SERVICE_PLAN.md             # 서비스 기획안 및 정책 정의서
├── README.md                   # 프로젝트 리드미 문서
│
├── api/                        # Vercel Serverless 백엔드 엔드포인트
│   └── analyze.py              # 분석 요청 수신 및 듀얼 라인 제어 핸들러
│
├── html/                       # [모듈화] 섹션별 분할 마크업
│   ├── section01.html          # 히어로/입력폼/상단 네비 모달/결과 모달
│   ├── section02.html          # Memory Archive 갤러리 10점 + 상세 모달
│   └── section03.html          # MaC Concierge 프라이빗 문의 폼
│
├── css/                        # [모듈화] 계층형 스타일시트
│   ├── shared.css              # 전역 리셋, 컬러 시스템, 네비, 공용 모달
│   ├── section01.css           # 히어로 섹션 및 2-컬럼 레이아웃 전용 스타일
│   ├── section02.css           # 갤러리 5열 그리드 및 팝업 상세 스타일
│   ├── section03.css           # 컨시어지 폼 및 상태 안내 바 스타일
│   └── style.css               # 프론트 통합 스타일시트
│
├── js/                         # [모듈화] 인터랙션 스크립트
│   ├── shared.js               # Web Audio 엔진, 네비 모달, Escape 제어
│   ├── section01.js            # 색채 합성 폼 비동기 전송 및 지니 모달
│   ├── section02.js            # 갤러리 데이터 바인딩 및 상세 팝업
│   ├── section03.js            # 컨시어지 5초 자동 복구 UX 피드백
│   └── main.js                 # 프론트엔드 스크립트 통합본
│
├── prompts/                    # AI 추론 프롬프트 엔지니어링 모듈
│   ├── color_prompt.py         # Gemini 색채 분석 구조화 시스템 프롬프트
│   └── color_association.py    # 색채 심리 및 감정-색채 매핑 정의 모듈
│
├── services/                   # 백엔드 핵심 비즈니스 로직
│   ├── __init__.py             # Python 패키지 초기화
│   └── llm_engine.py           # Gemini AI 모델 결합 분리 추론 엔진
│
├── images/                     # 웹사이트 정적 그래픽 및 원화 자산
│   ├── gallery.png             # 아카이브 전시작 스프라이트 이미지
│   ├── generReference.png      # 레퍼런스 무드 원화 아트워크
│   └── reference.png           # 파비콘 및 참조 심볼
│
└── records/                    # 커밋 스크린샷 및 프로젝트 증빙 기록물

```
</details>  


<br>

```
🔮 중요
MaC 은 의료·치료용 서비스가 아니며, 추상적인 언어 기억을 정량적 디지털 데이터(HEX)로 변환해 소장성과 창작 영감을 제공하는 색채 아카이빙 서비스 입니다. 그러나 제작자의 의도와는 무관하게 드물게는 개인에 따라 치료나 치유 효과를 줄 수는 있습니다.
```



