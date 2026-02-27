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

# 단계형 Walk-forward 튜닝(진입/청산/레짐/사이징, coarse→fine)
python -m testing.optimize_walkforward --market KRW-BTC --lookback-days 30 --result-csv testing/optimize_walkforward_results.csv
# (산출: 결과 CSV + 상위 조합 패턴 문서 testing/optimize_walkforward_patterns.md)
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

## 5-1) 실거래/백테스트 공통 로그 스키마

실거래(`core/engine.py`)와 백테스트(`testing/backtest_runner.py`)는 오프라인-온라인 비교를 위해 아래 이벤트 키를 최대한 동일하게 맞춥니다.

### `ENTRY_DIAGNOSTICS`
- 공통 핵심 필드
  - `type`: `ENTRY_DIAGNOSTICS`
  - `market`
  - `entry_score`, `quality_score`, `quality_bucket`, `quality_multiplier`
  - `entry_regime`
  - `sizing.base_order_krw`, `sizing.final_order_krw`, `sizing.entry_price`, `sizing.risk_per_unit`
- 실거래 추가 필드
  - `candle_time`, `strategy`, `regime`, `regime_diagnostics`, `strategy_diagnostics`, `market_damping`
  - `sizing.risk_sized_order_krw`, `sizing.cash_cap_order_krw`, `sizing.stop_price`

### `EXIT_DIAGNOSTICS`
- 공통 핵심 필드
  - `type`: `EXIT_DIAGNOSTICS`
  - `market`, `exit_reason`, `holding_minutes`
  - `mfe_r`, `mae_r`, `realized_r`
  - `fee_estimate_krw`, `slippage_estimate_krw`
  - `entry_score`, `entry_regime`
- 실거래 추가 필드
  - `qty_ratio`, `daily_realized_pnl_krw`

## 5-2) 운영자 주간 리뷰 KPI 정의
- **빈도(Frequency)**: `ENTRY_DIAGNOSTICS` 수, `EXIT_DIAGNOSTICS` 수, 마켓/레짐별 거래수.
- **승률(Win rate)**: `EXIT_DIAGNOSTICS.realized_r > 0` 비율.
- **평균 R(Average R)**: `EXIT_DIAGNOSTICS.realized_r` 평균/중앙값, 청산사유별 분해.
- **손실 꼬리(Loss tail)**: `realized_r` 하위 10%(`p10`), `mae_r` 상위 분위수, `stop_loss`/`trailing_stop` 비중.
- **온라인-오프라인 일치성**: 동일 기간 `entry_score` 분위수별 승률 및 `quality_bucket` 성과 비교(실거래 로그 vs 백테스트 CSV/로그).

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
- 2026-02-27: 레짐 분류를 `strong_trend / weak_trend / sideways`로 명시화하고, 레짐별 전략 파라미터 오버라이드(진입 강도/트리거 수/목표 R)를 엔진 진입 시점에 동적으로 적용. 백테스트 세그먼트 CSV에 레짐별 거래수·승률·expectancy 컬럼을 추가.
- 2026-02-27: 엔트리 `diagnostics`에 표준화된 `quality_score`(divergence 강도/밴드 이탈 강도/레짐 정합도)를 추가하고, 엔진 진입 사이징에 quality multiplier(저/중/고 구간)를 연동. 리스크 매니저에 multiplier 상·하한 및 일일손실 임계 근접 시 동적 캡을 도입. 백테스트 CSV에 quality bucket별 거래수·승률·expectancy 컬럼을 추가.

- 2026-02-27: `testing/optimize_walkforward.py` 추가. 진입/청산/레짐/사이징 4단계에 대해 coarse→fine 탐색, 다목적 스코어(CAGR/MDD penalty/거래수/승률), IS-OOS 괴리(과최적화) 자동 탈락, 결과 CSV 및 상위 조합 패턴 문서 자동 생성 기능을 도입. `core/config.py`에 운영 기본값 반영 게이트(`WALKFORWARD_DEFAULT_UPDATE_CRITERIA`)를 추가.
- 2026-02-27: 캔들/엔트리/청산 시각 파싱 및 저장 시 timezone 처리를 UTC aware 기준으로 통일. `EXIT_DIAGNOSTICS` 계산 시 `entry_time` tz 정규화 가드를 추가해 naive/aware 혼용으로 인한 예외를 방지.

### 변경 요약 (2026-02-27)
- 변경 요약: RSI-BB 리버설 전략의 진입 조건을 불리언 게이트에서 가중치 기반 score 합산으로 변경하고, 설정/백테스트 리포트에 튜닝 지표를 확장.
- 영향 파일: `core/rsi_bb_reversal_long.py`, `core/strategy.py`, `core/config.py`, `core/config_loader.py`, `config.py`, `testing/backtest_runner.py`, `testing/test_rsi_bb_reversal_long.py`, `testing/test_config_loader.py`.
- 실행/검증 방법 변경 여부: 기본 실행 방법은 동일. 백테스트 CSV에 score 관련 컬럼(`avg_entry_score`, `score_q25/50/75`, `score_win_rate_q1~q4`)이 추가되어 튜닝 검증 지표가 확장됨.

### 변경 요약 (2026-02-27, regime dynamic params)
- 변경 요약: 전략 레짐 분류를 `strong_trend / weak_trend / sideways`로 표준화하고, 엔진 `_try_buy`에서 레짐별 파라미터 세트를 동적으로 선택하도록 확장. 횡보 레짐은 진입 조건 완화 + 목표 R 축소, 강추세 레짐은 진입 조건 강화 + 목표 R 확대 규칙을 반영.
- 영향 파일: `core/strategy.py`, `core/config.py`, `core/engine.py`, `core/position_policy.py`, `testing/backtest_runner.py`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. `testing/backtest_runner.py` 산출 CSV에 레짐별 통계 컬럼(`regime_*_trades`, `regime_*_win_rate`, `regime_*_expectancy`)이 추가되어 레짐 단위 성능 검증이 가능해짐.

### 변경 요약 (2026-02-27, quality multiplier sizing)
- 변경 요약: `rsi_bb_reversal_long` 진단값에 quality score를 표준화해 추가하고, `_try_buy`에서 quality 구간별 multiplier로 최종 주문 금액을 조정하도록 확장. 리스크 계층에서 multiplier 상·하한 및 일일 손실 한도 근접 시 동적 캡을 적용해 과도한 증액을 방지.
- 영향 파일: `core/rsi_bb_reversal_long.py`, `core/engine.py`, `core/risk.py`, `core/config.py`, `core/config_loader.py`, `core/strategy.py`, `config.py`, `testing/backtest_runner.py`, `testing/test_rsi_bb_reversal_long.py`, `testing/test_risk_and_policy.py`, `testing/test_config_loader.py`, `testing/test_backtest_runner.py`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. 백테스트 세그먼트 CSV에 quality multiplier 구간 성과 컬럼(`quality_bucket_{low,mid,high}_{trades,win_rate,expectancy}`)이 추가되어 "큰 사이즈가 실제 알파를 내는지"를 구간별 검증 가능.


### 변경 요약 (2026-02-27, walk-forward optimizer)
- 변경 요약: `testing/backtest_runner.py` 호출 기반의 단계형 튜닝 스크립트(`testing/optimize_walkforward.py`)를 추가. 파라미터 그룹(진입/청산/레짐/사이징)별 coarse→fine 탐색과 다목적 스코어(CAGR + MDD penalty + 거래수/승률 하한)를 적용하고, IS/OOS 괴리 기반 과최적화 조합을 자동 탈락 처리.
- 영향 파일: `testing/optimize_walkforward.py`, `core/config.py`, `testing/test_optimize_walkforward.py`.
- 실행/검증 방법 변경 여부: 튜닝 전용 실행 커맨드가 추가됨(`python -m testing.optimize_walkforward ...`). 산출물로 결과 CSV(`--result-csv`)와 상위 조합 패턴 문서(`--pattern-doc`)가 생성됨.

### 변경 요약 (2026-02-27, structured entry/exit diagnostics)
- 변경 요약: 실거래 엔진에 `ENTRY_DIAGNOSTICS`/`EXIT_DIAGNOSTICS` 구조화 로그를 추가해 진입 진단값, 사이징 근거, 레짐 상태, 청산 reason/보유시간/MFE/MAE/실현 R/비용 추정치를 기록하도록 확장. 알림 포맷을 요약형으로 변경해 핵심 메트릭(진입 score, 청산 R, 당일 누적손익)을 포함.
- 영향 파일: `core/engine.py`, `core/position_policy.py`, `message/notifier.py`, `testing/backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. 로그/알림 포맷이 변경되며, 백테스트에서도 동일 이벤트 키(`ENTRY_DIAGNOSTICS`, `EXIT_DIAGNOSTICS`)를 출력해 오프라인-온라인 비교가 쉬워짐.

### 변경 요약 (2026-02-27, UTC aware timestamp 정규화)
- 변경 요약: candle/entry/exit timestamp timezone 처리 통일. `candle_date_time_utc`/`timestamp` 파싱 결과를 UTC aware `datetime`으로 고정하고, 엔진의 `entry_time`/`latest_time`/`exit_time` 저장 경로 및 `EXIT_DIAGNOSTICS` 계산 구간에 UTC 정규화 가드를 추가.
- 영향 파일: `core/candle_buffer.py`, `core/engine.py`.
- 실행/검증 방법 변경 여부: 실행 커맨드 변경 없음. 로그 기반 검증 포인트로 **SELL_ACCEPTED 이후 `EXIT_DIAGNOSTICS` 로그가 정상 출력되고 `TypeError`(naive/aware datetime 연산)가 발생하지 않는지** 확인 필요.
