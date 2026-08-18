import json
import sys
from types import SimpleNamespace
import time
import pytest

import ots_manager


class DummyResp:
    def __init__(self, status_code=200, text='ok', data=None):
        self.status_code = status_code
        self.text = text
        self._data = data

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def test_get_csrf_token_prefers_cookie_names(monkeypatch):
    mapping = {'csrf_token': None, 'csrf_access_token': 'tok1'}
    cookie = SimpleNamespace(get=lambda k, d=None: mapping.get(k, d))
    monkeypatch.setattr(ots_manager.session, 'cookies', cookie)
    assert ots_manager.get_csrf_token() == 'tok1'


def test_login_success_with_cookie(monkeypatch):
    # session.post returns 200 and cookies contain token
    cookie = SimpleNamespace(get=lambda k, d=None: 'abc' if k == 'csrf_token' else None)
    monkeypatch.setattr(ots_manager.session, 'cookies', cookie)

    def fake_post(url, json=None, timeout=None):
        return DummyResp(status_code=200, data={})

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    assert ots_manager.login() is True
    assert 'X-CSRFToken' in ots_manager.session.headers


def test_login_success_with_body(monkeypatch):
    cookie = SimpleNamespace(get=lambda k, d=None: None)
    monkeypatch.setattr(ots_manager.session, 'cookies', cookie)

    def fake_post(url, json=None, timeout=None):
        return DummyResp(status_code=200, data={'csrf_token': 'bodytoken'})

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    assert ots_manager.login() is True
    assert ots_manager.session.headers.get('X-CSRFToken') == 'bodytoken'


def test_login_failure_and_exception(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'cookies', SimpleNamespace(get=lambda k, d=None: None))

    def fake_post_fail(url, json=None, timeout=None):
        return DummyResp(status_code=401, text='denied')

    monkeypatch.setattr(ots_manager.session, 'post', fake_post_fail)
    assert ots_manager.login() is False

    def fake_post_exc(url, json=None, timeout=None):
        raise Exception('boom')

    monkeypatch.setattr(ots_manager.session, 'post', fake_post_exc)
    assert ots_manager.login() is False


def test_create_group_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=201))
    assert ots_manager.create_group('G1') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=400, text='exists'))
    assert ots_manager.create_group('G1') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.create_group('G1') is False


def test_create_user_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=201))
    assert ots_manager.create_user('u', 'p') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=400, text='exists'))
    assert ots_manager.create_user('u', 'p') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.create_user('u', 'p') is False


def test_add_user_to_group_directions(monkeypatch):
    calls = []

    def fake_put(url, json=None, headers=None):
        calls.append((json.get('direction'), json.get('groups')))
        return DummyResp(status_code=204)

    monkeypatch.setattr(ots_manager.session, 'put', fake_put)
    assert ots_manager.add_user_to_group('u', 'G', direction='BOTH') is True
    assert len(calls) == 2

    calls.clear()
    # invalid direction should be coerced
    assert ots_manager.add_user_to_group('u', 'G', direction='X') is True
    assert len(calls) == 2

    # simulate failure
    def fake_put_err(url, json=None, headers=None):
        return DummyResp(status_code=500)

    monkeypatch.setattr(ots_manager.session, 'put', fake_put_err)
    assert ots_manager.add_user_to_group('u', 'G', direction='IN') is False


def test_parse_expiration():
    assert ots_manager.parse_expiration(None) is None
    ts = ots_manager.parse_expiration('1')
    assert isinstance(ts, int) and ts > time.time()
    ts2 = ots_manager.parse_expiration('2030-01-01')
    assert isinstance(ts2, int) and ts2 > 1600000000
    assert ots_manager.parse_expiration('bad-format') is None


def test_get_qr_string_android_and_iphone(monkeypatch):
    # android json
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200, data={'qr_string':'abc'}))
    assert ots_manager.get_qr_string('u', app_type='android') == 'abc'

    # android text
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200, data=None, text='"tok"'))
    # force json() to raise
    def jfail():
        raise Exception('nojson')
    r = DummyResp(status_code=200, data=Exception('nojson'), text='"tok"')
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: r)
    assert ots_manager.get_qr_string('u', app_type='android') == '"tok"'.strip('"')

    # android error
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.get_qr_string('u', app_type='android') is None

    # iphone
    monkeypatch.setattr(ots_manager.session, 'get', lambda url: DummyResp(status_code=200, data={'qr_string':'iphone'}))
    assert ots_manager.get_qr_string('u', app_type='iphone') == 'iphone'
    monkeypatch.setattr(ots_manager.session, 'get', lambda url: DummyResp(status_code=500, text='err'))
    assert ots_manager.get_qr_string('u', app_type='iphone') is None


def test_save_qr_code_image(tmp_path):
    out = tmp_path / 'q.png'
    ots_manager.save_qr_code_image('some data', str(out))
    assert out.exists()


def test_parse_group_entry_variants():
    assert ots_manager.parse_group_entry({'name':'G','direction':'IN'}) == ('G','IN')
    assert ots_manager.parse_group_entry('G:OUT') == ('G','OUT')
    assert ots_manager.parse_group_entry('G') == ('G','BOTH')
    assert ots_manager.parse_group_entry(123) == (None,'BOTH')


def test_list_groups_and_process_batch(monkeypatch, tmp_path):
    # list_groups returns mixed formats
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data=['G1','G2']))
    assert ots_manager.list_groups() == ['G1','G2']

    # prepare mocks for process_batch_list
    created_groups = []
    monkeypatch.setattr(ots_manager, 'create_group', lambda name: created_groups.append(name) or True)
    monkeypatch.setattr(ots_manager, 'create_user', lambda u,p,e,a: True)
    linked = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**kwargs: linked.append((u,g,kwargs.get('direction','BOTH'))) or True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda username, app_type, exp_timestamp, max_uses: 'tok')
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda qr_data, out: open(out,'wb').write(b'1'))
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['G1','G2'])

    data = [
        {'username':'u1','password':'p','groups':['G1:G:IN','ALL'],'app':'android'},
        {'username':'u2','password':'p2','groups':['G2'],'app':'iphone'},
    ]
    out_file = tmp_path / 'out.json'
    ots_manager.process_batch_list(data, output_summary_file=str(out_file))
    assert out_file.exists()
    res = json.loads(out_file.read_text(encoding='utf-8'))
    assert isinstance(res, list) and len(res) == 2


def test_list_users_variants(monkeypatch):
    responses = [
        DummyResp(status_code=200, data=[
            {'username': 'u1', 'administrator': True, 'last_login': 1700000000},
            {'username': 'u2', 'admin': False, 'lastLogin': '2024-01-01T00:00:00Z'},
        ]),
        DummyResp(status_code=200, data={'users': [
            {'username': 'u3', 'is_admin': True, 'last_login_at': '2024-02-02T03:04:05+00:00'}
        ]}),
    ]

    calls = iter(responses)
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: next(calls))
    users = ots_manager.list_users()
    assert users[0]['username'] == 'u1'
    assert users[0]['admin'] is True
    assert '2023-11-14' in users[0]['last_login']
    assert users[1]['username'] == 'u2'
    assert users[1]['admin'] is False
    assert users[1]['last_login'].startswith('2024-01-01')

    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data={'results': [
        {'username': 'u4', 'isAdministrator': True, 'last_seen': '2024-03-03T00:00:00Z'}
    ]}))
    users = ots_manager.list_users()
    assert users[0]['username'] == 'u4'
    assert users[0]['admin'] is True
    assert users[0]['last_login'].startswith('2024-03-03T00:00:00')


def test_main_list_users(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_users', lambda: [
        {'username': 'u1', 'admin': True, 'last_login': '2024-01-01T00:00:00+00:00'},
        {'username': 'u2', 'admin': False, 'last_login': None},
    ])
    monkeypatch.setattr(sys, 'argv', ['prog', 'list-users'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Usuários existentes' in captured.out
    assert 'admin=SIM' in captured.out
    assert 'ultimo_login=' in captured.out


def test_main_commands(monkeypatch, capsys, tmp_path):
    # list-groups via CLI
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['A','B'])
    monkeypatch.setattr(sys, 'argv', ['prog','list-groups'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Grupos existentes' in captured.out

    # create-user with ALL
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'create_user', lambda u,p,e,a: True)
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['G1'])
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda qr, out: None)
    monkeypatch.setattr(ots_manager, 'create_group', lambda name: True)
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**kwargs: None)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda username, app_type, exp_timestamp, max_uses: 'tok')
    monkeypatch.setattr(sys, 'argv', ['prog','create-user','-u','x','-p','y','-g','ALL'])
    ots_manager.main()

    # link ALL
    calls = []
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['L1'])
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**kwargs: calls.append((u,g,kwargs.get('direction','BOTH'))) or True)
    monkeypatch.setattr(sys, 'argv', ['prog','link','-u','u','-g','ALL','-d','IN'])
    ots_manager.main()
    assert calls and calls[0][1] == 'L1'


def test_get_csrf_token_none(monkeypatch):
    cookie = SimpleNamespace(get=lambda k, d=None: None)
    monkeypatch.setattr(ots_manager.session, 'cookies', cookie)
    assert ots_manager.get_csrf_token() is None


def test_list_groups_various_structures(monkeypatch):
    # list as dicts
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data={'groups':[{'name':'A'},{'name':'B'}]}))
    assert ots_manager.list_groups() == ['A','B']

    # results key
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data={'results':['X','Y']}))
    assert ots_manager.list_groups() == ['X','Y']

    # nested list in values
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data={'meta':['z'],'items':['I1','I2']}))
    # function picks first list found in values
    assert ots_manager.list_groups() == ['z']


def test_get_qr_string_edge_cases(monkeypatch):
    # token key
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200, data={'token':'tok2'}))
    assert ots_manager.get_qr_string('u', app_type='android') == 'tok2'

    # invalid app
    assert ots_manager.get_qr_string('u', app_type='desktop') is None


def test_process_batch_skip_and_main_errors(monkeypatch, capsys):
    # process_batch_list should skip entries without username/password
    monkeypatch.setattr(ots_manager, 'create_group', lambda name: True)
    monkeypatch.setattr(ots_manager, 'create_user', lambda u,p,e,a: True)
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**kwargs: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *args, **kwargs: None)
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda qr, out: None)
    data = [{'username':None,'password':'p','groups':['G1']},{'username':'u','password':None,'groups':['G1']}]
    out = '/tmp/nonexistent.json'
    ots_manager.process_batch_list(data, output_summary_file=out)

    # main batch (create-user -f) error handling when file not found
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog','create-user','-f','nope.json'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Erro ao processar arquivo batch' in captured.out or 'Erro' in captured.out


def test_login_when_response_json_raises(monkeypatch):
    # cookies empty, response.json raises
    monkeypatch.setattr(ots_manager.session, 'cookies', SimpleNamespace(get=lambda k, d=None: None))
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, timeout=None: DummyResp(status_code=200, data=Exception('nojson'), text='ok'))
    # ensure no leftover CSRF headers
    ots_manager.session.headers.pop('X-CSRFToken', None)
    ots_manager.session.headers.pop('X-CSRF-TOKEN', None)
    # should return True but not set csrf header
    assert ots_manager.login() is True
    assert 'X-CSRFToken' not in ots_manager.session.headers and 'X-CSRF-TOKEN' not in ots_manager.session.headers


def test_list_groups_errors(monkeypatch):
    # json() raises -> returns []
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=200, data=Exception('x'), text='raw'))
    assert ots_manager.list_groups() == []
    # non-200 -> returns []
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, timeout=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.list_groups() == []


def test_parse_expiration_special_strings():
    for v in ['none', 'null', 'eterno', 'infinito']:
      assert ots_manager.parse_expiration(v) is None


def test_get_qr_string_android_payload(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
      captured['payload'] = json
      return DummyResp(status_code=200, data={'qr_string':'ok'})

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    res = ots_manager.get_qr_string('u', app_type='android', exp_timestamp=1600000000, max_uses=3)
    assert res == 'ok'
    assert 'max' in captured['payload'] and 'exp' in captured['payload'] and 'nbf' in captured['payload']


def test_get_qr_string_iphone_itak(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url: DummyResp(status_code=200, data={'itak_qr_string':'itok'}))
    assert ots_manager.get_qr_string('u', app_type='iphone') == 'itok'


def test_main_other_cli_paths(monkeypatch, tmp_path):
    # qr command
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: 'QR')
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda q,o: None)
    monkeypatch.setattr(sys, 'argv', ['prog','qr','-u','user'])
    ots_manager.main()

    # create-group
    called = {}
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'create_group', lambda name: called.setdefault('name', name) or True)
    monkeypatch.setattr(sys, 'argv', ['prog','create-group','-n','GZ'])
    ots_manager.main()
    assert called.get('name') == 'GZ'

    # link single group
    calls = []
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**k: calls.append((u,g)) or True)
    monkeypatch.setattr(sys, 'argv', ['prog','link','-u','u','-g','G1','-d','IN'])
    ots_manager.main()
    assert calls and calls[0][1] == 'G1'

    # batch success (main, now under create-user -f) -> mock process_batch_list
    called_batch = {}
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'process_batch_list', lambda data, output_summary_file=None: called_batch.setdefault('ok', True))
    # create a temp json file
    f = tmp_path / 'b.json'
    f.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog','create-user','-f',str(f),'-o','out.json'])
    ots_manager.main()
    assert called_batch.get('ok') is True


def test_list_groups_connection_error(monkeypatch):
        def raise_conn(url, timeout=None):
            raise Exception('conn')
        monkeypatch.setattr(ots_manager.session, 'get', raise_conn)
        assert ots_manager.list_groups() == []


def test_get_qr_string_with_csrf_headers(monkeypatch):
        # ensure csrf from cookies is added to headers
        monkeypatch.setattr(ots_manager.session, 'cookies', SimpleNamespace(get=lambda k, d=None: 'csrfval'))
        captured = {}
        def fake_post(url, json=None, headers=None):
            captured['headers'] = headers
            return DummyResp(status_code=200, data={'qr_string':'ok'})
        monkeypatch.setattr(ots_manager.session, 'post', fake_post)
        res = ots_manager.get_qr_string('u', app_type='android')
        assert res == 'ok'
        assert captured['headers'].get('X-CSRFToken') == 'csrfval'


def test_get_qr_string_iphone_json_exception(monkeypatch):
        monkeypatch.setattr(ots_manager.session, 'get', lambda url: DummyResp(status_code=200, data=Exception('x'), text='"rawiphone"'))
        assert ots_manager.get_qr_string('u', app_type='iphone') == 'rawiphone'


def test_main_no_args_and_login_false(monkeypatch):
        # no args -> exits
        monkeypatch.setattr(sys, 'argv', ['prog'])
        with pytest.raises(SystemExit):
            ots_manager.main()

        # login false -> exits
        monkeypatch.setattr(sys, 'argv', ['prog','list-groups'])
        monkeypatch.setattr(ots_manager, 'login', lambda: False)
        with pytest.raises(SystemExit):
            ots_manager.main()


def test_main_create_user_non_all(monkeypatch):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        calls = {'created':[],'linked':[]}
        monkeypatch.setattr(ots_manager, 'create_group', lambda name: calls['created'].append(name) or True)
        monkeypatch.setattr(ots_manager, 'create_user', lambda u,p,e,a: True)
        monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u,g,**k: calls['linked'].append((u,g)) or True)
        monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: None)
        monkeypatch.setattr(sys, 'argv', ['prog','create-user','-u','x','-p','y','-g','G1'])
        ots_manager.main()
        assert 'G1' in calls['created']
        assert ('x','G1') in calls['linked']


def test_main_create_user_missing_password(monkeypatch, capsys):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        monkeypatch.setattr(sys, 'argv', ['prog', 'create-user', '-u', 'x'])
        with pytest.raises(SystemExit) as exc_info:
            ots_manager.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert '-p/--password' in captured.out


def test_main_create_user_and_batch_mutually_exclusive(monkeypatch):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        monkeypatch.setattr(sys, 'argv', ['prog', 'create-user', '-u', 'x', '-f', 'file.json'])
        with pytest.raises(SystemExit):
            ots_manager.main()


@pytest.mark.parametrize('command', ['create-user', 'delete-user', 'deactivate-user', 'activate-user'])
def test_main_requires_username_or_file(monkeypatch, command):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        monkeypatch.setattr(sys, 'argv', ['prog', command])
        with pytest.raises(SystemExit):
            ots_manager.main()


@pytest.mark.parametrize('command', ['delete-user', 'deactivate-user', 'activate-user'])
def test_main_lifecycle_commands_and_batch_mutually_exclusive(monkeypatch, command):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        monkeypatch.setattr(sys, 'argv', ['prog', command, '-u', 'x', '-f', 'file.json'])
        with pytest.raises(SystemExit):
            ots_manager.main()


def test_main_list_groups_no_results(monkeypatch, capsys):
        monkeypatch.setattr(ots_manager, 'login', lambda: True)
        monkeypatch.setattr(ots_manager, 'list_groups', lambda: [])
        monkeypatch.setattr(sys, 'argv', ['prog','list-groups'])
        ots_manager.main()
        captured = capsys.readouterr()
        assert 'Nenhum grupo encontrado' in captured.out


def test_delete_user_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200))
    assert ots_manager.delete_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.delete_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.delete_user('u') is False


def test_deactivate_user_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=204))
    assert ots_manager.deactivate_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.deactivate_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.deactivate_user('u') is False


def test_activate_user_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200))
    assert ots_manager.activate_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.activate_user('u') is True

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.activate_user('u') is False


def test_extract_usernames_variants(capsys):
    data = ['u1', {'username': 'u2', 'password': 'p'}, {'password': 'no-username'}, 123]
    result = ots_manager.extract_usernames(data)
    assert result == ['u1', 'u2']
    captured = capsys.readouterr()
    assert 'Registro ignorado' in captured.out


def test_process_batch_delete(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ots_manager, 'delete_user', lambda u: calls.append(u) or (u != 'bad'))
    data = ['u1', {'username': 'u2'}, {'username': 'bad'}]
    out_file = tmp_path / 'del.json'
    results = ots_manager.process_batch_delete(data, output_summary_file=str(out_file))
    assert calls == ['u1', 'u2', 'bad']
    assert results == [
        {'username': 'u1', 'deleted': True},
        {'username': 'u2', 'deleted': True},
        {'username': 'bad', 'deleted': False},
    ]
    assert out_file.exists()
    assert json.loads(out_file.read_text(encoding='utf-8')) == results


def test_process_batch_delete_no_output(monkeypatch):
    monkeypatch.setattr(ots_manager, 'delete_user', lambda u: True)
    results = ots_manager.process_batch_delete(['u1'])
    assert results == [{'username': 'u1', 'deleted': True}]


def test_process_batch_deactivate(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ots_manager, 'deactivate_user', lambda u: calls.append(u) or (u != 'bad'))
    data = ['u1', {'username': 'u2'}, {'username': 'bad'}]
    out_file = tmp_path / 'deact.json'
    results = ots_manager.process_batch_deactivate(data, output_summary_file=str(out_file))
    assert calls == ['u1', 'u2', 'bad']
    assert results == [
        {'username': 'u1', 'deactivated': True},
        {'username': 'u2', 'deactivated': True},
        {'username': 'bad', 'deactivated': False},
    ]
    assert out_file.exists()
    assert json.loads(out_file.read_text(encoding='utf-8')) == results


def test_process_batch_deactivate_no_output(monkeypatch):
    monkeypatch.setattr(ots_manager, 'deactivate_user', lambda u: True)
    results = ots_manager.process_batch_deactivate(['u1'])
    assert results == [{'username': 'u1', 'deactivated': True}]


def test_process_batch_activate(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ots_manager, 'activate_user', lambda u: calls.append(u) or (u != 'bad'))
    data = ['u1', {'username': 'u2'}, {'username': 'bad'}]
    out_file = tmp_path / 'act.json'
    results = ots_manager.process_batch_activate(data, output_summary_file=str(out_file))
    assert calls == ['u1', 'u2', 'bad']
    assert results == [
        {'username': 'u1', 'activated': True},
        {'username': 'u2', 'activated': True},
        {'username': 'bad', 'activated': False},
    ]
    assert out_file.exists()
    assert json.loads(out_file.read_text(encoding='utf-8')) == results


def test_process_batch_activate_no_output(monkeypatch):
    monkeypatch.setattr(ots_manager, 'activate_user', lambda u: True)
    results = ots_manager.process_batch_activate(['u1'])
    assert results == [{'username': 'u1', 'activated': True}]


def test_main_create_user_batch_warns_on_ignored_single_flags(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'process_batch_list', lambda data, output_summary_file=None: None)
    f = tmp_path / 'b.json'
    f.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [
        'prog', 'create-user', '-f', str(f),
        '-p', 'Senha123!', '-e', 'a@b.com', '-g', 'G1',
        '--admin', '--app', 'iphone', '--exp', '30', '--max', '2',
        '--save-qr', 'out.png',
    ])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Modo lote' in captured.out
    for flag in ['-p/--password', '-e/--email', '-g/--groups', '--admin', '--app', '--exp', '--max', '--save-qr']:
        assert flag in captured.out


def test_main_create_user_batch_no_warning_when_no_extra_flags(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'process_batch_list', lambda data, output_summary_file=None: None)
    f = tmp_path / 'b.json'
    f.write_text('[]', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog', 'create-user', '-f', str(f)])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Modo lote' not in captured.out


def test_main_delete_user_single(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    calls = []
    monkeypatch.setattr(ots_manager, 'delete_user', lambda u: calls.append(u) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'delete-user', '-u', 'u1'])
    ots_manager.main()
    assert calls == ['u1']


def test_main_delete_user_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    called = {}

    def fake_process_batch_delete(data, output_summary_file=None):
        called['data'] = data
        called['out'] = output_summary_file

    monkeypatch.setattr(ots_manager, 'process_batch_delete', fake_process_batch_delete)
    f = tmp_path / 'users.json'
    f.write_text(json.dumps(['u1', 'u2']), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog', 'delete-user', '-f', str(f), '-o', 'out.json'])
    ots_manager.main()
    assert called['data'] == ['u1', 'u2']
    assert called['out'] == 'out.json'


def test_main_delete_user_batch_file_error(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'delete-user', '-f', 'nope.json'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Erro ao processar arquivo de remoção em lote' in captured.out


def test_main_deactivate_user_single(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    calls = []
    monkeypatch.setattr(ots_manager, 'deactivate_user', lambda u: calls.append(u) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'deactivate-user', '-u', 'u1'])
    ots_manager.main()
    assert calls == ['u1']


def test_main_deactivate_user_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    called = {}

    def fake_process_batch_deactivate(data, output_summary_file=None):
        called['data'] = data
        called['out'] = output_summary_file

    monkeypatch.setattr(ots_manager, 'process_batch_deactivate', fake_process_batch_deactivate)
    f = tmp_path / 'users.json'
    f.write_text(json.dumps([{'username': 'u1'}]), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog', 'deactivate-user', '-f', str(f), '-o', 'out.json'])
    ots_manager.main()
    assert called['data'] == [{'username': 'u1'}]
    assert called['out'] == 'out.json'


def test_main_deactivate_user_batch_file_error(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'deactivate-user', '-f', 'nope.json'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Erro ao processar arquivo de desativação em lote' in captured.out


def test_main_activate_user_single(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    calls = []
    monkeypatch.setattr(ots_manager, 'activate_user', lambda u: calls.append(u) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'activate-user', '-u', 'u1'])
    ots_manager.main()
    assert calls == ['u1']


def test_main_activate_user_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    called = {}

    def fake_process_batch_activate(data, output_summary_file=None):
        called['data'] = data
        called['out'] = output_summary_file

    monkeypatch.setattr(ots_manager, 'process_batch_activate', fake_process_batch_activate)
    f = tmp_path / 'users.json'
    f.write_text(json.dumps([{'username': 'u1'}]), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog', 'activate-user', '-f', str(f), '-o', 'out.json'])
    ots_manager.main()
    assert called['data'] == [{'username': 'u1'}]
    assert called['out'] == 'out.json'


def test_main_activate_user_batch_file_error(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'activate-user', '-f', 'nope.json'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Erro ao processar arquivo de habilitação em lote' in captured.out


def test_run_module_main_executes_main(monkeypatch):
        import runpy
        monkeypatch.setattr(sys, 'argv', ['prog'])
        with pytest.raises(SystemExit):
            runpy.run_module('ots_manager', run_name='__main__')
