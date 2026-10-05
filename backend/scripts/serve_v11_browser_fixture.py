"""Isolated browser acceptance server; controlled provider only, zero model requests."""
import json
import sys
from pathlib import Path
import argparse
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'tests')]
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Base
from app.config import Settings
from app.agent import work_once
from test_m21 import ScanProvider
import uvicorn

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', type=Path, required=True)
args = parser.parse_args()
if args.database.exists():
    raise SystemExit('Refuse to replace an existing fixture database')
app = create_app(Settings(_env_file=None, database_url='sqlite:///' + str(args.database.resolve()),
      csrf_secret='v11-browser-fixture-secret-with-32-characters', llm_provider='deepseek', deepseek_api_key='',
      allowed_origins=['http://127.0.0.1:4181'], rate_limit=100))
Base.metadata.create_all(app.state.engine)
with TestClient(app) as client:
    client.headers.update({'Origin': 'http://127.0.0.1:4181', 'X-CSRF-Token': client.get('/api/v1/csrf').json()['token']})
    me = client.post('/api/v1/registrations', json={'email': 'v11-browser@example.test', 'password': 'local-test-password', 'display_name': '本地验收'}).json()
    request = {'schema_version': '1', 'mode': 'analyze', 'question': 'V1.1本地受控验收：核查全部异常', 'session_id': None, 'parent_run_id': None,
               'context': {'snapshot_set_id': None, 'item_ids': [], 'department_ids': [], 'analysis_id': None}, 'options': {'window_days': 14, 'focus': 'risk_scan'}}
    result = client.post('/api/v1/projects/' + me['projects'][0]['id'] + '/runs', json=request, headers={'Idempotency-Key': 'v11-browser-fixture'}).json()
    work_once(app.state.factory, app.state.settings, ScanProvider())
    assert client.get('/api/v1/runs/' + result['run_id']).json()['status'] == 'succeeded'
print('Browser fixture only: controlled provider; no real model calls; http://127.0.0.1:8011', flush=True)
uvicorn.run(app, host='127.0.0.1', port=8011)
