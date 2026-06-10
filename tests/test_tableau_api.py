import pytest
import app_v2 as flask_app


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def authed(client):
    with client.session_transaction() as s:
        s['user'] = {'username': 'testuser', 'display_name': 'T', 'role': 'viewer'}


def test_views_list_requires_login(client):
    resp = client.get('/api/views')
    assert resp.status_code == 302


def test_tableau_fields_requires_login(client):
    resp = client.get('/api/tableau/fields')
    assert resp.status_code == 302


def test_views_put_auth_check(client):
    authed(client)
    resp = client.put('/api/views/99999', json={'name': 'x'})
    assert resp.status_code == 403


def test_views_delete_auth_check(client):
    authed(client)
    resp = client.delete('/api/views/99999')
    assert resp.status_code == 403
