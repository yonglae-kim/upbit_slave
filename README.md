# upbit_slave

## 실행 환경
- Python 3.10 권장 (최소 3.9 이상)
- `pip` 최신 버전 권장
- 권장: Python 3.10+/OpenSSL 1.1.1+ 환경으로 업그레이드
- 레거시 OpenSSL 환경에서는 `urllib3<2` 제약을 유지해야 함

### 재현/검증 포인트
- 재현 키워드: `ImportError: urllib3 v2 only supports OpenSSL 1.1.1+`
- 점검 파일
  - `requirements.txt` (`urllib3`, `requests` 버전 범위)
  - `README.md` (실행 환경/OpenSSL 안내)

## 설치 가이드
1. 가상환경 생성 및 활성화
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. 의존성 설치
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

## 실행 방법
권장 실행 순서는 아래와 같습니다.

1. **첫 실행은 `paper` 또는 `dry_run` 모드**로 진행해 전략/환경 설정을 먼저 검증합니다.
2. 동작 확인 후 필요한 리스크 설정과 모니터링 체계를 갖춘 다음 `live` 모드로 전환합니다.

모드별 실행 예시:

```bash
TRADING_MODE=paper python main.py
TRADING_MODE=dry_run python main.py
```

라이브 실행(마지막 단계):

```bash
TRADING_MODE=live python main.py
```

라이브 실행 전 체크리스트:

- [ ] 업비트 자격 증명(API Key/Secret) 및 권한이 올바르게 설정되어 있는지 확인
- [ ] 허용 손실 범위, 포지션/보유 수 제한 등 리스크 설정을 점검
- [ ] 실행 중 상태를 확인할 모니터링(로그/알림) 경로를 준비

로그/알림 확인 포인트:

- 콘솔 출력에서 모드(`TRADING_MODE`)와 주요 이벤트(신호/주문 시도/에러) 확인
- notifier가 정상 동작하는지(알림 채널 전송 여부) 확인

실패 시 우선 확인할 파일:

- `main.py`
- `core/config_loader.py`

### API 디버그 로그 옵션

API 호출 추적이 필요할 때 `UPBIT_API_DEBUG` 환경변수로 요청/응답 로그를 켤 수 있습니다.

- 활성화 값: `1`, `true`, `yes`, `on` (대소문자/공백 무시)
- 비활성화 시(기본값) 디버그 로그를 출력하지 않습니다.

예시:

```bash
UPBIT_API_DEBUG=1 python main.py
```

디버그 로그는 `[UPBIT_API_DEBUG]` prefix로 출력되며, `Authorization` 헤더는 `Bearer ****<tail>` 형태로 마스킹되어 출력됩니다.

## 설정 (Configuration)

`core/config_loader.py` 기준으로 `TRADING_MODE`는 아래 3가지를 지원합니다.

- `live`: 업비트 실거래 API를 사용해 실제 주문을 실행하는 모드
- `paper`: 가상 잔고(`TRADING_PAPER_INITIAL_KRW`)로 주문을 시뮬레이션하는 모드
- `dry_run`: 신호/의사결정만 점검하고 실제 체결(실거래/가상체결)을 하지 않는 점검 모드

최소 시작용 환경 변수 예시(`.env` 스타일):

```env
TRADING_MODE=paper
TRADING_DO_NOT_TRADING=KRW-BTC,KRW-ETH
TRADING_PAPER_INITIAL_KRW=1000000
TRADING_MAX_HOLDINGS=4
```

기본값은 `TradingConfig`를 따르며, 상세 키와 로딩/검증 규칙은 `core/config.py`, `core/config_loader.py`를 참고하세요.

> [!WARNING]
> `live` 모드 사용 전에는 반드시 **실거래 API 키 권한(주문/출금 제한 포함)** 과 **허용 가능한 손실 범위/리스크 설정**을 재확인하세요.

## 운영 보안 체크리스트
토큰/비밀값이 코드 또는 Git 히스토리에 노출된 경우 아래 절차를 따르세요.

1. 노출된 토큰 즉시 폐기(Revocation) 및 재발급
2. 배포 환경/로컬 환경의 환경 변수 값을 신규 토큰으로 교체
3. Git 히스토리 정리 도구(`git filter-repo`, BFG 등)로 민감정보 제거
4. 원격 저장소 강제 푸시 후, 협업자 로컬 저장소 히스토리 동기화 안내
5. 보안 스캔/로그 점검으로 재노출 여부 확인

## 구현 계획 문서
- 순차 실행 계획: `docs/implementation_plan.md`
