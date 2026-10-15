"""Shared input allowlist. Overseas is collected but never calculated as Seoul."""
import json
from pathlib import Path

DATA = json.loads(
    (Path(__file__).resolve().parent.parent / 'assets' / 'birth-locations.json')
    .read_text(encoding='utf-8')
)
COUNTRY_CODES = frozenset(DATA['country_codes'])
CITY_NAMES = set()
for province, cities in DATA['regions'].items():
    if not province.endswith('도'):
        short = province.replace('특별자치시', '').replace('특별시', '').replace('광역시', '')
        CITY_NAMES.update((province, short, short + '시'))
    for city in cities:
        CITY_NAMES.update((city, province + ' ' + city))
for old, current in DATA['province_aliases'].items():
    for city in DATA['regions'][current]:
        CITY_NAMES.add(old + ' ' + city)

def valid_korean_city(value):
    return value in CITY_NAMES
