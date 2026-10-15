


# MaC 
## **AI Memory-to-Color Specimen Web Service (MVP) Plan**

##  Service Idea
```
본 미션은  
만약 우리의 추억(기억)속에 컬러가 담겨 있다면,  
반대로 컬러 속에 기억(추억)을 넣을 수 있지 않을까 라는 상상속에서 기획되었습니다.
```

## 1. Overview and  Purpose

### 1.1. Overview
- **서비스명**: MaC (Memory & Color | My and Color)
- **슬로건**: *What color is your memory?*
- **정의**: 사용자가 입력한 한 문장의 기억에서 장면, 감각, 시공간, 등의 정서적 단서를 AI가 분석하여 고유의 맞춤 색면추상화(유료) 및 정량적 HEX 코드와 MaC 라이브러리 기반 SPECIMEN(색표본) 컬러칩 코드로 추출하는 프라이빗 색채 서비스

### 1.2 Service Purpose: 
본 서비스의 목적은 단순한 감정 진단이나 기계적 감성 분석이 아닙니다.   

"무형의 언어적 기억을 영구 보존 가능한 정량적 색채 데이터로 변환·아카이빙하는 시스템 구축" 입니다.

1. **언어적 기억의 시각적 영구화 (Visual Preservation)**  
시간이 지남에 따라 점차 희미해지고 왜곡되기 쉬운 개인의 기억과 순간의 감각(시간, 날씨, 빛, 분위기)을 시각 매체인 4색 팔레트로 고정하여 영구히 간직할 수 있는 기록 체계를 만듭니다.
2. **주관적 감각의 정량적 데이터화 (Sensory Quantification)**  
“따스했던 5월의 햇살”처럼 모호하고 추상적인 언어 표현을 디자인 툴과 웹 환경에서 즉시 사용할 수 있는 16진수 표준 규격(HEX Code)으로 환원하여 데이터화합니다.
3. **독자적 기억색 표본 규격 정립 (Proprietary Specimen Standard)**  
타사 상표권(예.Pantone 등)에 종속되지 않는 웹 표준 기반의 독자 표본 규격인 **MaC SPECIMEN** 을 정의하여, memory 색채 아카이브를 확장할 수 있는 시스템 기반을 마련합니다.  

---

## 2. Target Users

>### 2.1. Primary Target: 전문 컬러 디자이너 및 창작자
- 주관적인 영감과 기억을 온전한 색채 덩어리로 시각화하고, 이를 실제 조형 작업 및 제품 기획에 즉시 활용할 수 있는 정량적 컬러 데이터(HEX Code)로 환원하여 상업화하려는 전문가 (그래픽 디자이너, 브랜드 디자이너, CMF 디자이너, 아티스트, 상품 기획자).

>### 2.2 Secondary Target: 기록과 정서 정리를 원하는 일반 사용자
- 일상 속 특별한 순간이나 복잡한 내면의 감정을 글이나 사진이 아닌 정갈한 색채 표본으로 암호화하고 싶은 사용자.

---

## 3. Page Architecture

MaC 은 단일 페이지(Single Page Application) 내 직관적인 3단계 섹션으로 구성됩니다.  
또한 ,
MaC 은 단일 페이지 애플리케이션(SPA) 구조 위에서 사용자의 흐름이 끊기지 않도록 상단 고정 네비게이션(Global Navigation Bar) 기반의 부드러운 스크롤 이동(Smooth Scroll Anchor) 방식을 채택합니다.
```
[ 상단 고정 헤더 GNB ]
[ 로고: MaC ] ────────────── [ ARCHIVE (Main) ] ── [ GALLERY ] ── [ CONTACT ]
                                    │                   │              │
                                    ▼                   ▼              ▼
                              #main-section      #gallery-section  #contact-section
                               (색채 추출)         (표본 아카이브)    (고객센터 문의)  
```                               
                          
<br>  

| 섹션 | 명칭 | 세부 구성 및 기능 |
| :--- | :--- | :--- |
| **Section 1** | **Main (Hero & Extraction)** | - 헤더에 대표 레퍼런스 이미지<br>- **기억 문장 입력 필드** (One Sentence Memory)<br>- **이메일 입력 필드** (결과 수신용)<br>- Resend API를 통해 관리자 계정(`MaC@mac.ai.kr`)에서 전송<br>- [추억색 추출] [사주기반 서비스-유료] CTA 버튼<br>- **Modal Result Window**: 추출 완료 시 섹션 이동 없이 4색 칩, 색상명, HEX, MaC SPECIMEN, 입력 문장, 결과 해석 |
| **Section 2** | **Gallery (Archive)** | - 생성된 대표 HEX 값 표기 아카이브 카드<br>- 문장, 해당 색면추상화, 컬러칩, 확장 서비스 예시 전시로 시각적 가능성 제시 |
| **Section 3** | **Customer Center (Inquiry)** | - 이름, 이메일, 문의 내용을 입력하는 피드백/지원 폼<br>- Resend API를 통해 컨시어지 계정(`concierge@mac.ai.kr`)으로 전송 (유료 서비스 시) |  

---

## 4. AI Features & Logic  

### 4.1. 입출력 규격 I/O Specification
- **Input**: 사용자가 작성한 단일 문장의 기억 텍스트 (문자 수 10~300자 제한) + 수신용 이메일
- **Core Engine**: Google Gemini 2.5 Flash(가변)
- **Output**: 엄격한 4단계 계층 JSON 구조 (Dominant 45%, Supporting 30%, Atmospheric 15%, Accent 10%)
  - 기억 요약문 (`memory_summary`)
  - 모델 신뢰도 점수 (`confidence`: 0.0 ~ 1.0)
  - 4색 팔레트 배열 (`palette`):
    - `role`: 색채 역할 (`dominant`, `supporting`, `atmospheric`, `accent`)
    - `color_name`: 표본 색상명 (예: `Sugar Pink`)
    - `hex`: 웹 표준 대문자 16진수 색상 코드 (`#RRGGBB`)
    - `area_ratio`: 화면 배색 면적비 (합계 1.0)
    - `reason`: 색채 선정 근거 문장



```json
{
  "specimen_hash": "MaC-8F4E2B9A",
  "memory_summary": "5월 휴일의 달콤하고 따뜻한 유원지 기억",
  "confidence": 0.94,
  "palette": [
    {
      "role": "dominant",
      "color_name": "Sugar Pink",
      "hex": "#FFB7C5",
      "area_ratio": 0.45,
      "reason": "장면 전체를 지배하는 솜사탕의 달콤함과 포근한 정서 외재화"
    },
    {
      "role": "supporting",
      "color_name": "May Sky",
      "hex": "#87CEEB",
      "area_ratio": 0.30,
      "reason": "5월 오후의 맑은 야외 공간감 및 시각적 배경"
    },
    {
      "role": "atmospheric",
      "color_name": "Carousel Gold",
      "hex": "#FFD700",
      "area_ratio": 0.15,
      "reason": "회전목마 불빛과 햇살이 자아내는 시간의 빛"
    },
    {
      "role": "accent",
      "color_name": "Warm Brown",
      "hex": "#A0522D",
      "area_ratio": 0.10,
      "reason": "아빠의 손과 목재 기둥이 주는 안정감 있는 시각적 모티브"
    }
  ]
}
```

>### 4.2. 실패 처리 및 예외 기준 (Error Handling Standards)

>시스템의 안정성과 사용자 경험을 위해 다음과 같은 계층별 예외 처리 기준을 적용합니다.

* **입력 유효성 검증 실패 (`HTTP 400 Bad Request`)**
  * **조건**: 기억 문장이 공백이거나 10자 미만인 경우, 또는 이메일 정규식 포맷에 맞지 않는 경우
  * **처리**: 서버 자원 소모(Gemini API 호출)를 사전에 차단하고, 사용자 화면에 즉각적인 안내 메시지를 반환합니다.
    * 문장 오류: `"기억 문장을 최소 10자 이상 구체적으로 입력해 주세요."`
    * 이메일 오류: `"올바른 이메일 주소 형식을 입력해 주세요."`

* **AI 추론 및 JSON 파싱 실패 (`HTTP 502 Bad Gateway`)**
  * **조건**: Gemini API 호출 타임아웃, 비정상 텍스트 반환, 필수 스키마(`palette`, `specimen_code` 등) 누락
  * **처리**: 백엔드 내부에서 최대 1회 즉시 재호출(Retry)을 시도하며, 지속 실패 시 시스템 에러 문구 대신 친화적 가이드 메시지를 반환합니다.
    * 반환 메시지: `"색채 표본 추출에 실패했습니다. 문장을 조금 더 구체적으로 작성해 주세요."`

* **HEX 데이터 형식 오류 (`Validation Error`)**
  * **조건**: 생성된 색상 코드가 대문자 6자리 16진수 규격(`^#[0-9A-F]{6}$`)을 충족하지 못하는 경우
  * **처리**: 비정상 데이터로 판단하여 화면 렌더링 및 이메일 발송을 중단하고 파싱 재시도 로직으로 이관합니다.

* **이메일 발송 실패 (`Resend API Error`)**
  * **조건**: 네트워크 단절, 도메인 인증 일시 오류, 수신자 주소 불능 등으로 Resend 전송 실패
  * **처리**: 
    * **추억색 결과 발송**: 웹 화면 모달(Modal)에는 정상적으로 추출된 4색 표본을 즉시 표시하여 사용자 경험을 단절시키지 않으며, 실패 로그만 서버에 기록합니다.
    * **고객센터 문의 폼**: 백엔드에서 동일한 멱등성 키(Idempotency Key)를 사용하여 최대 3회 자동 재시도하며, 최종 실패 시 `"문의 전송에 실패했습니다. 잠시 후 다시 시도해 주세요."` 알림을 노출합니다.

---

## 5. Service Value 
>### **User Value**
1. **감정의 탈중심화와 관찰 가치 (Emotional Decentering & Objectification)**  
기억과 뒤엉켜 있던 주관적인 감정(기쁨, 그리움, 슬픔)을 #FFB7C5, #87CEEB와 같은 독립된 물리적 데이터로 분리해 줍니다.
"내가 곧 그 감정"이었던 상태에서 벗어나, 자신의 기억을 한 발짝 떨어져 관조할 수 있는 심리적 여백과 정서 정리 경험을 제공합니다.
2. **나만의 비밀 암호로서의 개인화 가치 (Personalized Subjective Polysemy)** 
사실적인 사진은 타인에게도 뻔한 장면이 되지만, 기억을 색면 덩어리로 압축한 팔레트는 타인에게는 단순하고 감각적인 배색 디자인으로 보일 뿐이지만 나에게는 그날의 공기, 빛, 온도를 즉각 호출하는 '오직 나만 알고 있는 사적 암호'를 소장하는 특별함입니다.
3. **상업적 환원이 가능한 정량화 가치 (Quantified Creative Asset)**  
머릿속의 막연한 영감을 디자이너가 즉시 일러스트, 웹 디자인, 브랜드 아이덴티티, 굿즈 제작에 복사해 쓸 수 있는 정밀한 16진수 HEX 코드로 환원하여 창작 실무의 원천 소스로 기능합니다.


