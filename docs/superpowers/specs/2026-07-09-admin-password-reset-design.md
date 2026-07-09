# 관리자 비밀번호 초기화 기능

## 배경

`dashboard_users` 테이블은 비밀번호를 `password_hash`(werkzeug 단방향 해시)로만 저장하므로 원본 비밀번호 조회는 불가능하다. 사용자가 비밀번호를 잊었을 때 이를 도와줄 방법이 현재 관리자 화면(`templates/admin.html`)에 없다.

한편 `/signup`(app_v2.py:399-465)은 이미 "관리자가 사전 등록했지만 `password_hash`가 비어있는 계정"이 재방문 시 새 비밀번호를 설정하도록 처리하는 로직을 갖고 있다(app_v2.py:420-445, 기존 유저 + `password_hash` 없음 → `UPDATE ... SET password_hash=%s, is_active=1`). `/login`(app_v2.py:368-377)도 `password_hash`가 없는 계정에 대해 "비밀번호가 설정되지 않았습니다. 회원가입을 통해 비밀번호를 설정하세요." 안내 메시지를 이미 보여준다.

이 두 로직을 그대로 재사용하면, 관리자가 계정의 `password_hash`를 `NULL`로 리셋하는 것만으로 "비밀번호 찾기"를 구현할 수 있다. 새 DB 컬럼, 이메일/SMTP 인프라, 토큰 발급 로직이 전혀 필요 없다.

## 범위

- 신규 라우트 `POST /admin/users/<int:uid>/reset-password` 1개 추가 (app_v2.py)
- `templates/admin.html`의 사용자별 액션 버튼에 "비밀번호 초기화" 버튼 + JS 함수 1개 추가
- `/login`, `/signup` 로직 변경 없음 (기존 그대로 재사용)
- DB 스키마 변경 없음

## 변경 1 — 백엔드: 비밀번호 초기화 라우트

`app_v2.py`의 기존 `/admin/users/<int:uid>/toggle` 라우트(1430번대)와 동일한 패턴으로 작성:

```python
@app.route('/admin/users/<int:uid>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(uid):
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

- `is_active`는 건드리지 않는다 — 이미 활성 계정은 활성 상태를 유지한 채 비밀번호만 비워진다.
- 리셋 직후 해당 계정으로 로그인을 시도하면 기존 `/login` 로직이 "비밀번호가 설정되지 않았습니다. 회원가입을 통해 비밀번호를 설정하세요." 메시지를 그대로 보여준다.
- 사용자가 `/signup`에서 같은 아이디로 새 비밀번호를 입력하면 기존 로직이 `password_hash`를 갱신하고 즉시 로그인 세션을 만든다.
- 정확한 데코레이터 이름(`admin_required` 등)은 파일 내 기존 admin 라우트들이 실제로 쓰는 것을 그대로 따른다 (구현 단계에서 확인).

## 변경 2 — 프론트엔드: 관리자 화면 버튼

`templates/admin.html`의 `action-btns` 블록(159-169번 줄)에 삭제 버튼 앞에 버튼 추가:

```html
<button class="btn-sm" onclick="resetPassword({{ u.id }}, '{{ u.username }}')">비밀번호 초기화</button>
```

JS 함수는 기존 `toggleUser`/`deleteUser`와 동일한 fetch 패턴으로 추가하고, `deleteUser`와 같은 톤의 confirm 다이얼로그를 넣는다:

```js
function resetPassword(id, username){
  if(!confirm(username+'의 비밀번호를 초기화하시겠습니까? 다음 로그인 시 회원가입 페이지에서 새 비밀번호를 설정해야 합니다.')) return;
  fetch('/admin/users/'+id+'/reset-password',{method:'POST'}).then(function(r){ return r.json(); }).then(function(d){
    if(d.ok){ showMsg('비밀번호가 초기화되었습니다','success'); }
    else showMsg(d.error||'오류 발생','error');
  });
}
```

- 테이블 상태 표시(활성/승인 대기/비활성 뱃지, 143-157번 줄)는 `is_active`를 우선 체크하므로 변경 불필요 — 리셋 후에도 "활성" 뱃지 그대로 유지된다.

## 영향받지 않는 부분

- `/login`, `/signup` 라우트 코드 — 완전히 그대로 재사용, 한 줄도 변경 없음
- `dashboard_users` 테이블 스키마 — 컬럼 추가/변경 없음
- 사용자 추가/삭제/역할변경/활성화 토글 등 기존 admin 라우트 — 변경 없음
- 이메일/SMTP — 애초에 도입하지 않음

## 엣지 케이스

- 관리자가 자기 자신의 비밀번호도 이 버튼으로 초기화할 수 있다. 막을 이유가 없다 — 초기화 후 재로그인 시도하면 안내 메시지를 보고 `/signup`에서 재설정하면 된다.
- 이미 `password_hash`가 비어있는 계정(승인 대기 중인 신규 가입자)에 다시 초기화를 눌러도 결과는 동일(NULL→NULL, no-op)하므로 별도 방어 로직 불필요.

## 테스트 관점

- 관리자 화면에서 임의 계정에 "비밀번호 초기화" 클릭 → confirm → 성공 메시지 확인
- DB에서 해당 계정의 `password_hash`가 `NULL`이 되었는지 확인
- 초기화된 계정으로 `/login` 시도 → "비밀번호가 설정되지 않았습니다..." 메시지 확인
- `/signup`에서 같은 아이디로 새 비밀번호 설정 → 로그인 성공, 이후 `/login`으로도 새 비밀번호로 로그인 가능한지 확인
- 초기화 후에도 관리자 화면의 상태 뱃지가 "활성"으로 유지되는지 확인 (승인 대기로 잘못 표시되지 않는지)
