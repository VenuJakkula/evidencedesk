import json
import pytest
from app.core import Store
from app.questionnaires import Questionnaires
from app.workbooks import Mapping
from scripts.browser_fixture import reset
from scripts.sample_workbooks import template


def test_browser_reset_is_owned_scoped_and_keeps_schema(tmp_path):
    root = tmp_path / 'evidencedesk-browser-fixture'
    root.mkdir()
    (root / '.browser-fixture.json').write_text(json.dumps({'database': 'browser.db', 'purpose': 'synthetic-browser-tests'}))
    store = Store(root / 'browser.db')
    store.add_document('a', 'Synthetic policy', 'Customer data is encrypted at rest using AES-256.', '1', '2099-01-01')
    service = Questionnaires(store)
    data, mapping = template()
    questionnaire = service.create('a', data, 'security.xlsx', Mapping.model_validate(mapping), 'fixture')
    service.draft('a', questionnaire['id'])
    service.approve('a', service.items('a', questionnaire['id'])['items'][0]['id'], 1, 'test')
    service.export('a', questionnaire['id'])
    unrelated = Store(tmp_path / 'unrelated.db')
    unrelated.add_document('other', 'Keep me', 'Unrelated test evidence', '1', '2099-01-01')
    reset(root)
    with store.connect() as db:
        for table in ('questionnaire_exports', 'questionnaire_approvals', 'answer_revisions', 'questionnaire_items',
                      'questionnaires', 'workbook_assets', 'answers', 'documents'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 3
    with unrelated.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 1
    assert service.create('a', data, 'security.xlsx', Mapping.model_validate(mapping), 'fresh')['total'] == 5


def test_browser_reset_refuses_unowned_directories_before_changing_data(tmp_path):
    root = tmp_path / 'user-workspace'
    root.mkdir()
    store = Store(root / 'browser.db')
    store.add_document('user', 'Preserved', 'Keep existing evidence', '1', '2099-01-01')
    (root / '.browser-fixture.json').write_text(json.dumps({'database': 'browser.db', 'purpose': 'synthetic-browser-tests'}))
    with pytest.raises(ValueError, match='harness-owned'):
        reset(root)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 1
    owned_name = tmp_path / 'evidencedesk-browser-wrong-marker'
    owned_name.mkdir()
    (owned_name / '.browser-fixture.json').write_text(json.dumps({'database': 'other.db'}))
    with pytest.raises(ValueError, match='ownership marker'):
        reset(owned_name)
    assert not (owned_name / 'browser.db').exists()
