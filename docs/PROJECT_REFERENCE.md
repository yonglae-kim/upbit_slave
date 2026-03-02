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
# (산출 CSV에 exit reason별 mean/median/p10 R + 보유 bar 통계 컬럼 포함)
# (추가 산출: stop_loss/partial_stop_loss/trailing_stop 진단 CSV, 기본값 backtest_stop_loss_diagnostics.csv)
# (추가 산출: stop 청산 후 재상승 진단 CSV, 기본값 backtest_stop_recovery_diagnostics.csv)
# (로그: BACKTEST_CONFIG_DEFAULT_VS_EFFECTIVE 로 코드 기본값 vs 환경변수 적용값 동시 출력)

# 단계형 Walk-forward 튜닝(진입/청산/레짐/사이징, coarse→fine)
python -m testing.optimize_walkforward --market KRW-BTC --lookback-days 30 --result-csv testing/optimize_walkforward_results.csv
# (산출: 결과 CSV + 상위 조합 패턴 문서 testing/optimize_walkforward_patterns.md)
```


### reason별 조기청산 기여도 확인 절차
1. 백테스트를 실행하고 표준 출력에서 `BACKTEST_CONFIG_DEFAULT_VS_EFFECTIVE` 로그를 먼저 확인합니다. 특히 `TRADING_PARTIAL_STOP_LOSS_RATIO`의 `default / effective / env_raw / env_applied` 값을 함께 검토해 “코드 기본값 vs 실행값” 혼동을 제거합니다.
2. `backtest_walkforward_segments.csv`에서 `exit_reason_compare_{strategy_signal,trailing_stop,partial_stop_loss,stop_loss}_{mean,median,p10}_r` 컬럼을 비교해 reason별 R 분포를 한 번에 비교합니다.
3. 같은 CSV의 `exit_reason_{reason}_early_bar_share_1_pct`~`exit_reason_{reason}_early_bar_share_8_pct`를 확인해 각 reason이 초반(1~8 bars)에서 얼마나 조기 청산에 기여했는지 누적 비율로 판단합니다.
4. 세부 근거는 `backtest_stop_loss_diagnostics.csv`(stop 이벤트 시점)와 `backtest_stop_recovery_diagnostics.csv`(청산 후 3/5/10 bars 재상승)에서 `reason`, `exit_stage`, `bars_held`, `realized_r`를 교차 검증합니다.

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

#### 구조 기반 손절 vs R 기반(정책 기반) 손절 구분
- **구조 기반 손절(진입 시점)**: `core/rsi_bb_reversal_long.py`의 `_compute_stop_price`에서 `stop_mode_long`(`swing_low`/`conservative`/`lower_band`)으로 초기 손절을 산출합니다. 이 값은 진입 직후 `entry_stop_price`의 기준이 됩니다.
- **R 기반(정책 기반) 손절(보유 중 관리)**: `core/position_policy.py`의 `PositionOrderPolicy.evaluate`가 `hard_stop_price`를 재평가하며, `initial_defense(0.85R)`, `mid/late 구간 손익분기 상향`, `ATR+스윙 결합` 규칙으로 stop을 단계적으로 끌어올립니다.
- **구조 정보 무시(또는 약화) 케이스 정의**: 백테스트에서는 아래 케이스를 `structure_ignore_case`로 분류해 stop 진단 CSV에 기록합니다.
  - `entry_lower_band_mode`: 진입 자체가 구조 저점(`swing_low`)이 아닌 하단밴드 기준
  - `atr_or_policy_overrides_swing`: 보유 중 정책 stop이 진입 구조 저점보다 위로 올라감
  - `initial_defense_tightening`: `entry - 0.85R` 방어 규칙이 stop을 상향
  - `breakeven_or_higher`: 손익분기 이상으로 stop 상향되어 구조 저점 기준이 사실상 비활성화
  - `structure_respected`: 관리 stop이 진입 구조 기준을 실질적으로 유지

1. **포지션 상태 갱신**
   - 매 사이클마다 `peak_price`, `bars_held`, ATR/스윙로우 참조값을 갱신합니다.
   - `PositionExitState`에 `entry_regime`, `highest_r`, `drawdown_from_peak_r`를 유지해 레짐/성과/되돌림 기반 청산 판단을 수행합니다.
2. **3단계 정책 기반 청산 (`PositionOrderPolicy.evaluate`)**
   - **초기 방어 (`initial_defense`)**: `highest_r < 1.0` && `bars_held < 8` 구간. 손절을 더 엄격하게 적용하고(엔트리 대비 약 `0.85R`), 분할익절은 대기.
   - **중기 관리 (`mid_management`)**: `highest_r >= 1.0` 또는 `bars_held >= 8` 이후. 분할익절 허용 + 본절 이동(브레이크이븐) 활성화.
   - **후기 추적 (`late_trailing`)**: `highest_r >= 2.0` 또는 `bars_held >= 24` 이후. 트레일링 스탑을 강화해 이익 잠금 비중을 높임.
#### 하드 스탑 기준선 (초기 0.85R 타이트닝 + ATR/swing max 규칙)
| 구간 | 기준식 | 최종 hard stop 산식 |
| --- | --- | --- |
| ATR 모드 기본 | `atr_stop = entry - ATR×atr_stop_mult`, `swing_base = entry_swing_low` | `max(atr_stop, swing_base)` (둘 다 0 이하이면 `entry×stop_loss_threshold`) |
| 초기 방어 (`initial_defense`) | 기본 스탑 + `entry - 0.85R` | `max(기본 스탑, entry - 0.85R)` |
| 중기/후기 (`mid/late`) | 기본 스탑 + 본절 가드 | `max(기본 스탑, entry)` (`breakeven_armed` 또는 `highest_r>=1.0`) |

- 따라서 **hard_stop_price가 가장 높아지는 조건은** `mid_management/late_trailing`에서 본절 가드가 활성화되고, ATR/swing 기반 스탑이 엔트리보다 낮을 때입니다(최종값이 `entry_price`로 상향 고정).

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



### 변경 요약 (2026-03-02, 최근 10건 거래 사유 텍스트 로그)
- 변경 요약: 엔진에서 매수/매도 주문 수락 시점마다 거래 사유를 기록하고, 최근 10건만 유지해 `logs/recent_trade_reasons.txt` 파일로 저장하도록 추가.
- 영향 파일: `core/engine.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. 실행 후 `logs/recent_trade_reasons.txt` 파일에서 `BUY/SELL`, `market`, `price`, `reason`을 최근 10건 기준으로 확인 가능.

### 변경 요약 (2026-03-02, 거래 사유 로그에 수량/주문금액 필드 확장)
- 변경 요약: `_append_trade_reason` 시그니처를 확장해 `qty`, `notional_krw`, `qty_ratio`를 선택적으로 기록하도록 변경. 매도 경로에서는 `decision.qty_ratio`, preflight 산출값(`order_value`, `notional`)을 함께 전달하고, 매수 경로에서도 preflight 주문금액(`order_value`)과 추정 수량(`order_value / reference_price`)을 로그에 포함하도록 확장. 로그 포맷은 `qty=... | notional_krw=... | qty_ratio=...` 필드를 고정 포함(`미제공 시 na`)하도록 통일.
- 영향 파일: `core/engine.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. `logs/recent_trade_reasons.txt` 확인 시 기존 `price/reason` 외에 `qty/notional_krw/qty_ratio` 필드가 함께 출력되는지 검증 필요.

### 변경 요약 (2026-03-02, stop reason 로그 진단 필드 고정)
- 변경 요약: `PositionOrderPolicy.evaluate`의 stop 계열 의사결정(`stop_loss`, `partial_stop_loss`, `trailing_stop`)에 `exit_stage`, `hard_stop_price`, `trailing_floor`를 포함한 진단값을 일관되게 담도록 정리하고, 엔진 SELL 경로에서 `decision.diagnostics`를 거래 사유 로그 기록 함수로 전달하도록 확장. `_append_trade_reason`는 stop 계열 reason에 한해 `stop_ref_price`, `stop_gap_pct`를 추가 기록하며 숫자 포맷을 고정(`price/qty/stop_ref_price: 8자리`, `qty_ratio/stop_gap_pct: 4자리`, `없음: na`)하도록 통일.
- 영향 파일: `core/position_policy.py`, `core/engine.py`, `testing/test_risk_and_policy.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: `python -m unittest testing.test_risk_and_policy testing.test_engine_order_acceptance`로 stop 진단 키 포함 및 stop reason 전용 로그 필드 출력 여부를 검증.


### 변경 요약 (2026-03-02, 거래 사유 로그에 포지션 식별자/보유시간 필드 추가)
- 변경 요약: 엔진에 시장별 포지션 식별자(`entry_order_id` 기반 `position_id`)와 진입 시각 상태 맵을 추가하고, BUY/SELL 거래 사유 로그 공통 필드에 `position_id`를 고정 기록하도록 확장. SELL 로그에는 진입 시각 대비 `holding_seconds`와 `holding_bars`를 함께 포함하고, 완전 청산(`decision.qty_ratio >= 1.0`) 시 관련 상태를 정리하도록 보강.
- 영향 파일: `core/engine.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 실행 커맨드는 동일. `python -m unittest testing.test_engine_order_acceptance` 실행 후 `logs/recent_trade_reasons.txt`에서 `position_id`, `holding_seconds`, `holding_bars` 필드 포함 여부를 확인.

### 변경 요약 (2026-03-02, 거래 사유 JSONL 추가 및 로테이션)
- 변경 요약: 기존 `logs/recent_trade_reasons.txt`(최근 10건 유지)는 유지하면서, append 전용 구조화 로그 `logs/trade_reasons.jsonl`를 추가. JSONL 스키마는 `ts, side, market, price, reason, qty, notional_krw, qty_ratio, position_id, holding_seconds, diagnostics`로 고정했으며, 파일이 최대 크기(기본 5MB)를 넘기면 `logs/trade_reasons.YYYYMMDDTHHMMSSZ.jsonl`로 회전 후 새 파일에 이어 기록.
- 영향 파일: `core/engine.py`, `testing/test_engine_order_acceptance.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일. 운영 확인 시 (1) `tail -n 10 logs/recent_trade_reasons.txt`로 최신 텍스트 10건을 점검하고, (2) `tail -n 5 logs/trade_reasons.jsonl` 또는 `python - <<'PY' ...`로 JSONL 필드 존재/타입(`diagnostics` 객체 포함)을 확인. 로그 파일 시스템 오류 시 콘솔에 `TRADE_REASON_JSONL_LOG_WRITE_FAILED` 경고가 출력됨.

### 변경 요약 (2026-03-02, trailing_floor 활성화 게이트 강화)
- 변경 요약: `PositionOrderPolicy.evaluate`의 트레일링 발동 조건을 강화해 `initial_defense` 구간에서는 트레일링을 비활성화하고 `hard_stop`만 적용하도록 분기했으며, 트레일링은 `breakeven_armed` 또는 `current_price >= entry_price` 게이트(옵션화)와 최소 보유 bar 게이트(`trailing_activation_bars`)를 모두 통과했을 때만 활성화되도록 조정.
- 영향 파일: `core/position_policy.py`, `core/config.py`, `core/config_loader.py`, `core/engine.py`, `testing/backtest_runner.py`, `config.py`, `testing/test_risk_and_policy.py`, `testing/test_config_loader.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기존 실행 커맨드는 동일하며, 필요 시 `TRADING_TRAILING_REQUIRES_BREAKEVEN`, `TRADING_TRAILING_ACTIVATION_BARS` 환경변수로 트레일링 게이트를 조정 가능. 회귀 검증 시 stop 계열 거래 사유 로그/진단(`trailing_armed`, `breakeven_armed`, `bars_held`, `trailing_floor_candidate`)을 함께 확인.

### 변경 요약 (2026-03-02, RSI-BB 진입 필터 강화 및 거절 사유 집계)
- 변경 요약: 시장 레짐별 `entry_score_threshold`를 상향 조정(특히 `sideways`)해 횡보 구간 과잉 진입을 억제했고, `entry_experiment_profile`에 `neckline_confirmed` 실험 프로파일을 추가해 `require_neckline_break=True` 조합을 선택적으로 적용할 수 있게 했습니다. 또한 기본값에서 `macd_histogram_filter_enabled=True`로 전환해 1분봉 노이즈 구간 MACD 히스토그램 방향성 확인을 기본 게이트로 강화했습니다.
- 영향 파일: `core/config.py`, `core/strategy.py`, `core/rsi_bb_reversal_long.py`, `core/engine.py`, `config.py`, `testing/test_rsi_bb_reversal_long.py`, `testing/test_config_loader.py`, `docs/PROJECT_REFERENCE.md`.
- 실행/검증 방법 변경 여부: 기본 실행 커맨드는 동일합니다. 운영 시 `engine.debug_counters`에서 `fail_entry_score_below_threshold`, `fail_entry_trigger_fail` 누적치를 확인해 진입 거절 사유 통계를 추적할 수 있습니다. `entry_experiment_profile=neckline_confirmed` 적용 시 더블바텀 neckline 돌파 확정 전 진입이 줄어드는지 백테스트/페이퍼에서 비교 검증하세요.
