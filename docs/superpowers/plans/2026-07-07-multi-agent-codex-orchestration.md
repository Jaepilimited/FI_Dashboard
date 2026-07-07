# Claude+Codex 멀티에이전트 오케스트레이션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FI Dashboard 프로젝트에 [netwaif/multi-agent-starter](https://github.com/netwaif/multi-agent-starter)(`claude` flavor)를 설치해 Codex를 워커로 쓰되, codex-main/codex-critic 호출은 자동 승인하고 git worktree 격리 + 자동 테스트 게이트를 안전망으로 삼는다.

**Architecture:** 공식 generator(`init.py`)로 표준 구조(`CLAUDE.md`, `.mcp.json`, `_shared/*`, `_templates/*`, `tasks/`, `_local/`)를 생성한 뒤, 문서 4개(`CLAUDE.md`/`approval-policy.md`/`routing.md`/`task-folder.md`)를 텍스트 패치해 승인 게이트를 자동화하고 target_repo를 worktree 경로로 자동 채우는 절차를 명문화한다. `_shared/adapters/call_worker.sh`/`_shared/backends.json`/`.mcp.json`은 생성된 그대로 사용(코드 수정 없음) — codex-main/codex-critic 호출은 `mcp__codex__codex` MCP 도구(오케스트레이터가 직접 호출)가 기본 경로다.

**Tech Stack:** Python 3.11(generator/validate 실행 및 pytest 게이트), Codex CLI v0.142.5(이미 설치, `codex mcp-server`로 MCP 등록), git worktree, bash.

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-07-07-multi-agent-codex-design.md` (이 계획은 그 문서의 "구성 요소"/"워크플로우 매핑"/"검증 계획"을 구현한다)
- Python 실행 파일: `C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe` (PATH의 `python`은 다른 프로젝트 venv를 가리켜 `pytest`가 없음 — 반드시 이 전체 경로 사용)
- generator 소스 클론 위치: `C:\tmp_mas\src` (이미 클론됨 — Windows 긴 경로 문제로 `C:\` 바로 아래 짧은 경로 사용). generator 실행 시 Windows 콘솔 인코딩 문제 회피를 위해 `PYTHONIOENCODING=utf-8` 환경변수 필수
- flavor는 `claude` 고정. Gemini 워커 정의(`backends.json`)는 `validate.py`의 C6 검사가 요구하므로 삭제하지 않고 그대로 둔다 — 실사용에서만 배제
- codex-main/codex-critic 자동승인은 **이 프로젝트 로컬 규칙**이며 claude-main(Opus subagent)에는 적용하지 않는다 — claude-main은 기존 승인 정책 유지
- worktree 경로 규칙: `_local/wt-<task-id>`, 브랜치명 `agent/<task-id>` (task-id는 `_templates/task-folder.md`의 명명 규칙대로 kebab-case 또는 `YYYYMMDD-keyword`)
- 자동 테스트 게이트 기본값: `python -m pytest tests/test_tableau_api.py -q` (이 프로젝트에서 확인된 가장 빠르고 안정적인 회귀 테스트, 4.29초/6 passed 확인함). 전체 `pytest`(bare)는 라이브 Playwright/BigQuery 의존 테스트가 섞여 있고 `tests/test_report_route.py`는 이미 `import app` 실패로 깨져 있어(무관한 기존 이슈, 이번 작업 범위 아님) 게이트로 쓰지 않는다
- 이번 계획에서 만드는 스모크 테스트용 산출물(임시 테스트 파일 등)은 파이프라인 검증 후 제거한다 — 영구 기능이 아님

---

## Task 1: Generator 실행 + .gitignore 병합 + 검증

**Files:**
- Create (generator 산출물, 루트 기준): `CLAUDE.md`, `.mcp.json`, `.claude/agents/claude-main.md`, `_shared/backends.json`, `_shared/approval-policy.md`, `_shared/routing.md`, `_shared/orchestrator-rules.md`, `_shared/design-basis.md`, `_shared/system-invariants.md`, `_shared/learnings.md`, `_shared/adapters/call_worker.sh`, `_shared/adapters/_run.py`, `_shared/adapters/gemini_api.sh`, `_templates/{context,log,task,task-folder,worker-brief,worker-result}.md`, `tasks/.gitkeep`, `_local/.gitkeep`, `assets/brand/harness-multiagent-banner.png`, `README.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `LICENSE`, `NOTICE`
- Modify: `.gitignore` (generator가 덮어쓰므로 기존 규칙과 병합 필요)

**Interfaces:**
- Produces: 위 전체 파일 세트. Task 2가 `CLAUDE.md`/`_shared/approval-policy.md`/`_shared/routing.md`/`_templates/task-folder.md`를 이어서 수정한다.

- [ ] **Step 1: 기존 .gitignore 백업**

```bash
cp ".gitignore" "/c/tmp_mas/original.gitignore"
```

- [ ] **Step 2: generator 실행**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
PYTHONIOENCODING=utf-8 "/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" \
  /c/tmp_mas/src/plugins/multi-agent-starter/skills/configure-multiagent/generator/init.py \
  --flavor claude --target . --yes
```

Expected: 마지막 줄 근처에 `28개 파일 생성 완료` (또는 유사) 메시지. `validate.py` 자동 실행 결과는 무시(다음 Step에서 별도 재실행).

- [ ] **Step 3: .gitignore 병합 (덮어써진 프로젝트 규칙 복원 + json 예외 추가)**

`.gitignore`를 다음 내용으로 교체 (원본 규칙 유지 + json 예외 2줄 추가 + generator 추가분 하단에 병합):

```
# Credentials & secrets
config.py
*.json
!.mcp.json
!_shared/backends.json

# Python
__pycache__/
*.py[cod]
*.pyo
.env
venv/
.venv/

# Data files
*.xlsx
*.xls
*.csv

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
.gstack/
pw_shots/

# --- multi-agent-starter ---
*.log
*.tmp

# 런타임 캐시 — 로컬 경로·UUID 포함, git 추적 안 함
cache/

# 작업 데이터 — 사용자 사적 자료, git 추적 안 함 (폴더 구조 유지를 위해 .gitkeep만 추적)
tasks/*
!tasks/.gitkeep

# 프로젝트 특화 교훈 — 작성자 사적 누적물, git 추적 안 함 (폴더만 유지)
_local/*
!_local/.gitkeep
```

- [ ] **Step 4: validate.py로 검증**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
PYTHONIOENCODING=utf-8 "/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" \
  /c/tmp_mas/src/plugins/multi-agent-starter/skills/configure-multiagent/generator/validate.py \
  --flavor claude --target .
```

Expected: `전부 PASS (12개).`

- [ ] **Step 5: 생성물 확인 + 커밋**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git status
git add CLAUDE.md .mcp.json .claude _shared _templates tasks/.gitkeep _local/.gitkeep \
  assets README.md CHANGELOG.md KNOWN_ISSUES.md LICENSE NOTICE .gitignore
git status
```

두 번째 `git status`에서 `_shared/backends.json`, `.mcp.json`이 "Changes to be committed"에 나타나는지 확인(=.gitignore의 `*.json` 예외가 정상 동작).

```bash
git commit -m "$(cat <<'EOF'
feat: multi-agent-starter(claude flavor) 설치 — Codex 워커 오케스트레이션 기반

netwaif/multi-agent-starter generator로 표준 구조 생성. 승인게이트/target_repo
자동화 등 프로젝트 전용 커스터마이징은 다음 커밋에서 진행

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 승인 게이트 자동화 + target_repo 자동화 문서 패치

**Files:**
- Modify: `CLAUDE.md`
- Modify: `_shared/approval-policy.md`
- Modify: `_shared/routing.md`
- Modify: `_templates/task-folder.md`

**Interfaces:**
- Consumes: Task 1이 생성한 위 4개 파일의 원본 텍스트
- Produces: codex-main/codex-critic 자동승인 규칙 + worktree 기반 target_repo 자동 결정 절차(Task 3~5가 이 절차를 그대로 따라 실행한다)

- [ ] **Step 1: `CLAUDE.md` 아키텍처 주석 수정**

```
- old_string:
└── Worker Pool (모두 외부 호출 — 승인 필요)
- new_string:
└── Worker Pool (claude-main은 승인 필요 / codex-main·codex-critic은 이 프로젝트에서 자동승인 — worktree+테스트 게이트가 안전망)
```

- [ ] **Step 2: `CLAUDE.md` Task Lifecycle 3번 항목 교체**

```
- old_string:
3. **target_repo 확인** (외부 산출물 작업인 경우):
   - codex-main이 planned_workers에 포함되거나 코드·문서·이미지를 만드는 작업이면 사용자에게 `target_repo` 경로를 묻는다
   - 사용자가 "없음"이라고 답하거나 분석·리뷰·요약·기획만 하는 작업이면 묻지 않고 `tasks/<task>/artifacts/`에 diff·patch로 산출
   - 사용자가 자연어 요청에 이미 경로를 포함했으면 다시 묻지 않음
- new_string:
3. **target_repo 자동 결정** (FI Dashboard 프로젝트 전용, 외부 산출물 작업인 경우):
   - codex-main이 planned_workers에 포함되고 실제 프로젝트 파일에 쓰는 작업이면, 사용자에게 묻지 않고 오케스트레이터가 `git worktree add _local/wt-<task-id> -b agent/<task-id>` 로 격리 브랜치를 만들어 그 절대경로를 `target_repo`로 자동 채운다 (`write_scope`는 작업 성격에 맞는 경로 패턴)
   - 분석·리뷰·요약·기획만 하는 작업(codex-critic 포함)은 프로젝트 루트를 `target_repo`로 직접 사용(읽기 전용이므로 worktree 불필요)
   - 작업 완료 후 병합 절차는 "FI Dashboard 프로젝트 전용 규칙" 섹션 참조
```

- [ ] **Step 3: `CLAUDE.md` Approval Gate 섹션 교체**

```
- old_string:
## Approval Gate

- `workers_approved`에 없는 worker 호출 금지 (claude-main 포함 전체 worker pool 적용)
- 작업당 첫 호출 전 사용자에게 확인 후 `task.md` 업데이트
- 예외: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요
- new_string:
## Approval Gate

- **claude-main**: 기존 정책 유지 — `workers_approved`에 없으면 호출 금지, 작업당 첫 호출 전 사용자에게 확인 후 `task.md` 업데이트
- **codex-main / codex-critic (FI Dashboard 프로젝트 전용)**: 자동 승인. 사용자에게 매 호출 확인을 구하지 않되, `workers_approved`/`log.md` `[APPROVAL]` 기록은 그대로 자동 작성한다(감사 추적용, 승인 대기 없음). 안전망은 git worktree 격리 + 자동 테스트 게이트(아래 "FI Dashboard 프로젝트 전용 규칙" 참조)
- 예외: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요
```

- [ ] **Step 4: `CLAUDE.md`에 "FI Dashboard 프로젝트 전용 규칙" 섹션 신규 삽입** ("## Worker 파일 쓰기 정책" 섹션의 마지막 줄 뒤, "## CLAUDE.md 적용 범위" 섹션 앞에 삽입)

```
- old_string:
직접 쓰기 가능한 worker도 `_shared/`, `_templates/`, 다른 작업 폴더는 쓰지 말 것.

## CLAUDE.md 적용 범위
- new_string:
직접 쓰기 가능한 worker도 `_shared/`, `_templates/`, 다른 작업 폴더는 쓰지 말 것.

## FI Dashboard 프로젝트 전용 규칙 (2026-07-07 추가)

이 프로젝트에서는 codex-main/codex-critic 호출을 자동 승인하는 대신, git worktree 격리와 자동 테스트 게이트를 안전망으로 쓴다.

### codex-main이 실제 프로젝트 파일을 수정하는 경우

1. 오케스트레이터가 `git worktree add _local/wt-<task-id> -b agent/<task-id>` 로 현재 브랜치에서 격리된 브랜치를 만든다(사용자에게 묻지 않음)
2. brief.md의 `target_repo`에 그 worktree 절대경로, `write_scope`에 작업에 필요한 경로 패턴을 채운다
3. `mcp__codex__codex` 호출 (cwd=worktree 경로, sandbox=`workspace-write`). MCP 실패 시 `bash _shared/adapters/call_worker.sh codex-main <brief-file>` (CLI 폴백, backends.json에 이미 정의됨)로 재시도
4. codex 응답 완료 후 worktree 안에서 변경사항을 커밋: `git -C _local/wt-<task-id> add -A && git -C _local/wt-<task-id> commit -m "agent: <task-id>"` (커밋이 있어야 이후 병합할 내용이 생김)
5. worktree 안에서 `python -m pytest tests/test_tableau_api.py -q` 실행 (이 프로젝트의 가장 빠르고 안정적인 회귀 테스트. 전체 `pytest`는 라이브 DB/Playwright 의존 테스트가 섞여 있어 게이트로 부적합 — `_shared/learnings.md` 참조)
   - **통과** → 원래 브랜치로 `git merge --no-ff agent/<task-id>` 자동 병합, worktree 삭제(`git worktree remove`), 브랜치 삭제(`git branch -d`), diff 요약을 채팅에 통지
   - **실패** → 병합 보류, worktree/브랜치 보존, 실패 사유 + 브랜치명을 채팅으로 즉시 통지 (자동 재시도 없음, 사용자가 직접 검토 후 처리)
6. `mcp__codex__codex` 호출 자체가 실패(설치/인증 문제 등)한 경우도 worktree를 정리하고 즉시 에러 보고

### codex-critic (리뷰, read-only)

- worktree 불필요. `target_repo`=프로젝트 루트, `write_scope: none`, sandbox=`read-only`(이미 backends.json에 고정)
- 리뷰 결과에서 문제 제기 시, 관련 병합/작업을 보류하고 사용자에게 요약 보고

## CLAUDE.md 적용 범위
```

- [ ] **Step 5: `_shared/approval-policy.md` 원칙 섹션 교체**

```
- old_string:
## 원칙

**모든 worker 호출은 작업별로 명시적 승인 필요** (claude-main 포함 전체 pool 적용).  
`task.md`의 `workers_approved` 리스트에 없으면 호출 금지.

**예외**: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요. 다만 별도 claude-main worker를 호출해 산출물을 `result.md`로 받는 것은 승인 대상.
- new_string:
## 원칙

**claude-main**: 기존 정책 유지 — 작업별 명시적 승인 필요, `task.md`의 `workers_approved` 리스트에 없으면 호출 금지.

**codex-main / codex-critic (FI Dashboard 프로젝트 전용)**: 자동 승인. git worktree 격리 + 자동 테스트 게이트(`CLAUDE.md`의 "FI Dashboard 프로젝트 전용 규칙" 참조)가 안전망이므로 사용자 승인 대기 없이 호출한다. `workers_approved`/`log.md` `[APPROVAL]` 기록은 감사 추적용으로 자동 작성.

**예외**: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요. 다만 별도 claude-main worker를 호출해 산출물을 `result.md`로 받는 것은 승인 대상.
```

- [ ] **Step 6: `_shared/approval-policy.md` 승인 절차 2번 항목에 예외 추가**

```
- old_string:
2. 사용자에게 다음 정보와 함께 승인 요청:
   - 어떤 worker를
   - 무슨 목적으로
   - 예상 호출 횟수 (쿼터 영향 포함)
3. 승인 시 `task.md`의 `workers_approved`에 추가
- new_string:
2. 사용자에게 다음 정보와 함께 승인 요청 (**FI Dashboard 프로젝트 전용**: codex-main/codex-critic은 이 단계를 생략하고 바로 3번으로 진행):
   - 어떤 worker를
   - 무슨 목적으로
   - 예상 호출 횟수 (쿼터 영향 포함)
3. 승인 시 `task.md`의 `workers_approved`에 추가
```

- [ ] **Step 7: `_shared/routing.md` codex-main brief 필수 필드 절 교체**

```
- old_string:
- **brief 필수 필드** (오케스트레이터가 사용자에게 target_repo를 먼저 묻고 답을 받아 채운다 — 분석·리뷰·요약 작업은 예외):
  ```yaml
  target_repo: /absolute/path/to/repo                   # 작업 대상 절대 경로 (없으면 N/A)
  write_scope: none | tasks-only | "src/**, tests/**"   # none=쓰기금지 / tasks-only=tasks/<task>/ 내부만(codex-main 기본) / 패턴=외부 repo 해당 경로(외부는 4조건)
  ```
- new_string:
- **brief 필수 필드** (FI Dashboard 프로젝트 전용: 오케스트레이터가 `git worktree add`로 격리 브랜치를 자동 생성해 target_repo를 채운다 — 사용자에게 묻지 않음. 분석·리뷰·요약 작업은 프로젝트 루트를 그대로 target_repo로 사용):
  ```yaml
  target_repo: /absolute/path/to/repo                   # 작업 대상 절대 경로 (없으면 N/A)
  write_scope: none | tasks-only | "src/**, tests/**"   # none=쓰기금지 / tasks-only=tasks/<task>/ 내부만(codex-main 기본) / 패턴=외부 repo 해당 경로(외부는 4조건)
  ```
```

- [ ] **Step 8: `_templates/task-folder.md` Step 1.5 교체**

```
- old_string:
### Step 1.5: target_repo 확인 (외부 산출물 작업인 경우)

codex-main이 planned_workers에 포함되거나 코드·문서·이미지를 만드는 작업이면, task.md 채우기 전에 사용자에게 짧게 묻는다:

> "이 작업의 산출물이 들어갈 외부 폴더(target_repo)가 있나요?
> (예: ~/projects/my-app. 없으면 tasks/<task>/artifacts/에 diff로 남깁니다)"

답을 task.md의 메모 또는 후속 brief.md의 `target_repo` 필드에 기록한다.

**예외 (묻지 않음)**:
- 분석·리뷰·요약·기획만 하는 작업 (gemini 단독 또는 claude-main 단독 문서 작성)
- 사용자가 자연어 요청에 이미 target_repo 경로를 포함한 경우
- new_string:
### Step 1.5: target_repo 자동 결정 (FI Dashboard 프로젝트 전용)

codex-main이 planned_workers에 포함되고 실제 프로젝트 파일에 쓰는 작업이면, 사용자에게 묻지 않고 오케스트레이터가 다음을 자동 수행한다:

```bash
git worktree add "_local/wt-$TASK" -b "agent/$TASK"
```

그 절대경로를 후속 brief.md의 `target_repo` 필드에 기록한다 (`write_scope`는 작업에 필요한 경로 패턴).

**예외 (worktree 불필요, 프로젝트 루트를 target_repo로 직접 사용)**:
- 분석·리뷰·요약·기획만 하는 작업 (codex-critic, gemini 단독, claude-main 단독 문서 작성)
- 사용자가 자연어 요청에 이미 다른 target_repo 경로를 명시한 경우
```

- [ ] **Step 9: 검증**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
PYTHONIOENCODING=utf-8 "/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" \
  /c/tmp_mas/src/plugins/multi-agent-starter/skills/configure-multiagent/generator/validate.py \
  --flavor claude --target .
```

Expected: `전부 PASS (12개).` (텍스트 패치가 C4/C7 등 구조 검사를 깨지 않았는지 확인)

- [ ] **Step 10: 커밋**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git add CLAUDE.md _shared/approval-policy.md _shared/routing.md _templates/task-folder.md
git commit -m "$(cat <<'EOF'
feat: codex-main/codex-critic 자동승인 + worktree 기반 target_repo 자동화

claude-main은 기존 승인 정책 유지. codex 워커만 git worktree 격리 +
자동 테스트 게이트(tests/test_tableau_api.py)를 안전망으로 자동 진행

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 성공 경로 엔드투엔드 스모크 테스트

**Files:**
- Create (임시, Step 6에서 제거): `tasks/2026-07-07-smoke-codex-demo/{task.md,log.md,context.md,workers/codex-main/{brief.md,result.md}}`
- Create (임시, Step 6에서 제거): `tests/test_multiagent_smoke.py`

**Interfaces:**
- Consumes: Task 2가 patch한 worktree/자동승인/게이트 절차
- Produces: 파이프라인이 실제로 동작함을 증명하는 로그(`git log`, `tasks/2026-07-07-smoke-codex-demo/log.md`) — 이후 실제 작업에서 동일 절차를 재사용

- [ ] **Step 1: 작업 폴더 생성**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
TASK=2026-07-07-smoke-codex-demo
mkdir -p "tasks/$TASK/workers/codex-main"
cp _templates/task.md "tasks/$TASK/task.md"
cp _templates/log.md "tasks/$TASK/log.md"
cp _templates/context.md "tasks/$TASK/context.md"
```

`tasks/$TASK/task.md`를 열어 다음으로 채운다:
- `status: in_progress`, `created`/`updated`: 오늘 날짜(`date +%Y-%m-%d`)
- Goal: "codex-main 워커 파이프라인(worktree 격리+자동 테스트 게이트+자동 병합) 엔드투엔드 동작 확인"
- Acceptance Criteria: "tests/test_multiagent_smoke.py가 codex-main에 의해 생성되고, 게이트 테스트 통과 후 자동 병합됨"
- `workers_approved`: `- worker: codex-main` / `approved_at: <오늘 날짜>` / `purpose: 파이프라인 스모크 테스트` / `approved_by: auto (FI Dashboard 프로젝트 자동승인 정책)`
- `planned_workers`: `- role: codex-main`

- [ ] **Step 2: git worktree 생성**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git worktree add "_local/wt-2026-07-07-smoke-codex-demo" -b "agent/2026-07-07-smoke-codex-demo"
```

Expected: `Preparing worktree ...` 성공 메시지, `_local/wt-2026-07-07-smoke-codex-demo` 디렉터리 생성 확인.

- [ ] **Step 3: brief.md 작성**

`tasks/2026-07-07-smoke-codex-demo/workers/codex-main/brief.md`:

```markdown
# Brief — codex-main / smoke-codex-demo

## Worker 행동 규약 (고정 — 모든 brief에 그대로 유지, 삭제 금지)

- 요청 범위만 최소로. 사변적 추상화·기능 추가 금지
- 외과수술식 수정: 기존 스타일 유지, 무관 코드 비접촉
- 사용자 대화 채널 없음: 가정은 명시하고, 불확실·불일치는 result의 Issues/Caveats에 표면화

## Execution Context (codex-main / codex-critic 필수)

```yaml
target_repo: C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard\_local\wt-2026-07-07-smoke-codex-demo
write_scope: "tests/test_multiagent_smoke.py"
```

## Objective

`tests/test_multiagent_smoke.py` 파일을 새로 만들고, 그 안에 순수 함수 `add(a, b)`(정수 두 개를 더해 반환)와 이를 검증하는 pytest 테스트 `test_add()` 하나를 작성한다.

## Input

없음(신규 파일).

## Constraints

- 이 파일 하나만 생성. 다른 파일은 절대 건드리지 말 것
- 외부 라이브러리 의존 없이 표준 pytest만 사용

## Output Format

- 파일 위치: `tests/test_multiagent_smoke.py`
- 형식: Python 코드 (pytest 테스트 파일)

## Do NOT

- `tests/test_tableau_api.py` 등 기존 테스트 파일 수정 금지
- README/CLAUDE.md 등 문서 파일 수정 금지
```

- [ ] **Step 4: codex-main 호출 (MCP)**

`mcp__codex__codex` 도구를 다음 파라미터로 호출한다(cwd=worktree 절대경로, sandbox=workspace-write):
- prompt: 위 brief.md 파일 내용 전체
- cwd: `_local/wt-2026-07-07-smoke-codex-demo`의 절대경로
- sandbox: `workspace-write`
- approval-policy: `never`

완료 후 `tasks/2026-07-07-smoke-codex-demo/workers/codex-main/result.md`를 `_templates/worker-result.md` 형식대로 채운다(응답 요약 + Verification Checklist).

- [ ] **Step 5: worktree 안 파일 확인**

```bash
cat "_local/wt-2026-07-07-smoke-codex-demo/tests/test_multiagent_smoke.py"
```

Expected: `def add(a, b):` 와 `def test_add` 를 포함하는 파일 내용 출력. 다른 파일이 변경되지 않았는지 확인:

```bash
git -C "_local/wt-2026-07-07-smoke-codex-demo" status --porcelain
```

Expected: `tests/test_multiagent_smoke.py` 한 줄만 `??` (untracked)로 표시.

- [ ] **Step 6: worktree 안에서 커밋 + 게이트 테스트 + 병합**

```bash
git -C "_local/wt-2026-07-07-smoke-codex-demo" add tests/test_multiagent_smoke.py
git -C "_local/wt-2026-07-07-smoke-codex-demo" commit -m "agent: 2026-07-07-smoke-codex-demo — add smoke test"

cd "_local/wt-2026-07-07-smoke-codex-demo"
"/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" -m pytest \
  tests/test_tableau_api.py tests/test_multiagent_smoke.py -q
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
```

Expected: `7 passed` (기존 6개 + 신규 1개).

게이트 통과 시 자동 병합:

```bash
git merge --no-ff agent/2026-07-07-smoke-codex-demo -m "merge: agent/2026-07-07-smoke-codex-demo (gate passed)"
git worktree remove "_local/wt-2026-07-07-smoke-codex-demo"
git branch -d agent/2026-07-07-smoke-codex-demo
```

- [ ] **Step 7: task.md/log.md 마무리**

`tasks/2026-07-07-smoke-codex-demo/task.md`의 `status: done`으로 갱신. `log.md`에 다음 라인 추가:

```
[YYYY-MM-DD HH:MM] [WORKER_CALL] codex-main 호출, worktree agent/2026-07-07-smoke-codex-demo
[YYYY-MM-DD HH:MM] [VERIFICATION] tests/test_tableau_api.py + test_multiagent_smoke.py 7 passed
[YYYY-MM-DD HH:MM] [COMPLETE] 자동 병합 완료
```

(날짜/시간은 `date +"%Y-%m-%d %H:%M"` 실제 값으로 채운다)

- [ ] **Step 8: 스모크 테스트 산출물 제거 (파이프라인 검증용 임시 파일이므로)**

```bash
git rm tests/test_multiagent_smoke.py
git commit -m "$(cat <<'EOF'
chore: 멀티에이전트 파이프라인 스모크 테스트 산출물 제거

Task 3 성공 경로 검증(worktree 생성→codex-main MCP 호출→pytest 게이트
통과→자동 병합) 확인 완료, 임시 산출물 정리

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

`tasks/2026-07-07-smoke-codex-demo/`는 `.gitignore`(`tasks/*`)에 의해 git 추적되지 않으므로 별도 삭제 불필요 — 로컬 기록으로 남는다.

---

## Task 4: 실패 경로 스모크 테스트 (병합 보류 확인)

**Files:**
- Create (임시, Step 6에서 제거): `tasks/2026-07-07-smoke-codex-fail-demo/{task.md,log.md,context.md,workers/codex-main/{brief.md,result.md}}`
- Create (임시, Step 6에서 제거 — 병합되지 않으므로 worktree 삭제만으로 충분): `tests/test_multiagent_smoke_fail.py` (worktree 브랜치에만 존재, main 브랜치에는 병합 안 됨)

**Interfaces:**
- Consumes: Task 2/3와 동일한 worktree+게이트 절차
- Produces: "게이트 실패 시 병합 보류 + worktree/브랜치 보존 + 통지" 경로가 실제로 동작함을 증명

- [ ] **Step 1: 작업 폴더 + worktree 생성**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
TASK=2026-07-07-smoke-codex-fail-demo
mkdir -p "tasks/$TASK/workers/codex-main"
cp _templates/task.md "tasks/$TASK/task.md"
cp _templates/log.md "tasks/$TASK/log.md"
cp _templates/context.md "tasks/$TASK/context.md"
git worktree add "_local/wt-$TASK" -b "agent/$TASK"
```

- [ ] **Step 2: brief.md 작성 (의도적 실패 유발)**

`tasks/2026-07-07-smoke-codex-fail-demo/workers/codex-main/brief.md`:

```markdown
# Brief — codex-main / smoke-codex-fail-demo

## Worker 행동 규약 (고정 — 모든 brief에 그대로 유지, 삭제 금지)

- 요청 범위만 최소로. 사변적 추상화·기능 추가 금지
- 외과수술식 수정: 기존 스타일 유지, 무관 코드 비접촉
- 사용자 대화 채널 없음: 가정은 명시하고, 불확실·불일치는 result의 Issues/Caveats에 표면화

## Execution Context (codex-main / codex-critic 필수)

```yaml
target_repo: C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard\_local\wt-2026-07-07-smoke-codex-fail-demo
write_scope: "tests/test_multiagent_smoke_fail.py"
```

## Objective

`tests/test_multiagent_smoke_fail.py`를 새로 만들고, 항상 실패하는 pytest 테스트 `test_intentional_failure()`를 작성한다 (예: `assert 1 == 2, "intentional failure for multiagent gate rehearsal"`). 이건 자동 병합 게이트의 "실패 시 보류" 경로를 검증하기 위한 의도적 실패 테스트임을 파일 상단 주석에 명시한다.

## Input

없음(신규 파일).

## Constraints

- 이 파일 하나만 생성. 다른 파일은 절대 건드리지 말 것

## Output Format

- 파일 위치: `tests/test_multiagent_smoke_fail.py`
- 형식: Python 코드 (pytest 테스트 파일, 반드시 실패해야 함)

## Do NOT

- 기존 테스트 파일 수정 금지
```

- [ ] **Step 3: codex-main 호출 (MCP)**

Task 3 Step 4와 동일한 방식으로 `mcp__codex__codex` 호출 (cwd=`_local/wt-2026-07-07-smoke-codex-fail-demo` 절대경로, sandbox=`workspace-write`, approval-policy=`never`). 완료 후 result.md 작성.

- [ ] **Step 4: 커밋 + 게이트 테스트 실행 (실패 확인)**

```bash
git -C "_local/wt-2026-07-07-smoke-codex-fail-demo" add tests/test_multiagent_smoke_fail.py
git -C "_local/wt-2026-07-07-smoke-codex-fail-demo" commit -m "agent: 2026-07-07-smoke-codex-fail-demo — intentional failing test"

cd "_local/wt-2026-07-07-smoke-codex-fail-demo"
"/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" -m pytest \
  tests/test_tableau_api.py tests/test_multiagent_smoke_fail.py -q
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
```

Expected: `1 failed, 6 passed` (신규 테스트만 실패).

- [ ] **Step 5: 병합 보류 확인 (병합하지 않음) + task.md/log.md 기록**

`git merge`를 실행하지 **않는다**. 대신:

```bash
git worktree list
git branch --list "agent/2026-07-07-smoke-codex-fail-demo"
```

Expected: 두 명령 모두 해당 worktree/브랜치가 여전히 존재함을 보여줌(=보류 상태 확인).

`tasks/2026-07-07-smoke-codex-fail-demo/task.md`의 `status: reviewing`으로 갱신. `log.md`에 추가:

```
[YYYY-MM-DD HH:MM] [WORKER_CALL] codex-main 호출, worktree agent/2026-07-07-smoke-codex-fail-demo
[YYYY-MM-DD HH:MM] [VERIFICATION] 게이트 테스트 실패(1 failed) — 병합 보류
[YYYY-MM-DD HH:MM] [ERROR] 실패 사유: test_intentional_failure 의도적 실패. 브랜치 agent/2026-07-07-smoke-codex-fail-demo 보존, 사용자 통지 필요
```

이 시점에 오케스트레이터가 사용자에게 통지할 채팅 메시지 예시를 남긴다: "codex-main 작업(2026-07-07-smoke-codex-fail-demo)이 게이트 테스트를 통과하지 못해 병합을 보류했습니다. 브랜치 `agent/2026-07-07-smoke-codex-fail-demo`(worktree `_local/wt-2026-07-07-smoke-codex-fail-demo`)에 보존되어 있습니다."

- [ ] **Step 6: 데모 정리 (의도적 실패 확인 완료 후, 실사용 실패와 달리 즉시 폐기)**

```bash
git worktree remove "_local/wt-2026-07-07-smoke-codex-fail-demo" --force
git branch -D "agent/2026-07-07-smoke-codex-fail-demo"
```

(`--force`/`-D`는 이 브랜치가 병합되지 않았고 커밋 내용이 의도적 실패 테스트뿐인 데모 전용 브랜치이기 때문에 안전 — 실사용 실패 케이스에서는 이렇게 즉시 삭제하지 않고 사용자 검토를 기다린다)

---

## Task 5: codex-critic 리뷰 스모크 테스트

**Files:**
- Create (임시, 로컬에만 남음): `tasks/2026-07-07-smoke-codex-critic-demo/{task.md,log.md,context.md,workers/codex-critic/{brief.md,result.md}}`

**Interfaces:**
- Consumes: `_shared/backends.json`의 `codex-critic`(이미 `sandbox: read-only` 고정)
- Produces: `upload_adj.py`에 대한 실제 리뷰 결과(부가가치 있는 실사용 산출물)

- [ ] **Step 1: 작업 폴더 생성 (worktree 불필요 — read-only)**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
TASK=2026-07-07-smoke-codex-critic-demo
mkdir -p "tasks/$TASK/workers/codex-critic"
cp _templates/task.md "tasks/$TASK/task.md"
cp _templates/log.md "tasks/$TASK/log.md"
cp _templates/context.md "tasks/$TASK/context.md"
```

- [ ] **Step 2: brief.md 작성**

`tasks/2026-07-07-smoke-codex-critic-demo/workers/codex-critic/brief.md`:

```markdown
# Brief — codex-critic / smoke-codex-critic-demo

## Worker 행동 규약 (고정 — 모든 brief에 그대로 유지, 삭제 금지)

- 요청 범위만 최소로. 사변적 추상화·기능 추가 금지
- 외과수술식 수정: 기존 스타일 유지, 무관 코드 비접촉
- 사용자 대화 채널 없음: 가정은 명시하고, 불확실·불일치는 result의 Issues/Caveats에 표면화

## Execution Context (codex-main / codex-critic 필수)

```yaml
target_repo: C:\Users\DB_PC\Desktop\python_bcj\FI Dashboard
write_scope: none
```

## Objective

`upload_adj.py`(FI_Adjustment 업로드 스크립트)를 비평 모드로 리뷰한다: 에러 처리 누락, 잘못된 가정, 사이드 이펙트, 테스트 커버리지 공백을 찾는다.

## Input

```
target: upload_adj.py (target_repo 루트 기준)
```

## Constraints

- 읽기 전용 리뷰. 파일 수정 시도 금지(sandbox가 어차피 차단함)

## Output Format

- 파일 위치: `tasks/2026-07-07-smoke-codex-critic-demo/workers/codex-critic/result.md`
- 형식: Markdown, 비평 리스트 + 수정 제안

## Do NOT

- 코드 수정 제안을 코드로 직접 적용하지 말 것(리뷰 텍스트만)
```

- [ ] **Step 3: codex-critic 호출 (MCP, read-only)**

`mcp__codex__codex` 호출 (cwd=프로젝트 루트 절대경로, sandbox=`read-only`, approval-policy=`never`, brief에 "비평 모드" 명시). 완료 후 `result.md` 작성.

- [ ] **Step 4: 쓰기 없음 확인**

```bash
git status --porcelain
```

Expected: `upload_adj.py`를 포함해 어떤 추적 파일도 변경되지 않음(`tasks/` 하위는 gitignore 대상이라 애초에 안 보임).

- [ ] **Step 5: task.md/log.md 마무리**

`status: done`, `log.md`에 `[WORKER_CALL]`/`[VERIFICATION]`/`[COMPLETE]` 태그로 기록.

---

## Task 6: 스크래치 정리 + 참고 회귀 테스트

**Files:**
- 없음 (정리 작업)

- [ ] **Step 1: 레포 자체 회귀 테스트 참고 실행**

```bash
cd /c/tmp_mas/src && bash tests/run.sh
```

Expected: 외부 모델 호출 없는 결정적 테스트가 통과(참고용 — 실패해도 이번 프로젝트 커밋을 막지 않음. 실패 시 원인만 기록하고 진행).

- [ ] **Step 2: 스크래치 클론/타겟 제거**

```bash
rm -rf /c/tmp_mas
```

- [ ] **Step 3: 최종 상태 확인**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git status
git worktree list
git log --oneline -10
```

Expected: `git status`가 clean(추적 대상 기준), `git worktree list`에 데모용 worktree가 남아있지 않음, `git log`에 Task 1/2/3/(옵션)의 커밋이 순서대로 보임.
