#!/usr/bin/env python3
"""
송파 헬리오시티 국토교통부 실거래가(매매 및 전월세) 자동 수집기
공공데이터포털(data.go.kr) 오픈API 연동
GitHub Secrets의 OTTER_API_KEY를 사용하여 실행됩니다.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

# 1. 설정값
API_KEY = os.environ.get('OTTER_API_KEY', '').strip()
OUTPUT_DIR = 'data'

# 수집 대상 아파트 목록 설정
TARGET_APTS = [
    {
        "id": "helio",
        "lawd_cd": "11710",       # 송파구
        "keyword": "헬리오시티",
        "dong_keyword": "가락"
    },
    {
        "id": "kolon",
        "lawd_cd": "11170",       # 용산구
        "keyword": "코오롱",
        "dong_keyword": "이촌"
    }
]

if not API_KEY:
    print("[ERROR] OTTER_API_KEY 환경변수가 설정되지 않았습니다. GitHub Secrets를 확인하세요.")
    sys.exit(1)

# API 키 디코딩/인코딩 안전 처리
API_KEY_DECODED = urllib.parse.unquote(API_KEY)

# 최근 6개월의 년월(YYYYMM) 목록 생성
def get_recent_months(count=6):
    now = datetime.now()
    months = []
    year = now.year
    month = now.month
    for _ in range(count):
        months.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return months

# 평형 구분 (전용면적 기준 - 코오롱아파트의 평형대도 포괄하도록 적용)
def classify_pyeong(area_float):
    if area_float < 45.0:
        return '39'
    elif area_float < 55.0:
        return '49'
    elif area_float < 70.0:
        return '59'
    elif area_float < 90.0:
        return '84'
    elif area_float < 105.0:
        return '99'
    elif area_float < 120.0:
        return '110'
    else:
        return '130'

# 공공데이터 API 호출 함수 (XML 파싱)
def fetch_api(endpoint, lawd_cd, deal_ymd):
    url = f"{endpoint}?serviceKey={urllib.parse.quote(API_KEY_DECODED)}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&pageNo=1&numOfRows=1000"
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/xml'}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            items = root.findall('.//item')
            return items
    except Exception as e:
        print(f"[WARN] {deal_ymd} 데이터 요청 실패 ({endpoint}): {e}")
        return []

def process_target(target, months, trade_endpoint, rent_endpoint):
    print(f"\n---> [{target['keyword']}] 데이터 수집 시작")
    all_trades = []
    trade_id = 1

    # [1] 매매 실거래가 수집
    for ymd in months:
        items = fetch_api(trade_endpoint, target['lawd_cd'], ymd)
        for item in items:
            apt_nm = (item.findtext('aptNm') or '').strip()
            umd_nm = (item.findtext('umdNm') or '').strip()
            
            # 단지명 및 법정동 필터링
            if (target['keyword'] in apt_nm) and (target['dong_keyword'] in umd_nm or umd_nm == ''):
                # 해제된 거래 건너뛰기
                cancel_type = item.findtext('cdealType') or ''
                if cancel_type.strip() == 'O':
                    continue

                amount_str = (item.findtext('dealAmount') or '0').replace(',', '').strip()
                area_str = item.findtext('excluUseAr') or '0'
                year = item.findtext('dealYear') or ymd[:4]
                month = item.findtext('dealMonth') or ymd[4:]
                day = item.findtext('dealDay') or '01'
                floor = item.findtext('floor') or '1'
                dong = item.findtext('aptDong') or f"{floor}층 거래"

                try:
                    price = int(amount_str)
                    area = float(area_str)
                    pyeong_key = classify_pyeong(area)
                    date_formatted = f"{year}.{int(month):02d}.{int(day):02d}"

                    all_trades.append({
                        "id": trade_id,
                        "date": date_formatted,
                        "pyeong": pyeong_key,
                        "type": f"{pyeong_key}㎡ ({'18평' if pyeong_key=='39' else ('21평' if pyeong_key=='49' else ('25평' if pyeong_key=='59' else ('33평' if pyeong_key=='84' else ('38평' if pyeong_key=='99' else ('42평' if pyeong_key=='110' else '50평')))))})",
                        "deal": "매매",
                        "price": price,
                        "deposit": 0,
                        "rent": 0,
                        "floor": int(floor) if floor.isdigit() else 1,
                        "dong": dong if ('동' in dong) else f"{dong}동",
                        "diff": 0,
                        "note": "국토교통부 실거래 체결"
                    })
                    trade_id += 1
                except ValueError:
                    continue

    # [2] 전월세 실거래가 수집
    for ymd in months:
        items = fetch_api(rent_endpoint, target['lawd_cd'], ymd)
        for item in items:
            apt_nm = (item.findtext('aptNm') or '').strip()
            umd_nm = (item.findtext('umdNm') or '').strip()

            if (target['keyword'] in apt_nm) and (target['dong_keyword'] in umd_nm or umd_nm == ''):
                deposit_str = (item.findtext('deposit') or '0').replace(',', '').strip()
                rent_str = (item.findtext('monthlyRent') or '0').replace(',', '').strip()
                area_str = item.findtext('excluUseAr') or '0'
                year = item.findtext('dealYear') or ymd[:4]
                month = item.findtext('dealMonth') or ymd[4:]
                day = item.findtext('dealDay') or '01'
                floor = item.findtext('floor') or '1'
                dong = item.findtext('aptDong') or f"{floor}층 거래"

                try:
                    deposit = int(deposit_str)
                    monthly_rent = int(rent_str)
                    area = float(area_str)
                    pyeong_key = classify_pyeong(area)
                    deal_type = "월세" if monthly_rent > 0 else "전세"
                    date_formatted = f"{year}.{int(month):02d}.{int(day):02d}"

                    all_trades.append({
                        "id": trade_id,
                        "date": date_formatted,
                        "pyeong": pyeong_key,
                        "type": f"{pyeong_key}㎡",
                        "deal": deal_type,
                        "price": deposit,
                        "deposit": deposit,
                        "rent": monthly_rent,
                        "floor": int(floor) if floor.isdigit() else 1,
                        "dong": dong if ('동' in dong) else f"{dong}동",
                        "diff": 0,
                        "note": "국토교통부 전월세 체결"
                    })
                    trade_id += 1
                except ValueError:
                    continue

    # 최신 날짜순 정렬
    all_trades.sort(key=lambda x: x['date'], reverse=True)

    # 평형별 통계 요약 계산
    pyeong_summary = {}
    pyeong_configs = {
        '39': {"name": "39㎡ (18평형)", "default_trade": 198000, "default_jeonse": 72000},
        '49': {"name": "49㎡ (21평형)", "default_trade": 234000, "default_jeonse": 88000},
        '59': {"name": "59㎡ (25평형)", "default_trade": 260000, "default_jeonse": 108000},
        '84': {"name": "84㎡ (33평형)", "default_trade": 295000, "default_jeonse": 130000},
        '99': {"name": "99㎡ (38평형)", "default_trade": 322000, "default_jeonse": 153000},
        '110': {"name": "110㎡ (42평형)", "default_trade": 335000, "default_jeonse": 168000},
        '130': {"name": "130㎡ (50평형)", "default_trade": 420000, "default_jeonse": 215000}
    }

    for pk, cfg in pyeong_configs.items():
        matched_trades = [t for t in all_trades if t['pyeong'] == pk and t['deal'] == '매매']
        matched_jeonse = [t for t in all_trades if t['pyeong'] == pk and t['deal'] == '전세']
        matched_rent = [t for t in all_trades if t['pyeong'] == pk and t['deal'] == '월세']

        # 데이터가 없을 시 default 값 대신 최근 실거래가 없음을 반영하기 위해 0 또는 기존 로직 유지
        trade_avg = int(sum(t['price'] for t in matched_trades) / len(matched_trades)) if matched_trades else cfg['default_trade']
        jeonse_avg = int(sum(t['price'] for t in matched_jeonse) / len(matched_jeonse)) if matched_jeonse else cfg['default_jeonse']
        rent_avg = int(sum(t['rent'] for t in matched_rent) / len(matched_rent)) if matched_rent else 400

        # 호가 밴드 산출 (실거래 기반)
        min_ask = int(trade_avg * 0.94)
        max_ask = int(trade_avg * 1.10)

        pyeong_summary[pk] = {
            "name": cfg['name'],
            "trade": {
                "avg": trade_avg,
                "minAsk": min_ask,
                "maxAsk": max_ask,
                "count": len(matched_trades)
            },
            "jeonse": {
                "avg": jeonse_avg,
                "minAsk": int(jeonse_avg * 0.95),
                "maxAsk": int(jeonse_avg * 1.06),
                "count": len(matched_jeonse)
            },
            "rent": {
                "deposit": 30000,
                "monthly": rent_avg,
                "minRent": int(rent_avg * 0.9),
                "maxRent": int(rent_avg * 1.1),
                "count": len(matched_rent)
            }
        }

    # 결과 JSON 데이터 저장
    result_data = {
        "status": "success",
        "lastCrawledAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "국토교통부 실거래가 공개시스템 API",
        "aptName": target['keyword'],
        "tradeCount": len(all_trades),
        "pyeongSummary": pyeong_summary,
        "trades": all_trades
    }
    
    output_file = f"{OUTPUT_DIR}/{target['id']}_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] {target['keyword']} 실거래 총 {len(all_trades)}건 수집 완료 -> {output_file} 저장 성공!")

def main():
    print(f"=== 부동산 실거래가 수집 시작 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    months = get_recent_months(6)
    
    trade_endpoint = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
    rent_endpoint = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

    for target in TARGET_APTS:
        process_target(target, months, trade_endpoint, rent_endpoint)

    print("\n=== 모든 수집 작업 완료 ===")

if __name__ == '__main__':
    main()