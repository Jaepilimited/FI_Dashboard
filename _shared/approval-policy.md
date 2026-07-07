# Worker Approval Policy

## 원칙

**claude-main**: 기존 정책 유지 — 작업별 명시적 승인 필요, `task.md`의 `workers_approved` 리스트에 없으면 호출 금지.

**codex-main / codex-critic (FI Dashboard 프로젝트 전용)**: 자동 승인. git worktree 격리 + 자동 테스트 게이트(`CLAUDE.md`의 "FI Dashboard 프로젝트 전용 규칙" 참조)가 안전망이므로 사용자 승인 대기 없이 호출한다. `workers_approved`/`log.md` `[APPROVAL]` 기록은 감사 추적용으로 자동 작성.

**예외**: Orchestrator의 내부 추론은 worker 호출이 아니므로 승인 불필요. 다만 별도 claude-main worker를 호출해 산출물을 `result.md`로 받는 것은 승인 대상.

## 승인 절차

1. Orchestrator가 worker 필요성 판단 (`_shared/routing.md` 참조)
2. 사용자에게 다음 정보와 함께 승인 요청 (**FI Dashboard 프로젝트 전용**: codex-main/codex-critic은 이 단계를 생략하고 바로 3번으로 진행):
   - 어떤 worker를
   - 무슨 목적으로
   - 예상 호출 횟수 (쿼터 영향 포함)
3. 승인 시 `task.md`의 `workers_approved`에 추가
4. `log.md`에 `[APPROVAL]` 태그로 승인 기록
5. 이후 해당 작업 내에서는 동일 worker 재승인 불필요

## 승인 예외

- **Orchestrator 내부 추론**: worker 호출이 아니므로 승인 불필요.
- **동일 작업 재호출**: `workers_approved`에 이미 있으면 재승인 불필요.
- **검증 실패 후 재시도**: 승인된 worker 범위 내에서 자동 허용.

## 비용·쿼터 가이드라인 (참고)

| Worker | 예상 비용 | 쿼터 부담 |
|--------|---------|----------|
| claude-main | 중간 | Claude API/구독 쿼터 차감 |
| codex-main | 중간 | Codex 호출 쿼터 |
| codex-critic | 낮음-중간 | Codex 호출 쿼터 |
| gemini flash | 낮음 | Gemini 쿼터 |
| gemini pro | 중간-높음 | Gemini 쿼터 |

claude-main이 "내부 추론"과 같은 모델이라도 별도 호출이므로 쿼터·비용 발생.

## 승인 기록 형식 (task.md에 기록)

```yaml
workers_approved:
  - worker: claude-main
    approved_at: <YYYY-MM-DD>      # 승인 당시 날짜로 교체
    purpose: 메인 코드 구현 및 디버깅
    approved_by: user
  - worker: codex-critic
    approved_at: <YYYY-MM-DD>
    purpose: claude-main 산출물 리뷰·비평
    approved_by: user
```

날짜 명령어: `date +%Y-%m-%d`
