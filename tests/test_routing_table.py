"""The routing table is generated from the policy and obeys it."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = yaml.safe_load((ROOT / 'config/routing-policy.yaml').read_text())
TABLE = json.loads((ROOT / 'config/routing-table.json').read_text())
ALLOWED = {m['openrouter'] for m in POLICY['allowed_models']}


def test_table_is_up_to_date():
    r = subprocess.run([sys.executable, 'scripts/build_routing_table.py', '--check'], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_pick_is_an_allowed_servable_model():
    for row in TABLE['rows'].values():
        for pick in ('best', 'efficient', 'economy', 'escalated'):
            assert row[pick]['model'] in ALLOWED and row[pick]['model'] in TABLE['models']


def test_escalation_is_opus_5_5_on_every_row():
    assert {r['escalated']['model'] for r in TABLE['rows'].values()} == {'anthropic/claude-opus-5.5'}


def test_efficient_stays_in_the_pool_and_near_the_top():
    for row in TABLE['rows'].values():
        assert row['efficient'] in row['pool'] and row['top'] == row['pool'][0]
        assert row['top']['score'] - row['efficient']['score'] <= POLICY['efficient_within_points']
        assert row['efficient']['cost_per_test'] <= row['best']['cost_per_test']


def test_every_practice_area_has_a_row_and_unknown_work_has_overall():
    areas = json.loads((ROOT / 'config/questions.json').read_text())['questions']['practice_area']['criteria']
    assert set(POLICY['line_of_practice_area']) == set(areas)
    assert POLICY['line_of_practice_area']['other'] == 'overall' and 'overall' in TABLE['rows']


def test_best_knows_the_law():
    """Best serves research and advice, so it must pass the Artificial Analysis law gate."""
    assert set(TABLE['knows_law']) <= ALLOWED
    for name, row in TABLE['rows'].items():
        assert row['best']['model'] in TABLE['knows_law'], name
    assert 'meta/muse-wonder' not in TABLE['knows_law'] and 'google/gemini-4-hydrogen' not in TABLE['knows_law']


def test_economy_is_cheapest_near_the_top_without_more_tokens_than_it():
    vals = json.loads((ROOT / POLICY['benchmark']).read_text())['lines']
    tokens = {m['vals_id']: vals['overall'][m['vals_id']]['tokens_per_test'] for m in TABLE['models'].values()}
    for name, row in TABLE['rows'].items():
        ok = [m for m in tokens if vals[name][m]['accuracy'] >= row['top']['score'] - POLICY['economy_within_points']
              and tokens[m] <= tokens[row['top']['vals_id']]]
        cheapest = min([row['best']['cost_per_test'], *(round(vals[name][m]['cost_per_test'], 2) for m in ok)])
        assert row['economy']['cost_per_test'] == cheapest <= row['best']['cost_per_test'], name
        assert row['economy']['model'] != 'google/gemini-4-hydrogen'


def test_savings_estimate_runs_offline():
    r = subprocess.run([sys.executable, 'scripts/estimate_savings.py'], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and '195 requests' in r.stdout, r.stdout + r.stderr
