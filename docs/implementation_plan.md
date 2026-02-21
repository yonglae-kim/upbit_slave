# 업비트 자동매매 전략 구현 플랜 (순차 실행)

이 문서는 `SR → OB → FVG` 기반 분봉 전략을 저사양 환경에서 안전하게 운영하기 위한 **실행 순서 중심** 계획서입니다.

## 0. 작업 원칙
- 실시간 데이터는 WebSocket 우선, REST는 최소화
- Rate Limit(429/418)와 상태 동기화(myOrder 중심)를 최우선 리스크로 관리
- 저사양 환경을 고려해 종목 수/구독 타입/연산 시점을 제한

## 1단계: 기반 안정화 (우선 시작)
### 1-1. 인증/요청 제어
- [x] JWT 서명 유틸 정리 (`access_key`, `nonce`, `query_hash`)
- [x] nonce 충돌 방지 정책(프로세스 재시작 포함) 확정
- [x] REST 공통 응답에서 `Remaining-Req` 파싱
- [x] 그룹별 호출 스로틀러(초 단위) 추가
- [x] 429/418 백오프 정책 공통화

### 1-2. WebSocket 생존성
- [x] ping/pong 또는 주기 ping 구현
- [x] 120초 idle timeout 대응 재연결 로직
- [x] 재연결 후 구독 복원(마켓/타입) 구현
- [x] SIMPLE/SIMPLE_LIST 포맷 적용 여부 점검

### 1-3. 주문 상태 동기화
- [x] 주문 API 응답을 "접수"로만 처리
- [x] `myOrder` 이벤트 기반 상태 머신 확정
- [x] `myAsset`은 리컨실리에이션 용도로 분리
- [x] identifier 유일성 정책(재시도 포함) 설계

## 2단계: 데이터/유니버스 파이프라인
### 2-1. 종목 선별
- [ ] `market/all`로 유니버스 구성
- [ ] 24h 거래대금 상위 N1 선별
- [ ] 상대 스프레드 필터 적용
- [ ] 결측률(체결 없는 분봉 누락) 기준 적용
- [ ] 최종 감시 N2(저사양 상한) 확정

### 2-2. 버퍼/정합성
- [ ] 1m/5m/15m 고정 길이 링버퍼 구성
- [ ] 캔들 누락 구간 정렬 정책 정의
- [ ] 지표 계산 트리거를 "캔들 종료 시점"으로 제한

## 3단계: 전략 엔진
### 3-1. SR
- [x] 피벗 탐지 + 밴드 클러스터링 구현 (`core/strategy.py`: `detect_sr_pivots`, `cluster_sr_levels`)
- [ ] 터치 횟수/최근성/거래대금 기반 SR 스코어링

### 3-2. OB/FVG
- [x] FVG 3캔들 불균형 탐지 (`core/strategy.py`: `detect_fvg_zones`)
- [x] FVG 폭(ATR/틱) 및 변위 필터 (`core/config.py` 파라미터 + `detect_fvg_zones`)
- [x] OB(마지막 반대 캔들 + 변위 조건) 구현 (`core/strategy.py`: `detect_ob_zones`)
- [x] 존 무효화/만료 규칙 반영 (`core/strategy.py`: `filter_active_zones`)

### 3-3. 시그널 결합
- [x] 15m SR(컨텍스트) + 5m OB/FVG(셋업) + 1m(트리거) (`check_buy`/`check_sell` 교체)
- [x] 존 충돌 우선순위(OB∩FVG∩SR > 단일) 적용 (`pick_best_zone`)
- [x] 신호-주문 전 검증(틱 라운딩/최소 주문금액)
  - 근거: `TradingEngine._preflight_order`

## 4단계: 리스크·집행
- [ ] 트레이드당 리스크(%) 기반 포지션 사이징
- [ ] 일손실/연속손실 서킷브레이커
- [ ] 동시 포지션 및 상관 노출 제한
- [ ] 부분익절/손절/트레일링 정책 구현
- [ ] 주문 실패/부분체결 재시도 규칙 구현

## 5단계: 백테스트/검증
- [ ] 캔들 최대 200개 제한 고려한 백필러 점검
- [ ] 수수료+스프레드+슬리피지 비용 모델 반영
- [ ] IS/OOS 분리 + 워크포워드 검증
- [ ] 성과지표(CAGR, MDD, Sharpe, 체결률) 리포트

## 6단계: 운영 전환
- [ ] 페이퍼 트레이딩(최소 1~2주)
- [ ] 알림/모니터링 임계치 튜닝
- [ ] 소액 실거래 점진 전환
- [ ] 장애/손실 이벤트 회고 후 룰 업데이트

---

## 즉시 실행 TODO (이번 사이클)
1. [x] JWT/nonce/Remaining-Req 처리 위치를 코드에서 식별
2. [x] WebSocket 연결 수명(ping/idle/reconnect) 구현 상태 점검
3. [x] 주문 상태를 `myOrder` 중심으로 재정렬할 영향 범위 분석

완료 기준: 위 3개 항목의 현황/갭/개선 우선순위를 문서화하고 다음 커밋에서 구현 착수.


## 이번 사이클 결과 (현황/갭/우선순위)
### A. JWT/nonce/Remaining-Req
- **현황**: `apis.py`에 인증 헤더 생성 공통화(`_auth_headers`), 프로세스/시간/카운터 기반 nonce 생성기(`NonceGenerator`), `Remaining-Req` 파싱(`parse_remaining_req`), 그룹별 초당 제한(`GroupThrottle`), 429/418 지수 백오프+`Retry-After` 반영 재시도가 구현됨.
- **갭**: nonce는 단일 프로세스 내 충돌 방지 중심이며, 다중 프로세스 간 전역 단조 증가 보장 저장소는 없음.
- **우선순위**: 중간 — 현재 단일 프로세스 운영 전제에서는 즉시 리스크가 낮고, 멀티프로세스 전환 시 보강 필요.

### B. WebSocket 연결 수명
- **현황**: `infra/upbit_ws_client.py`에 주기 ping, 120초 idle timeout 감지 후 소켓 종료, 연결 루프 기반 재연결, 저장된 구독 payload 복원(`_restore_subscriptions`)이 구현됨. 기본 포맷은 `SIMPLE`이며 구독 시 포맷 오버라이드가 가능해 `SIMPLE_LIST` 적용 점검 경로도 확보됨.
- **갭**: 장애/재연결 카운트 및 ping 실패율 같은 운영 메트릭은 아직 코드 내 표준화되어 있지 않음.
- **우선순위**: 중간 — 생존성 핵심은 충족, 운영 관측성 보강이 다음 과제.

### C. 주문 상태(`myOrder`) 중심 재정렬
- **현황**: `core/engine.py`에서 주문 API 응답은 `_record_accepted_order`로 `ACCEPTED` 상태만 기록하고, `_route_ws_message`가 `myOrder`를 `apply_my_order_event`로 라우팅해 상태 머신을 갱신한다. `myAsset`은 `portfolio_snapshot` 갱신으로 분리되어 있으며, `reconcile_orders`는 타임아웃/부분체결 보정 루프를 수행한다. `orders_by_identifier`와 `_next_order_identifier`로 주문 추적 및 유일 identifier를 유지한다.
- **갭**: timeout 이후 amend/cancel 정책(`_on_order_timeout`)은 아직 훅만 존재한다.
- **우선순위**: 중간 — 주문 동기화의 골격은 충족, 후속 집행 정책 고도화 필요.

### 다음 커밋 구현 착수 제안
1. `_on_order_timeout`의 amend/cancel/알림 정책 구현 **(진행중)**
2. WebSocket 장애 메트릭(재연결 횟수, ping 실패, idle timeout 발생 수) 노출
3. nonce 멀티프로세스 전략(외부 저장소 또는 중앙 발급기) 필요성 검토

## 검증 기준
- `core/engine.py`의 `orders_by_identifier`, `_record_accepted_order`, `_route_ws_message`, `reconcile_orders`, `infra/upbit_ws_client.py`의 ping/idle timeout/reconnect/`_restore_subscriptions`, `apis.py`의 `NonceGenerator`/`parse_remaining_req`/`GroupThrottle`/429·418 재시도 로직을 직접 확인해 1-1~1-3 체크 상태를 유지/판정함.

## 문서 운영 규칙 (다음 사이클부터 고정)
- 코드 수정 커밋 직후 `docs/implementation_plan.md`에 동일 커밋의 작업내역을 즉시 반영한다(완료: 체크박스 `[x]` + 근거 함수, 진행: 현재 상태/남은 작업, 보류: 보류 사유/재개 조건 1줄).


### 전략 보조 지표 정리
- `strategy/strategy.py`는 보조 계산 전용으로 축소하고 `rsi`, `macd`, `atr`만 유지함.
- `stoch_rsi`, `bollinger_bands`, `ichimoku_cloud`는 현재 전략 경로에서 제거했으며 필요 시 별도 분석 모듈로 복구/이관 예정.


### 다음 커밋 구현 착수 제안 1 진행 현황
- `_on_order_timeout`에 상태별 분기(ACCEPTED/PARTIALLY_FILLED), retry 상한/쿨다운, identifier lineage 추적, 구조화 timeout 로그, 경고 알림 훅을 반영해 집행 정책 구현을 진행 중이다.
- 남은 작업: 실거래 브로커의 amend 지원 시 해당 경로를 우선 사용하도록 API 확장 및 운영 임계치 튜닝.
