"""OpenAI / Codyssey adapters with separate local and durable public gateways."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import struct
import time
from collections import OrderedDict
from threading import Lock, Timer
from urllib import request, error
from urllib.parse import urlsplit

from api.astral import handler as JsonHandler
from astral.artwork import ART_VERSION, ART_SIZE, build_art_spec, build_art_prompt, build_art_explanation
from astral.public_art import deployment_config
from astral.art_store import ArtStore, ArtLimitError

_SECRET = secrets.token_bytes(32)
_LOCK = Lock()
_CACHE = OrderedDict()
_ATTEMPTS = {}
_CALLS = 0
CODYSSEY_IMAGE_SIZE = '1024x1536'
CODYSSEY_PRESENTATION_SIZE = '1152x1536'

def expire_cached_art(key, expires):
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry[0] == expires:
            _CACHE.pop(key,None)

def art_configuration():
    provider = os.environ.get('ASTRAL_IMAGE_PROVIDER','openai').strip().lower()
    ready = provider in {'openai','codyssey'} and bool(image_api_key(provider)) and os.environ.get('ASTRAL_IMAGE_ENABLED') == '1' and not os.environ.get('VERCEL')
    return {'configured':ready, 'provider':provider, 'model':os.environ.get('ASTRAL_IMAGE_MODEL','gpt-image-2'),
            'message':('생성 버튼을 누르면 이미지 API 사용 비용이 발생합니다.' if ready else
                       '전통화 생성 연결은 준비되었습니다. 운영자가 서버 API 키와 생성 설정을 완료하면 이용할 수 있습니다.')}

def image_api_key(provider):
    # Keep existing local .env working without copying or displaying its secret.
    if provider == 'codyssey':
        return os.environ.get('CODYSSEY_API_KEY') or os.environ.get('OPENAI_API_KEY','')
    return os.environ.get('OPENAI_API_KEY','') if provider == 'openai' else ''

def provider_art_prompt(spec, provider):
    if provider != 'codyssey': return build_art_prompt(spec)
    # Only production geometry changes; immutable saju interpretation / 8 colors.
    painting_spec = {**spec, 'size':CODYSSEY_IMAGE_SIZE, 'aspect_ratio':'2:3',
                     'presentation_note':'원화는 2:3 전체 화면이다. 서비스가 잘림 없이 좌우 여백을 더해 최종 3:4 PNG로 저장한다.'}
    return build_art_prompt(painting_spec,canvas_ratio='2:3')

def signing_secret():
    configured = os.environ.get('ASTRAL_SIGNING_SECRET', '')
    return configured.encode() if len(configured) >= 32 else _SECRET


def make_art_package(report, owner=None):
    spec = build_art_spec(report)
    body = json.dumps({'expires':int(time.time())+3600, 'spec':spec, 'owner':owner}, ensure_ascii=False, separators=(',',':')).encode()
    signature = hmac.new(signing_secret(),body,hashlib.sha256).digest()
    ticket = base64.urlsafe_b64encode(body).decode() + '.' + base64.urlsafe_b64encode(signature).decode()
    return {'spec':spec, 'ticket':ticket, **art_configuration()}

def read_art_ticket(ticket, owner=None):
    if not isinstance(ticket,str) or len(ticket)>30000:
        raise ValueError('작품 요청을 확인해 주세요.')
    try:
        encoded, signature = ticket.split('.')
        body = base64.b64decode(encoded,altchars=b'-_',validate=True)
        signed = base64.b64decode(signature,altchars=b'-_',validate=True)
        if not hmac.compare_digest(signed,hmac.new(signing_secret(),body,hashlib.sha256).digest()):
            raise ValueError()
        data = json.loads(body)
        if data['expires'] < time.time() or data['spec']['version'] != ART_VERSION:
            raise ValueError()
        if owner is not None and data.get('owner') != owner:
            raise ValueError()
        return data['spec']
    except (ValueError,KeyError,TypeError):
        raise ValueError('결과 요청이 만료되거나 변경되었습니다. 사주 결과를 다시 생성해 주세요.') from None

def generate_openai(spec):
    payload = {'model':art_configuration()['model'], 'prompt':build_art_prompt(spec),
               'n':1,'size':ART_SIZE,'quality':'high','output_format':'png','background':'opaque'}
    req = request.Request('https://api.openai.com/v1/images/generations',
                          data=json.dumps(payload).encode(),method='POST',
                          headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['OPENAI_API_KEY']})
    with request.urlopen(req,timeout=150) as response:
        raw = response.read(28_000_001)
        if len(raw)>28_000_000:
            raise ValueError('image response too large')
        return json.loads(raw)['data'][0]['b64_json']

def generate_codyssey(spec):
    # Contract supplied by the user's Codyssey console image/Python example.
    # Do not pass OpenAI-only optional settings to the media gateway.
    payload = {'model':art_configuration()['model'], 'prompt':provider_art_prompt(spec,'codyssey'),
               'size':CODYSSEY_IMAGE_SIZE, 'response_format':'b64_json'}
    req = request.Request('https://copa.codyssey.kr/api/v1/images',
                          data=json.dumps(payload).encode(),method='POST',
                          headers={'Content-Type':'application/json',
                                   'Authorization':'Bearer '+image_api_key('codyssey')})
    with request.urlopen(req,timeout=150) as response:
        raw = response.read(28_000_001)
        if len(raw)>28_000_000:
            raise ValueError('image response too large')
        return json.loads(raw)['result']['images'][0]['b64_json']

def generate_image(spec):
    provider = art_configuration()['provider']
    if provider == 'codyssey': return generate_codyssey(spec)
    if provider == 'openai': return generate_openai(spec)
    raise ValueError('unsupported image provider')

def image_presentation(spec):
    neutral = spec.get('presentation_mat')
    mat_color = neutral['hex'] if neutral else next(color['hex'] for color in spec['palette'] if color['art_role']=='균형색 1')
    return {'mode':'side-mat','size':CODYSSEY_PRESENTATION_SIZE,'mat_color':mat_color,
            'mat_name':neutral['name'] if neutral else '보완색'}

def image_failure(exc):
    # Never return provider response bodies (they may contain credentials/prompt).
    if isinstance(exc,error.HTTPError):
        if exc.code == 401:
            return 'API 인증에 실패했습니다. 선택한 서비스의 키와 호환 방식을 확인해 주세요.'
        if exc.code == 403:
            return '이미지 API 사용 권한이 없습니다. 키의 권한과 모델 사용 가능 여부를 확인해 주세요.'
        if exc.code == 429:
            return 'API 잔여 사용량 또는 요청 한도에 도달했습니다. API 콘솔에서 사용량을 확인해 주세요.'
        if exc.code in {400,404,422}:
            if exc.code in {400,422}:
                try:
                    detail = json.loads(exc.read(64000))
                    fields = detail.get('errors',{}).get('fields',[])
                    names = {entry.get('field') for entry in fields if isinstance(entry,dict) and isinstance(entry.get('field'),str)}
                    if 'size' in names:
                        return '이미지 API가 요청한 크기를 지원하지 않습니다. 서버의 이미지 크기 설정을 확인해야 합니다.'
                    if 'model' in names:
                        return '이미지 API가 모델명을 거절했습니다. API 콘솔의 이미지 모델 사용 가능 여부를 확인해 주세요.'
                except (ValueError,AttributeError,TypeError,OSError):
                    pass
            return '이미지 API가 요청을 거절했습니다. 모델명·이미지 크기·요청 형식의 지원 여부를 확인해 주세요.'
        return '이미지 API 서버에서 오류가 발생했습니다. 잠시 후 상태를 확인해 주세요.'
    if isinstance(exc,(TimeoutError,error.URLError)):
        return '이미지 API 연결이 끊기거나 대기 시간이 초과되었습니다. 생성이 처리되었을 수도 있으니 API 사용량을 먼저 확인해 주세요.'
    return '이미지 응답 형식이나 3:4 PNG 크기가 예상과 다릅니다. API 응답을 확인해야 합니다.'

def validate_png(encoded, expected_size=ART_SIZE):
    if not isinstance(encoded,str) or len(encoded)>28_000_000:
        raise ValueError('invalid image')
    raw = base64.b64decode(encoded,validate=True)
    if len(raw)<33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
        raise ValueError('invalid PNG')
    if struct.unpack('>II',raw[16:24]) != tuple(map(int,expected_size.split('x'))):
        raise ValueError('wrong aspect ratio')
    return encoded

def process_astral_art_request(data, local=False, generator=None, production=False, owner=None):
    global _CALLS
    if not isinstance(data,dict) or set(data) != {'ticket'}:
        return 400, {'status':'error','error':'서버에서 받은 작품 요청만 사용할 수 있습니다.'}
    try:
        spec = read_art_ticket(data['ticket'], owner=owner if production else None)
    except ValueError as exc:
        return 400, {'status':'error','error':str(exc)}
    if production:
        return process_public_art(spec, owner, generator)
    if not local or os.environ.get('VERCEL'):
        return 503, {'status':'error','error':'공개 이미지 생성은 비용 보호용 서버 연결 후 지원합니다. 현재 로컬 테스트만 가능합니다.'}
    if not art_configuration()['configured']:
        return 503, {'status':'error','error':'서버 이미지 API 키 또는 생성 활성화 설정이 없습니다.'}
    config = art_configuration()
    image_size = CODYSSEY_IMAGE_SIZE if config['provider']=='codyssey' else ART_SIZE
    cache_key = hashlib.sha256((provider_art_prompt(spec,config['provider'])+config['provider']+config['model']+image_size).encode()).hexdigest()
    if not _LOCK.acquire(blocking=False):
        return 429, {'status':'error','error':'다른 작품을 생성 중입니다. 완료 후 다시 시도해 주세요.'}
    try:
        now = time.time()
        for key in list(_CACHE):
            if _CACHE[key][0] < now: del _CACHE[key]
        if cache_key in _CACHE:
            cached_result = {**_CACHE[cache_key][1], 'cached':True}
            if config['provider']=='codyssey': cached_result['presentation']=image_presentation(spec)
            return 200, cached_result
        if _CALLS>=20 or _ATTEMPTS.get(cache_key,0)>=3:
            return 429, {'status':'error','error':'로컬 생성 횟수 제한에 도달했습니다. 운영자에게 확인해 주세요.'}
        _CALLS += 1
        _ATTEMPTS[cache_key] = _ATTEMPTS.get(cache_key,0)+1
        # Bound metadata as well as images; no raw birth data or disk cache.
        if len(_ATTEMPTS)>256: _ATTEMPTS.pop(next(iter(_ATTEMPTS)))
        try:
            encoded = validate_png((generator or generate_image)(spec),image_size)
        except (error.URLError,TimeoutError,ValueError,KeyError,TypeError,IndexError) as exc:
            message = image_failure(exc)
            if isinstance(exc,error.HTTPError): exc.close()
            return 502, {'status':'error','error':message+' 자동 재시도하지 않으며 재요청 시 추가 사용량이 차감될 수 있습니다.'}
        result = {'status':'success','image_base64':encoded,'mime_type':'image/png','size':image_size,
                  'art_version':ART_VERSION,'cached':False,'visual_validation':'not_automated',
                  'explanation':build_art_explanation(spec)}
        if config['provider']=='codyssey':
            result['presentation'] = image_presentation(spec)
        expires = time.time()+3600
        _CACHE[cache_key] = (expires,result)
        expiry_timer = Timer(3600,expire_cached_art,args=(cache_key,expires))
        expiry_timer.daemon = True
        expiry_timer.start()
        while len(_CACHE)>4: _CACHE.popitem(last=False)
        return 200,result
    finally:
        _LOCK.release()


def process_public_art(spec, owner, generator=None):
    deployment = deployment_config()
    if not deployment or not owner or not art_configuration()['configured']:
        return 503, {'status':'error','error':'운영 서버의 전통화 설정이 완료되지 않았습니다.'}
    config = art_configuration()
    size = CODYSSEY_IMAGE_SIZE if config['provider']=='codyssey' else ART_SIZE
    # Bind cached images to the anonymous session, never another visitor's ticket.
    key = hashlib.sha256((owner+provider_art_prompt(spec,config['provider'])+config['provider']+config['model']+size).encode()).hexdigest()
    try:
        store = ArtStore(deployment['db_path'])
        reservation, cached = store.reserve(owner, key, deployment['daily_limit'], deployment['total_limit'])
    except ArtLimitError as exc:
        return 429, {'status':'error','error':str(exc)}
    except Exception:
        return 503, {'status':'error','error':'생성 한도 저장소에 연결할 수 없어 요청을 중단했습니다.'}
    if cached:
        return 200, cached
    result = None
    try:
        encoded = validate_png((generator or generate_image)(spec), size)
        result = {'status':'success','image_base64':encoded,'mime_type':'image/png','size':size,
                  'art_version':ART_VERSION,'cached':False,'visual_validation':'not_automated',
                  'explanation':build_art_explanation(spec)}
        if config['provider']=='codyssey':
            result['presentation'] = image_presentation(spec)
    except Exception as exc:
        message = image_failure(exc)
        if isinstance(exc,error.HTTPError): exc.close()
        return 502, {'status':'error','error':message+' 자동 재시도하지 않습니다. 사용량을 확인한 뒤 다시 요청해 주세요.'}
    finally:
        try:
            store.finish(reservation, key, result)
        except Exception:
            # Reservation remains charged; never make a second provider request.
            pass
    return 200, result

class handler(JsonHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length',0))
            if not 0<length<=32000:
                raise ValueError()
            data=json.loads(self.rfile.read(length).decode())
            origin = self.headers.get('Origin')
            local = ipaddress.ip_address(self.client_address[0]).is_loopback and (origin is None or urlsplit(origin).netloc == self.headers.get('Host'))
            status,payload=process_astral_art_request(data,local=local)
        except (ValueError,UnicodeDecodeError):
            status,payload=400,{'status':'error','error':'작품 요청 형식을 확인해 주세요.'}
        self._send_json(status,payload)
