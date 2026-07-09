# 관리자 비밀번호 초기화 기능 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자가 사용자 계정의 비밀번호를 초기화(`password_hash`를 `NULL`로 리셋)할 수 있게 하여, 기존 `/signup`·`/login` 로직을 그대로 재사용해 "비밀번호 찾기"를 구현한다.

**Architecture:** 새 관리자 전용 라우트 `POST /admin/users/<int:uid>/reset-password`가 `password_hash`를 `NULL`로 갱신한다. 이미 존재하는 `/signup`(빈 `password_hash`를 가진 기존 계정 재설정 로직)과 `/login`(빈 `password_hash` 안내 메시지)은 변경하지 않는다. `templates/admin.html`에 버튼 하나와 fetch 호출 하나를 추가한다.

**Tech Stack:** Flask, PyMySQL, Jinja2, vanilla JS(fetch). 테스트는 `pytest` + `Flask test_client` (프로젝트 기존 패턴, `tests/test_tableau_api.py` 참조 — 인증/권한 경계만 검증하고 실제 DB 접속 없이 동작).

## Global Constraints

- 신규 라우트는 기존 admin 라우트들과 동일하게 데코레이터 `@admin_required` 하나만 사용한다 (내부에서 로그인 여부까지 체크함, `app_v2.py:324-332`). `@login_required`를 별도로 겹쳐 쓰지 않는다.
- 라우트 함수명은 기존 admin 라우트 네이밍 패턴(`admin_delete_user`, `admin_change_role`, `admin_toggle_user`)을 따라 `admin_reset_user_password`로 한다.
- DB 스키마 변경 없음. `/login`, `/signup` 코드 변경 없음.
- 스펙 문서: `docs/superpowers/specs/2026-07-09-admin-password-reset-design.md`

---

### Task 1: 백엔드 — 비밀번호 초기화 라우트

**Files:**
- Modify: `app_v2.py` (기존 `@app.route('/admin/users/<int:uid>/toggle', ...)` 블록, 1430-1442번 줄 바로 뒤에 새 라우트 추가)
- Test: `tests/test_admin_reset_password.py` (신규)

**Interfaces:**
- Consumes: `admin_required` 데코레이터(`app_v2.py:324`), `get_db()`(`app_v2.py` 상단 DB 헬퍼, 기존 admin 라우트들과 동일하게 사용)
- Produces: 라우트 `POST /admin/users/<int:uid>/reset-password` — 성공 시 `{'ok': True}` JSON, 200. 미로그인 시 302 redirect. 로그인했지만 role != 'admin'이면 403 `{'error': '권한이 없습니다'}` (모두 `admin_required`가 처리, 기존 라우트들과 동일 동작).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_admin_reset_password.py` 새로 생성:

```python
import pytest
import app_v2 as flask_app


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def authed_admin(client):
    with client.session_transaction() as s:
        s['user'] = {'username': 'testadmin', 'display_name': 'A', 'role': 'admin'}


def authed_viewer(client):
    with client.session_transaction() as s:
        s['user'] = {'username': 'testviewer', 'display_name': 'V', 'role': 'viewer'}


def test_reset_password_requires_login(client):
    resp = client.post('/admin/users/99999/reset-password')
    assert resp.status_code == 302


def test_reset_password_requires_admin_role(client):
    authed_viewer(client)
    resp = client.post('/admin/users/99999/reset-password')
    assert resp.status_code == 403
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_admin_reset_password.py -v`
Expected: FAIL — 라우트가 아직 없으므로 `404 NOT FOUND` (Flask가 미정의 라우트에 404를 반환하여 assert 실패)

- [ ] **Step 3: 최소 구현 작성**

`app_v2.py`의 `admin_toggle_user` 함수(1430-1442번 줄) 바로 다음에 추가:

```python
@app.route('/admin/users/<int:uid>/reset-password', methods=['POST'])
@admin_required
def admin_reset_user_password(uid):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE dashboard_users SET password_hash=NULL WHERE id=%s", (uid,)
            )
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_admin_reset_password.py -v`
Expected: PASS (2 passed) — 두 테스트 모두 `admin_required`가 DB 접속 전에 리다이렉트/403을 반환하므로 실제 DB 연결 없이 통과한다.

- [ ] **Step 5: 회귀 테스트 실행**

Run: `python -m pytest tests/test_tableau_api.py tests/test_admin_reset_password.py -v`
Expected: 전부 PASS. 기존 라우트에 영향 없음을 확인.

- [ ] **Step 6: 커밋**

```bash
git add app_v2.py tests/test_admin_reset_password.py
git commit -m "feat: 관리자용 비밀번호 초기화 라우트 추가"
```

---

### Task 2: 프론트엔드 — 관리자 화면에 초기화 버튼 추가

**Files:**
- Modify: `templates/admin.html:159-169` (action-btns 블록), `templates/admin.html:230-253` (JS 함수 블록)

**Interfaces:**
- Consumes: Task 1에서 만든 `POST /admin/users/<int:uid>/reset-password` (응답 `{'ok': True}` 또는 `{'error': '...'}`), 기존 `showMsg(text, type)` 헬퍼(`admin.html:210-214`)
- Produces: 없음 (최종 UI 계층)

- [ ] **Step 1: action-btns 블록에 버튼 추가**

`templates/admin.html`의 158-170번 줄(action-btns div)을 다음으로 교체:

```html
          <td>
            <div class="action-btns">
              {% if not u.is_active and u.password_hash %}
                <button class="btn-sm" style="color:var(--positive);border-color:rgba(16,185,129,.3)" onclick="toggleUser({{ u.id }})">승인</button>
              {% else %}
                <button class="btn-sm" onclick="changeRole({{ u.id }}, '{{ 'viewer' if u.role == 'admin' else 'admin' }}')">
                  → {{ '뷰어로' if u.role == 'admin' else '관리자로' }}
                </button>
                <button class="btn-sm" onclick="toggleUser({{ u.id }})">{{ '비활성화' if u.is_active else '활성화' }}</button>
              {% endif %}
              <button class="btn-sm" onclick="resetPassword({{ u.id }}, '{{ u.username }}')">비밀번호 초기화</button>
              <button class="btn-sm danger" onclick="deleteUser({{ u.id }}, '{{ u.username }}')">삭제</button>
            </div>
          </td>
```

- [ ] **Step 2: JS 함수 추가**

`templates/admin.html`의 `toggleUser` 함수(248-253번 줄) 바로 뒤에 추가:

```javascript
function resetPassword(id, username){
  if(!confirm(username+'의 비밀번호를 초기화하시겠습니까? 다음 로그인 시 회원가입 페이지에서 새 비밀번호를 설정해야 합니다.')) return;
  fetch('/admin/users/'+id+'/reset-password',{method:'POST'}).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('비밀번호가 초기화되었습니다','success'); }
    else showMsg(d.error||'오류 발생','error');
  });
}
```

- [ ] **Step 3: 수동 검증**

이 프로젝트에는 템플릿/JS용 자동화 테스트가 없으므로(`pw_full_test.py`는 실 DB·브라우저 데몬 의존 수동 검증 스크립트) 다음을 수동으로 확인한다:

1. `python app_v2.py`로 서버 기동 (또는 기존 운영 방식대로)
2. 관리자 계정으로 로그인 → `/admin` 접속
3. 임의 사용자 행에서 "비밀번호 초기화" 클릭 → confirm 창에서 확인
4. 초록색 성공 토스트("비밀번호가 초기화되었습니다") 노출 확인
5. 로그아웃 → 방금 초기화한 계정으로 `/login` 시도 → "비밀번호가 설정되지 않았습니다. 회원가입을 통해 비밀번호를 설정하세요." 메시지 확인
6. `/signup`에서 같은 아이디로 새 비밀번호 설정 → 로그인 성공 확인
7. `/admin`으로 돌아가 해당 계정 상태 뱃지가 여전히 "활성"인지 확인 (승인 대기로 잘못 표시되지 않는지)

- [ ] **Step 4: 커밋**

```bash
git add templates/admin.html
git commit -m "feat: 관리자 화면에 비밀번호 초기화 버튼 추가"
```

---

## Self-Review Notes

- **Spec coverage**: 스펙의 변경 1(백엔드 라우트) → Task 1, 변경 2(프론트엔드 버튼) → Task 2. 엣지 케이스(자기 자신 초기화 허용, 이미 NULL인 계정에 재실행해도 no-op)는 코드 자체가 별도 분기 없이 자연히 만족하므로 추가 태스크 불필요 — Task 2 Step 3 수동 검증에 상태 뱃지 확인 항목으로 반영.
- **데코레이터 정정**: 스펙 초안에는 `@login_required` + `@admin_required`로 적었으나, 실제 코드(`app_v2.py:1400,1413,1430`)의 기존 admin 라우트는 전부 `@admin_required` 단독 사용 — 플랜은 실제 패턴을 따르도록 수정함.
- **타입/네이밍 일관성**: 라우트 함수명 `admin_reset_user_password`는 Task 1·Task 2에서 동일하게 참조(단, 프론트는 URL 문자열만 사용하므로 함수명 불일치 리스크 없음). JS 함수명 `resetPassword`는 Task 2 내에서만 정의·사용.
