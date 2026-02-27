# 프로젝트 참고 문서 (업데이트 기준 포함)

이 문서는 `upbit_slave` 저장소를 **빠르게 파악**하기 위한 요약 문서입니다.
코드 변경 시 아래 "업데이트 규칙"에 따라 함께 최신화합니다.

## 1) 실행 진입점
- `main.py`: 실행 엔트리포인트
- `core/config_loader.py`: 환경변수 기반 설정 로딩/검증
- `core/engine.py`: 시그널 평가/주문 흐름의 핵심 실행 엔진

## 2) 핵심 모듈 맵
### Core
- `core/config.py`: 트레이딩 설정 데이터 구조/기본값
- `core/strategy.py`, `core/rsi_bb_reversal_long.py`: 전략 인터페이스/구현
- `core/risk.py`, `core/position_policy.py`: 리스크/포지션 정책
- `core/order_state.py`, `core/reconciliation.py`: 주문 상태/체결 정합성
- `core/universe.py`: 거래 대상(유니버스) 구성
- `core/candle_buffer.py`: 캔들 버퍼 관리

### Infra
- `infra/upbit_broker.py`: 업비트 실거래 브로커 연동
- `infra/paper_broker.py`: 모의 체결 브로커
- `infra/upbit_ws_client.py`: 업비트 웹소켓 수신

### 보조 모듈
- `apis.py`: 업비트 API 호출 래퍼
- `message/notifier.py`: 알림 전송
- `testing/`: pytest 기반 테스트/백테스트 스크립트

## 3) 실행/검증 커맨드 (자주 쓰는 것)
```bash
# 의존성 설치
pip install -r requirements.txt

# 기본 실행 (권장: paper -> dry_run -> live 순)
TRADING_MODE=paper python main.py
TRADING_MODE=dry_run python main.py

# 테스트
pytest -q

# 최근 1주 백테스트
python -m testing.backtest_runner --market KRW-BTC --lookback-days 7
# (산출 CSV에 exit reason별 mean/median/p10 R 컬럼 포함)
```

## 4) 환경변수 핵심 포인트
- `TRADING_MODE`: `live | paper | dry_run`
- `TRADING_MIN_ORDER_KRW`: 최소 주문금액 하한
- `TRADING_MIN_BUYABLE_KRW`: 추가 버퍼(엔진 하한 계산 시 `max` 적용)
- `TRADING_DO_NOT_TRADING`: 제외 심볼/마켓 목록(쉼표 구분)
- `UPBIT_API_DEBUG`: API 요청/응답 디버그 로그 on/off
- `TRADING_ENTRY_SCORE_THRESHOLD`, `TRADING_*_WEIGHT`: RSI-BB 리버설 전략의 진입 점수 임계값/가중치 튜닝

## 5) 현재 진입/청산 로직 요약 (rsi_bb_reversal_long 기준)

### 진입(BUY)
1. **전략 실행 대상 검증 (Engine 레벨)**
   - 최소 캔들 수/쿨다운/보유 종목 수/가용 KRW 등 사전 조건을 확인한 뒤 전략 평가를 진행합니다.
2. **점수 기반 진입 평가 (`evaluate_long_entry`)**
   - 기존 필터/셋업/트리거 불리언 게이트를 시그널별 강도 점수 합산으로 분리했습니다.
   - `entry_score = Σ(signal_strength × weight)` 구조를 사용하며, 신호는 RSI 과매도, BB 터치 강도, RSI 다이버전스, MACD 크로스, 엔걸핑, 최근 변동성 대비 밴드 이탈폭을 포함합니다.
   - 최종 진입은 `entry_score >= entry_score_threshold` 조건으로 판단하고, 최소 안전장치(최소 캔들 수, 유효 손절 거리)는 유지합니다.
3. **주문 리스크/사이징 계산**
   - `stop_mode_long`으로 초기 손절가를 만들고, `entry_price - stop_price`를 1R로 사용.
   - 리스크 기반 주문금액 + 현금관리 캡 + (옵션) 시장 댐핑 계수를 적용해 최종 매수 금액을 계산합니다.
4. **주문 전 검증 후 매수 실행**
   - 최소 주문금액/잔여 슬롯/잔여 현금/호가 단위 preflight 통과 시 `buy_market` 실행.
   - 체결 후 포지션 종료 상태(`PositionExitState`)에 진입가, 초기손절가, risk_per_unit 등을 저장합니다.

### 청산(SELL)
1. **포지션 상태 갱신**
   - 매 사이클마다 `peak_price`, `bars_held`, ATR/스윙로우 참조값을 갱신합니다.
   - `PositionExitState`에 `entry_regime`, `highest_r`, `drawdown_from_peak_r`를 유지해 레짐/성과/되돌림 기반 청산 판단을 수행합니다.
2. **3단계 정책 기반 청산 (`PositionOrderPolicy.evaluate`)**
   - **초기 방어 (`initial_defense`)**: `highest_r < 1.0` && `bars_held < 8` 구간. 손절을 더 엄격하게 적용하고(엔트리 대비 약 `0.85R`), 분할익절은 대기.
   - **중기 관리 (`mid_management`)**: `highest_r >= 1.0` 또는 `bars_held >= 8` 이후. 분할익절 허용 + 본절 이동(브레이크이븐) 활성화.
   - **후기 추적 (`late_trailing`)**: `highest_r >= 2.0` 또는 `bars_held >= 24` 이후. 트레일링 스탑을 강화해 이익 잠금 비중을 높임.
3. **전략 신호 청산(`strategy_signal`) 가드**
   - 기존 고정 2R 대신 `entry_regime + bars_held + ATR/risk_per_unit` 조합으로 최소 R 임계값을 동적으로 계산합니다.
   - 고변동/방어적 레짐일수록 요구 R을 높이고, 장기 보유 포지션은 임계값을 완화해 청산 유연성을 높입니다.

### 청산 사유 기록/재진입 쿨다운
- 전량 청산 시 마지막 청산 시점/사유를 마켓별로 저장합니다.
- 설정에 따라 손실성 청산(`trailing_stop`, `stop_loss`)에만 쿨다운을 적용할 수 있습니다.

## 6) 변경 시 반드시 같이 업데이트할 항목
코드 변경이 아래 영역에 해당하면 본 문서를 함께 업데이트합니다.

1. **파일 구조/역할 변경**
   - 신규 핵심 모듈 추가, 기존 모듈 역할 변경/이동/삭제
2. **실행 방법 변경**
   - 실행 인자/모드/초기화 절차 변경
3. **설정 키 변경**
   - 환경변수 추가/삭제/기본값/의미 변경
4. **운영 플로우 변경**
   - 주문/리스크/전략 평가 흐름 변경

업데이트 시 최소 반영 규칙:
- 변경 요약 1~3줄
- 영향 받는 파일 경로
- 실행/검증 방법 변경 여부
- 필요 시 마이그레이션 메모(기존 설정과의 차이)

---

## 최근 업데이트 로그
- 2026-02-26: 초기 참조 문서 작성
- 2026-02-26: `rsi_bb_reversal_long` 실운영 기준 진입/청산 플로우 문서화(전략/엔진/포지션 정책 반영).
- 2026-02-27: 청산 정책을 3단계(초기 방어/중기 관리/후기 추적)로 재구성하고, strategy signal 가드를 레짐·보유시간·변동성 기반 동적 R 임계값으로 변경. `testing/backtest_runner.py`에 exit reason별 R 분포(mean/median/p10) 리포트를 추가.
- 2026-02-27: `rsi_bb_reversal_long` 진입 판정을 점수 합산(`entry_score`) 기반으로 전환하고 임계값/가중치(`entry_score_threshold`, `*_weight`)를 설정/환경변수로 노출. 백테스트 세그먼트 리포트에 평균 score 및 score 분위수별 승률 컬럼을 추가.

### 변경 요약 (2026-02-27)
- 변경 요약: RSI-BB 리버설 전략의 진입 조건을 불리언 게이트에서 가중치 기반 score 합산으로 변경하고, 설정/백테스트 리포트에 튜닝 지표를 확장.
- 영향 파일: `core/rsi_bb_reversal_long.py`, `core/strategy.py`, `core/config.py`, `core/config_loader.py`, `config.py`, `testing/backtest_runner.py`, `testing/test_rsi_bb_reversal_long.py`, `testing/test_config_loader.py`.
- 실행/검증 방법 변경 여부: 기본 실행 방법은 동일. 백테스트 CSV에 score 관련 컬럼(`avg_entry_score`, `score_q25/50/75`, `score_win_rate_q1~q4`)이 추가되어 튜닝 검증 지표가 확장됨.

