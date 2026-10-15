"""Deterministic CIELCH(D50) tone separation, without changing names/meaning.

sRGB/XYZ/Bradford/Lab conversions: https://www.w3.org/TR/css-color-4/#color-conversion-code
"""
from copy import deepcopy
from functools import lru_cache
from math import atan2, cos, degrees, hypot, radians, sin, sqrt

MIN_TONE_DISTANCE = 12.0  # CIE76 design threshold, not a color-vision guarantee.
MAX_HEX_HUE_ERROR = 1.0  # Quantization only; continuous LCH H is never changed.
PALETTE_TONE_VERSION = 'lch-d50-distinct-2'
D50 = (.3457/.3585, 1, (1-.3457-.3585)/.3585)
RGB_TO_XYZ = ((506752/1228815,87881/245763,12673/70218),
              (87098/409605,175762/245763,12673/175545),
              (7918/409605,87881/737289,1001167/1053270))
XYZ_TO_RGB = ((12831/3959,-329/214,-1974/3959),
              (-851781/878810,1648619/878810,36519/878810),
              (705/12673,-2585/12673,705/667))
D65_TO_D50 = ((1.0479297925449969,.022946870601609652,-.05019226628920524),
              (.02962780877005599,.9904344267538799,-.017073799063418826),
              (-.009243040646204504,.015055191490298152,.7518742814281371))
D50_TO_D65 = ((.955473421488075,-.02309845494876471,.06325924320057072),
              (-.0283697093338637,1.0099953980813041,.021041441191917323),
              (.012314014864481998,-.020507649298898964,1.330365926242124))


def multiply(matrix, vector):
    return tuple(sum(a*b for a,b in zip(row,vector)) for row in matrix)


def rgb(hex_color):
    return tuple(int(hex_color[i:i+2],16)/255 for i in (1,3,5))


@lru_cache(maxsize=8192)
def lab(hex_color):
    linear = tuple(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb(hex_color))
    xyz = multiply(D65_TO_D50, multiply(RGB_TO_XYZ,linear))
    def f(v):
        return v**(1/3) if v>(6/29)**3 else v/(3*(6/29)**2)+4/29
    x,y,z = (f(v/white) for v,white in zip(xyz,D50))
    return (116*y-16,500*(x-y),200*(y-z))


def to_lch(values):
    light,a,b = values
    chroma = hypot(a,b)
    return (light,0,0) if chroma<=.0015 else (light,chroma,degrees(atan2(b,a))%360)


def lch(hex_color):
    return to_lch(lab(hex_color))


def hue_error(first,second):
    return abs((first-second+180)%360-180)


def lch_to_hex(light,chroma,hue):
    a,b = chroma*cos(radians(hue)),chroma*sin(radians(hue))
    fy = (light+16)/116
    f = (fy+a/500,fy,fy-b/200)
    xyz = tuple((v**3 if v>6/29 else 3*(6/29)**2*(v-4/29))*white for v,white in zip(f,D50))
    linear = multiply(XYZ_TO_RGB,multiply(D50_TO_D65,xyz))
    if any(v < -1e-7 or v > 1+1e-7 for v in linear):
        return None  # Reject out-of-gamut tones; channel clipping would shift H.
    channels = [12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055 for v in linear]
    return '#' + ''.join(f'{round(min(1,max(0,v))*255):02X}' for v in channels)


def distance(first,second):
    return sqrt(sum((a-b)**2 for a,b in zip(first,second)))


@lru_cache(maxsize=64)
def tone_candidates(base_hex):
    base_lab = lab(base_hex)
    _,chroma,hue = lch(base_hex)
    chromas = [0] if chroma==0 else sorted({
        chroma,max(.5,chroma*.4),max(.5,chroma*.7),chroma*1.3,chroma*1.6,
        max(.5,chroma-16),max(.5,chroma-8),chroma+8,chroma+16})
    candidates = {}
    for light in range(1,100):
        for candidate_chroma in chromas:
            hex_color = lch_to_hex(light,candidate_chroma,hue)
            if hex_color is None: continue
            realized = lch(hex_color)
            if chroma and (not realized[1] or hue_error(hue,realized[2])>MAX_HEX_HUE_ERROR):
                continue
            candidate_lab = lab(hex_color)
            cost = distance(base_lab,candidate_lab)+.15*abs(realized[1]-chroma)
            candidates[hex_color] = (cost,hex_color,candidate_lab,(light,candidate_chroma,hue))
    return tuple(sorted(candidates.values()))


def distinct_palette_tones(colors):
    """Separate every pair at ΔE76 >= 12; preserve non-colliding anchors.

    Caller priority: four representatives, then companions. Names are immutable.
    Reserve distinct anchors FIRST, then repair against all anchors, including
    later colors. Never feed corrected tones back as original bases.
    """
    if len(colors)!=8: raise ValueError('8개 컬러칩이 필요합니다.')
    result = deepcopy(colors)
    anchors = {}
    pending = []
    for index,color in enumerate(result):
        original = color['hex'].upper()
        color['base_hex'] = original
        color['hex'] = original
        if all(distance(lab(original),existing)>=MIN_TONE_DISTANCE for existing in anchors.values()):
            anchors[original] = lab(original)
        else:
            pending.append(index)
    for index in pending:
        color = result[index]
        original = color['base_hex']
        candidate = next((entry for entry in tone_candidates(original)
                          if all(distance(entry[2],existing)>=MIN_TONE_DISTANCE for existing in anchors.values())),None)
        if candidate is None: raise ValueError('같은 색 계열에서 구별되는 8색을 구성할 수 없습니다.')
        _,final_hex,final_lab,target_lch = candidate
        base_lch = lch(original)
        realized = lch(final_hex)
        tone = '밝은' if realized[0]>base_lch[0] else '깊은'
        if realized[1]>base_lch[1]+3: tone+=' 선명한'
        elif realized[1]<base_lch[1]-3: tone+=' 부드러운'
        color['hex'] = final_hex
        color['tone_adjustment'] = {
            'rule':PALETTE_TONE_VERSION,'original_hex':original,'final_hex':final_hex,
            'color_space':'CIELCH-D50','hue_policy':'preserve-lch-h',
            'original_lch':list(base_lch),'target_lch':list(target_lch),
            'realized_lch':list(realized),'tone':tone,
        }
        color['description'] = (color.get('description','')+
            f' 같은 색 계열의 {tone} 톤({final_hex})으로 표현해 다른 컬러칩과 구분합니다.')
        anchors[final_hex] = final_lab
    if any(distance(lab(a['hex']),lab(b['hex']))<MIN_TONE_DISTANCE
           for i,a in enumerate(result) for b in result[i+1:]):
        raise ValueError('8색 구분 검증에 실패했습니다.')
    return result
