# upbit_slave

## 실행 환경
- Python 3.10 권장 (최소 3.9 이상)
- `pip` 최신 버전 권장

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

## 환경 변수 설정
애플리케이션 실행 전에 아래 환경 변수를 반드시 설정해야 합니다.

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 메시지를 전송할 텔레그램 채팅 ID

예시는 `.env.example` 파일을 참고하세요.

## 실행 방법
```bash
python main.py
```

## 보안 취약점 점검
GitHub Actions CI에 `pip-audit` 점검 단계를 추가했습니다.
- 워크플로우: `.github/workflows/security-audit.yml`
- 점검 내용: `requirements.txt` 기준 알려진 파이썬 패키지 취약점 검사

로컬에서도 동일하게 점검할 수 있습니다.
```bash
pip install pip-audit
pip-audit -r requirements.txt --strict
```

## 운영 보안 체크리스트
토큰/비밀값이 코드 또는 Git 히스토리에 노출된 경우 아래 절차를 따르세요.

1. 노출된 토큰 즉시 폐기(Revocation) 및 재발급
2. 배포 환경/로컬 환경의 환경 변수 값을 신규 토큰으로 교체
3. Git 히스토리 정리 도구(`git filter-repo`, BFG 등)로 민감정보 제거
4. 원격 저장소 강제 푸시 후, 협업자 로컬 저장소 히스토리 동기화 안내
5. 보안 스캔/로그 점검으로 재노출 여부 확인
