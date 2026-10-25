# CloudShell 배포 스크립트 (초안, 보류)

결정 0007-5. **지금은 쓰지 않는다.** 첫 배포는 사람이 콘솔에서 직접 한다(2026-10-25 팀 결정). 콘솔 작업이 익숙해진 뒤 반복 배포가 번거로우면 이 스크립트로 바꾼다.

- 실행해 본 적 없음(`bash -n` 문법 검사만).
- `create.sh`: 처음 1번 리소스 생성. `update.sh`: 코드 변경 반영. `build_zip.sh`: Lambda 공통 zip.
- 쓰기 전에 필요한 것: `infra/asl/analyze.asl.json`, `scripts/create_tables.py --region` 옵션, 학교 계정 권한 확인.
