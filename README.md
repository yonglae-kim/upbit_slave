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

## 실행 방법
```bash
python main.py
```

## 운영 보안 체크리스트
토큰/비밀값이 코드 또는 Git 히스토리에 노출된 경우 아래 절차를 따르세요.

1. 노출된 토큰 즉시 폐기(Revocation) 및 재발급
2. 배포 환경/로컬 환경의 환경 변수 값을 신규 토큰으로 교체
3. Git 히스토리 정리 도구(`git filter-repo`, BFG 등)로 민감정보 제거
4. 원격 저장소 강제 푸시 후, 협업자 로컬 저장소 히스토리 동기화 안내
5. 보안 스캔/로그 점검으로 재노출 여부 확인

## 구현 계획 문서
- 순차 실행 계획: `docs/implementation_plan.md`
