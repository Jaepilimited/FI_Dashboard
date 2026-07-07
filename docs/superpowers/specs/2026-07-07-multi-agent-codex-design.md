# Claude+Codex 멀티에이전트 오케스트레이션 (multi-agent-starter 적용)

## 배경

[netwaif/multi-agent-starter](https://github.com/netwaif/multi-agent-starter)는 Claude Code를 오케스트레이터로, Codex/Gemini를 워커로 붙이는 파일 기반 멀티에이전트 시스템을 자동 생성해주는 도구다. 이 프로젝트(FI Dashboard)에서 Codex CLI(설치됨, v0.142.5)를 워커로 활용해 다음 3가지 용도에 쓰고자 한다:

1. 코드 작성/리팩터링 병렬화
2. 독립적인 2차 검증(리뷰)
3. 대량/반복 작업 실행

레포의 핵심 안전장치는 "모든 워커 호출 전 명시적 승인"이지만, 이 프로젝트에서는 매번 승인받는 대신 **git worktree 격리 + 자동 테스트 게이트**를 안전망으로 삼아 전 과정을 자동화하기로 결정했다.

**주의(2026-07-07 실사용 조사 후 수정)**: 최초 설계 당시엔 `call_worker.sh`가 git worktree/병합까지 담당하는 범용 디스패처라고 가정했으나, 실제로 스크래치 폴더에 generator를 돌려 생성물을 확인한 결과 다르다는 게 드러났다. 아래는 실제 도구 동작 확인 후 수정된 내용이다.

## 실제 도구 동작 (2026-07-07 스크래치 실행으로 확인)

- **codex-main/codex-critic 호출은 MCP가 기본 경로**다. generator가 `.mcp.json`에 `codex mcp-server`(설치된 codex CLI의 서브커맨드)를 자동 등록하고, 오케스트레이터가 `mcp__codex__codex` 도구를 직접 호출한다. `_shared/adapters/call_worker.sh`는 **native/mcp 호출을 거부**하며(`die "native/mcp는 오케스트레이터 직접 호출"`), MCP 실패 시의 CLI 폴백(`codex exec -`, stdin)에만 쓰이는 범용 cli/api 디스패처다. git/worktree와는 무관.
- **git worktree 격리·자동 병합은 도구에 원래 없는 기능**이다. 실제 안전 모델(`_shared/routing.md`, `CLAUDE.md`)은: 워커는 기본적으로 `tasks/<task>/` 폴더 안에만 쓰고, 실제 프로젝트 파일(`target_repo`)에 쓰려면 브리핑에 `target_repo`+`write_scope`를 지정하고 4조건(target_repo 명시/write_scope 명시/task.md workers_approved 승인/log.md `[APPROVAL]` 기록)을 충족해야 한다. "병합"이라는 개념 자체가 없다 — 그냥 지정된 cwd에 sandbox(`workspace-write`)로 직접 쓴다.
- **승인 게이트는 설정값이 아니라 텍스트**다: `CLAUDE.md`의 "## Approval Gate" 섹션과 `_shared/approval-policy.md` 전체가 "모든 worker 호출은 작업별 명시적 승인 필요"를 명문화한 마크다운이다. 이 프로젝트에서는 이 텍스트를 자동승인 규칙으로 교체한다.
- **Gemini 워커는 삭제 불가**: `validate.py`의 C6 검사가 `claude` flavor에서 `backends.json`에 `gemini` 워커 항목(call_type=cli, command=agy, model=gemini-3.1-pro-high)이 존재하기를 요구한다. 삭제하면 검증이 깨지므로, 정의는 그대로 두고 `_shared/routing.md`의 기존 규칙("gemini는 명시적 트리거 시만 호출")으로 실사용에서만 배제한다. **backends.json 자체는 패치 불필요.**
- codex-critic은 이미 생성 시점부터 `sandbox: read-only` 고정 — 별도 조치 불필요.

## 범위

- 대상: FI Dashboard 프로젝트 루트 (`git remote: Jaepilimited/FI_Dashboard`) 전용 설정. 다른 프로젝트에 재사용하지 않음
- flavor: `claude` (오케스트레이터=Claude Code, 워커=Codex). Gemini는 정의만 남기고 실사용에서 배제(위 사유)
- 기존 `docs/superpowers/{plans,specs}`(브레인스토밍/계획 스킬 산출물)와는 별개 메커니즘. multi-agent-starter의 `tasks/`는 오케스트레이션 실행 상태(file-as-memory)를 담는 폴더로, 계획 문서와 혼용하지 않는다

## 구성 요소

### 1. Generator 실행
```
python /c/tmp_mas/src/plugins/multi-agent-starter/skills/configure-multiagent/generator/init.py \
  --flavor claude --target "<FI Dashboard 루트>" --yes
```
(Windows 환경에서는 `PYTHONIOENCODING=utf-8`을 붙여야 `validate.py`가 한글/이모지 출력 시 `cp949` 인코딩 오류 없이 동작함)

생성물(확인됨, 28개 파일): `CLAUDE.md`(루트), `.mcp.json`, `.claude/agents/claude-main.md`, `_shared/backends.json`, `_shared/approval-policy.md`, `_shared/routing.md`, `_shared/orchestrator-rules.md`, `_shared/design-basis.md`, `_shared/system-invariants.md`, `_shared/learnings.md`, `_shared/adapters/{call_worker.sh,_run.py,gemini_api.sh}`, `_templates/*`, `tasks/.gitkeep`, `_local/.gitkeep`, `README.md`/`CHANGELOG.md`/`KNOWN_ISSUES.md`/`LICENSE`/`NOTICE`.

### 2. 커스터마이징 패치 (2곳 + 1개 신규 섹션)

**a. `CLAUDE.md` + `_shared/approval-policy.md` 승인 게이트 텍스트 교체**
"모든 worker 호출은 작업별로 명시적 승인 필요" 원칙을 다음으로 대체:
> Codex 워커(codex-main, codex-critic) 호출은 이 프로젝트에서 자동 승인한다. 사용자에게 매 호출 승인을 구하지 않되, `task.md`의 `workers_approved`와 `log.md`의 `[APPROVAL]` 기록은 그대로 자동 작성한다(감사 추적용, 승인 대기 없음). claude-main(Opus subagent)은 기존 정책 유지 — 별도 비용 발생 호출이므로 그대로 승인 필요.

**b. `CLAUDE.md`에 "FI Dashboard 프로젝트 전용 규칙" 섹션 신규 추가** — codex-main을 실제 프로젝트 파일 작업에 쓸 때(target_repo가 필요한 경우)의 절차를 명문화:
1. 오케스트레이터가 `git worktree add _local/wt-<task-id> -b agent/<task-id>` 로 격리된 브랜치 생성 (사용자에게 target_repo를 묻지 않고 자동으로 이 경로를 브리핑의 `target_repo`에 채움, `write_scope`는 작업 성격에 맞는 경로 패턴)
2. `mcp__codex__codex` 호출 (cwd=worktree 경로, sandbox=`workspace-write`) — 실패 시 `_shared/adapters/call_worker.sh codex-main <brief>` CLI 폴백(기존 backends.json 폴백 그대로 사용)
3. 완료 후 worktree 안에서 기존 `pytest` 실행 (테스트로 커버 안 되는 변경은 codex-critic 리뷰 통과 여부로 대체)
   - 통과 → 현재 브랜치로 자동 병합(`git merge --no-ff agent/<task-id>`), worktree 삭제, diff 요약을 채팅에 통지
   - 실패 → 병합 보류, worktree/브랜치 보존, 실패 사유+브랜치명을 채팅으로 즉시 통지 (자동 재시도 없음)
4. codex 호출 자체가 실패한 경우(설치/인증 문제 등)도 worktree 정리 후 즉시 에러 보고
5. codex-critic(리뷰 전용, read-only)은 worktree 불필요 — cwd=프로젝트 루트 직접 참조로 충분(쓰기 자체가 sandbox로 막혀 있음)

**c. `_shared/routing.md`의 codex-main "brief 필수 필드" 절 업데이트** — "오케스트레이터가 사용자에게 target_repo를 먼저 묻고" 문구를 "오케스트레이터가 worktree를 자동 생성해 target_repo에 채움(사용자에게 묻지 않음)"으로 수정.

## 워크플로우 매핑 (3용도 → 토폴로지)

| 용도 | 토폴로지 | 실행 방식 |
|---|---|---|
| 코드 작성/리팩터링 병렬화 | Fan-out/Fan-in | 독립 파일/모듈 단위로 worktree를 여러 개 만들어 codex-main 병렬 호출, 각각 위 자동 게이트 통과 후 개별 병합 |
| 독립적 2차 검증(리뷰) | Producer-Reviewer | Claude(claude-main 또는 오케스트레이터 자신)가 작성한 변경을 병합 전 codex-critic(read-only, MCP)으로 자동 리뷰, 문제 제기 시 병합 보류 |
| 대량/반복 작업 | Pipeline | 여러 파일에 동일 패턴 적용 시 파일별 codex-main 순차/병렬 호출 후 동일 게이트 적용 |

Expert Pool 패턴은 생성은 되지만(문서로만 존재, "worker 선택 정책"이라는 의미로 이미 decision tree에 내재) 별도 실행 예시로 강조하지 않는다.

## 영향받지 않는 부분

- 기존 `docs/superpowers/{plans,specs}` 워크플로우(브레인스토밍→계획→실행) — 변경 없음, multi-agent-starter는 그 위에 추가되는 별도 실행 메커니즘
- 앱 코드(`app_v2.py`, `build_fi_sm.py` 등)의 로직 — 이번 설정 자체는 오케스트레이션 인프라만 추가, 앱 기능 변경 없음
- 사용자의 글로벌 `~/.claude/CLAUDE.md` 모델 위임 규칙 — 별도 체계이며 충돌하지 않음 (multi-agent-starter는 이 프로젝트 로컬 실행 규칙)
- `_shared/adapters/call_worker.sh`, `_shared/backends.json`, `.mcp.json` — 생성된 그대로 사용, 코드 수정 없음

## 검증 계획

1. `init.py --flavor claude --target . --yes` 실행 → `PYTHONIOENCODING=utf-8 python validate.py --flavor claude --target .` 로 12개 체크 전부 PASS 확인
2. 패치 적용 후 실제 더미 태스크로 엔드투엔드 1회 시연:
   - 사소한 실제 리팩터링 1건을 codex-main에 위임 → worktree 생성 → MCP(`mcp__codex__codex`) 호출 → pytest 게이트 → 자동 병합까지 전 과정 확인
   - 의도적으로 실패하는 케이스(존재하지 않는 테스트 참조 등) 1회 시연 → "병합 보류 + 브랜치 보존 + 통지" 경로 확인
   - codex-critic 리뷰 1회 시연 (read-only, target_repo=프로젝트 루트)
3. `bash tests/run.sh` (레포 자체 회귀 테스트, 외부 모델 호출 없음, `/c/tmp_mas/src`에서) 참고 실행
