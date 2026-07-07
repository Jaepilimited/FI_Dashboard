# Context Engineering 스킬 설치 + Codex 파이프라인 개선

## 배경

[muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering)는 AI 에이전트 시스템(멀티에이전트 오케스트레이션, 도구 설계, 컨텍스트 압축 등)을 위한 15개 Claude Code/Cursor 스킬 모음이다. 이 프로젝트에 방금 설치한 netwaif/multi-agent-starter(Codex 워커) 파이프라인과 직접 관련된 지식이 있어, (1) 관련 스킬 일부를 이 프로젝트에 설치하고 (2) 그 지식을 실제로 방금 만든 파이프라인 문서에 적용해 개선한다.

## 범위

- 15개 스킬 중 이 프로젝트(Flask+BigQuery 금융 대시보드 + 방금 설치한 Codex 멀티에이전트 파이프라인) 성격에 실용적인 3개만 선별 설치: `multi-agent-patterns`, `tool-design`, `context-optimization`
- 나머지 12개(bdi-mental-states, hosted-agents, book-sft-pipeline, project-development 등 범용 AI 에이전트 개발/연구용)는 이 프로젝트와 관련성이 낮아 설치하지 않음
- 파이프라인 개선은 기존 `CLAUDE.md`/`_shared/routing.md`/`_shared/approval-policy.md`에 텍스트를 추가하는 것으로 한정. `_shared/adapters/call_worker.sh` 등 코드 변경은 검토만 하고, 실제로 고칠 결함이 발견될 때만 수정

## 구성 요소

### 1. 스킬 설치 (`.claude/skills/<name>/SKILL.md`)

이 harness는 프로젝트 스킬을 `.claude/skills/<name>/SKILL.md`에 두면 자동 인식한다(레포 자체 README의 "개별 skill 설치" 방식을 Claude Code 컨벤션에 맞게 적용). 각 스킬의 실제 GitHub 원문(SKILL.md 전체, 요약이 아님)을 가져와 그대로 저장한다:
- `.claude/skills/multi-agent-patterns/SKILL.md`
- `.claude/skills/tool-design/SKILL.md`
- `.claude/skills/context-optimization/SKILL.md`

원본 레포에 `scripts/`, `references/` 하위 폴더가 있는 경우 핵심 참고자료면 함께 가져오고, 없으면 SKILL.md만으로 충분.

### 2. 파이프라인 개선 (5건, multi-agent-patterns/tool-design 스킬 원문 근거)

**a. 워커 수 상한 — `_shared/routing.md` Fan-out/Fan-in 설명에 추가**
> 워커 3~5개를 초과하면 오케스트레이터가 각 응답을 요약하는 과정에서 정보 손실("전화게임 문제")과 병목이 발생한다(출처: multi-agent-patterns). 그 이상 필요하면 계층을 추가하거나 작업을 나눈다.

**b. 비용 경고 — `_shared/approval-policy.md` 비용표에 각주 추가**
> 병렬 멀티에이전트 호출은 단일 호출 대비 약 15배의 토큰 비용이 든다(출처: multi-agent-patterns). 이 프로젝트는 codex-main/codex-critic을 자동승인하므로, 병렬 호출 규모를 키우기 전에 이 비용 배수를 감안할 것 — 매 호출 사용자 확인이 없다는 점에서 특히 중요.

**c. 원문 보존 규칙을 codex-critic 리뷰 경로에도 명시 — `_shared/routing.md`**
기존 Fan-in 규칙("각 worker 원문을 result.md에 그대로 보존")은 병렬 워커 통합 상황만 언급한다. codex-critic 리뷰 결과(단일 워커, 병합 없음)에도 동일 원칙이 적용됨을 명시: 오케스트레이터가 리뷰 내용을 요약하지 않고 result.md에 원문 그대로 옮겨 적는다(Task 5에서 실제로 이렇게 했으나 규칙화는 안 되어 있었음).

**d. 과도한 분해 경고 — `_templates/task-folder.md` 생성 절차에 한 줄 추가**
> 태스크를 지나치게 잘게 쪼개면(예: 파일 하나당 별도 태스크) 핸드오프(brief 작성·읽기·result 기록) 오버헤드가 실제 작업량을 초과할 수 있다(출처: multi-agent-patterns). 최소한으로 나눌 것.

**e. 에러 메시지 점검 — `_shared/adapters/call_worker.sh` 검토만**
tool-design의 "에러 메시지는 무엇이 잘못됐는지+어떻게 고치는지를 담아야 한다" 체크리스트로 기존 `die()` 메시지들을 재검토. 이미 상당수가 복구 방법을 포함하고 있음(예: "git 설치 후 재시도하거나... MULTIAGENT_CODEX_SKIP_GIT=1로 우회"). 실제 결함이 발견되면만 수정, 없으면 변경 없음.

## 영향받지 않는 부분

- `_shared/backends.json`, `.mcp.json` — 코드/설정 변경 없음, 텍스트 문서만 수정
- claude-main 관련 정책 — 변경 없음
- 이번 개선은 순수 문서 추가/보강. 기존 승인된 auto-approve + worktree 격리 + 게이트 테스트 안전 모델 자체는 바꾸지 않음

## 검증 계획

1. 스킬 설치 후 `.claude/skills/<name>/SKILL.md` 파일이 실제 GitHub 원문과 일치하는지 확인(요약이 아닌 원문 여부)
2. 파이프라인 문서 개선 후 `PYTHONIOENCODING=utf-8` + `validate.py`로 구조 검증 — 단, `/c/tmp_mas`는 이전 작업에서 삭제됐으므로 generator 소스를 다시 클론해야 함(`git clone --depth 1 https://github.com/netwaif/multi-agent-starter.git` → `C:\tmp_mas2\src` 등 짧은 경로)
3. 5개 개선 항목이 실제로 반영됐는지 grep으로 확인
