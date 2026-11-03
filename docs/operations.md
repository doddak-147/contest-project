# 운영 가이드

## 개발 DB 관리

프로젝트 루트에서 실행합니다. 사용자 지정 값은 `.env.example`을 참고해 `.env`에 설정합니다. 운영 DB·세션·백업·환경 파일은 Git에서 제외했습니다.

```powershell
py -3 -m backend.manage init-db
py -3 -m backend.manage import-data
py -3 -m backend.manage create-admin --username operator
py -3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`init-db`는 Alembic을 최신 버전까지 적용합니다. 기존 계정을 CLI로 자동 승격하지 않으며 기존 관리자가 화면에서 변경해야 합니다. 자기 자신의 관리자 권한을 내리는 요청은 거절합니다.

## Docker Compose 배포 준비

필요 조건은 Docker Compose, 서비스 도메인의 서버 IP 연결, 외부 80/443 포트입니다. CI에서 이미지 빌드·PostgreSQL 복원·복원 DB에 연결한 앱 컨테이너 기동은 검증했습니다. Caddy·수집·백업을 포함한 Compose 전체 기동은 배포 서버에서 추가 확인해야 합니다. 아래 기본 절차는 80/443 포트를 이 서비스가 사용할 수 있는 서버 기준입니다.

1. `.env.example`을 `.env`로 복사하고 `DOMAIN`을 실제 도메인으로 설정합니다.
2. `POSTGRES_PASSWORD`에 생성한 임의의 16진수 비밀번호를 설정합니다. `python -c "import secrets; print(secrets.token_hex(32))"`로 생성할 수 있습니다.
3. `docker compose config --quiet`로 설정을 확인한 뒤 `docker compose up -d --build`로 실행합니다.
4. `docker compose ps`와 `https://도메인/api/health`를 확인합니다.
5. `docker compose exec app python -m backend.manage create-admin --username operator`로 관리자를 생성합니다.

Compose는 `.env`의 개발용 `DATABASE_URL`·`APP_ENV` 대신 서비스에 명시한 PostgreSQL·운영 설정을 사용합니다. Caddy가 HTTPS를 제공하고 앱 포트는 호스트 루프백에만 연결합니다. DB 포트는 외부에 공개하지 않습니다. 앱 시작 시 마이그레이션과 스냅샷 반영 후 서버를 실행합니다.

### 기존 서비스와 같은 서버를 사용하는 경우

네이버 클라우드의 기존 서버도 활용할 수 있지만 OS·자원·현재 서비스 구성을 먼저 확인합니다. **기존 웹서버가 80/443 또는 8000을 사용 중인 상태에서 위의 전체 실행 명령을 바로 실행하지 않습니다.** 기존 Nginx/Caddy가 있으면 해당 프록시를 유지하고 새 서비스용 도메인과 내부 포트를 별도로 연결하는 구성을 먼저 정합니다.

Linux 서버에서는 다음과 같이 읽기 전용으로 상태를 확인할 수 있습니다. Docker가 없거나 권한이 부족하면 해당 명령은 오류만 확인하고 설치·권한 변경을 자동으로 진행하지 않습니다.

```sh
cat /etc/os-release
free -h
df -h /
ss -lnt
docker --version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
```

확인 후 이 프로젝트의 Compose 프로젝트명·컨테이너·볼륨을 기존 서비스와 분리하고, 여유 있는 내부 포트와 기존 프록시 연결을 결정합니다. 기존 서비스 중단·프록시 설정 교체·포트 개방·인프라 증설은 서버 정보를 검토하고 변경 범위를 확인한 뒤 진행합니다. 네이버 클라우드의 접속 방식과 ACG는 [공식 서버 접속 안내](https://guide.ncloud-docs.com/docs/server-access-classic)도 참고하되, 실제 VPC/Classic 환경에 맞춰 확인해야 합니다.

| 서비스 | 역할·영속 데이터 |
| --- | --- |
| `app` | API·웹 화면, 수집 스냅샷 `catalogue` 볼륨 |
| `db` | PostgreSQL 17, `postgres_data` 볼륨 |
| `collector` | 매일 한국 시간 09시 이후 당일 1회 수집 시도, 같은 스냅샷 볼륨 공유 |
| `backup` | 기동 시 및 이후 한국 날짜마다 1회 백업, `database_backups` 볼륨 |
| `proxy` | Caddy HTTPS, 인증서·설정 영속 볼륨 |

예약 수집 실패는 자동 무한 재시도하지 않습니다. 원인을 확인하고 관리자 화면이나 CLI로 다시 실행합니다. 예약 백업은 실패 시 30초 후 다시 시도합니다. 백업 보관 기간별 삭제와 외부 저장소 복제는 아직 자동화하지 않았습니다. 같은 호스트의 볼륨만으로는 호스트 손실에 대비할 수 없으므로 별도 저장소로의 복사가 필요합니다.

## 일상 점검과 장애 대응

```sh
docker compose ps
docker compose logs --tail=100 app collector backup
docker compose exec app python -m backend.manage collect --sources wevity --max-pages 5
```

앱 `/api/health`는 DB 연결을 확인하며 연결 실패 시 503입니다. 관리자 화면은 출처별 성공·캐시 상태, 최근 실행·실패 사유, 미검토 충돌, 사용자 권한과 감사 로그를 제공합니다. 요청 로그의 `request_id`는 응답의 `X-Request-ID`와 대조할 수 있습니다.

| 증상 | 확인과 대응 |
| --- | --- |
| 특정 사이트만 실패 | 마지막 성공 시각·실패 사유 확인 → 외부 응답·파서 확인 → 해당 출처만 재수집 |
| 전체 수집 실패 | 기존 DB 유지 확인 → 네트워크·사이트 변경 점검 → 수정 후 재실행 |
| 중단 후 수집 중으로 남음 | 프로세스 상태 확인, 1시간 임대 만료 후 다음 수집에서 회수; 실행 중인 잠금 강제 삭제 금지 |
| 기록 저장 409 | 다른 기기의 최신 기록을 불러온 뒤 수정 내용을 다시 적용 |
| 헬스 체크 503 | DB 컨테이너 상태·연결 설정·디스크 확인; DB 파일/볼륨을 지우지 않음 |
| 마감일 충돌 | 양쪽 원문 확인 → 검토 메모와 처리 상태 저장; 이 작업은 공고 자동 병합이 아님 |

## SQLite 백업·복원 실증

```powershell
py -3 -m backend.manage backup --output backups/manual-20261103.sqlite
py -3 -m backend.manage restore --input backups/manual-20261103.sqlite --target sqlite:///runtime/recovered-20261103.db
```

백업은 SQLite 온라인 백업 API를 사용합니다. DB 파일과 `.json` 매니페스트가 한 쌍이며 SHA-256, 생성 시각, 테이블별 건수를 포함합니다. 완료된 스냅샷만 게시하고 같은 파일 이름을 덮어쓰지 않습니다. 복원 대상은 **존재하지 않는 새 파일**이어야 합니다.

복원은 체크섬·DB 무결성·테이블별 건수를 확인한 후 로그인 세션을 폐기합니다. 건수 비교는 세션 폐기 전에 수행하므로 이후 `login_sessions` 건수는 0이 정상입니다. 실증 자동화는 다음 명령으로 실행합니다. 매번 새 디렉터리를 만들며 원본 DB는 변경하지 않습니다.

```powershell
py -3 -B scripts/verify_recovery.py
```

보고서와 실증 DB는 `runtime/recovery-qa/run-*/`에 생성됩니다. 검증 보고서의 소요 시간은 해당 데이터·장비에서 측정한 값이지 운영 환경의 복구 시간 보장은 아닙니다.

## PostgreSQL 백업·별도 DB 복원

수동 백업 예시입니다. 파일 이름은 매번 바꿉니다.

```sh
docker compose exec backup python -m backend.manage backup --output /backups/manual-20261103.dump
docker compose exec db createdb -U contestly contestly_recovery
```

백업은 `REPEATABLE READ`에서 내보낸 스냅샷으로 `pg_dump`와 건수 조회를 일치시킵니다. 복원은 **비어 있는 별도 DB**에만 허용하며 `pg_restore --single-transaction`을 사용합니다. 다음은 Linux 배포 서버에서 비밀번호를 명령 인자로 적지 않고 대상 DB 이름만 바꿔 복원하는 예시입니다.

```sh
docker compose exec -T backup python - <<'PY'
import os
from sqlalchemy.engine import make_url
from backend.backup import restore_database
target = make_url(os.environ['DATABASE_URL']).set(database='contestly_recovery')
print(restore_database('/backups/manual-20261103.dump', target))
PY
```

결과의 `verified`와 `sessions_revoked`를 확인하고 복구 DB의 실제 화면·사용자 기록을 별도 앱에서 검증합니다. 이 단계는 운영 DB를 교체하지 않습니다. 전환은 유지보수 창에서 앱·수집·백업 프로세스를 중지하고 연결 대상과 롤백 방법을 확정한 뒤 진행해야 합니다. 원본 볼륨을 삭제하는 `docker compose down -v`는 복구 절차에 사용하지 않습니다.

## 자동 검증

`Application checks`는 단위·API 테스트, 별도 PostgreSQL 17 DB 통합 테스트, Chrome 화면 시나리오, SQLite 복원 실증, Docker 이미지 빌드, PostgreSQL 복원 후 앱 기동을 실행합니다. 브라우저 증거와 복원 보고서를 CI 산출물로 남깁니다. [2026-11-03 성공 실행](https://github.com/doddak-147/contest-project/actions/runs/41579385107)과 측정값은 [검증 기록](verification.md)에 있습니다. CI의 테스트 DB 실증과 실제 운영 서버 배포는 구분합니다.
