# 프로젝트 참고 문서 (업데이트 기준 포함)

이 문서는 `upbit_slave` 저장소를 **빠르게 파악**하기 위한 요약 문서입니다.
코드 변경 시 아래 "업데이트 규칙"에 따라 함께 최신화합니다.

## 1) 실행 진입점
- `main.py`: 실행 엔트리포인트
- `core/config_loader.py`: 환경변수 기반 설정 로딩/검증. runtime promotion gate는 승인 대상 후보 전략(`candidate_v1`)에만 적용되며, `paper/live`에서만 `TRADING_STRATEGY_DECISION_PATH`의 decision artifact를 fail-closed로 검증한다. 현재 shared runtime seam에서 지원하는 selectable strategy는 `baseline`/`rsi_bb_reversal_long`/`candidate_v1`/`ict_v1`이며, 기본 active strategy는 `ict_v1`다. `baseline` 계열과 `ict_v1`는 ungated runtime strategy이고, `sr_ob_fvg`는 시작 전 config validation에서 reject된다. `dry_run`은 현재 정책상 candidate artifact gate 없이 전략 선택을 허용한다.
- `core/engine.py`: 실거래 adapter 엔진. raw market/portfolio/runtime snapshot만 조립해 `core.decision_core.evaluate_market`에 전달하고, seam이 돌려준 intent/sizing proposal을 기준으로 broker preflight/주문 실행/알림/정합성만 처리. 다만 live 메모리에 이전 청산 상태가 아직 없을 때의 bootstrap payload(`_default_position_state_payload`) 생성만 엔진 소유로 유지한다.
- `testing/backtest_runner.py`: 백테스트 adapter. 진입/청산 판단은 `core.decision_core.evaluate_market`에 위임하고, backtest 쪽은 fill/slippage/fee accounting, ledger/segment CSV, stop diagnostics, `sell_decision_rule` 전달과 재진입 cooldown bookkeeping만 유지한다. 진입 context에는 live와 같은 market-damping seam을 위해 synthetic ticker diagnostics(`trade_price`, `ask_price`, `bid_price`, `acc_trade_price_24h`)도 함께 실어 backtest/live sizing divergence를 줄인다.
- `testing/experiment_runner.py`: walk-forward 세그먼트 CSV와 parity artifact를 재사용해 후보 전략의 `promote/reject` decision artifact를 생성한다. OOS acceptance는 `testing/optimize_walkforward.py`의 scoring/threshold contract를 그대로 사용하고, parity gate는 후보 전략명과 parity artifact의 `strategy_name`이 일치할 때만 통과한다. 기본 parity fixture는 `testing/fixtures/parity_<strategy>_cases.json`가 있으면 그것을 자동 선택한다.
- `testing/parity_runner.py`: 승인된 parity fixture 세트를 replay해 intent/reason/size 일치 여부를 machine-checkable parity artifact로 기록한다. snapshot이 0건이면 fail-closed로 `pass = false`를 기록한다.

## 2) 핵심 모듈 맵
### Core
- `core/config.py`: 트레이딩 설정 데이터 구조/기본값. 기본 전략 이름은 이제 `ict_v1`이며, `candidate_v1`는 전략 파라미터로 변환될 때만 stricter default `3.6`을 사용한다. `ict_v1`는 short-horizon 기본값(`regime_ema_fast=8`, `regime_ema_slow=24`, `trigger_mode=balanced`, `required_trigger_count=2`, `take_profit_r=1.6`) 위에서 deterministic ICT rule set을 사용한다.
- `core/strategy.py`, `core/rsi_bb_reversal_long.py`: 기존 전략 인터페이스/구현과 SR/FVG/OB/trigger primitive library
- `core/strategy_registry.py`: 전략 이름을 공유 전략 엔트리로 정규화/조회하는 레지스트리. `ict_v1`가 새 canonical runtime strategy로 등록됨
- `core/candidate_strategy_defaults.py`: `candidate_v1` proof-window 기본값과 bounded symbol-conditioned override를 별도 helper로 분리한 모듈. `core/config.py`와 `core/strategies/candidate_v1.py`가 같은 default source를 공유하면서 import cycle 없이 candidate-only state 기본값을 읽는다.
- `core/decision_models.py`: 공유 의사결정용 순수 데이터 모델(`MarketSnapshot`, `DecisionIntent` 등)
- `core/decision_core.py`: 전략 진입/청산 판단을 pure function 경계에서 평가하고 `DecisionIntent` + `next_position_state`를 반환하는 공유 decision core. `ict_v1` 청산 경로에서는 exit seam이 전략 파라미터를 정규화해 TP1 partial / breakeven / TP2 runner semantics가 shared `PositionOrderPolicy` 경계에 정확히 전달되도록 맞춘다. `candidate_v1` proof-window state propagation과 baseline/candidate alias semantics는 계속 유지한다.
- `core/strategies/baseline.py`: 기존 `rsi_bb_reversal_long` 진입/청산 로직을 재사용하는 `baseline` 래퍼
- `core/strategies/candidate_v1.py`: shared strategy seam 뒤에 붙는 regime-aware pullback continuation 후보 전략. promotion gate / proof-window semantics는 그대로 유지된다.
- `core/strategies/ict_models.py`: `ict_v1` 전용 pure helper layer. Turtle Soup sweep/reclaim, Unicorn overlap, OTE pocket, Silver Bullet session-gated setup detection을 deterministic closed-candle rule로 계산한다. Unicorn long setup은 overlap 내부 진입이라도 상단 1/3 chase 구간이면 reject해 늦은 추격 진입을 줄인다.
- `core/strategies/ict_sessions.py`: UTC candle timestamp를 New York local time으로 변환해 Silver Bullet windows(`03:00-04:00`, `10:00-11:00`, `14:00-15:00` NY local)를 판정한다. Python 3.9+에서는 `zoneinfo`, Python 3.8 배포 환경에서는 `pytz` fallback을 사용한다.
- `core/strategies/ict_v1.py`: 기본 active ICT 전략. `15m` dealing range/OTE context, `5m` sweep/FVG/OB context, `1m` trigger를 조합해 Turtle Soup / Unicorn / Silver Bullet / OTE long setup을 동시에 평가하고 가장 높은 deterministic score의 setup 하나만 채택한다. 현재는 short-horizon 15m regime pass와 bullish micro-breakout trigger를 모두 통과한 setup만 진입 대상으로 허용한다. 진입 diagnostics에는 `setup_model`, `entry_price`, `stop_price`, `r_value`, `tp1_r`, `tp2_r`, `entry_regime`, `regime_diagnostics`, `trigger_result`가 포함된다.
- `core/risk.py`, `core/position_policy.py`: 리스크/포지션 정책. `candidate_v1` proof-window semantics는 그대로 유지하고, strategy-side partial take profit branch가 더 이상 `rsi_bb_reversal_long`에만 묶이지 않도록 일반화되어 `ict_v1`도 TP1 partial + breakeven arm + TP2 runner를 shared boundary 안에서 사용할 수 있다.
- `core/order_state.py`, `core/reconciliation.py`: 주문 상태/체결 정합성
- `core/universe.py`: 거래 대상(유니버스) 구성. 기존 recent 10m trade value / spread / missing-rate filter pipeline은 유지하되, `ict_v1`가 active strategy이고 `1m` candle cohort가 있을 때는 final cap 직전에 liquidity + recent candle movement quality 기반 ranking overlay를 적용한다.
- `core/candle_buffer.py`: 캔들 버퍼 관리

### Infra
- `infra/upbit_broker.py`: 업비트 실거래 브로커 연동
- `infra/paper_broker.py`: 모의 체결 브로커
- `infra/upbit_ws_client.py`: 업비트 웹소켓 수신

### 보조 모듈
- `apis.py`: 업비트 API 호출 래퍼
- `message/notifier.py`: 알림 전송
- `testing/`: unittest 기반 테스트/백테스트 스크립트

## 3) 실행/검증 커맨드 (자주 쓰는 것)
```bash
# 의존성 설치
pip install -r requirements.txt

# 기본 실행 (권장: paper -> dry_run -> live 순)
TRADING_MODE=paper python main.py
TRADING_MODE=dry_run python main.py

# 테스트
python -m unittest discover -s testing

# ict_v1 pure model / registry / config / exit / universe 검증
python3 -m unittest testing.test_ict_models testing.test_ict_strategy_v1 testing.test_risk_and_policy testing.test_decision_core testing.test_universe testing.test_engine_universe_refresh testing.test_strategy_registry testing.test_config_loader

# chunk 1 전략 레지스트리/공유 decision model 검증
python -m unittest testing.test_strategy_registry testing.test_decision_core testing.test_config_loader

# proof-window chunk 1 candidate/seam 상태 검증
python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core

# chunk 2 task 3 proof-gated exit progression 검증
python3 -m unittest testing.test_risk_and_policy testing.test_decision_core

# chunk 2 task 4 live engine adapter 검증
python -m unittest testing.test_engine_order_acceptance testing.test_engine_ws_hooks testing.test_engine_candle_trigger testing.test_main_signals

# 최근 1주 백테스트
python -m testing.backtest_runner --market KRW-BTC --lookback-days 7
# (산출 CSV에 exit reason별 mean/median/p10 R + 보유 bar 통계 컬럼 포함)
# (추가 산출: stop_loss/partial_stop_loss/trailing_stop 진단 CSV, 기본값 backtest_stop_loss_diagnostics.csv)
# (추가 산출: stop 청산 후 재상승 진단 CSV, 기본값 backtest_stop_recovery_diagnostics.csv)
# (로그: BACKTEST_CONFIG_DEFAULT_VS_EFFECTIVE 로 코드 기본값 vs 환경변수 적용값 동시 출력)

# 단계형 Walk-forward 튜닝(진입/청산/레짐/사이징, coarse→fine)
python -m testing.optimize_walkforward --market KRW-BTC --lookback-days 30 --result-csv testing/optimize_walkforward_results.csv
# (산출: 결과 CSV + 상위 조합 패턴 문서 testing/optimize_walkforward_patterns.md)

# 후보 전략 의사결정 artifact 생성 (기본 smoke fixture 사용)
python -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json

# candidate parity artifact 생성 (승인 fixture replay)
python -m testing.parity_runner --strategy candidate_v1 --output testing/artifacts/candidate_v1_parity.json

# paper/live 후보 전략 promotion gate 검증
TRADING_MODE=paper TRADING_STRATEGY_NAME=candidate_v1 TRADING_STRATEGY_DECISION_PATH=testing/artifacts/candidate_v1_decision.json python main.py
TRADING_MODE=paper TRADING_STRATEGY_NAME=candidate_v1 TRADING_STRATEGY_DECISION_PATH=testing/fixtures/rejected_candidate_v1_decision.json python main.py

# dry_run은 현재 정책상 candidate artifact gate를 적용하지 않음
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python main.py

# 기본 active strategy(ict_v1) safe-mode 부팅 확인
TRADING_MODE=paper python3 main.py
TRADING_MODE=dry_run python3 main.py

# 진짜 multi-symbol KRW 비교는 심볼별 workbook path를 명시해 실행
python3 -m testing.backtest_runner --market KRW-BTC --path testing/artifacts/backdata_krw_btc_7d.xlsx --lookback-days 7
python3 -m testing.backtest_runner --market KRW-ETH --path testing/artifacts/backdata_krw_eth_7d.xlsx --lookback-days 7
```


### reason별 조기청산 기여도 확인 절차
1. 백테스트를 실행하고 표준 출력에서 `BACKTEST_CONFIG_DEFAULT_VS_EFFECTIVE` 로그를 먼저 확인합니다. 특히 `TRADING_PARTIAL_STOP_LOSS_RATIO`의 `default / effective / env_raw / env_applied` 값을 함께 검토해 “코드 기본값 vs 실행값” 혼동을 제거합니다.
2. `backtest_walkforward_segments.csv`에서 `exit_reason_compare_{strategy_signal,trailing_stop,partial_stop_loss,stop_loss}_{mean,median,p10}_r` 컬럼을 비교해 reason별 R 분포를 한 번에 비교합니다.
3. 같은 CSV의 `exit_reason_{reason}_early_bar_share_1_pct`~`exit_reason_{reason}_early_bar_share_8_pct`를 확인해 각 reason이 초반(1~8 bars)에서 얼마나 조기 청산에 기여했는지 누적 비율로 판단합니다.
4. 세부 근거는 `backtest_stop_loss_diagnostics.csv`(stop 이벤트 시점)와 `backtest_stop_recovery_diagnostics.csv`(청산 후 3/5/10 bars 재상승)에서 `reason`, `exit_stage`, `bars_held`, `realized_r`를 교차 검증합니다.

## 4) 환경변수 핵심 포인트
- `TRADING_MODE`: `live | paper | dry_run`
- `TRADING_STRATEGY_NAME`: 현재 shared runtime seam이 허용하는 값은 `baseline`, `candidate_v1`, `rsi_bb_reversal_long`, `ict_v1`다. 레지스트리는 `rsi_bb_reversal_long` 별칭을 `baseline` canonical identity로 정규화하고, `candidate_v1`/`ict_v1`는 별도 canonical 엔트리로 조회된다. 기본 runtime selection은 `ict_v1`이며, `sr_ob_fvg`는 레거시 research surface로만 남아 있고 runtime/backtest config selection에서는 reject된다. `StrategyParams.strategy_name` 자체는 canonical 이름을 유지함
- `TRADING_STRATEGY_DECISION_PATH`: 승인 대상 후보 전략(`candidate_v1`)을 `paper/live`에서 실행할 때 필요한 promotion decision artifact 경로. baseline 계열(`baseline`, `rsi_bb_reversal_long`)과 `ict_v1`는 gate 대상이 아니며, `dry_run`도 현재 정책상 artifact 없이 실행 가능하다. Gate 대상 후보는 artifact의 `candidate_strategy`, `decision`, `oos_gate.pass`, `parity_gate.pass`, `parity_gate.strategy_name`, `parity_gate.expected_strategy_name`가 런타임 선택과 일치해야 하며, `oos_gate.pass`와 `parity_gate.pass`는 literal boolean `true`여야 한다
- `TRADING_MIN_ORDER_KRW`: 최소 주문금액 하한
- `TRADING_MIN_BUYABLE_KRW`: 추가 버퍼(엔진 하한 계산 시 `max` 적용)
- `TRADING_DO_NOT_TRADING`: 제외 심볼/마켓 목록(쉼표 구분)
- `UPBIT_API_DEBUG`: API 요청/응답 디버그 로그 on/off
- `TRADING_ENTRY_SCORE_THRESHOLD`, `TRADING_*_WEIGHT`: 진입 점수 임계값/가중치 튜닝. baseline 계열은 기존 shared regime override profile을 그대로 사용하고, `candidate_v1`는 기본 전략 threshold를 `3.6`으로 시작하되 이 환경변수로 명시한 값은 그대로 유지한다.

## 5) 현재 진입/청산 로직 요약 (`ict_v1` 기본 전략 기준)

### 진입(BUY)
1. **전략 실행 대상 검증 (Engine 레벨)**
   - 최소 캔들 수/쿨다운/보유 종목 수/가용 KRW 등 사전 조건을 확인한 뒤 전략 평가를 진행합니다.
2. **다중 ICT setup 평가 (`core/strategies/ict_v1.py`)**
   - `15m`는 dealing range / premium-discount / 상위 liquidity context를 제공합니다.
    - `5m`는 Turtle Soup sweep, Unicorn overlap, Silver Bullet FVG retrace, OTE supportive context를 평가합니다.
    - Unicorn은 overlap 안에 있기만 하면 통과하지 않고, overlap 상단 1/3에 가까운 chase entry는 reject합니다.
   - `1m`는 현재 진입 가격과 Silver Bullet session clock을 제공합니다.
   - 현재 tuning cycle에서는 short-horizon 15m regime filter와 bullish micro-breakout trigger가 추가되어, loose raw setup만으로는 더 이상 진입하지 않습니다.
   - 전략은 아래 long setup을 동시에 평가하고 score가 가장 높은 setup 하나만 채택합니다.
     - `turtle_soup`: 이전 저점 sweep 후 range reclaim
     - `unicorn`: bullish FVG + bullish OB overlap
     - `silver_bullet`: NY local window 안의 bullish FVG retrace setup
     - `ote`: dealing range 62%~79% pocket 진입
3. **진입 진단값/손절 정의**
   - accepted setup은 `setup_model`, `entry_price`, `stop_price`, `r_value`, `tp1_r`, `tp2_r`를 diagnostics에 고정 기록합니다.
   - `entry_price - stop_price`를 1R로 사용합니다.
4. **주문 리스크/사이징 계산**
   - 공용 risk-first sizing seam이 `entry_price`/`stop_price`를 받아 주문금액을 계산합니다.
   - quality multiplier는 계속 shared sizing 경계를 통해 적용되지만, `ict_v1` diagnostics는 현재 pure ICT setup 우선으로 남습니다.
5. **주문 전 검증 후 매수 실행**
   - 최소 주문금액/잔여 슬롯/잔여 현금/호가 단위 preflight 통과 시 `buy_market` 실행합니다.
   - 체결 후 포지션 종료 상태(`PositionExitState`)에 진입가, 초기손절가, risk_per_unit, partial/breakeven 상태가 저장됩니다.

### 청산(SELL)
1. **TP1 partial + 브레이크이븐 전환**
   - `ict_v1`는 strategy-side partial exit를 기본 활성화하며, TP1은 `partial_take_profit_r`(기본 1R)입니다.
   - TP1 체결 후 `PositionExitState.strategy_partial_done = true`, `breakeven_armed = true`가 되어 손익분기 stop guard가 활성화됩니다.
2. **TP2 runner**
   - `ict_v1.should_exit_long(...)`는 현재가가 `entry_price + risk_per_unit * take_profit_r`(현재 기본 1.6R)를 넘으면 full `strategy_signal`을 반환합니다.
   - 그 전까지는 shared stop/trailing guardrail이 포지션을 관리합니다.
3. **공용 정책 경계 유지**
   - `core/position_policy.py`의 `initial_defense` / `mid_management` / `late_trailing` 3단계 구조는 유지됩니다.
   - strategy-side partial branch가 일반화되어 `ict_v1`도 공용 `PositionOrderPolicy` 안에서 TP1 -> breakeven -> TP2 runner semantics를 사용합니다.
4. **청산 사유 기록/재진입 쿨다운**
   - 전량 청산 시 마지막 청산 시점/사유를 마켓별로 저장합니다.
   - 설정에 따라 손실성 청산(`trailing_stop`, `stop_loss`)에만 쿨다운을 적용할 수 있습니다.

### 유니버스 선정
- 기본 pipeline은 여전히 recent 10m trade value -> relative spread -> missing-rate filter -> final cap 순서를 유지합니다.
- 다만 `ict_v1`가 active strategy이고 second-pass `1m` candle cohort가 있을 때는 final cap 직전에 liquidity + recent candle movement quality score로 eligible ticker를 다시 정렬합니다.
- baseline/candidate 전략은 기존 liquidity-first order를 그대로 유지합니다.

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
- **진입 직후 손절 후 재상승 진단 지표**: `backtest_stop_recovery_diagnostics.csv`에서 `reason in {stop_loss, partial_stop_loss, trailing_stop}`만 필터해 N bars(3/5/10) `mfe_r_N` 평균과 `recovered_1r_N` 비율을 확인하고, `entry_regime/entry_score/bars_held` 구간별로 노이즈 손절 집중 여부를 점검.

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
- 2026-03-21: recent trade log loader의 Python 3.8 호환성 수정. `core/engine.py`의 `_load_recent_trade_records()`가 `str.removeprefix()` 대신 prefix slice를 사용하도록 바꿔, Python 3.8 런타임에서도 `runtime_logs/recent_trades.txt`의 `PAYLOAD_JSON:` 라인을 읽을 때 부팅이 죽지 않도록 수정했다. 회귀 테스트는 `testing/test_engine_order_acceptance.py`에 추가했고, 영향 파일은 `core/engine.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`다. 실행/검증 방법 변경은 없고 검증은 `python3 -m unittest testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_recent_trade_log_loader_supports_python38_string_lines`, 관련 recent-trade log 테스트 묶음, changed-file `lsp_diagnostics`, 수동 startup 재현 시나리오로 수행했다.
- 2026-03-21: `ict_v1` Unicorn 진입 위치 guard 추가. `core/strategies/ict_models.py`의 Unicorn detector가 overlap 내부 진입이라도 상단 1/3 chase 구간이면 `entry_too_high_in_overlap`으로 reject하도록 조정했고, `testing/test_ict_models.py`와 `testing/test_ict_strategy_v1.py`에 pure model / strategy seam 회귀 테스트를 추가했다. 영향 파일은 `core/strategies/ict_models.py`, `testing/test_ict_models.py`, `testing/test_ict_strategy_v1.py`, `docs/PROJECT_REFERENCE.md`이며 실행/검증 방법 변경은 없고 검증은 `python3 -m unittest testing.test_ict_models testing.test_ict_strategy_v1`와 modified Python files 대상 `lsp_diagnostics` 및 수동 재현 시나리오로 수행했다.
- 2026-03-20: Python 3.8 배포 호환성 수정. `core/strategies/ict_sessions.py`가 stdlib `zoneinfo`에만 의존하던 경로를 `zoneinfo -> pytz` fallback으로 바꿔 Python 3.8에서도 `ict_v1` session import가 깨지지 않도록 수정했다. 영향 파일은 `core/strategies/ict_sessions.py`, `testing/test_ict_sessions.py`, `docs/PROJECT_REFERENCE.md`다. 검증은 `python3 -m unittest testing.test_ict_sessions testing.test_ict_models testing.test_ict_strategy_v1`, `python3` subprocess에서 `zoneinfo` import를 차단한 뒤 `core.config_loader` import 확인(`PY38_IMPORT_OK`), `TRADING_MODE=paper timeout 20s python3 main.py`로 수행했다.
- 2026-03-19: `ict_v1` multi-symbol tuning cycle. 실제 KRW 다중 심볼 비교는 `testing.backtest_runner` 기본 workbook(`backdata_candle_day.xlsx`)이 아니라 심볼별 workbook path를 명시해야 한다는 점을 확인했고, tuning은 그 경로로 재검증했다. 이번 cycle에서 `core/config.py`는 `ict_v1` short-horizon 기본값(`8/24` regime, `balanced` trigger, `required_trigger_count=2`, `take_profit_r=1.6`)을 갖도록 조정됐고, `core/strategies/ict_v1.py`는 short-horizon 15m regime pass + bullish micro-breakout trigger를 통과한 setup만 진입 허용하도록 tightening 되었다. 영향 파일은 `core/config.py`, `core/strategies/ict_v1.py`, `testing/test_ict_strategy_v1.py`, `testing/test_strategy_registry.py`, `docs/PROJECT_REFERENCE.md`, `docs/superpowers/plans/2026-03-19-ict-multi-symbol-performance-tuning.md`다. 검증은 `python3 -m unittest testing.test_ict_strategy_v1 testing.test_strategy_registry testing.test_decision_core testing.test_risk_and_policy`, workbook-backed six-symbol basket backtests, changed-file `lsp_diagnostics`, `TRADING_MODE=paper timeout 20s python3 main.py`, `TRADING_MODE=dry_run timeout 20s python3 main.py`로 수행했다. 동일 six-symbol baseline은 `combined_compounded_pct=-31.1829`, `median_compounded_pct=-5.7729`, `combined_return_pct=-4.7791`, `median_return_pct=-0.8431`였고, tuning 후에는 `-2.8818`, `-0.5037`, `-0.5526`, `-0.0718`로 개선되었다.
- 2026-03-19: `ict_v1` 기본 전략 도입. `core/strategies/ict_models.py`, `core/strategies/ict_sessions.py`, `core/strategies/ict_v1.py`를 추가해 Turtle Soup / Unicorn / Silver Bullet / OTE long setup을 deterministic하게 평가하도록 확장했고, `core/position_policy.py`/`core/decision_core.py`는 `ict_v1`가 shared seam 안에서 TP1 partial -> breakeven -> TP2 runner semantics를 사용할 수 있게 정리했다. 또한 `core/universe.py`/`core/engine.py`는 `ict_v1` active 시 liquidity + 1m movement quality overlay ranking을 적용한다. 영향 파일은 `config.py`, `core/config.py`, `core/config_loader.py`, `core/decision_core.py`, `core/engine.py`, `core/position_policy.py`, `core/strategy_registry.py`, `core/strategies/__init__.py`, `core/strategies/ict_models.py`, `core/strategies/ict_sessions.py`, `core/strategies/ict_v1.py`, `core/universe.py`, `testing/test_config_loader.py`, `testing/test_decision_core.py`, `testing/test_engine_order_acceptance.py`, `testing/test_engine_universe_refresh.py`, `testing/test_ict_models.py`, `testing/test_ict_strategy_v1.py`, `testing/test_risk_and_policy.py`, `testing/test_strategy_registry.py`, `testing/test_universe.py`, `docs/PROJECT_REFERENCE.md`다. 실행/검증은 `python3 -m unittest testing.test_ict_models testing.test_ict_strategy_v1 testing.test_risk_and_policy testing.test_decision_core testing.test_universe testing.test_engine_universe_refresh testing.test_strategy_registry testing.test_config_loader`, `python3 -m unittest testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_real_entry_seam_supports_legacy_default_strategy_surface`, `python3 -m unittest testing.test_universe testing.test_engine_universe_refresh`, `python3 -m testing.backtest_runner --market KRW-BTC --lookback-days 7`, `TRADING_MODE=paper timeout 20s python3 main.py`, `TRADING_MODE=dry_run timeout 20s python3 main.py`로 수행했다. 전체 `python3 -m unittest discover -s testing`는 현재 `testing/test_apis.py`가 `sys.modules["pandas"]`를 `SimpleNamespace`로 치환한 뒤 복구하지 않아 `testing.test_optimize_walkforward.OptimizeWalkForwardTest.test_optimize_saves_csv_and_pattern_doc`가 order-dependent ImportError로 실패하는 기존 harness 오염 이슈가 남아 있다.
- 2026-03-17: proof-window redesign chunk 2 task 3. `core/position_policy.py`의 shared `PositionExitState` boundary가 `proof_window_*` 상태를 직접 읽도록 확장되어, proof state가 있는 `candidate_v1` 포지션은 promotion 전까지 `highest_r`나 오래된 `bars_held`만으로 `late_trailing`에 진입하지 않는다. 대신 non-promoted trade는 tighter `initial_defense` 관리에 남고, `proof_window_promoted = true`일 때만 기존 delayed-trailing semantics를 사용한다. `core/decision_core.py`는 policy boundary가 반환한 proof-window state를 merge 시 덮어쓰지 않도록 정리했다. 영향 파일은 `core/position_policy.py`, `core/decision_core.py`, `testing/test_risk_and_policy.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`이며 실행 방법 변경은 없고 검증은 `python3 -m unittest testing.test_risk_and_policy testing.test_decision_core`와 modified Python files 대상 `lsp_diagnostics`로 수행.
- 2026-03-17: proof-window redesign chunk 1 state/seam implementation. `candidate_v1` accepted entries now initialize `proof_window_*` diagnostics with candidate-only config defaults, including bounded symbol-conditioned stricter proof defaults for `KRW-ADA`. `core/decision_core.py` persists that proof state into `next_position_state` and advances elapsed-bar / favorable-excursion tracking so proof windows can expire without auto-promoting from time alone, while the shared exit policy semantics stay unchanged in this chunk. 영향 파일은 `core/candidate_strategy_defaults.py`, `core/config.py`, `core/strategies/candidate_v1.py`, `core/decision_core.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`이며 실행 방법 변경은 없고 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`와 modified Python files 대상 `lsp_diagnostics`로 수행.
- 2026-03-17: task 4 bounded follow-up iteration. `candidate_v1`가 backtest/runtime shared seam에서 baseline용 global regime override map(`entry_score_threshold=2.9/2.5/2.2`)을 상속해 stricter calibration threshold가 조용히 낮아지던 경로를 끊었다. 이제 `core/config.py`가 전략별 regime override payload를 생성하고, `candidate_v1`는 explicit `TRADING_ENTRY_SCORE_THRESHOLD`가 없을 때만 stricter default `3.6`을 사용한다. `core/engine.py`와 `testing/backtest_runner.py`는 이 전략별 payload만 decision core로 전달한다. 영향 파일은 `core/config.py`, `core/engine.py`, `testing/backtest_runner.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_config_loader.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`이며 실행 방법 변경은 없고 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_config_loader`로 수행.
- 2026-03-17: task 4 runtime regression fix. `testing/backtest_runner.py`의 score 분위수 승률 계산이 sparse `entry_score` 분포에서 `pd.qcut(..., duplicates="drop")`가 실제 bin 수를 줄여도 고정 4-label mismatch로 죽지 않도록, 내부 bucket은 numeric code로 계산하고 결과는 항상 `q1~q4` key를 유지하도록 정리했다. 회귀 테스트는 `testing/test_backtest_runner.py`에 추가했고 실행 방법 변경은 없으며 검증은 `python3 -m pytest testing/test_backtest_runner.py -k sparse_distinct_scores`와 `python3 -m pytest testing/test_backtest_runner.py`로 수행.
- 2026-03-17: profitability redesign chunk 1 task 3. `candidate_v1`는 여전히 custom strategy exit signal 없이 shared `PositionOrderPolicy` 경로를 사용하지만, seam이 진입 시 `stop_basis`를 position state에 보존하고 shared policy가 `initial_defense` 구간에서는 entry-defined `pullback_low` 초기 손절을 그대로 존중하도록 조정했다. 이로써 short-horizon 7일/3분봉 백테스트에서 ATR/swing 기반 hard stop이 첫 보유 bar부터 구조 손절 위로 즉시 들리는 노이즈를 줄이고, hold/exit diagnostics에도 `stop_basis`/`initial_stop_price`/`risk_per_unit`/`hard_stop_price`가 계속 남도록 정리했다. trailing stop exit도 이제 같은 diagnostics payload를 유지한다. 영향 파일은 `core/decision_core.py`, `core/position_policy.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`이며 실행 방법 변경은 없고 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry testing.test_risk_and_policy`로 수행.
- 2026-03-17: profitability redesign chunk 1 task 2 quality follow-up. `candidate_v1` accepted-entry diagnostics가 later comparison에 더 유용하도록 reclaim strength와 pullback depth를 `reclaim_recovery_ratio`/`pullback_depth_ratio`/`continuation_quality`로 노출하고, 이를 이용해 `entry_score`와 `quality_score`가 accepted setup 사이에서 완만하게 변하도록 조정했다. 동시에 reclaim floor boundary, bullish final candle requirement, oversized deep-pullback reject contract(`pullback_too_deep`)를 테스트로 고정했고, seam tests는 candidate 내부 수치 대신 reason/regime/stop-basis/state propagation invariant 중심으로 완화했다. 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`로 수행.
- 2026-03-17: profitability redesign chunk 1 task 2. `candidate_v1`의 1m reclaim trigger를 “직전 impulse 고점 종가 돌파” 단일 하드게이트에서 “마지막 pullback 종가 대비 impulse gap의 50% 이상을 bullish candle로 회복”하는 deterministic continuation 확인으로 완화했다. 이로써 short-horizon continuation false negative를 줄이면서도 `entry_price`/`stop_price`/`r_value`/`entry_score`/`quality_score`/`regime`과 shared risk-first sizing seam(`use_quality_multiplier = False`)은 그대로 유지한다. 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`로 수행.
- 2026-03-17: profitability redesign chunk 1 task 1 follow-up. `core/decision_core.py`의 candidate seam regime resolution이 `core/strategies/candidate_v1.py`와 동일한 short-horizon normalization helper를 사용하도록 정리해, `regime_ema_slow=200` 같은 override가 들어와도 `evaluate_market`의 `regime`/`entry_regime`/persisted `entry_regime`가 candidate 실제 entry evaluation과 일치하도록 수정. 회귀 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`로 수행.
- 2026-03-17: profitability redesign chunk 1 task 1. `candidate_v1`의 15m regime horizon을 short-horizon 기본값(12/48 EMA cap)으로 줄여 7일 3분봉 평가에서 `insufficient_15m_candles=201`류 warmup 지배 현상을 완화했고, 실제로 부족한 경우에는 기존처럼 explicit insufficiency reason과 `required_15m`/`actual_15m`를 유지한다. shared seam에서는 `candidate_v1` 기본 strategy params도 같은 short-horizon regime 값을 쓰도록 맞춰 `evaluate_market`의 `regime`/`entry_regime` 라벨이 전략 내부 판정과 어긋나지 않게 정리했다. 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`로 수행.
- 2026-03-17: `core/config_loader.py`에 runtime promotion gate를 추가/정교화. gate 범위는 승인 대상 후보 전략 `candidate_v1`의 `paper/live` 실행으로 한정되고, `dry_run`은 현재 정책상 ungated로 유지된다. 승인 artifact가 없거나 mismatch/`reject`이면 시작 전 차단되며, 수동 rejection QA용 fixture `testing/fixtures/rejected_candidate_v1_decision.json`를 함께 유지한다.
- 2026-03-17: final integration blocker fix. `core/config_loader.py`가 shared registry에 없는 `sr_ob_fvg`를 runtime/backtest config 단계에서 fail-closed로 reject하도록 정리했고, `testing/backtest_runner.py`는 market damping seam에 필요한 synthetic ticker diagnostics(`ask/bid/trade_price`, recent 24h trade value proxy)를 entry context에 실어 supported damping configs에서 `final_order_krw`가 0으로 붕괴하지 않도록 맞췄다.
- 2026-03-17: `testing/experiment_runner.py`, `testing/parity_runner.py`, `testing/fixtures/` 기반 synthetic promote/reject/parity fixture를 추가. decision artifact(`testing/artifacts/candidate_v1_decision.json`)와 parity artifact(`testing/artifacts/candidate_v1_parity.json`)를 machine-checkable JSON으로 생성하고, OOS gate는 `testing/optimize_walkforward.py`/`core/config.py`의 기존 threshold contract를 그대로 재사용하도록 정리.
- 2026-03-16: profitability redesign chunk 1 착수. `core/strategy_registry.py`, `core/strategies/baseline.py`, `core/decision_models.py`를 추가해 `baseline` 레지스트리 조회와 공유 decision dataclass 계약을 도입하고, `core/config.py`/`core/config_loader.py`가 `baseline` 선택을 허용하도록 확장.
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

### 변경 요약 (2026-02-28, stop-loss diagnostics 강화)
- 변경 요약: `PositionOrderPolicy.evaluate`에서 stop 계열 결정 시 `exit_stage/hard_stop_price/entry_price/risk_per_unit/atr_to_risk` 진단값을 함께 반환하고, 백테스트에서 `stop_loss/partial_stop_loss` 이벤트 분포 CSV를 별도 저장하도록 확장. 또한 `exit_reason_r_stats`에 reason별 보유 bar 통계를 추가해 stop_loss의 초기 보유 구간 집중 여부를 확인 가능하게 함.
- 영향 파일: `core/position_policy.py`, `testing/backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: `python -m testing.backtest_runner ...` 실행 시 기본 세그먼트 CSV 외에 stop 이벤트 진단 CSV(`--stop-diagnostics-path`, 기본 `backtest_stop_loss_diagnostics.csv`)가 추가 생성됨.


### 변경 요약 (2026-02-28, stop re-acceleration diagnostics)
- 변경 요약: 백테스트에서 손절성 청산(`stop_loss`, `partial_stop_loss`, `trailing_stop`) 거래를 식별해 청산 후 N bars(3/5/10) 최대 상승폭(MFE)과 1R 회복 여부를 계산/저장하도록 확장. `entry_regime`, `entry_score`, `bars_held`를 함께 기록해 노이즈 손절 구간 분석이 가능하도록 개선.
- 영향 파일: `testing/backtest_runner.py`, `testing/test_backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: `python -m testing.backtest_runner ...` 실행 시 별도 재상승 진단 CSV(`--stop-recovery-path`, 기본 `backtest_stop_recovery_diagnostics.csv`)가 추가 생성되고, 세그먼트 CSV에 stop reason별 `mfe_r_3/5/10` 평균 및 `recovered_1r_3/5/10` 비율 컬럼이 포함됨.


### 변경 요약 (2026-03-01, reason별 조기청산 기여도/설정 오버라이드 가시화)
- 변경 요약: 백테스트 거래 로그(`EXIT_DIAGNOSTICS`)에 `reason`, `exit_stage`, `bars_held_at_exit`, `realized_r`를 고정 포함하도록 강화하고, reason별 1~8 bar 조기청산 누적 비율 및 `strategy_signal/trailing_stop/partial_stop_loss/stop_loss`의 평균/중앙값/p10 R 비교 컬럼을 세그먼트 CSV에 추가.
- 영향 파일: `testing/backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. 실행 시 `BACKTEST_CONFIG_DEFAULT_VS_EFFECTIVE` 로그가 추가되어 코드 기본값과 환경변수 적용값(특히 `TRADING_PARTIAL_STOP_LOSS_RATIO`)을 동시에 확인 가능.

### 변경 요약 (2026-03-01, 구조기반 vs 정책기반 stop 괴리 진단)
- 변경 요약: 진입 진단에 `stop_mode_long/entry_swing_low/entry_lower_band`를 노출하고, 백테스트 stop 진단 CSV에 `stop_mode_long`, `entry_swing_low`, `entry_atr`, `entry_stop_price`, `hard_stop_price`, `stop_gap_from_entry(_r)`, `structure_ignore_case`를 함께 기록하도록 확장. 또한 큰 stop 괴리 거래군(상위 25% gap-R)과 비-괴리 거래군의 `win_rate/expectancy/avg_loss` 비교 통계를 콘솔에 출력하도록 추가.
- 영향 파일: `core/rsi_bb_reversal_long.py`, `testing/backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: `python -m testing.backtest_runner ...` 실행 커맨드는 동일. `backtest_stop_loss_diagnostics.csv`에 진입/청산 stop 괴리 컬럼이 추가되며, 실행 로그에 `stop gap deterioration stats` 요약이 출력됨.


### 변경 요약 (2026-03-10, 유니버스 거래량 기준 10분/1시간 리프레시)
- 변경 요약: 후보 유니버스 탐색의 거래량 기준을 기존 24시간 누적 거래대금(`acc_trade_price_24h`) 우선순위에서 최근 10분(1분봉 10개 합산 거래대금) 기준으로 전환. 또한 유니버스 재탐색은 매 사이클이 아니라 1시간 캐시 주기로 수행하도록 엔진에 리프레시 간격을 도입.
- 영향 파일: `core/engine.py`, `core/universe.py`, `testing/test_universe.py`, `testing/test_engine_universe_refresh.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. 정적/단위 검증 시 `python -m unittest testing.test_universe testing.test_engine_universe_refresh`로 10분 거래대금 우선순위와 1시간 리프레시 동작을 확인 가능.

### 변경 요약 (2026-03-16, profitability redesign chunk 1)
- 변경 요약: `baseline` 전략을 공유 레지스트리 엔트리로 노출하고, 향후 공용 decision core에서 사용할 순수 데이터 모델을 추가. 또한 레지스트리가 canonical strategy identity와 entry/exit hook을 함께 보존하도록 확장하고, `core/config.py`가 `StrategyParams.strategy_name`에 legacy 런타임 이름 대신 canonical 이름을 유지하도록 정리.
- 영향 파일: `core/strategy_registry.py`, `core/strategies/__init__.py`, `core/strategies/baseline.py`, `core/decision_models.py`, `core/config.py`, `core/config_loader.py`, `testing/test_strategy_registry.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. chunk 1 검증용으로 `python -m unittest testing.test_strategy_registry testing.test_decision_core testing.test_config_loader`를 추가 사용.

### 변경 요약 (2026-03-16, profitability redesign chunk 2 task 3)
- 변경 요약: `core/decision_core.py`를 추가해 baseline 전략 진입과 `PositionOrderPolicy` 기반 청산을 하나의 순수 경계에서 평가하도록 연결. shared core는 adapter 소유 mutable state를 직접 변경하지 않고 `DecisionIntent`와 `next_position_state` payload를 함께 반환하며, `core/position_policy.py`에는 state payload <-> `PositionExitState` 변환 래퍼를 추가. 또한 청산 seam에서 policy용 cost basis와 전략용 entry snapshot을 분리하고, `DecisionContext.diagnostics.sell_decision_rule`로 backtest의 `and/or` 결합 규칙을 전달할 수 있게 함.
- 영향 파일: `core/decision_core.py`, `core/position_policy.py`, `core/strategy_registry.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 3 검증용으로 `python -m unittest testing.test_decision_core testing.test_risk_and_policy testing.test_main_signals`를 추가 사용.

### 변경 요약 (2026-03-16, profitability redesign chunk 2 task 4)
- 변경 요약: `core/engine.py`가 embedded entry/exit 판단 대신 raw `DecisionContext`를 조립해 `core.decision_core.evaluate_market`로 위임하도록 refactor. task 4 경계에 맞춰 seam이 regime 선택, effective strategy params, quality bucket/multiplier, market damping, 최종 proposed order sizing을 반환하고, 엔진은 cooldown/risk gate 확인 후 broker preflight, order execution, notifier/reconciliation, `next_position_state` persistence만 유지한다. 예외적으로 persisted exit state가 아직 없는 live 포지션의 bootstrap payload 생성만 `_default_position_state_payload`로 엔진에 남긴다.
- 영향 파일: `core/engine.py`, `core/decision_core.py`, `testing/test_engine_order_acceptance.py`, `testing/test_engine_candle_trigger.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 4 검증용으로 `python -m unittest testing.test_engine_order_acceptance testing.test_engine_ws_hooks testing.test_engine_candle_trigger testing.test_main_signals`를 추가 사용.

### 변경 요약 (2026-03-16, profitability redesign chunk 2 task 5)
- 변경 요약: `testing/backtest_runner.py`가 로컬 `check_buy`/`check_sell`/entry sizing 중복 경로 대신 `core.decision_core.evaluate_market`로 진입 intent, sizing proposal, 청산 intent, `next_position_state`를 받아 쓰는 얇은 adapter로 전환. 백테스트는 기존 fill/slippage/fee accounting, ledger/segment metrics, stop diagnostics, debug fail 요약, `sell_decision_rule`/재진입 cooldown semantics를 유지하면서, 보유 중 hold cycle에서도 seam이 돌려준 `next_position_state`를 계속 반영하고 realized-R은 실제 포지션 risk (`entry_quantity * risk_per_unit`) 기준으로 계산한다.
- 영향 파일: `testing/backtest_runner.py`, `testing/test_backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 5 검증용으로 `python3 -m unittest testing.test_backtest_runner`와 `python3 -m testing.backtest_runner --market KRW-BTC --lookback-days 30`를 사용.

### 변경 요약 (2026-03-16, profitability redesign chunk 2 task 6)
- 변경 요약: `candidate_v1` 전략을 shared registry seam 뒤에 추가. 이 전략은 `sideways`를 건너뛰고 `strong_trend`/`weak_trend`에서만 5m trend continuation + 1m pullback-and-reclaim 패턴을 평가하며, `stop_basis`와 `regime`을 포함한 안정적인 진단값을 반환한다. 진입 sizing은 공용 risk-based sizing 경로를 그대로 재사용하지만 baseline의 quality bucket multiplier는 적용하지 않는다. 독자적 청산 로직은 두지 않고 기존 공용 `PositionOrderPolicy` 경로를 그대로 사용한다.
- 영향 파일: `core/strategies/candidate_v1.py`, `core/strategies/__init__.py`, `core/strategy_registry.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 6 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`를 사용.

### 변경 요약 (2026-03-17, profitability redesign chunk 1 task 1)
- 변경 요약: `candidate_v1`의 15m regime warmup을 후보 전략 전용 short-horizon window로 줄여 7일 3분봉 평가에서 과도한 15m insufficiency가 거래 기회를 가리지 않도록 조정. 동시에 데이터가 정말 부족할 때는 `insufficient_15m_candles`와 `required_15m`/`actual_15m`를 그대로 유지하고, `TradingConfig.to_strategy_params()`도 `candidate_v1` 기본 regime 값을 같은 short-horizon window로 맞춰 shared seam의 `regime`/`entry_regime` 라벨이 전략 내부 판정과 일치하도록 정리.
- 영향 파일: `core/strategies/candidate_v1.py`, `core/config.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 1 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`를 사용.

### 변경 요약 (2026-03-17, profitability redesign chunk 1 task 1 follow-up)
- 변경 요약: `candidate_v1`가 내부에서 쓰는 short-horizon param normalization helper를 public helper로 승격하고, `core/decision_core.py`가 candidate entry seam regime resolution에도 그 same helper를 override 전/후로 적용하도록 수정. 이로써 raw seam params나 override에 `regime_ema_slow=200` 같은 값이 들어와도 `evaluate_market`의 `regime`, `entry_regime`, persisted `entry_regime`가 실제 candidate entry signal과 일관되게 유지된다.
- 영향 파일: `core/strategies/candidate_v1.py`, `core/decision_core.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. follow-up 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`를 사용.

### 변경 요약 (2026-03-17, short-horizon candidate redesign task 3)
- 변경 요약: `candidate_v1`가 여전히 독자적 strategy exit signal 없이 공용 `PositionOrderPolicy`를 사용하되, shared seam이 `pullback_low` 기반 초기 손절 컨텍스트(`stop_basis`, `initial_stop_price`, `risk_per_unit`)를 position state에 보존하도록 조정. `initial_defense` 구간에서는 정책 stop이 ATR/swing 기준으로 곧바로 상향되기보다 candidate 진입 시 정의된 구조 손절을 우선 존중해 단기 백테스트의 즉시 stop-out 노이즈를 줄이도록 맞췄다.
- 영향 파일: `core/decision_core.py`, `core/position_policy.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. task 3 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry testing.test_risk_and_policy`를 사용.

### 변경 요약 (2026-03-17, full redesign next cycle chunk 1)
- 변경 요약: `candidate_v1`의 기존 patchwork 진입 경로를 compact short-horizon regime map + unified multi-timeframe signal engine 형태로 재구성하기 시작했다. 새 candidate는 `regime_map_state`, `expected_hold_type`, `signal_quality`, `invalidation_price`를 포함한 하나의 coherent signal을 내보내며, 5m reset context와 1m reclaim trigger를 함께 평가해서 이전보다 entry thesis와 invalidation을 같은 레이어에서 정의한다. 기존 `StrategySignal`/shared seam 표면은 유지하고 risk-based sizing 경로는 그대로 두되, invalidation winner에 따라 `stop_basis`가 `pullback_low` 또는 `reset_low_5m`로 남을 수 있다.
- 영향 파일: `core/strategies/candidate_v1.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. full redesign chunk 1 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`를 사용.

### 변경 요약 (2026-03-17, full redesign next cycle chunk 2)
- 변경 요약: `candidate_v1`의 shared exit controller semantics를 조정해 bars_held만으로 trailing 단계가 활성화되지 않도록 바꿨다. candidate는 이제 `highest_r`가 실제로 room을 벌기 전까지 `initial_defense`에 머물며, trailing floor도 `late_trailing` 단계 전에는 비활성화된다. 또한 baseline 공용 generic `partial_take_profit` 분기에는 더 이상 candidate가 걸리지 않도록 막아서, exit progression을 시간보다 profit progression에 더 가깝게 맞췄다.
- 영향 파일: `core/position_policy.py`, `testing/test_risk_and_policy.py`, `testing/test_decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. full redesign chunk 2 검증용으로 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_risk_and_policy testing.test_strategy_registry`를 사용.

### 변경 요약 (2026-03-18, Python 3.8 decision_core cast 호환성 수정)
- 변경 요약: `core/decision_core.py`의 `_dict_str_object()`가 `cast(dict[object, object], value)`를 사용하면서 Python 3.8에서 런타임 평가 시 `TypeError: 'type' object is not subscriptable`를 내던 문제를 `typing.Dict` 기반 cast로 교체해 수정했다.
- 영향 파일: `core/decision_core.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. 검증은 `TRADING_MODE=dry_run`에서 `main.create_engine(...).run_once()`를 실제 실행해 현재 TypeError 경로가 사라졌는지 확인했다.

### 변경 요약 (2026-03-19, candidate-only market-profile gate)
- 변경 요약: broader KRW universe(`KRW-ANKR` 포함) 대응을 위해 `candidate_v1` entry path에 generic market-profile gate를 추가했다. gate 자체는 `core/decision_core.py`에 있지만, 활성화는 candidate 전용 runtime/backtest entry context에서만 이루어져 synthetic seam/parity fixture와 baseline 전략은 영향을 받지 않는다. 판단 기준은 코인 이름이 아니라 `ticker.acc_trade_price_24h`, 상대 스프레드, ATR 비율에서 계산한 `market_damping.damping_factor`이며, 현재 기준 `damping_factor < 0.5`면 `market_profile_blocked`로 hold 처리한다.
- 영향 파일: `core/decision_core.py`, `core/engine.py`, `testing/backtest_runner.py`, `testing/test_decision_core.py`, `testing/test_backtest_runner.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: broader fee-aware KRW loop는 `TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market <KRW-SYMBOL> --lookback-days 7 ...`를 6심볼(`BTC/ETH/XRP/SOL/ADA/ANKR`)에 대해 반복 실행해 검증했다. 현재 fresh 6심볼 결과는 `trade_count=30`, `approx_win_rate_pct=3.33`, `combined_return_pct=+0.6409`, `median_return_pct=+0.0322`이다.

### 변경 요약 (2026-03-19, backtest segment-end close accounting)
- 변경 요약: `testing/backtest_runner.py`가 세그먼트 종료 시 남아 있는 오픈 포지션을 같은 fee/spread/slippage 모델로 강제 청산해 `trade_ledger`, `closed_trades`, `win_rate`가 최종 `mark_to_market` 수익률과 같은 trade population을 보도록 맞췄다. 또한 segment CSV에 새 exit reason인 `segment_end` 컬럼을 노출해 리포트가 실제 청산 사유를 숨기지 않도록 정리했다. 이 변경으로 6심볼 candidate broad backtest의 수익률은 그대로 유지하면서 `closed_trade_count=30`, `approx_win_count=8`, `approx_win_rate_pct=26.67`로 win-rate proxy가 의미 있는 값으로 복구된다.
- 영향 파일: `testing/backtest_runner.py`, `testing/test_backtest_runner.py`, `testing/artifacts/backtest_7d_candidate_summary.json`, `testing/artifacts/krw_btc_candidate_7d_segments.csv`, `testing/artifacts/krw_eth_candidate_7d_segments.csv`, `testing/artifacts/krw_xrp_candidate_7d_segments.csv`, `testing/artifacts/krw_sol_candidate_7d_segments.csv`, `testing/artifacts/krw_ada_candidate_7d_segments.csv`, `testing/artifacts/krw_ankr_candidate_7d_segments.csv`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 검증은 `python3 -m unittest testing.test_backtest_runner`와 `python3 -m unittest testing.test_decision_core testing.test_candidate_strategy_v1 testing.test_strategy_registry testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`로 수행했다. 이후 `TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market <KRW-SYMBOL> --lookback-days 7 ...`를 6심볼에 다시 실행해 현재 결과 `trade_count=30`, `closed_trade_count=30`, `approx_win_rate_pct=26.67`, `combined_return_pct=+0.6409`, `median_return_pct=+0.0322`를 확인했다.

### 변경 요약 (2026-03-19, candidate FVG/OB/SR confluence integration)
- 변경 요약: 활성 전략 경로인 `candidate_v1`에 dormant `core/strategy.py`의 순수 helper를 재사용하는 zone-confluence layer를 추가했다. `15m`는 그대로 regime를 결정하고, `5m`는 기존 trend-reset setup 위에 bullish FVG / bullish OB / scored support intersection을 요구하며, `1m` reclaim은 최종 trigger로 유지한다. 이 사이클에서 S/R Flip은 별도 runtime strategy를 부활시키지 않고 `support` band와 active bullish zone의 교집합을 reclaim 가능한 지원 컨텍스트로 해석해 candidate 진입의 필수 조건으로 적용했다.
- 영향 파일: `core/strategies/candidate_v1.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `testing/test_experiment_runner.py`, `testing/test_parity_runner.py`, `docs/superpowers/specs/2026-03-19-candidate-zone-confluence-redesign.md`, `docs/superpowers/plans/2026-03-19-candidate-zone-confluence-redesign.md`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 검증은 `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`와 `python3 -m unittest testing.test_main_signals testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`로 수행했다. 이후 fee-aware 6심볼 candidate backtest를 다시 실행해 결과를 비교했고, 새 결과는 `trade_count=27`, `closed_trade_count=27`, `approx_win_rate_pct=22.22`, `combined_return_pct=+0.3076`, `median_return_pct=+0.0322`였다. 이전 checkpoint(`30 / 26.67 / +0.6409 / +0.0322`) 대비 개선이 아니므로 이 변경은 아직 commit/push 하지 않았다.

### 변경 요약 (2026-03-19, candidate_v1 OB/FVG/SR-Flip adapter rewrite)
- 변경 요약: `candidate_v1`를 기존 short-horizon pullback/reclaim 전략에서 제거하고, `core/strategy.py`의 성숙한 OB/FVG/SR helper engine 위에 올라가는 adapter로 재작성했다. 새 candidate 경로는 `15m` regime filter + scored SR levels + `5m` bullish OB/FVG zone + explicit S/R Flip(break -> retest -> hold) + 기존 `1m` trigger engine을 사용한다. 또한 `candidate_v1.should_exit_long(...)`는 더 이상 항상 `False`를 반환하지 않고 strategy-side sell engine을 통해 `strategy_signal`을 생성할 수 있다.
- 영향 파일: `core/strategy.py`, `core/strategies/candidate_v1.py`, `core/candidate_strategy_defaults.py`, `core/position_policy.py`, `testing/test_main_signals.py`, `testing/test_candidate_strategy_v1.py`, `testing/test_decision_core.py`, `testing/test_risk_and_policy.py`, `testing/test_parity_runner.py`, `testing/test_experiment_runner.py`, `docs/superpowers/specs/2026-03-19-ob-fvg-sr-flip-runtime-redesign.md`, `docs/superpowers/plans/2026-03-19-ob-fvg-sr-flip-runtime-redesign.md`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 검증은 `python3 -m unittest testing.test_main_signals testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry testing.test_risk_and_policy`와 `python3 -m unittest testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`로 수행했다. 현재 local 6심볼 fee-aware candidate checkpoint는 `trade_count=37`, `closed_trade_count=37`, `approx_win_rate_pct=32.43`, `combined_return_pct=+0.3171`, `median_return_pct=+0.0071`이다. 이는 직전 dirty checkpoint(`27 / 22.22 / +0.3076 / +0.0322`) 대비 trade count, win rate, combined return은 개선했지만, earlier best combined-return checkpoint(`30 / 26.67 / +0.6409 / +0.0322`)는 아직 회복하지 못했다. coin-specific proof-window lane(`KRW-XRP`/`KRW-ADA`)도 제거해 user constraint와 맞췄다. 이 상태는 아직 local-only이며 commit/push 하지 않았다.
