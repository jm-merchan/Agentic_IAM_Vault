"""The explanatory matrix must agree with the existing OBO user/task limits."""
import time

import pytest

from app.i18n import Translator
from app.permission_matrix import AGENTS, PROFILES, current_profile, decisions, summary
from app.security import Session

CONFIG = {'runtime': {'groups': {'readonly': ['r'], 'readwrite': ['w'], 'sensitive': ['s']}}}


@pytest.mark.parametrize('profile,expected', [
    ('reader', [{'read'}, {'read'}, {'read'}, {'read'}]),
    ('writer', [{'read', 'write'}, {'read'}, {'read', 'write'}, {'read'}]),
    ('supervisor', [{'read', 'reveal'}, {'read'}, {'read'}, {'read', 'reveal'}]),
])
def test_twelve_documented_combinations(profile, expected):
    for mode, allowed in zip(AGENTS, expected):
        actual = decisions(PROFILES[profile][1], mode)
        assert {row['operation'] for row in actual if row['expected']} == allowed


def test_reader_reveal_explains_user_denial_and_supervisor_read_agent_denial():
    reader = {row['operation']: row for row in decisions(PROFILES['reader'][1], 'reveal')}
    assert reader['reveal']['agent'] and not reader['reveal']['user'] and not reader['reveal']['expected']
    supervisor = {row['operation']: row for row in decisions(PROFILES['supervisor'][1], 'read')}
    assert supervisor['reveal']['user'] and not supervisor['reveal']['agent'] and not supervisor['reveal']['expected']


@pytest.mark.parametrize('groups,key,operations', [
    (['r'], 'reader', {'read'}), (['w'], 'writer', {'read', 'write'}),
    (['s'], 'supervisor', {'read', 'reveal'}),
    (['r', 'w', 's'], 'session', {'read', 'write', 'reveal'}),
    (['unknown'], 'session', set()),
])
def test_current_profile_uses_groups_even_if_display_name_says_supervisor(groups, key, operations):
    session = Session('test', subject='user', name='Supervisor', groups=groups, expires_at=time.time()+60)
    profile = current_profile(CONFIG, session)
    assert profile[0] == key and profile[2] == operations


def test_missing_expired_or_pending_login_never_highlights_reader_as_authenticated():
    assert current_profile(CONFIG, None) is None
    assert current_profile(CONFIG, Session('expired', subject='user', groups=['r'])) is None
    assert current_profile(CONFIG, Session('pending', groups=['r'], expires_at=time.time()+60)) is None


def test_unknown_agent_does_not_display_legacy_permissions():
    assert not any(row['expected'] for row in decisions(PROFILES['supervisor'][1], 'unknown'))


def test_comparison_preserves_session_and_translates_summary():
    session = Session('test', subject='user', groups=['r'], task_agent='reveal', expires_at=time.time()+60)
    original = vars(session).copy()
    profile = current_profile(CONFIG, session)
    assert summary(profile[2], 'reveal', Translator('en')) == 'View'
    assert summary(PROFILES['writer'][1], 'write', Translator('en')) == 'View and create'
    assert summary(PROFILES['supervisor'][1], 'reveal', Translator('es')) == 'Consultar y revelar'
    assert vars(session) == original
