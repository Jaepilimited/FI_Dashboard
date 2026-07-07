# Context Engineering 스킬 설치 + Codex 파이프라인 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** muratcankoylan/Agent-Skills-for-Context-Engineering에서 관련 스킬 3개(multi-agent-patterns/tool-design/context-optimization)를 이 프로젝트에 설치하고, 그 지식을 근거로 방금 설치한 Codex 멀티에이전트 파이프라인 문서(routing.md/approval-policy.md/task-folder.md/call_worker.sh)를 개선한다.

**Architecture:** 스킬은 원본 GitHub 레포를 스크래치 클론해 폴더 전체(`SKILL.md`+`references/`+`scripts/`)를 `.claude/skills/<name>/`로 그대로 복사. 파이프라인 개선은 기존 문서 5곳에 old_string/new_string 텍스트 패치(4곳은 짧은 문구 추가, 1곳은 `call_worker.sh`의 `die()` 에러 메시지 4건에 복구 힌트 추가).

**Tech Stack:** git(스크래치 클론), bash(diff 검증), Python 3.11 + `validate.py`(구조 검증, generator 재클론 필요 — 이전 작업에서 `/c/tmp_mas` 삭제됨).

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-07-07-context-engineering-skills-design.md`
- Python 실행 파일: `C:\Users\DB_PC\AppData\Local\Programs\Python\Python311\python.exe`
- 스킬 소스 스크래치 클론 위치: `/c/tmp_ace/src` (Windows 긴 경로 문제 회피를 위해 `C:\` 바로 아래 짧은 경로 사용, 작업 종료 후 삭제)
- multi-agent-starter generator 소스는 이전 플랜에서 `/c/tmp_mas`에 있었으나 그 플랜의 Task 6에서 삭제됨 — 이번 플랜에서 `validate.py`가 다시 필요하면 `/c/tmp_ace2/src`(또는 다른 짧은 경로)에 재클론
- 설치 대상 스킬은 정확히 3개만: `multi-agent-patterns`, `tool-design`, `context-optimization`. 나머지 12개는 설치하지 않음
- 복사되는 스킬 폴더 내용은 반드시 원본과 바이트 단위로 동일해야 함(요약·의역 금지)

---

## Task 1: Context Engineering 스킬 3개 설치

**Files:**
- Create: `.claude/skills/multi-agent-patterns/SKILL.md`, `.claude/skills/multi-agent-patterns/references/frameworks.md`, `.claude/skills/multi-agent-patterns/scripts/coordination.py`
- Create: `.claude/skills/tool-design/SKILL.md`, `.claude/skills/tool-design/references/architectural_reduction.md`, `.claude/skills/tool-design/references/best_practices.md`, `.claude/skills/tool-design/scripts/description_generator.py`
- Create: `.claude/skills/context-optimization/SKILL.md`, `.claude/skills/context-optimization/references/optimization_techniques.md`, `.claude/skills/context-optimization/scripts/compaction.py`

**Interfaces:**
- Produces: 3개 프로젝트 스킬 폴더 (`.claude/skills/<name>/`) — 이후 Claude Code 세션에서 Skill 도구로 직접 호출 가능

- [ ] **Step 1: 원본 레포 스크래치 클론**

```bash
rm -rf /c/tmp_ace
mkdir -p /c/tmp_ace
git clone --depth 1 https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering.git /c/tmp_ace/src
```

Expected: `Cloning into '/c/tmp_ace/src'...` 성공 메시지.

- [ ] **Step 2: 3개 스킬 폴더 확인**

```bash
find /c/tmp_ace/src/skills/multi-agent-patterns /c/tmp_ace/src/skills/tool-design /c/tmp_ace/src/skills/context-optimization -type f
```

Expected: 각각 `SKILL.md`, `references/*.md`(1~2개), `scripts/*.py`(1개) — 총 9개 파일.

- [ ] **Step 3: `.claude/skills/`로 복사**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
mkdir -p .claude/skills
cp -R /c/tmp_ace/src/skills/multi-agent-patterns .claude/skills/
cp -R /c/tmp_ace/src/skills/tool-design .claude/skills/
cp -R /c/tmp_ace/src/skills/context-optimization .claude/skills/
```

- [ ] **Step 4: 원본과 바이트 단위 일치 검증**

```bash
diff -r /c/tmp_ace/src/skills/multi-agent-patterns "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard/.claude/skills/multi-agent-patterns"
diff -r /c/tmp_ace/src/skills/tool-design "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard/.claude/skills/tool-design"
diff -r /c/tmp_ace/src/skills/context-optimization "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard/.claude/skills/context-optimization"
```

Expected: 세 명령 모두 출력 없음(동일).

- [ ] **Step 5: 스크래치 클론 삭제**

```bash
rm -rf /c/tmp_ace
```

- [ ] **Step 6: 커밋**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git add .claude/skills/multi-agent-patterns .claude/skills/tool-design .claude/skills/context-optimization
git status
git commit -m "$(cat <<'EOF'
feat: context-engineering 스킬 3개 설치 (multi-agent-patterns/tool-design/context-optimization)

muratcankoylan/Agent-Skills-for-Context-Engineering에서 이 프로젝트의
Codex 멀티에이전트 파이프라인과 관련된 스킬만 선별 설치

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 파이프라인 문서 개선 (4건)

**Files:**
- Modify: `_shared/routing.md` (2곳)
- Modify: `_shared/approval-policy.md` (1곳)
- Modify: `_templates/task-folder.md` (1곳)

**Interfaces:**
- Consumes: Task 1에서 설치한 `multi-agent-patterns` 스킬의 실제 권장사항(워커 수 상한, 토큰 비용 배수, 원문 보존 원칙, 과도한 분해 경고)
- Produces: 개선된 파이프라인 운영 문서 — Task 3(call_worker.sh 검토)과 독립적, 순서 무관

- [ ] **Step 1: `_shared/routing.md` — Fan-out/Fan-in 워커 수 상한 추가**

```
- old_string:
| Fan-out/Fan-in (병렬→통합) | 서로 독립된 산출물 여럿을 하나로 통합 | 예: claude-main(코드) ∥ gemini(이미지). 각 brief에 "타 worker 결과 미참조" 명시. 통합은 아래 Fan-in 규칙 |
- new_string:
| Fan-out/Fan-in (병렬→통합) | 서로 독립된 산출물 여럿을 하나로 통합 | 예: claude-main(코드) ∥ gemini(이미지). 각 brief에 "타 worker 결과 미참조" 명시. 통합은 아래 Fan-in 규칙. **워커 3~5개 초과 금지** — 그 이상은 오케스트레이터가 각 응답을 요약하며 정보 손실("전화게임 문제")과 병목이 발생한다(출처: multi-agent-patterns 스킬). 더 필요하면 계층을 추가하거나 작업을 나눌 것 |
```

- [ ] **Step 2: `_shared/routing.md` — Fan-in 규칙에 단일 워커(비병렬) 원문 보존 항목 추가**

```
- old_string:
병렬 worker 결과를 orchestrator가 하나로 합칠 때:
1. 각 worker 원문을 `result.md`에 그대로 보존 (요약본만 남기지 말 것 — telephone game 방지)
2. 결과가 충돌하면 삭제 금지 → 양쪽 출처 병기, 권위 우선순위/사실검증으로 해소, `log.md` [DECISION]에 근거 기록
3. 통합 결론 한 줄을 `context.md`에 기록
- new_string:
병렬 worker 결과를 orchestrator가 하나로 합칠 때:
1. 각 worker 원문을 `result.md`에 그대로 보존 (요약본만 남기지 말 것 — telephone game 방지)
2. 결과가 충돌하면 삭제 금지 → 양쪽 출처 병기, 권위 우선순위/사실검증으로 해소, `log.md` [DECISION]에 근거 기록
3. 통합 결론 한 줄을 `context.md`에 기록
4. **단일 워커(병합 없음) 결과에도 동일 원칙 적용** — 예: codex-critic 리뷰는 요약하지 말고 원문을 그대로 `result.md`에 옮겨 적을 것(출처: multi-agent-patterns 스킬)
```

- [ ] **Step 3: `_shared/approval-policy.md` — 병렬 호출 비용 경고 추가**

```
- old_string:
claude-main이 "내부 추론"과 같은 모델이라도 별도 호출이므로 쿼터·비용 발생.
- new_string:
claude-main이 "내부 추론"과 같은 모델이라도 별도 호출이므로 쿼터·비용 발생.

**병렬 호출 비용 경고**: 병렬 멀티에이전트 호출은 단일 호출 대비 약 15배의 토큰 비용이 든다(출처: multi-agent-patterns 스킬). 이 프로젝트는 codex-main/codex-critic을 자동승인하므로 매 호출 사용자 확인이 없다 — 병렬 호출 규모를 키우기 전에 이 비용 배수를 감안할 것.
```

- [ ] **Step 4: `_templates/task-folder.md` — 과도한 분해 경고 추가**

```
- old_string:
### Step 2: task.md 채우기

- `status: pending` → 작업 진행에 따라 갱신
- `goal`, `constraints`, `acceptance criteria` 작성
- `planned_workers`에 `_shared/routing.md` 참조하여 최소 set만 명시
- `workers_approved`는 비워두고 승인 후 채움
- new_string:
### Step 2: task.md 채우기

- `status: pending` → 작업 진행에 따라 갱신
- `goal`, `constraints`, `acceptance criteria` 작성
- `planned_workers`에 `_shared/routing.md` 참조하여 최소 set만 명시
- `workers_approved`는 비워두고 승인 후 채움
- **과도한 분해 금지**: 태스크를 지나치게 잘게 쪼개면(예: 파일 하나당 별도 태스크) handoff(brief 작성·읽기·result 기록) 오버헤드가 실제 작업량을 초과할 수 있다(출처: multi-agent-patterns 스킬) — 최소 단위로 나눌 것
```

- [ ] **Step 5: validate.py로 구조 검증**

generator 소스가 이전 플랜에서 삭제되었으므로 재클론 필요:

```bash
rm -rf /c/tmp_ace2
git clone --depth 1 https://github.com/netwaif/multi-agent-starter.git /c/tmp_ace2/src
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
PYTHONIOENCODING=utf-8 "/c/Users/DB_PC/AppData/Local/Programs/Python/Python311/python.exe" \
  /c/tmp_ace2/src/plugins/multi-agent-starter/skills/configure-multiagent/generator/validate.py \
  --flavor claude --target .
rm -rf /c/tmp_ace2
```

Expected: `전부 PASS (12개).`

- [ ] **Step 6: 커밋**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git add _shared/routing.md _shared/approval-policy.md _templates/task-folder.md
git commit -m "$(cat <<'EOF'
feat: multi-agent-patterns 스킬 근거로 파이프라인 문서 4건 개선

워커 수 상한(3~5개), 병렬 호출 비용 경고(~15배), 단일 워커 결과 원문
보존 원칙, 과도한 분해 경고를 routing.md/approval-policy.md/
task-folder.md에 추가

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `call_worker.sh` 에러 메시지 tool-design 체크리스트 검토

**Files:**
- Modify: `_shared/adapters/call_worker.sh` (4곳)

**Interfaces:**
- Consumes: Task 1에서 설치한 `tool-design` 스킬의 "에러 메시지는 무엇이 잘못됐는지+어떻게 고치는지를 담아야 한다" 체크리스트
- Produces: 개선된 4개 에러 메시지. 나머지 `die()` 호출(usage, jq 필요, backends.json 없음, timeout 유틸 필요, brief 경로 `..` 금지, native/mcp 비경유, 잘못된 call_type, git 필요, api.ref 제약, api.ref `..` 금지)은 이미 자체설명적이거나 이미 복구 방법을 포함하고 있어 변경하지 않음 — 아래 4곳만 수정

- [ ] **Step 1: `role 미정의` 메시지에 유효 role 목록 추가**

```
- old_string:
[ -n "$rec" ] || die "role 미정의: $ROLE" 2
- new_string:
[ -n "$rec" ] || die "role 미정의: $ROLE (backends.json의 .workers 키 중 하나를 사용할 것: claude-main, codex-main, codex-critic, gemini)" 2
```

- [ ] **Step 2: `brief 파일 없음` 메시지에 확인 힌트 추가**

```
- old_string:
[ -f "$BRIEF" ] || die "brief 파일 없음: $BRIEF" 6
- new_string:
[ -f "$BRIEF" ] || die "brief 파일 없음: $BRIEF (경로 오탈자 확인, 또는 tasks/<task>/workers/<role>/brief.md 먼저 생성했는지 확인)" 6
```

- [ ] **Step 3: `command allowlist 위반` 메시지에 허용값 안내 추가**

```
- old_string:
    case "$command_bin" in agy|codex|claude) ;; *) die "command allowlist 위반: $command_bin" 7;; esac
- new_string:
    case "$command_bin" in agy|codex|claude) ;; *) die "command allowlist 위반: $command_bin (backends.json의 cli.command는 agy|codex|claude 중 하나여야 함)" 7;; esac
```

- [ ] **Step 4: `api 스크립트 없음` 메시지에 확인 힌트 추가**

```
- old_string:
    [ -f "$ROOT/_shared/$ref" ] || die "api 스크립트 없음: $ref" 4
- new_string:
    [ -f "$ROOT/_shared/$ref" ] || die "api 스크립트 없음: $ref (_shared/$ref 경로에 실제 파일이 있는지, backends.json의 api.ref 값이 정확한지 확인)" 4
```

- [ ] **Step 5: bash 문법 검증**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
bash -n _shared/adapters/call_worker.sh
```

Expected: 출력 없음(문법 오류 없음).

- [ ] **Step 6: 동작 검증 (일부러 잘못된 role로 호출해 새 메시지 확인)**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
echo "dummy brief" > /tmp/dummy-brief.md 2>/dev/null || echo "dummy brief" > /c/tmp_ace_dummy_brief.md
bash _shared/adapters/call_worker.sh nonexistent-role /c/tmp_ace_dummy_brief.md 2>&1 || true
rm -f /c/tmp_ace_dummy_brief.md
```

Expected: `call_worker: role 미정의: nonexistent-role (backends.json의 .workers 키 중 하나를 사용할 것: claude-main, codex-main, codex-critic, gemini)` 출력.

- [ ] **Step 7: 커밋**

```bash
cd "/c/Users/DB_PC/Desktop/python_bcj/FI Dashboard"
git add _shared/adapters/call_worker.sh
git commit -m "$(cat <<'EOF'
fix: call_worker.sh 에러 메시지 4건에 복구 힌트 추가 (tool-design 스킬 체크리스트)

role 미정의/brief 파일 없음/command allowlist 위반/api 스크립트 없음
메시지에 무엇을 어떻게 확인·수정할지 추가. 나머지 메시지는 이미
자체설명적이거나 복구 방법을 포함하고 있어 변경 없음

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
