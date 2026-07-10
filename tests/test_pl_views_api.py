import pytest
import app_v2 as flask_app

TEST_USER = 'testuser_pl_views'


@pytest.fixture(scope='session', autouse=True)
def _ensure_schema():
    # 라이브 리로더 재시작 타이밍에 의존하지 않도록 테스트에서 직접 스키마 보장
    flask_app.init_db()


def _cleanup():
    db = flask_app.get_db()
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM user_views WHERE username=%s", (TEST_USER,))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_test_rows():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def authed(client):
    with client.session_transaction() as s:
        s['user'] = {'username': TEST_USER, 'display_name': 'T', 'role': 'viewer'}


def test_pl_views_list_empty_for_new_screen(client):
    authed(client)
    resp = client.get('/api/views?kind=pl&screen=org')
    assert resp.status_code == 200
    assert resp.get_json()['views'] == []


def test_pl_views_create_requires_screen(client):
    authed(client)
    resp = client.post('/api/views', json={'kind': 'pl', 'name': '내 뷰', 'config': {}})
    assert resp.status_code == 400


def test_pl_views_create_and_list_roundtrip(client):
    authed(client)
    create = client.post('/api/views', json={
        'kind': 'pl', 'screen': 'org', 'name': '내 뷰',
        'config': {'rows': {'hidden': ['sgaD.fee']}}
    })
    assert create.status_code == 200
    view_id = create.get_json()['id']

    listed = client.get('/api/views?kind=pl&screen=org').get_json()['views']
    assert len(listed) == 1
    assert listed[0]['id'] == view_id
    assert listed[0]['config']['rows']['hidden'] == ['sgaD.fee']


def test_pl_views_do_not_leak_into_tableau_list(client):
    authed(client)
    client.post('/api/views', json={'kind': 'pl', 'screen': 'org', 'name': 'PL 뷰', 'config': {}})
    tableau_views = client.get('/api/views').get_json()['views']
    assert all(v['name'] != 'PL 뷰' for v in tableau_views)


def test_pl_views_scoped_by_screen(client):
    authed(client)
    client.post('/api/views', json={'kind': 'pl', 'screen': 'org', 'name': 'Org 뷰', 'config': {}})
    product_views = client.get('/api/views?kind=pl&screen=product').get_json()['views']
    assert product_views == []
