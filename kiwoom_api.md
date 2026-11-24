# 키움 REST API 조회용 목록 (openapi.kiwoom.com API 가이드 기준, 2026-11-24 정리)

- 운영: `https://api.kiwoom.com` / 모의: `https://mockapi.kiwoom.com`
- 토큰: `POST /oauth2/token` (au10001) `{"grant_type":"client_credentials","appkey","secretkey"}` → `token`, `expires_dt`
- 호출: `POST {경로}` 헤더 `api-id`, `authorization: Bearer {token}`, `Content-Type: application/json;charset=UTF-8`
- 연속조회: 응답 헤더 `cont-yn=Y` 이면 다음 요청에 `cont-yn: Y`, `next-key: {응답 next-key}`
- 업무 오류도 HTTP 200 → `return_code` 0 이 정상
- 등록 IP에서만 토큰 발급 (카페24 서버 등록됨)

## 대시보드 서버 중계: `POST /api/kiwoom`
```json
{"group": "dostk", "category": "mrkcond", "api_id": "ka10086",
 "body": {"stk_cd": "144510", "qry_dt": "20261124", "indc_tp": "0"},
 "cont_yn": "N", "next_key": ""}
```
조회 전용. `kt*` API와 계좌(acnt)·주문(ordr)·신용주문(crdordr) 경로는 서버에서 차단.

## 국내주식 (group = dostk)

| category (경로) | 분류 | API |
|---|---|---|
| mrkcond `/api/dostk/mrkcond` | 시세 | ka10004 주식호가, ka10005 일주월시분, ka10006 시분, ka10007 시세표성정보, ka10011 신주인수권전체시세, ka10044 일별기관매매종목, ka10045 종목별기관매매추이, ka10046 체결강도추이시간별, ka10047 체결강도추이일별, ka10063 장중투자자별매매, ka10066 장마감후투자자별매매, ka10078 증권사별종목매매동향, ka10086 일별주가, ka90005~ka90013 프로그램매매, ka500xx 금현물 |
| stkinfo `/api/dostk/stkinfo` | 종목정보 | ka10001 주식기본정보, ka10002 거래원, ka10003 체결정보, ka10013 신용매매동향, ka10015 일별거래상세, ka10016 신고저가, ka10017 상하한가, ka10018 고저가근접, ka10019 가격급등락, ka10024 거래량갱신, ka10025 매물대집중, ka10026 고저PER, ka10028 시가대비등락률, ka10043 거래원매물대분석, ka10052 거래원순간거래량, ka10054 VI발동종목, ka10055 당일전일체결량, ka10058 투자자별일별매매종목, ka10059 종목별투자자기관별, ka10061 종목별투자자기관별합계, ka10084 당일전일체결, ka10095 지정종목정보, ka10099 종목정보리스트, ka10100 종목정보조회, ka10101 업종코드리스트, ka10102 회원사리스트, ka00198 실시간종목조회순위, ka90003 프로그램순매수상위50, ka90004 종목별프로그램매매현황 |
| rkinfo `/api/dostk/rkinfo` | 순위정보 | ka00190 대량체결상위, ka00196 체결금액대별매매비중, ka10020~ka10023 호가잔량·거래량급증, ka10027 전일대비등락률상위, ka10029 예상체결등락률상위, ka10030 당일거래량상위, ka10031 전일거래량상위, ka10032 거래대금상위, ka10033 신용비율상위, ka10034 외인기간별매매상위, ka10035 외인연속순매매상위, ka10036 외인한도소진율증가, ka10037 외국계창구매매상위, ka10038 종목별증권사순위, ka10039 증권사별매매상위, ka10040 당일주요거래원, ka10042 순매수거래원순위, ka10053 당일상위이탈원, ka10062 동일순매매순위, ka10065 장중투자자별매매상위, ka11310 애프터마켓등락률상위, ka11370 KRX/NXT괴리율순위, ka90009 외국인기관매매상위 |
| frgnistt `/api/dostk/frgnistt` | 기관/외국인 | ka10008 주식외국인종목별매매동향, ka10131 기관외국인연속매매현황, ka52301 금현물투자자현황 |
| shsa `/api/dostk/shsa` | 공매도 | ka10014 공매도추이 |
| slb `/api/dostk/slb` | 대차거래 | ka10068 대차거래추이, ka10069 대차거래상위10, ka20068 대차거래추이(종목별), ka90012 대차거래내역 |
| sect `/api/dostk/sect` | 업종 | ka10010 업종프로그램, ka10051 업종별투자자순매수, ka20001 업종현재가, ka20002 업종별주가, ka20003 전업종지수, ka20009 업종현재가일별 |
| chart `/api/dostk/chart` | 차트 | ka10060 종목별투자자기관별차트, ka10064 장중투자자별매매차트, ka10079~ka10083·ka10094 틱·분·일·주·월·년봉, ka11079~ka11094 정규장(KRX) 봉, ka20004~ka20008·ka20019 업종 봉 |
| thme `/api/dostk/thme` | 테마 | ka06550 인포스탁 섹터 구성종목, ka10106 테마코드리스트, ka10107 테마상세종목, ka90001 테마그룹별, ka90002 테마구성종목 |
| etf `/api/dostk/etf` | ETF | ka40001 수익율, ka40002 종목정보, ka40003 일별추이, ka40004 전체시세, ka40006~ka40010 시간대별·NAV·수급 |
| elw `/api/dostk/elw` | ELW | ka10048, ka10050, ka30001~ka30012 |

차단(중계 불가): 계좌 `/api/dostk/acnt`, 주문 `/api/dostk/ordr`, 신용주문 `/api/dostk/crdordr`, kt20016·kt20017 등 kt 계열.

## 미국주식 (group = us)

| category (경로) | 분류 | API |
|---|---|---|
| mrkcond `/api/us/mrkcond` | 시세 | usa20100 현재가 종목정보, usa20101 10호가, usa20150 상세체결, usa20151 일별체결, usa20590 일별주가 |
| stkinfo `/api/us/stkinfo` | 종목정보 | usa10098 거래소구분, usa10099 종목리스트, usa10100 종목조회, usa10101 업종리스트, usa10102 미국지수 리스트, usa10104 ETF·ETN 리스트, usa10105 ETF 카테고리, usa205xx·209xx·234xx·241xx·242xx 급등락·신고저 등, usa2641x 연도별 등락률 |
| chart `/api/us/chart` | 차트 | usa06010~usa06016 틱·분·일·주·월·년·분기 |
| rkinfo `/api/us/rkinfo` | 순위정보 | usa20510~usa24xxx 등락률·거래량·거래대금·시가총액 상위 등 |
| sect `/api/us/sect` | 업종 | usa23000 업종별 기간별 수익률, usa23100 업종별 등락률 상위/하위 |
| invtinfo `/api/us/invtinfo` | 투자정보 | usa24300 리서치 |

요청 필드는 API마다 다르므로 가이드(openapi.kiwoom.com/guide/apiguide)의 해당 API Request 표를 확인한다.
