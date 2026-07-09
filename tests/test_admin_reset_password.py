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
