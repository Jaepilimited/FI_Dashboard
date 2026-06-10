import pytest
import app as flask_app


@pytest.fixture
def client():
    flask_app.app.config['TESTING'] = True
    flask_app.app.secret_key = 'test-secret'
    with flask_app.app.test_client() as c:
        yield c


def test_report_redirects_when_not_logged_in(client):
    resp = client.get('/report')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_report_renders_when_logged_in(client):
    with client.session_transaction() as sess:
        sess['user'] = {'username': 'testuser', 'display_name': 'Test', 'role': 'viewer'}
    resp = client.get('/report')
    assert resp.status_code == 200
    assert '월간 재무 성과 리포트'.encode() in resp.data
