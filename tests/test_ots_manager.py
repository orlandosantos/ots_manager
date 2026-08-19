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


def test_create_user_sends_roles_not_administrator_flag(monkeypatch):
    # /api/user/add expects a 'roles' list; an 'administrator' boolean is
    # silently ignored by the server, which then defaults new users to
    # ['user'] regardless of the intended admin flag.
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=201)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)

    assert ots_manager.create_user('u', 'p', is_admin=True) is True
    assert captured['payload']['roles'] == ['administrator']
    assert 'administrator' not in captured['payload']

    assert ots_manager.create_user('u', 'p', is_admin=False) is True
    assert captured['payload']['roles'] == ['user']


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


def test_save_qr_code_image_creates_missing_directory(tmp_path):
    out = tmp_path / 'qrcodes' / 'nested' / 'q.png'
    assert not out.parent.exists()
    ots_manager.save_qr_code_image('some data', str(out))
    assert out.exists()


def test_parse_group_entry_variants():
    assert ots_manager.parse_group_entry({'name':'G','direction':'IN'}) == ('G','IN')
    assert ots_manager.parse_group_entry('G:OUT') == ('G','OUT')
    assert ots_manager.parse_group_entry('G') == ('G','BOTH')
    assert ots_manager.parse_group_entry(123) == (None,'BOTH')


def test_list_groups_and_process_batch(monkeypatch, tmp_path):
    # list_groups returns mixed formats
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=200, data=['G1','G2']))
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
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': [
            {'username': 'u1', 'administrator': True, 'last_login': 1700000000},
            {'username': 'u2', 'admin': False, 'lastLogin': '2024-01-01T00:00:00Z'},
        ]},
    ))
    users = ots_manager.list_users()
    assert users[0]['username'] == 'u1'
    assert users[0]['admin'] is True
    assert '2023-11-14' in users[0]['last_login']
    assert users[1]['username'] == 'u2'
    assert users[1]['admin'] is False
    assert users[1]['last_login'].startswith('2024-01-01')

    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 1, 'total_pages': 1, 'results': [
            {'username': 'u4', 'isAdministrator': True, 'last_seen': '2024-03-03T00:00:00Z'}
        ]},
    ))
    users = ots_manager.list_users()
    assert users[0]['username'] == 'u4'
    assert users[0]['admin'] is True
    assert users[0]['last_login'].startswith('2024-03-03T00:00:00')


def test_list_users_across_multiple_pages(monkeypatch):
    # per_page=10 on the server, 17 total users -> two pages must be fetched and merged
    page1 = DummyResp(status_code=200, data={
        'current_page': 1, 'per_page': 10, 'total': 17, 'total_pages': 2,
        'results': [{'username': f'u{i}', 'admin': False} for i in range(10)],
    })
    page2 = DummyResp(status_code=200, data={
        'current_page': 2, 'per_page': 10, 'total': 17, 'total_pages': 2,
        'results': [{'username': f'u{i}', 'admin': False} for i in range(10, 17)],
    })
    responses = {1: page1, 2: page2}
    requested_pages = []

    def fake_get(url, params=None, timeout=None):
        requested_pages.append(params['page'])
        return responses[params['page']]

    monkeypatch.setattr(ots_manager.session, 'get', fake_get)
    users = ots_manager.list_users()
    assert [u['username'] for u in users] == [f'u{i}' for i in range(17)]
    assert requested_pages == [1, 2]


def test_list_users_warns_on_total_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 9, 'total_pages': 1, 'results': [
            {'username': 'u1', 'admin': False}
        ]},
    ))
    users = ots_manager.list_users()
    assert len(users) == 1
    captured = capsys.readouterr()
    assert 'Warning' in captured.out and '9' in captured.out


def test_get_creator_uid_for_username(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': [
            {'username': 'u1', 'euds': [{'uid': 'EUD-1'}]},
            {'username': 'u2', 'euds': []},
        ]},
    ))
    assert ots_manager.get_creator_uid_for_username('u1') == 'EUD-1'
    assert ots_manager.get_creator_uid_for_username('u2') is None
    assert ots_manager.get_creator_uid_for_username('missing') is None


def test_main_list_users(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_users', lambda: [
        {'username': 'u1', 'admin': True, 'last_login': '2024-01-01T00:00:00+00:00'},
        {'username': 'u2', 'admin': False, 'last_login': None},
    ])
    monkeypatch.setattr(sys, 'argv', ['prog', 'list-users'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Existing users' in captured.out
    assert 'admin=YES' in captured.out
    assert 'last_login=' in captured.out


def test_main_commands(monkeypatch, capsys, tmp_path):
    # list-groups via CLI
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['A','B'])
    monkeypatch.setattr(sys, 'argv', ['prog','list-groups'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Existing groups' in captured.out

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
    # paginated response, single page, plain string results
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': ['X', 'Y']},
    ))
    assert ots_manager.list_groups() == ['X', 'Y']

    # paginated response, dict results (as returned by the real OTS API)
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': [{'name': 'A'}, {'name': 'B'}]},
    ))
    assert ots_manager.list_groups() == ['A', 'B']

    # bare list response (no pagination envelope) is still handled as a single page
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=200, data=['G1', 'G2']))
    assert ots_manager.list_groups() == ['G1', 'G2']


def test_list_groups_across_multiple_pages(monkeypatch):
    # per_page=10 on the server, 16 total groups -> two pages must be fetched and merged
    page1 = DummyResp(status_code=200, data={
        'current_page': 1, 'per_page': 10, 'total': 16, 'total_pages': 2,
        'results': [{'name': f'G{i}'} for i in range(10)],
    })
    page2 = DummyResp(status_code=200, data={
        'current_page': 2, 'per_page': 10, 'total': 16, 'total_pages': 2,
        'results': [{'name': f'G{i}'} for i in range(10, 16)],
    })
    responses = {1: page1, 2: page2}
    requested_pages = []

    def fake_get(url, params=None, timeout=None):
        requested_pages.append(params['page'])
        return responses[params['page']]

    monkeypatch.setattr(ots_manager.session, 'get', fake_get)
    groups = ots_manager.list_groups()
    assert groups == [f'G{i}' for i in range(16)]
    assert requested_pages == [1, 2]


def test_paginate_all_uses_configurable_page_size(monkeypatch):
    # default per_page comes from OTS_PAGE_SIZE (env-configurable), not a hardcoded value
    monkeypatch.setattr(ots_manager, 'OTS_PAGE_SIZE', 250)
    requested_params = []

    def fake_get(url, params=None, timeout=None):
        requested_params.append(params)
        return DummyResp(status_code=200, data={
            'current_page': 1, 'per_page': 250, 'total': 3, 'total_pages': 1,
            'results': ['A', 'B', 'C'],
        })

    monkeypatch.setattr(ots_manager.session, 'get', fake_get)
    items, total = ots_manager._paginate_all(f'{ots_manager.OTS_URL}/api/groups')
    assert items == ['A', 'B', 'C']
    assert total == 3
    assert requested_params == [{'page': 1, 'per_page': 250}]


def test_paginate_all_explicit_per_page_overrides_default(monkeypatch):
    requested_params = []

    def fake_get(url, params=None, timeout=None):
        requested_params.append(params)
        return DummyResp(status_code=200, data={
            'current_page': 1, 'per_page': 5, 'total': 1, 'total_pages': 1,
            'results': ['A'],
        })

    monkeypatch.setattr(ots_manager.session, 'get', fake_get)
    items, _ = ots_manager._paginate_all(f'{ots_manager.OTS_URL}/api/groups', per_page=5)
    assert items == ['A']
    assert requested_params == [{'page': 1, 'per_page': 5}]


def test_list_groups_warns_on_total_mismatch(monkeypatch, capsys):
    # API reports more groups than were actually returned (e.g. pagination stopped early)
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 5, 'total_pages': 1, 'results': ['A', 'B']},
    ))
    groups = ots_manager.list_groups()
    assert groups == ['A', 'B']
    captured = capsys.readouterr()
    assert 'Warning' in captured.out and '5' in captured.out


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
    assert 'Error processing batch file' in captured.out or 'Error' in captured.out


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
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=200, data=Exception('x'), text='raw'))
    assert ots_manager.list_groups() == []
    # non-200 -> returns []
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=500, text='err'))
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


def test_main_qr_command_defaults_to_qrcodes_dir(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: 'QR')
    captured = {}
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda q, o: captured.setdefault('path', o))
    monkeypatch.setattr(sys, 'argv', ['prog', 'qr', '-u', 'piloto1', '--app', 'android'])
    ots_manager.main()
    assert captured['path'] == 'qrcodes/piloto1_android.png'


def test_main_qr_command_respects_explicit_save_qr(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: 'QR')
    captured = {}
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda q, o: captured.setdefault('path', o))
    monkeypatch.setattr(sys, 'argv', ['prog', 'qr', '-u', 'piloto1', '--save-qr', 'custom/out.png'])
    ots_manager.main()
    assert captured['path'] == 'custom/out.png'


def test_main_create_user_single_defaults_to_qrcodes_dir(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'create_user', lambda u, p, e, a: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: 'QR')
    captured = {}
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda q, o: captured.setdefault('path', o))
    monkeypatch.setattr(sys, 'argv', ['prog', 'create-user', '-u', 'piloto1', '-p', 'Pass123!', '--app', 'iphone'])
    ots_manager.main()
    assert captured['path'] == 'qrcodes/piloto1_iphone.png'


def test_main_create_user_single_respects_explicit_save_qr(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'create_user', lambda u, p, e, a: True)
    monkeypatch.setattr(ots_manager, 'get_qr_string', lambda *a, **k: 'QR')
    captured = {}
    monkeypatch.setattr(ots_manager, 'save_qr_code_image', lambda q, o: captured.setdefault('path', o))
    monkeypatch.setattr(sys, 'argv', [
        'prog', 'create-user', '-u', 'piloto1', '-p', 'Pass123!', '--save-qr', 'custom/out.png',
    ])
    ots_manager.main()
    assert captured['path'] == 'custom/out.png'


def test_list_groups_connection_error(monkeypatch):
        def raise_conn(url, params=None, timeout=None):
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
        assert 'No groups found' in captured.out


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
    assert 'Record skipped' in captured.out


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
    assert 'Batch mode' in captured.out
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
    assert 'Batch mode' not in captured.out


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
    assert 'Error processing batch deletion file' in captured.out


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
    assert 'Error processing batch deactivation file' in captured.out


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
    assert 'Error processing batch activation file' in captured.out


def test_run_module_main_executes_main(monkeypatch):
        import runpy
        monkeypatch.setattr(sys, 'argv', ['prog'])
        with pytest.raises(SystemExit):
            runpy.run_module('ots_manager', run_name='__main__')


# ---------------------------------------------------------------------------
# delete_group()
# ---------------------------------------------------------------------------

def test_delete_group_variants(monkeypatch):
    captured = {}

    def fake_delete(url, params=None, headers=None):
        captured['params'] = params
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'delete', fake_delete)
    assert ots_manager.delete_group('G1') is True
    assert captured['params'] == {'group_name': 'G1'}

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.delete_group('G1') is True

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=400, text='The __ANON__ group cannot be deleted'))
    assert ots_manager.delete_group('__ANON__') is False


def test_main_delete_group(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    calls = []
    monkeypatch.setattr(ots_manager, 'delete_group', lambda name: calls.append(name) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'delete-group', '-n', 'G1'])
    ots_manager.main()
    assert calls == ['G1']


# ---------------------------------------------------------------------------
# get_groups_with_ids() / resolve_group_ids()
# ---------------------------------------------------------------------------

def test_get_groups_with_ids(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': [
            {'id': 1, 'name': 'A'},
            {'id': 2, 'name': 'B'},
        ]},
    ))
    assert ots_manager.get_groups_with_ids() == [{'id': 1, 'name': 'A'}, {'id': 2, 'name': 'B'}]


def test_resolve_group_ids(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_groups_with_ids', lambda: [
        {'id': 1, 'name': 'A'}, {'id': 2, 'name': 'B'},
    ])
    ids, missing = ots_manager.resolve_group_ids(['A', 'B'])
    assert ids == [1, 2]
    assert missing == []

    ids, missing = ots_manager.resolve_group_ids(['A', 'Ghost'])
    assert ids == [1]
    assert missing == ['Ghost']


# ---------------------------------------------------------------------------
# create_mission() / delete_mission() / list_missions()
# ---------------------------------------------------------------------------

def test_create_mission_minimal(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    assert ots_manager.create_mission('Op1', 'EUD-1') is True
    assert captured['payload'] == {'name': 'Op1', 'creator_uid': 'EUD-1'}


def test_create_mission_with_optional_fields(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=201)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    ok = ots_manager.create_mission(
        'Op2', 'EUD-1',
        description='desc', tool='public', classification='UNCLASS',
        default_role='MISSION_SUBSCRIBER', password='secret', keywords=['a', 'b'],
        chat_room='room1', base_layer='osm', bbox='1,2,3,4', path='/ops',
        invite_only=True, expiration=1234567890,
    )
    assert ok is True
    payload = captured['payload']
    assert payload['description'] == 'desc'
    assert payload['tool'] == 'public'
    assert payload['classification'] == 'UNCLASS'
    assert payload['default_role'] == 'MISSION_SUBSCRIBER'
    assert payload['password'] == 'secret'
    assert payload['keywords'] == ['a', 'b']
    assert payload['chat_room'] == 'room1'
    assert payload['base_layer'] == 'osm'
    assert payload['bbox'] == '1,2,3,4'
    assert payload['path'] == '/ops'
    assert payload['invite_only'] is True
    assert payload['expiration'] == 1234567890


def test_create_mission_resolves_groups(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    monkeypatch.setattr(ots_manager, 'resolve_group_ids', lambda names: ([1, 2], []))
    assert ots_manager.create_mission('Op3', 'EUD-1', groups=['CSAR', 'Rescue']) is True
    assert captured['payload']['groups'] == [1, 2]


def test_create_mission_expands_all_groups(monkeypatch):
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['A', 'B', 'C'])
    resolved_with = {}

    def fake_resolve(names):
        resolved_with['names'] = names
        return ([1, 2, 3], [])

    monkeypatch.setattr(ots_manager, 'resolve_group_ids', fake_resolve)
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=200))
    assert ots_manager.create_mission('Op4', 'EUD-1', groups=['ALL']) is True
    assert resolved_with['names'] == ['A', 'B', 'C']


def test_create_mission_missing_group_aborts(monkeypatch):
    monkeypatch.setattr(ots_manager, 'resolve_group_ids', lambda names: ([], ['Ghost']))
    posted = []
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: posted.append(1) or DummyResp(status_code=200))
    assert ots_manager.create_mission('Op5', 'EUD-1', groups=['Ghost']) is False
    assert posted == []


def test_create_mission_error(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.create_mission('Op6', 'EUD-1') is False


def test_delete_mission_variants(monkeypatch):
    captured = {}

    def fake_delete(url, params=None, headers=None):
        captured['params'] = params
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'delete', fake_delete)
    assert ots_manager.delete_mission('Op1') is True
    assert captured['params'] == {'name': 'Op1'}

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.delete_mission('Op1') is True

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.delete_mission('Op1') is False


def test_list_missions(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 2, 'total_pages': 1, 'results': [
            {'name': 'Op1'}, {'name': 'Op2'},
        ]},
    ))
    assert ots_manager.list_missions() == ['Op1', 'Op2']


def test_list_missions_empty(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.list_missions() == []


def test_list_missions_string_entries_and_total_warning(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'current_page': 1, 'per_page': 100, 'total': 5, 'total_pages': 1, 'results': ['Op1', 'Op2']},
    ))
    assert ots_manager.list_missions() == ['Op1', 'Op2']
    captured = capsys.readouterr()
    assert 'Warning' in captured.out and '5' in captured.out


def test_main_list_users_no_results(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_users', lambda: [])
    monkeypatch.setattr(sys, 'argv', ['prog', 'list-users'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'No users found' in captured.out


# ---------------------------------------------------------------------------
# CLI wiring: create-mission / delete-mission / list-missions
# ---------------------------------------------------------------------------

def test_main_create_mission_with_creator_uid(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    captured = {}

    def fake_create_mission(name, creator_uid, **kwargs):
        captured['name'] = name
        captured['creator_uid'] = creator_uid
        captured['kwargs'] = kwargs
        return True

    monkeypatch.setattr(ots_manager, 'create_mission', fake_create_mission)
    monkeypatch.setattr(sys, 'argv', [
        'prog', 'create-mission', '-n', 'Op1', '--creator-uid', 'EUD-1',
        '-g', 'CSAR', 'Rescue', '--description', 'desc', '--invite-only',
    ])
    ots_manager.main()
    assert captured['name'] == 'Op1'
    assert captured['creator_uid'] == 'EUD-1'
    assert captured['kwargs']['groups'] == ['CSAR', 'Rescue']
    assert captured['kwargs']['description'] == 'desc'
    assert captured['kwargs']['invite_only'] is True


def test_main_create_mission_with_creator_username(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'get_creator_uid_for_username', lambda u: 'EUD-RESOLVED')
    captured = {}

    def fake_create_mission(name, creator_uid, **kwargs):
        captured['creator_uid'] = creator_uid
        return True

    monkeypatch.setattr(ots_manager, 'create_mission', fake_create_mission)
    monkeypatch.setattr(sys, 'argv', ['prog', 'create-mission', '-n', 'Op1', '--creator-username', 'organizador'])
    ots_manager.main()
    assert captured['creator_uid'] == 'EUD-RESOLVED'


def test_main_create_mission_creator_username_not_found(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'get_creator_uid_for_username', lambda u: None)
    monkeypatch.setattr(sys, 'argv', ['prog', 'create-mission', '-n', 'Op1', '--creator-username', 'ghost'])
    with pytest.raises(SystemExit) as exc_info:
        ots_manager.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert 'ghost' in captured.out


def test_main_create_mission_uid_and_username_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', [
        'prog', 'create-mission', '-n', 'Op1',
        '--creator-uid', 'EUD-1', '--creator-username', 'organizador',
    ])
    with pytest.raises(SystemExit):
        ots_manager.main()


def test_main_delete_mission(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    calls = []
    monkeypatch.setattr(ots_manager, 'delete_mission', lambda name: calls.append(name) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'delete-mission', '-n', 'Op1'])
    ots_manager.main()
    assert calls == ['Op1']


def test_main_list_missions(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_missions', lambda: ['Op1', 'Op2'])
    monkeypatch.setattr(sys, 'argv', ['prog', 'list-missions'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Existing missions' in captured.out
    assert 'Op1' in captured.out and 'Op2' in captured.out


def test_main_list_missions_empty(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(ots_manager, 'list_missions', lambda: [])
    monkeypatch.setattr(sys, 'argv', ['prog', 'list-missions'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'No missions found' in captured.out


# ---------------------------------------------------------------------------
# remove_user_from_group() / get_user_group_memberships()
# ---------------------------------------------------------------------------

def test_remove_user_from_group_variants(monkeypatch):
    captured = {}

    def fake_delete(url, params=None, headers=None):
        captured['params'] = params
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'delete', fake_delete)
    assert ots_manager.remove_user_from_group('u1', 'G1', 'in') is True
    assert captured['params'] == {'username': 'u1', 'group_name': 'G1', 'direction': 'IN'}

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.remove_user_from_group('u1', 'G1', 'OUT') is True

    monkeypatch.setattr(ots_manager.session, 'delete', lambda url, params=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.remove_user_from_group('u1', 'G1', 'IN') is False


def test_get_user_group_memberships_variants(monkeypatch):
    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(
        status_code=200,
        data={'success': True, 'results': [
            {'group_name': 'CSAR', 'direction': 'IN', 'active': True},
            {'group_name': 'CSAR', 'direction': 'OUT', 'active': True},
        ]},
    ))
    memberships = ots_manager.get_user_group_memberships('u1')
    assert memberships == [
        {'group_name': 'CSAR', 'direction': 'IN', 'active': True},
        {'group_name': 'CSAR', 'direction': 'OUT', 'active': True},
    ]

    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=404, text='not found'))
    assert ots_manager.get_user_group_memberships('ghost') == []

    monkeypatch.setattr(ots_manager.session, 'get', lambda url, params=None, timeout=None: DummyResp(status_code=200, data=Exception('bad json'), text='raw'))
    assert ots_manager.get_user_group_memberships('u1') == []

    def raise_conn(url, params=None, timeout=None):
        raise Exception('conn')
    monkeypatch.setattr(ots_manager.session, 'get', raise_conn)
    assert ots_manager.get_user_group_memberships('u1') == []


# ---------------------------------------------------------------------------
# sync_user_groups()
# ---------------------------------------------------------------------------

def test_sync_user_groups_adds_and_removes(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [
        {'group_name': 'Old', 'direction': 'IN'},
        {'group_name': 'Keep', 'direction': 'IN'},
    ])
    added = []
    removed = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: added.append((g, direction)) or True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: removed.append((g, direction)) or True)

    ok = ots_manager.sync_user_groups('u1', ['Keep:IN', 'New:OUT'])
    assert ok is True
    assert added == [('New', 'OUT')]
    assert removed == [('Old', 'IN')]


def test_sync_user_groups_both_direction_expands(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [])
    added = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: added.append((g, direction)) or True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: True)

    ots_manager.sync_user_groups('u1', ['CSAR'])
    assert sorted(added) == [('CSAR', 'IN'), ('CSAR', 'OUT')]


def test_sync_user_groups_all_expands_to_every_group(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [])
    monkeypatch.setattr(ots_manager, 'list_groups', lambda: ['A', 'B'])
    added = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: added.append((g, direction)) or True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: True)

    ots_manager.sync_user_groups('u1', ['ALL'])
    assert sorted(added) == [('A', 'IN'), ('A', 'OUT'), ('B', 'IN'), ('B', 'OUT')]


def test_sync_user_groups_empty_list_removes_everything(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [
        {'group_name': 'A', 'direction': 'IN'},
        {'group_name': 'A', 'direction': 'OUT'},
    ])
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: True)
    removed = []
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: removed.append((g, direction)) or True)

    ots_manager.sync_user_groups('u1', [])
    assert sorted(removed) == [('A', 'IN'), ('A', 'OUT')]


def test_sync_user_groups_no_changes_needed(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [
        {'group_name': 'A', 'direction': 'IN'},
    ])
    calls = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: calls.append('add') or True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: calls.append('remove') or True)

    ok = ots_manager.sync_user_groups('u1', ['A:IN'])
    assert ok is True
    assert calls == []


def test_sync_user_groups_propagates_failure(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [])
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: False)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: True)
    assert ots_manager.sync_user_groups('u1', ['A:IN']) is False


def test_sync_user_groups_propagates_removal_failure(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [{'group_name': 'A', 'direction': 'IN'}])
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: False)
    assert ots_manager.sync_user_groups('u1', []) is False


def test_sync_user_groups_skips_invalid_entry(monkeypatch):
    monkeypatch.setattr(ots_manager, 'get_user_group_memberships', lambda u: [])
    calls = []
    monkeypatch.setattr(ots_manager, 'add_user_to_group', lambda u, g, direction: calls.append((g, direction)) or True)
    monkeypatch.setattr(ots_manager, 'remove_user_from_group', lambda u, g, direction: True)

    # a non-string, non-dict entry has no resolvable group name and is skipped
    ots_manager.sync_user_groups('u1', [123, 'A'])
    assert sorted(calls) == [('A', 'IN'), ('A', 'OUT')]


# ---------------------------------------------------------------------------
# reset_user_password() / set_user_admin()
# ---------------------------------------------------------------------------

def test_reset_user_password_variants(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    assert ots_manager.reset_user_password('u1', 'NovaSenha123!') is True
    assert captured['payload'] == {'username': 'u1', 'new_password': 'NovaSenha123!'}

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=400, text='err'))
    assert ots_manager.reset_user_password('u1', 'x') is False


def test_set_user_admin_variants(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None):
        captured['payload'] = json
        return DummyResp(status_code=200)

    monkeypatch.setattr(ots_manager.session, 'post', fake_post)
    assert ots_manager.set_user_admin('u1', True) is True
    assert captured['payload'] == {'username': 'u1', 'roles': ['administrator']}

    assert ots_manager.set_user_admin('u1', False) is True
    assert captured['payload'] == {'username': 'u1', 'roles': ['user']}

    monkeypatch.setattr(ots_manager.session, 'post', lambda url, json=None, headers=None: DummyResp(status_code=500, text='err'))
    assert ots_manager.set_user_admin('u1', True) is False


# ---------------------------------------------------------------------------
# update_user() / process_batch_update()
# ---------------------------------------------------------------------------

def test_update_user_applies_only_provided_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(ots_manager, 'reset_user_password', lambda u, p: calls.append(('password', p)) or True)
    monkeypatch.setattr(ots_manager, 'set_user_admin', lambda u, a: calls.append(('admin', a)) or True)
    monkeypatch.setattr(ots_manager, 'sync_user_groups', lambda u, g: calls.append(('groups', g)) or True)

    assert ots_manager.update_user('u1') is True
    assert calls == []

    calls.clear()
    assert ots_manager.update_user('u1', password='NewPass1!') is True
    assert calls == [('password', 'NewPass1!')]

    calls.clear()
    assert ots_manager.update_user('u1', is_admin=False) is True
    assert calls == [('admin', False)]

    calls.clear()
    assert ots_manager.update_user('u1', groups=['A', 'B']) is True
    assert calls == [('groups', ['A', 'B'])]

    calls.clear()
    assert ots_manager.update_user('u1', password='p', is_admin=True, groups=[]) is True
    assert calls == [('password', 'p'), ('admin', True), ('groups', [])]


def test_update_user_propagates_partial_failure(monkeypatch):
    monkeypatch.setattr(ots_manager, 'reset_user_password', lambda u, p: True)
    monkeypatch.setattr(ots_manager, 'set_user_admin', lambda u, a: False)
    monkeypatch.setattr(ots_manager, 'sync_user_groups', lambda u, g: True)
    assert ots_manager.update_user('u1', password='p', is_admin=True, groups=['A']) is False


def test_update_user_propagates_password_failure(monkeypatch):
    monkeypatch.setattr(ots_manager, 'reset_user_password', lambda u, p: False)
    assert ots_manager.update_user('u1', password='p') is False


def test_update_user_propagates_groups_failure(monkeypatch):
    monkeypatch.setattr(ots_manager, 'sync_user_groups', lambda u, g: False)
    assert ots_manager.update_user('u1', groups=['A']) is False


def test_process_batch_update(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ots_manager, 'update_user', lambda u, password=None, groups=None, is_admin=None: calls.append((u, password, groups, is_admin)) or (u != 'bad'))
    data = [
        'u1',
        {'username': 'u2', 'password': 'NewPass1!'},
        {'username': 'u3', 'groups': ['A:IN'], 'administrator': True},
        {'username': 'bad'},
    ]
    out_file = tmp_path / 'update.json'
    results = ots_manager.process_batch_update(data, output_summary_file=str(out_file))
    assert calls == [
        ('u1', None, None, None),
        ('u2', 'NewPass1!', None, None),
        ('u3', None, ['A:IN'], True),
        ('bad', None, None, None),
    ]
    assert results == [
        {'username': 'u1', 'updated': True},
        {'username': 'u2', 'updated': True},
        {'username': 'u3', 'updated': True},
        {'username': 'bad', 'updated': False},
    ]
    assert out_file.exists()
    assert json.loads(out_file.read_text(encoding='utf-8')) == results


def test_process_batch_update_skips_missing_username(capsys):
    data = [{'password': 'no-username'}, 123]
    results = ots_manager.process_batch_update(data)
    assert results == []
    captured = capsys.readouterr()
    assert 'Record skipped' in captured.out


def test_process_batch_update_no_output(monkeypatch):
    monkeypatch.setattr(ots_manager, 'update_user', lambda u, password=None, groups=None, is_admin=None: True)
    results = ots_manager.process_batch_update(['u1'])
    assert results == [{'username': 'u1', 'updated': True}]


# ---------------------------------------------------------------------------
# CLI wiring: update-user
# ---------------------------------------------------------------------------

def test_main_update_user_single_all_fields(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    captured = {}

    def fake_update_user(username, password=None, groups=None, is_admin=None):
        captured['username'] = username
        captured['password'] = password
        captured['groups'] = groups
        captured['is_admin'] = is_admin
        return True

    monkeypatch.setattr(ots_manager, 'update_user', fake_update_user)
    monkeypatch.setattr(sys, 'argv', [
        'prog', 'update-user', '-u', 'u1', '-p', 'NewPass1!',
        '-g', 'CSAR:IN', 'Rescue', '--admin',
    ])
    ots_manager.main()
    assert captured['username'] == 'u1'
    assert captured['password'] == 'NewPass1!'
    assert captured['groups'] == ['CSAR:IN', 'Rescue']
    assert captured['is_admin'] is True


def test_main_update_user_no_admin_flag(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    captured = {}
    monkeypatch.setattr(ots_manager, 'update_user', lambda u, password=None, groups=None, is_admin=None: captured.setdefault('is_admin', is_admin) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1', '--no-admin'])
    ots_manager.main()
    assert captured['is_admin'] is False


def test_main_update_user_groups_omitted_vs_empty(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    captured = {}
    monkeypatch.setattr(ots_manager, 'update_user', lambda u, password=None, groups=None, is_admin=None: captured.setdefault('groups', groups) or True)

    # -g omitted entirely -> groups stays None (don't touch group memberships)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1'])
    ots_manager.main()
    assert captured['groups'] is None

    # -g passed with no values -> groups is [] (explicitly clear all memberships)
    captured.clear()
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1', '-g'])
    ots_manager.main()
    assert captured['groups'] == []


def test_main_update_user_no_flags_is_noop_call(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    captured = {}
    monkeypatch.setattr(ots_manager, 'update_user', lambda u, password=None, groups=None, is_admin=None: captured.update(password=password, groups=groups, is_admin=is_admin) or True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1'])
    ots_manager.main()
    assert captured == {'password': None, 'groups': None, 'is_admin': None}


def test_main_update_user_batch(monkeypatch, tmp_path):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    called = {}

    def fake_process_batch_update(data, output_summary_file=None):
        called['data'] = data
        called['out'] = output_summary_file

    monkeypatch.setattr(ots_manager, 'process_batch_update', fake_process_batch_update)
    f = tmp_path / 'users.json'
    f.write_text(json.dumps([{'username': 'u1', 'password': 'NewPass1!'}]), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-f', str(f), '-o', 'out.json'])
    ots_manager.main()
    assert called['data'] == [{'username': 'u1', 'password': 'NewPass1!'}]
    assert called['out'] == 'out.json'


def test_main_update_user_batch_file_error(monkeypatch, capsys):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-f', 'nope.json'])
    ots_manager.main()
    captured = capsys.readouterr()
    assert 'Error processing batch update file' in captured.out


def test_main_update_user_requires_username_or_file(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user'])
    with pytest.raises(SystemExit):
        ots_manager.main()


def test_main_update_user_username_and_file_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1', '-f', 'file.json'])
    with pytest.raises(SystemExit):
        ots_manager.main()


def test_main_update_user_admin_and_no_admin_mutually_exclusive(monkeypatch):
    monkeypatch.setattr(ots_manager, 'login', lambda: True)
    monkeypatch.setattr(sys, 'argv', ['prog', 'update-user', '-u', 'u1', '--admin', '--no-admin'])
    with pytest.raises(SystemExit):
        ots_manager.main()
