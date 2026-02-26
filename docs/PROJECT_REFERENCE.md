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
```

## 4) 환경변수 핵심 포인트
- `TRADING_MODE`: `live | paper | dry_run`
- `TRADING_MIN_ORDER_KRW`: 최소 주문금액 하한
- `TRADING_MIN_BUYABLE_KRW`: 추가 버퍼(엔진 하한 계산 시 `max` 적용)
- `TRADING_DO_NOT_TRADING`: 제외 심볼/마켓 목록(쉼표 구분)
- `UPBIT_API_DEBUG`: API 요청/응답 디버그 로그 on/off

## 5) 변경 시 반드시 같이 업데이트할 항목
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
