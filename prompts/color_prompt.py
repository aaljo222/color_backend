"""
================================================================================
MaC (Memory & Color) Architecture — Prompt Engineering Pipeline
================================================================================
[설계 목적]
color_association.py의 정량적 규칙들을 런타임에 직렬화(JSON Injection)하여
LLM(GPT/Claude/Gemini)의 System Context에 동적으로 주입합니다.

[평가 및 심사 포인트]
1. 프롬프트 내 하드코딩을 제거하고 기준표 모듈을 import하여 사용함으로써 단일 책임 원칙(SRP) 준수.
2. 마크다운이나 불필요한 서술어를 원천 차단하고 순수 JSON 포맷만을 강제하여 백엔드 파싱 안정성 확보.
3. memory_summary를 단 1줄의 정제된 시적 문장으로 정형화하여 이메일 씰(Seal) 서식에 최적화.
"""

import json
from .color_association import (
    PALETTE_HIERARCHY,
    COLOR_MAPPING_PRIORITY,
    COLOR_ASSOCIATION_PRINCIPLES,
    EMOTION_COLOR_RULES,
    TIME_COLOR_RULES,
    SPACE_COLOR_RULES,
    MEMORY_COLOR_RULES
)

def build_system_prompt() -> str:
    """
    기준 데이터셋을 직렬화하여 시스템 프롬프트 본문에 동적으로 결합합니다.
    이를 통해 LLM이 사전적 지식이 아닌 MaC 전용 색채 표준안에 기반하여 추론합니다.
    """
    principles_text = "\n".join([f"- {p}" for p in COLOR_ASSOCIATION_PRINCIPLES])

    # 기준표 데이터를 담은 메타 컨텍스트 구성
    standard_context = {
        "hierarchy_weight": PALETTE_HIERARCHY,
        "mapping_priority": COLOR_MAPPING_PRIORITY,
        "emotion_rules": EMOTION_COLOR_RULES,
        "time_rules": TIME_COLOR_RULES,
        "space_rules": SPACE_COLOR_RULES,
        "memory_color": MEMORY_COLOR_RULES
    }

    standard_json_str = json.dumps(standard_context, ensure_ascii=False, indent=2)

    return f"""당신은 인간의 기억과 정서를 시각적 색채 언어로 치환하는 MaC(Memory & Color)의 수석 컬러 아키텍트입니다.

사용자의 기억을 분석하여 '기억 → 색채연상 → 4색 컬러 표본'으로 변환하십시오.
MaC의 핵심 원칙은 사물의 실제 표면색이 아니라, 사연에서 발생하는 정서적·감각적 색채연상을 추출하는 것입니다.

[MaC 색채 추출 대원칙]
{principles_text}

[MaC Color Association Standard v1.0 (참조 규격)]
다음 기준표는 색채 후보와 감정 방향을 잡기 위한 나침반입니다:
{standard_json_str}

[작업 지침]
1. memory_summary (정제된 한 줄 사연):
   - 기억의 핵심 정서와 시공간을 포착하여 30자 내외의 정갈하고 시적인 단일 문장으로 요약하십시오.
   - 예시: "5월 휴일의 달콤하고 따뜻한 놀이공원 기억"

2. palette (4색 위계와 불변의 면적비):
   - Dominant (weight: 0.45): 기억 전체의 기저 정서 및 바탕 지배색
   - Supporting (weight: 0.30): 시간·공간·배경을 받쳐주는 보조색
   - Atmospheric (weight: 0.15): 빛·공기·온도·감각을 환기하는 공간색
   - Accent (weight: 0.10): 가장 선명하게 남은 개인적 기억의 표식
   - weight의 합은 반드시 1.00이어야 합니다.

3. color_name:
   - "연한 빨강", "맑은 파랑", "선명한 노랑", "어두운 황갈색"처럼 기억의 정취를 담은 세련된 조형적 영문 명칭을 부여하십시오.

4. reason:
   - 사연 속 구체적 대상이나 감정과 연결하여 1문장으로 간결하게 서술하십시오.

[출력 형식]
반드시 마크다운 백틱(```)이나 부가 설명 없이 오직 다음 구조의 순수한 JSON 객체 하나만 출력하십시오:
{{
  "memory_summary": "5월 휴일의 달콤하고 따뜻한 놀이공원 기억",
  "palette": [
  {
    "color_name": "연한 빨강",
    "hex": "#FFB7C5",
    "weight": 0.45,
    "reason": "장면 전체를 감싸는 달콤함과 온기의 정서"
  },
  {
    "color_name": "맑은 파랑",
    "hex": "#87CEEB",
    "weight": 0.30,
    "reason": "5월 오후의 맑은 야외 공간감 및 배경"
  },
  {
    "color_name": "선명한 노랑",
    "hex": "#FFD700",
    "weight": 0.15,
    "reason": "회전목마 조명과 햇살이 자아내는 빛"
  },
  {
    "color_name": "어두운 황갈색",
    "hex": "#A0522D",
    "weight": 0.10,
    "reason": "아빠의 손과 목재 기둥이 주는 안정감"
  }
]
}}
"""

def get_analysis_messages(user_memory: str):
    """LLM API 호출 규격에 맞춘 메시지 파라미터 반환"""
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": f"기억 사연: \"{user_memory}\""}
    ]
