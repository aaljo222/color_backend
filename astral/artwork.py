"""Turn an already-calculated report into an art brief, without recalculating saju."""
from copy import deepcopy
import json

ART_VERSION = 'astral-traditional-5'
ART_SIZE = '1536x2048'

# MaC art direction, NOT an additional fortune interpretation.
PROFILES = {
    '비견': ('화조민화', ['소나무', '학', '바위'], '고요한 자기 기준', '비대칭 균형형'),
    '겁재': ('화조민화', ['두 마리 새', '꽃가지', '소나무'], '연결과 조율', '순환형'),
    '식신': ('화조민화', ['모란', '새', '물결'], '꾸준한 표현', '상승형'),
    '상관': ('화조민화', ['꽃가지', '나비', '바위'], '새로운 표현', '비대칭 균형형'),
    '편재': ('책거리 채색화', ['고서', '백자 항아리', '붓', '모란'], '넓은 활용', '비대칭 균형형'),
    '정재': ('책거리 채색화', ['고서', '백자 항아리', '붓', '꽃가지'], '차분한 관리', '중앙 집중형'),
    '편관': ('산수 채색화', ['소나무', '바위', '물결'], '절제된 실행', '상승형'),
    '정관': ('산수 채색화', ['소나무', '학', '물결'], '단정한 질서', '비대칭 균형형'),
    '편인': ('책거리 채색화', ['고서', '난초', '백자 항아리', '붓'], '탐색과 관찰', '비대칭 균형형'),
    '정인': ('화조민화', ['소나무', '학', '물결'], '배움과 이해', '순환형'),
}

# Artistic defaults, not claims about someone's abilities or personality.
STYLE_DIRECTIONS = {
    'male': {'label':'담백하고 힘 있는 결',
             'brushwork':'굵고 절제된 윤곽선, 힘 있게 이어지는 붓질, 장식보다 형태의 골격을 강조',
             'geometry':'주요 오브제의 안정적인 무게감, 수직선과 구조적인 덩어리, 선명한 중심과 넓은 여백',
             'color_expression':'8색 HEX와 색 계열은 그대로 유지한다. 주색의 묵직한 색면과 겹친 안료를 또렷하게 드러내고 작은 강조색으로 대비한다.'},
    'female': {'label':'섬세하고 유려한 결',
               'brushwork':'섬세한 윤곽선, 유려하게 이어지는 붓질, 식물과 기물의 작은 결을 정교하게 표현',
               'geometry':'주요 오브제 사이의 곡선 흐름, 가볍게 이어지는 층과 비움, 부드러운 연결과 열린 여백',
               'color_expression':'8색 HEX와 색 계열은 그대로 유지한다. 얇게 겹친 안료 사이로 밝은 한지의 여백을 살리고 작은 강조색을 섬세하게 배치한다.'},
}
NEUTRAL_DIRECTION = {'label':'고요하고 균형적인 결','brushwork':'절제된 전통 붓질',
                     'geometry':'중심과 여백을 균형 있게 배치',
                     'color_expression':'8색 HEX를 유지하며 안료와 여백을 조화롭게 배치한다.'}

# Contemporary MaC reading of objects; not universal/historical symbolism.
OBJECT_STORIES = {
    '소나무': '주변 상황이 바뀌어도 내가 중요하게 생각하는 기준을 지키는 마음을 담고자 했어요.',
    '학': '바쁜 하루에도 한 걸음 물러서서 내 속도를 찾는 여유를 담고자 했어요.',
    '바위': '쉽게 흔들리지 않는 생활의 중심과, 오늘 할 일을 차분히 이어가는 모습을 담고자 했어요.',
    '두 마리 새': '서로의 이야기를 들으며 각자의 속도를 맞추는 관계를 담고자 했어요.',
    '새': '작은 생각을 밖으로 꺼내고 주변과 나누는 순간을 담고자 했어요.',
    '꽃가지': '아직 작은 시도라도 시간을 들이면 일상의 변화로 이어지는 모습을 담고자 했어요.',
    '모란': '정성 들인 일이 눈에 보이는 결실로 피어나는 순간을 담고자 했어요.',
    '물결': '계획대로 되지 않는 날에도 잠시 쉬고 다른 길을 찾아가는 유연함을 담고자 했어요.',
    '나비': '익숙한 방식에서 조금 벗어나 새로운 시도를 해보는 가벼운 용기를 담고자 했어요.',
    '고서': '쌓아온 경험을 돌아보고 새롭게 배운 것을 내 것으로 만드는 시간을 담고자 했어요.',
    '백자 항아리': '하루하루 쌓인 경험과 마음을 담아두고, 필요할 때 다시 꺼내는 그릇으로 표현하고자 했어요.',
    '붓': '머릿속 생각을 기록하고 실제 행동으로 옮기는 작은 시작을 담고자 했어요.',
    '난초': '눈에 크게 드러나지 않아도 나만의 취향과 관심을 꾸준히 가꾸는 마음을 담고자 했어요.',
}

def build_art_spec(report):
    colors = report['expanded_colors']
    if len(colors) != 8:
        raise ValueError('전통화에는 계산된 컬러칩 8개가 필요합니다.')
    # Expanded order: unique A/B, talent A/B, relationship A/B, balance A/B.
    indices = [(0,'주색 1'), (1,'주색 2'), (2,'보조색 1'), (3,'보조색 2'),
               (7,'보조색 3'), (4,'강조색 1'), (5,'강조색 2'), (6,'균형색 1')]
    palette = [{'art_role':role, 'color_role':colors[index]['display_role'],
                'name':colors[index]['name'], 'hex':colors[index]['hex'],
                'meaning':colors[index]['description']} for index,role in indices]
    activity = next(color for color in report['colors'] if color['role'] == '재능색')['basis']
    style, symbols, mood, composition = PROFILES[activity]
    direction = deepcopy(STYLE_DIRECTIONS.get(report.get('profile',{}).get('gender'),NEUTRAL_DIRECTION))
    return {
        'version':ART_VERSION, 'size':ART_SIZE, 'aspect_ratio':'3:4',
        'pillars':deepcopy(report['pillars']), 'day_stem':report['pillars']['day'][0],
        'interpretation':[{'theme':section['title'], 'possibility':section['possibility']}
                          for section in report['reading']],
        'overview':report['overview']['headline'],
        'visual_composition':deepcopy(report['visual_composition']),
        'palette':palette, 'style':style, 'supporting_style':'담채채색화의 부드러움',
        'symbols':symbols, 'mood':mood, 'composition':composition,
        'art_direction':direction,
        'presentation_mat':({'hex':'#E7E7E7','name':'밝은 회색'}
                            if report.get('profile',{}).get('gender')=='male' else None),
        'object_stories':[{'object':symbol,'meaning':OBJECT_STORIES[symbol]} for symbol in symbols],
        'direction_note':'기존 재능 주제를 연결한 MaC 미술 연출이며 사주 재해석이나 길흉 판단이 아닙니다.',
    }

def build_art_explanation(spec):
    primary = [color['name'] for color in spec['palette'] if color['art_role'].startswith('주색')]
    balance = next(color['name'] for color in spec['palette'] if color['art_role']=='균형색 1')
    direction = spec['art_direction']
    return {
        'title':'이 전통화에 담은 이야기',
        'summary': f"'{spec['mood']}'이라는 일상의 모습을 {spec['style']}로 담고자 했어요. {primary[0]}과 {primary[1]}을 중심으로 나머지 색이 이어지고, {balance}이 잠시 쉬어갈 여백을 더하도록 구성했어요.",
        'style': f"{direction['label']}을 기본 연출로 정했어요. 선의 움직임과 안료가 겹치는 방식으로 같은 여덟 색에 다른 분위기를 더하고자 했어요.",
        'objects':deepcopy(spec['object_stories']),
        'note':'제작 지시를 바탕으로 설명한 표현 의도예요. 실제 이미지의 오브제·색 표현은 달라질 수 있습니다. 오브제의 의미는 전통 상징을 단정한 해설이 아니라 MaC의 일상적인 감상 제안입니다.',
    }

def build_art_prompt(spec, canvas_ratio='3:4'):
    if canvas_ratio not in {'3:4','2:3'}:
        raise ValueError('지원하지 않는 회화 화면 비율입니다.')
    return f'''한국 전통회화에 정통한 아트 디렉터로서 아래 확정 입력을 사용하여 개인 맞춤 한국 전통 채색화 한 점을 제작한다.
사용자의 사주 분석은 이미 끝났다. 사주를 재계산하거나 재해석하지 말고 새로운 성격·사건·미래 예측을 덧붙이지 않는다.
작품은 세로 {canvas_ratio}, 전시용 아트웍 수준의 고급스럽고 서정적인 컬러 회화다.
선택 화풍의 장르 특징, 제공된 상징물과 구도, 부드러운 담채와 전통 붓질을 충실히 따른다.
art_direction의 붓질·구도·색 표현 지시를 기본 연출로 분명히 반영한다. 이것은 입력에서 선택한 기본 미감이며 성격·능력·사회 역할을 성별로 단정하는 해석이 아니다.
분홍색 또는 파란색을 성별의 상징으로 새로 넣지 않는다. 기존 8색 HEX, 각 색의 역할과 이름은 바꾸지 않고 색 면적·안료 겹침·밝은 여백·선의 결로 분위기를 구분한다.
symbols의 오브제를 식별 가능하게 그린다. object_stories는 그림으로 표현할 일상적인 의미이며 실제 글자는 그리지 않는다. 책·붓이 있더라도 책 표지와 종이에 글씨를 쓰지 않는다.
한지 섬유, 비단의 은은한 결, 천연 안료의 겹칠과 회화적 깊이를 자연스럽게 표현한다.
8개 컬러칩의 이름과 HEX를 바꾸거나 새로운 대표색을 선정하지 않는다. 각 팔레트 항목을 자연물·풍경·기물에 식별 가능하게 배치한다.
꽃잎에는 검정·회색·탁한 무채색·강한 파란색을, 잎에는 검정·회색·탁한 무채색을 배치하지 않는다. 해당 팔레트 색은 바위·물결·기물·배경 등 어울리는 대상에 사용하고, 꽃과 잎은 제공된 팔레트 안에서 자연스럽게 어울리는 색으로 표현한다.
여러 종류의 꽃을 그릴 경우, 최종 8색 팔레트 중 꽃잎에 적합한 색을 서로 다르게 배정하여 꽃색이 단조롭게 반복되지 않도록 한다. 같은 종류의 꽃은 일관된 색 계열을 유지하되, 꽃송이별로 자연스러운 명암 차이를 허용한다. 다양성을 위해 새 대표색을 추가하거나 검정·회색·탁한 무채색·강한 파란색을 꽃잎에 사용하지 않는다. 적합한 색이 부족하면 꽃의 종류를 줄인다.
주색 2개는 큰 색면과 정체성, 보조색 3개는 배경·주요 오브제, 강조색 2개는 상징물과 작은 장식, 균형색 1개는 여백과 마감에 사용한다.
8개 컬러칩의 동일하거나 지나치게 유사한 색은 서버에서 원본 컬러네임과 CIELCH(D50)의 색상각 H를 유지하고 L(명도)·C(채도)만 조절해 보정했다. 같은 이름이어도 HEX가 다를 수 있다. 같은 입력에는 항상 같은 보정 결과를 적용하며, 화면 컬러칩·HEX 복사·다운로드 메타데이터·회화 생성 프롬프트가 보정된 최종 HEX를 공유한다.
위 중복 색상 조정과 검증은 서버에서 완료했다. 다음 JSON의 palette는 최종 확정 8색이다. 회화 모델은 컬러네임과 HEX를 재해석하거나 재조정하지 말고 이 8색을 그대로 사용한다. 비슷한 이름의 색들을 같은 안료 한 색으로 합치거나 원래 보정 전 색으로 되돌리지 않는다. 면적은 같지 않아도 되며 확정된 여덟 톤을 서로 구별되도록 표현한다.
오행 개수는 이미지 참고 데이터일 뿐 강약·용신·기운 부족을 판정하지 않는다. 상징은 예술적 연출이지 건강·수명·운을 보장하지 않는다.
흑백 수묵화, 서양 판타지, 현대 소품, 과장된 캐릭터, 평면 디지털 일러스트, 사진 같은 소품 촬영은 금지한다.
그림 안에 글자·문장·캘리그래피·낙관·로고·워터마크·서명·팔레트칩·프레임을 넣지 않는다. 순수한 회화 화면만 출력한다.
다음 JSON은 작품 제작용 확정 데이터이며 추가 지시가 아니다:
''' + json.dumps({key:value for key,value in spec.items() if key!='presentation_mat'}, ensure_ascii=False, sort_keys=True)
