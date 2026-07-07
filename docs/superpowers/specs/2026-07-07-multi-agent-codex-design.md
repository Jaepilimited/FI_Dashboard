# Claude+Codex 멀티에이전트 오케스트레이션 (multi-agent-starter 적용)

## 배경

[netwaif/multi-agent-starter](https://github.com/netwaif/multi-agent-starter)는 Claude Code를 오케스트레이터로, Codex/Gemini를 워커로 붙이는 파일 기반 멀티에이전트 시스템을 자동 생성해주는 도구다. 이 프로젝트(FI Dashboard)에서 Codex CLI(설치됨, v0.142.5)를 워커로 활용해 다음 3가지 용도에 쓰고자 한다:

1. 코드 작성/리팩터링 병렬화
2. 독립적인 2차 검증(리뷰)
3. 대량/반복 작업 실행

레포의 핵심 안전장치는 "모든 워커 호출 전 명시적 승인"이지만, 이 프로젝트에서는 매번 승인받는 대신 **git worktree 격리 + 자동 테스트 게이트**를 안전망으로 삼아 전 과정을 자동화하기로 결정했다.

## 범위

- 대상: FI Dashboard 프로젝트 루트 (`git remote: Jaepilimited/FI_Dashboard`) 전용 설정. 다른 프로젝트에 재사용하지 않음
- flavor: `claude` (오케스트레이터=Claude Code, 워커=Codex). Gemini 워커는 설정하지 않음(jq 등 추가 의존성 불필요, 현재 용도에 없음)
- 기존 `docs/superpowers/{plans,specs}`(브레인스토밍/계획 스킬 산출물)와는 별개 메커니즘. multi-agent-starter의 `tasks/`는 오케스트레이션 실행 상태(file-as-memory)를 담는 폴더로, 계획 문서와 혼용하지 않는다

## 구성 요소

### 1. Generator 실행
```
python3 plugins/multi-agent-starter/skills/configure-multiagent/generator/init.py \
  --flavor claude --target "<FI Dashboard 루트>" --yes
```
표준 구조 생성 후 `validate.py`로 구조 검증. 생성물: `CLAUDE.md`(프로젝트 루트, 신규), `_shared/backends.json`, `call_worker.sh`, `tasks/`, `_local/`, 4개 토폴로지 문서(Pipeline/Fan-out·Fan-in/Expert Pool/Producer-Reviewer).

### 2. 커스터마이징 패치 (3곳)

**a. `_shared/backends.json`** — Codex만 활성 워커로 등록:
- role: `codex-worker` → connection: `cli` → command: `codex` (worker 실행), `codex review` (리뷰 실행)
- Gemini 슬롯은 설정하지 않음

**b. `CLAUDE.md` 승인 게이트 섹션 교체** — "모든 워커 호출 전 명시적 승인" → 아래 규칙으로 대체:
> Codex 워커 호출은 자동 승인한다. 안전망은 (1) 모든 작업이 격리된 git worktree/브랜치에서 실행되고 (2) 병합 전 자동 테스트(또는 `codex review`) 게이트를 통과해야 현재 브랜치에 반영된다는 점이다. 사용자에게 매 호출 승인을 구하지 않되, 병합 완료/보류 시 결과를 채팅으로 통지한다.

**c. `call_worker.sh` 병합 로직에 자동 게이트 추가**:
1. `git worktree add _local/wt-<task-id> -b agent/<task-id>` 로 격리
2. `codex exec -s workspace-write -C _local/wt-<task-id> "<prompt>"` 비대화형 실행 (승인 프롬프트 없음, workspace 내 쓰기만 허용)
3. worktree 안에서 기존 `pytest` 실행 (테스트가 없는 변경은 `codex review --uncommitted` 통과 여부로 대체)
   - 통과 → 현재 브랜치로 자동 병합, worktree 삭제, diff 요약을 채팅에 통지
   - 실패 → 병합 보류, worktree/브랜치 보존, 실패 사유+브랜치명을 채팅으로 즉시 통지 (자동 재시도 없음)
4. `codex exec` 자체가 0이 아닌 종료코드로 실패한 경우(설치/인증 문제 등)도 동일하게 worktree 정리 후 즉시 에러 보고

## 워크플로우 매핑 (3용도 → 토폴로지)

| 용도 | 토폴로지 | 실행 방식 |
|---|---|---|
| 코드 작성/리팩터링 병렬화 | Fan-out/Fan-in | 독립 파일/모듈 단위로 `call_worker.sh codex` 여러 건 동시 호출, 각각 위 자동 게이트 통과 후 개별 병합 |
| 독립적 2차 검증(리뷰) | Producer-Reviewer | Claude가 작성한 변경을 병합 전 `codex review --uncommitted`(또는 `--base master`)로 자동 리뷰, 문제 제기 시 병합 보류 |
| 대량/반복 작업 | Pipeline | 여러 파일에 동일 패턴 적용 시 파일별 `codex exec` 순차/병렬 실행 후 동일 게이트 적용 |

Expert Pool 패턴은 생성은 되지만(문서로만 존재) 현재 용도에 해당 없어 실사용 예시에서 제외한다.

## 영향받지 않는 부분

- 기존 `docs/superpowers/{plans,specs}` 워크플로우(브레인스토밍→계획→실행) — 변경 없음, multi-agent-starter는 그 위에 추가되는 별도 실행 메커니즘
- 앱 코드(`app_v2.py`, `build_fi_sm.py` 등)의 로직 — 이번 설정 자체는 오케스트레이션 인프라만 추가, 앱 기능 변경 없음
- 사용자의 글로벌 `~/.claude/CLAUDE.md` 모델 위임 규칙 — 별도 체계이며 충돌하지 않음 (multi-agent-starter는 이 프로젝트 로컬 실행 규칙)

## 검증 계획

1. `init.py --flavor claude --target . --yes` 실행 → `validate.py` 통과 확인
2. 3곳 패치 적용 후 실제 더미 태스크로 엔드투엔드 1회 시연:
   - 사소한 실제 리팩터링 1건을 Codex 워커에 위임 → worktree 생성 → `codex exec` → pytest 게이트 → 자동 병합까지 전 과정 확인
   - 의도적으로 실패하는 케이스(존재하지 않는 테스트 참조 등) 1회 시연 → "병합 보류 + 브랜치 보존 + 통지" 경로 확인
3. `bash tests/run.sh` (레포 자체 회귀 테스트, 외부 모델 호출 없음) 참고 실행
