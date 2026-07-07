# MultiAgent Orchestration — Operating Rules

## Architecture

```
Orchestrator (Claude Code session, internal reasoning)
└── Worker Pool (claude-main은 승인 필요 / codex-main·codex-critic은 이 프로젝트에서 자동승인 — worktree+테스트 게이트가 안전망)
    ├── claude-main    메인 코딩 · 디버깅 · 설계 · 아키텍처 · 전략
    ├── codex-main     보조 구현 · 코드 분석 · 테스트 · diff · 로컬 검증 · 이미지 생성
    ├── codex-critic   산출물 리뷰·비평 (Codex의 주된 역할)
    └── gemini         멀티모달 · 긴 문서 · 제3자 시각의 검토
```

**중요**: Orchestrator의 내부 추론은 worker가 아님. claude-main worker 호출은 별도 모델 호출이므로 승인·쿼터 대상.

## 운영 원칙 (Operating Principles)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

**층별 적용**: 위 4원칙 풀버전은 Orchestrator(이 세션) 전용이다. 워커층 규약의 유일 정본은 `_templates/worker-brief.md`의 "Worker 행동 규약" 고정 블록 — ②단순함·③외과수술식은 그대로, ①은 번역형(워커는 one-shot/headless라 사용자 질문 채널 없음 → 가정을 명시하고 불확실·불일치를 result.md Issues/Caveats에 표면화), ④ loop은 Orchestrator만(Verification Checklist 루프와 결합). 워커 brief나 agent 정의에 "사용자에게 질문" 지시를 넣지 말 것. agent 정의에 규약 중복 금지.

> 출처: [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT) — adapted. 상세는 `NOTICE` 참조.

## Task Lifecycle

1. `tasks/<task-name>/task.md` 작성 (status: pending)
2. `_shared/routing.md` 참조 → 최소 worker set 결정
3. **target_repo 자동 결정** (FI Dashboard 프로젝트 전용, 외부 산출물 작업인 경우):
   - codex-main이 planned_workers에 포함되고 실제 프로젝트 파일에 쓰는 작업이면, 사용자에게 묻지 않고 오케스트레이터가 `git worktree add _local/wt-<task-id> -b agent/<task-id>` 로 격리 브랜치를 만들어 그 절대경로를 `target_repo`로 자동 채운다 (`write_scope`는 작업 성격에 맞는 경로 패턴)
   - 분석·리뷰·요약·기획만 하는 작업(codex-critic 포함)은 프로젝트 루트를 `target_repo`로 직접 사용(읽기 전용이므로 worktree 불필요)
   - 작업 완료 후 병합 절차는 "FI Dashboard 프로젝트 전용 규칙" 섹션 참조
4. 모든 worker(claude-main 포함) 사용 시 `task.md`의 `workers_approved`에 명시적 기록 필요
5. 각 worker의 brief를 **정확히 `tasks/<task>/workers/<role>/brief.md`** 에 작성 (≤ 1200자 한글 / 240단어 영문). 워커별 폴더로 분리할 것 — `<role>_brief.md`처럼 납작하게 만들지 말 것
6. worker 실행 → 원문을 **`tasks/<task>/workers/<role>/result.md`** 에 저장 (같은 워커별 폴더)
7. `result.md`의 Verification Checklist 실행
8. 검증 결과를 `log.md`에 append (`[VERIFICATION]` 태그). 작업이 끝나면 `task.md`의 `status`를 `done`으로 갱신
9. 완료 후 교훈 추가 (분류): **시스템 운영 자체**에 대한 일반 교훈 → `_shared/learnings.md`(추적·공개). **특정 외부 프로젝트 한정**(mat·hwpx 등) → `_local/learnings.md`(git 추적 안 함, 없으면 생성). `_local/learnings.md`는 명시 요청 없이는 로드하지 않는다.

> **기존 작업 재개 시**(새 세션 포함)는 1번부터가 아니라 `_shared/orchestrator-rules.md` §3 **재진입 프로토콜**을 먼저 따른다 (재정박 → 분기 → 에러 후 진행).

## Context Rules

| 파일 | 제한 (측정 가능 기준) | 목적 |
|------|------------------|------|
| `context.md` | ≤ 1500자 (한글) / ≤ 300단어 (영문) | 현재 스냅샷만. 히스토리 아님 |
| `brief.md` | ≤ 1200자 (한글) / ≤ 240단어 (영문) | worker가 실행에 필요한 것만 |
| `sources/` | 무제한 | 원본 자료. 경로로만 참조 |
| `artifacts/` | 무제한 | worker 산출물 원본 |

**측정 명령어**:
```bash
wc -m tasks/<task>/context.md   # 한글 글자수 (UTF-8 multi-byte)
wc -w tasks/<task>/context.md   # 영문 단어수
```

**context.md 초과 시**: 핵심만 남기고 나머지는 `log.md`에 append 후 초기화.  
**brief 작성 원칙**: 파일 내용을 inline 금지. 경로만 전달.

## Approval Gate

- **claude-main**: 기존 정책 유지 — `workers_approved`에 없으면 호출 금지, 작업당 첫 호출 전 사용자에게 확인 후 `task.md` 업데이트
- **codex-main / codex-critic (FI Dashboard 프로젝트 전용)**: 자동 승인. 사용자에게 매 호출 확인을 구하지 않되, `workers_approved`/`log.md` `[APPROVAL]` 기록은 그대로 자동 작성한다(감사 추적용, 승인 대기 없음). 안전망은 git worktree 격리 + 자동 테스트 게이트(아래 "FI Dashboard 프로젝트 전용 규칙" 참조)
- 예외: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요

## Verification (결과물 수락 전 필수)

각 worker `result.md`에 포함된 Verification Checklist를 실행하고, 결과를 `log.md`에 `[VERIFICATION]` 태그로 기록.

기본 항목:
- [ ] output이 `brief.md`의 `output_format`과 일치
- [ ] 파일 경로가 실제 존재하는지 확인
- [ ] `task.md`의 constraints 충족
- [ ] Do NOT 항목 위반 없음

## log.md 규칙

- append-only. 수정/삭제 금지
- 형식: `[YYYY-MM-DD HH:MM] [ACTION] 내용`
- 기록 대상: worker 호출, 주요 결정, verification 결과, 에러

## Worker 파일 쓰기 정책

| Worker | 기본 쓰기 권한 | 외부 repo 쓰기 |
|--------|------------|--------------|
| claude-main | ❌ Orchestrator 경유 | ❌ |
| codex-main | ✅ `tasks/<task>/` 내부 산출물·diff | ⚠️ 조건부 (아래 참조) |
| codex-critic | ❌ Orchestrator 경유 | ❌ |
| gemini | ❌ MCP 응답을 Orchestrator가 기록 | ❌ |

### `write_scope` 값 정의

- `none` — 쓰기 금지 (codex-critic 등 read-only 기본값)
- `tasks-only` — `tasks/<task>/` 내부만 쓰기 (codex-main 기본 동작. 외부 repo는 안 건드림)
- `"src/**, tests/**"` 같은 경로 패턴 — 외부 repo의 해당 경로만. 아래 4조건 모두 충족 시에만 유효

### codex-main 외부 repo 쓰기 조건 (모두 충족 필수)

1. `brief.md`에 `target_repo: <절대 경로>` 명시
2. `brief.md`에 `write_scope: <허용 경로 패턴>` 명시 (예: `src/**`, `tests/**`)
3. `task.md`의 `workers_approved`에 해당 worker 항목이 있고, `write_scope`도 함께 승인됨
4. `log.md`에 `[APPROVAL]` 태그로 외부 쓰기 승인 별도 기록

위 4개 중 하나라도 누락 → `tasks/<task>/` 내부에만 산출물 작성 (diff·patch 형태 권장, 사용자가 직접 적용).

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

이 파일은 **Claude Code를 `<설치한-폴더>/` 또는 그 하위에서 실행**할 때만 적용됨.

```bash
cd <설치한-폴더> && claude
```

다른 디렉토리에서 실행 시 적용 안 됨 (의도된 격리).  
전역 `~/.claude/CLAUDE.md`에 포함하지 말 것 — orchestration 규칙이 다른 프로젝트로 새어나감.
