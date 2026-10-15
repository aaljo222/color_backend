"""
================================================================================
MaC (Memory & Color) Engine Layer — LLM Service Provider
================================================================================
[설계 목적]
1. LLM API 종속성을 상위 비즈니스 로직(analyze.py, test_pipeline.py)과 완전히 격리(Decoupling).
2. 최상위 추론 모델(3.1-pro) 실패 시, 서비스 중단 없이 하위 고속 플래시 모델로 자동 전환(Graceful Failover).
3. 결정론적 파라미터(temperature: 0.0, seed: 42) 강제로 동일 사연 입력 시 재현 가능한 팔레트 도출.
"""

import os
import json
import time
from dotenv import load_dotenv

# .env 환경 변수 로드
load_dotenv()

# [모델 호출 체인 정의]
# 1순위: gemini-3.1-pro-preview  — 문맥 이해도와 은유적 감성 요약 능력이 가장 뛰어남
# 2순위: gemini-3.7-flash — 차세대 고성능 플래시, 고속 처리 및 높은 논리력
# 3순위: gemini-3.6-flash — 최신 표준 플래시 모델, 안정적인 속도 보장
# 4순위: gemini-3.5-flash — 인프라 부하가 분산된 성숙 백업 모델
MODEL_CHAIN = [
    #"gemini-3.1-pro-preview",
    #"gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash"
]

def analyze_memory_with_llm(full_prompt: str) -> dict:
    """
    기억 사연 프롬프트를 전달받아 4색 팔레트 및 요약문을 담은 딕셔너리를 반환합니다.
    
    [핵심 메커니즘]
    - MODEL_CHAIN에 등록된 모델을 순차적으로 탐색합니다.
    - 503(서버 과부하), 429(속도 제한) 발생 시 일시적 장애로 간주하여 지수 대기 후 최대 2회 재시도합니다.
    - 404(모델 미지원) 등 즉각적인 에러는 재시도 없이 바로 다음 모델로 승계합니다.
    """
    # 1. Google Gemini API 인증 키 유효성 검증
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY가 .env 파일에 설정되지 않았습니다. 키를 먼저 등록하세요.")

    # 2. 최신 구글 공식 SDK(google-genai) 클라이언트 인스턴스 초기화
    from google import genai
    client = genai.Client(api_key=gemini_key)

    last_error = None

    # 3. 모델 폴백 체인 순회 (1순위부터 차례대로 시도)
    for model_name in MODEL_CHAIN:
        
        # 4. 각 모델당 일시적 네트워크 글리치 대응을 위해 최대 2회 시도
        for attempt in range(1, 3):
            try:
                print(f"🤖 [Engine] 모델 시도: {model_name} (시도 {attempt}/2)")
                
                # 5. Gemini API 구조화된 콘텐츠 생성 호출
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_prompt,
                    config={
                        # 마크다운 백틱(```json) 없이 순수 JSON 포맷만 반환하도록 강제
                        "response_mime_type": "application/json",
                        
                        # 무작위 샘플링을 완전히 차단하여 동일 입력에 대한 동일 출력 보장
                        "temperature": 0.0,
                        
                        # 난수 시드를 42로 고정하여 결과의 결정론적(Deterministic) 재현성 확보
                        "seed": 42
                    }
                )
                
                # 6. 반환된 텍스트 공백 제거 및 Python Dict 역직렬화
                parsed_json = json.loads(response.text.strip())
                print(f"✅ [Engine] 호출 성공: {model_name}")
                return parsed_json

            except Exception as exc:
                err_text = str(exc)
                last_error = exc
                print(f"⚠️ [Engine] {model_name} 실패: {err_text}")

                # 7. 일시적 장애(트래픽 과부하 또는 Rate Limit) 판별
                # - 503 UNAVAILABLE: 순간 트래픽 폭주
                # - 429 RESOURCE_EXHAUSTED: 분당 요청 수 초과
                if "503" in err_text or "429" in err_text:
                    # 지수 백오프(Exponential Backoff): 1차 2초, 2차 4초 대기
                    sleep_sec = 2 * attempt
                    print(f"⏳ [Engine] 트래픽 병목 감지 — {sleep_sec}초간 대기 후 재시도합니다.")
                    time.sleep(sleep_sec)
                    continue
                else:
                    # 404 NOT_FOUND(모델 만료) 등 즉각 복구 불가능한 에러는 2회차 시도 없이 바로 다음 모델로 전환
                    print(f"⏩ [Engine] 복구 불가 오류 — 다음 순위 백업 모델로 즉시 전환합니다.")
                    break

    # 8. 체인에 등록된 4개 모델이 전부 실패했을 경우 최종 예외 발생
    raise RuntimeError(f"모든 AI 모델 호출에 실패했습니다. 마지막 오류: {last_error}")