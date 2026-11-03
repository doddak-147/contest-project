# Contestly

여러 사이트의 공모전을 통합 검색하고, 지원 준비부터 서비스 운영까지 관리하는 웹 애플리케이션입니다. 기존 정적 페이지를 **FastAPI + 관계형 DB** 구조로 확장했습니다.

이어서 작업하려면 [작업 체크포인트·집에서 이어하기](docs/HANDOFF.md)를 먼저 확인하세요. 완료한 구현·CI 검증·확인한 서버 사양과 다음 조회 명령을 정리했습니다.

## 구현한 기능

- 씽굿·위비티·콘테스트코리아 수집, 출처별 원본·ID 보존, 보수적인 중복 통합
- 서버 검색·필터·정렬, 페이지당 24개, 한국 시간 기준 접수 예정·접수 중·종료 구분
- 마감 후에도 보존되는 공모전과 개인 도전 보드, 메모·체크리스트·캘린더 내보내기
- 공고와 출처별 정보의 변경 이력, 마감일이 다른 유사 공고의 검토 대기 목록
- 회원가입·로그인, 계정별 기록 저장, 명시적인 비회원 기록 가져오기
- 일반 사용자·관리자 권한 분리, 수집 실행·결과·충돌 검토·권한 변경·감사 로그 화면
- Alembic 마이그레이션, 백업·복원 명령, Docker Compose 배포 구성, 자동 검증 CI

## 로컬 실행

Python 3.11 이상이 필요합니다. CI 기준은 3.13이며, 이번 로컬 검증은 Windows / Python 3.14에서 수행했습니다.

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

[서비스](http://127.0.0.1:8000), [API 문서](http://127.0.0.1:8000/docs)에 접속합니다. 개발 기본값에서는 첫 실행 시 스키마와 `data/` 스냅샷을 자동 반영합니다. DB는 `runtime/contestly.db`에 저장됩니다. 가상환경을 사용한다면 설치·실행·관리 명령 모두 `py -3` 대신 같은 가상환경의 Python 경로로 실행합니다.

관리자는 직접 생성합니다. 기본 관리자 계정이나 기본 비밀번호는 없습니다.

```powershell
py -3 -m backend.manage create-admin --username operator
```

비밀번호를 입력한 뒤 사이트에서 로그인하면 [운영 관리](http://127.0.0.1:8000/admin)로 이동할 수 있습니다. 일반 회원가입으로는 관리자 권한을 얻을 수 없습니다.

## 수집과 DB 갱신

```powershell
# 수집 → 검증 → DB 반영 → 변경 이력 기록
py -3 -m backend.manage collect
py -3 -m backend.manage collect --sources wevity contestkorea --max-pages 10

# 이미 저장된 JSON을 DB에 반영 / 매일 한국 시간 09시 이후 자동 수집
py -3 -m backend.manage import-data
py -3 -m backend.manage schedule
```

| 출처 | 기본 수집 범위 |
| --- | --- |
| [씽굿](https://www.thinkcontest.com/thinkgood/user/contest/index.do) | 접수 중·마감 임박·접수 예정 목록 전체 |
| [위비티](https://www.wevity.com/?c=find&s=1&gub=1) | 접수 중·예정 목록별 최근 5페이지와 상세 정보 |
| [콘테스트코리아](https://www.contestkorea.com/sub/list.php?int_gbn=1) | 대회·공모전 최근 5페이지와 상세 정보 |

`data/sources/*.json`은 출처별 마지막 성공 데이터, `data/contests.json`은 통합 목록, `data/collection-status.json`은 수집 결과입니다. 일부 출처가 실패하면 유효한 이전 데이터를 사용하고, 모두 실패하면 기존 통합 목록과 DB를 유지합니다. 최근 페이지 수집은 사이트 전체를 포괄하지 않습니다.

`scripts/scrape.py`와 `Daily Contest Update` GitHub Actions는 **JSON만 갱신**합니다. 운영 DB 갱신에는 위의 `manage collect` 또는 `import-data`가 필요합니다. Docker 운영 환경에서는 별도 수집 컨테이너가 이를 담당합니다.

## 검증

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -X utf8 -B -m unittest discover -s tests -v
py -3 -B scripts/verify_browser.py
py -3 -B scripts/verify_recovery.py
```

브라우저 검증에는 Chrome/Chromium이 필요하며 `CHROME_BIN`으로 경로를 지정할 수 있습니다. 별도 임시 DB·프로필을 사용합니다. 복원 검증은 현재 SQLite DB를 읽어 **새 DB**로 복원하며 원본을 변경하지 않습니다. 결과는 `runtime/` 아래에 생성됩니다.

2026-11-03 결과: 로컬 자동 테스트 **35개 통과 / PostgreSQL 1개 건너뜀**, GitHub Actions에서는 PostgreSQL 테스트를 포함해 **36개 모두 통과**, 브라우저 시나리오 **9개 통과**했습니다. CI에서 Docker 이미지 빌드, 공모전 **509개**의 PostgreSQL 백업·복원, 계정·메모 보존과 세션 폐기, 복원 DB에 연결한 컨테이너 기동까지 확인했습니다. SQLite 복원도 검증했습니다. [검증 기록](docs/verification.md)에 실행 링크와 측정값이 있습니다. 공개 서버 배포는 아직 하지 않았습니다.

## 설계·운영·포트폴리오 문서

- [아키텍처·ERD·설계 결정](docs/architecture.md)
- [배포·운영·장애 대응·백업과 복원](docs/operations.md)
- [포트폴리오 설명과 면접 시연 순서](docs/portfolio.md)
- [실제 검증 결과와 미검증 항목](docs/verification.md)
- [마감일 충돌 원문 검토 기록](docs/data-quality-review.md)

비회원 기록은 해당 브라우저의 `localStorage`, 로그인 기록은 서버 DB에 저장합니다. 기존 비회원 기록은 사용자 선택 시에만 계정으로 가져옵니다. 정적 미리보기(`py -3 -m http.server 8000`)도 유지하지만 계정·관리자·서버 이력 기능은 API 서버에서만 제공됩니다.
