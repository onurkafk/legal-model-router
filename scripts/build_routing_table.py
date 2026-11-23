"""Build the routing table: config/routing-policy.yaml joined with the Vals Legal Index.

Writes config/routing-table.json (read by the router) and config/routing-table.md (read by a
person). No network: both inputs are snapshots under benchmarks/.

    python scripts/build_routing_table.py           build both files
    python scripts/build_routing_table.py --check   exit 1 if either file is stale
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'config/routing-policy.yaml'
OUT_JSON = ROOT / 'config/routing-table.json'
OUT_MD = ROOT / 'config/routing-table.md'
# The package ships its own copies, so `pip install legal-router` needs nothing from the repo.
PKG_TABLE = ROOT / 'legal_router/data/routing-table.json'
PKG_CRITERIA = ROOT / 'legal_router/data/questions.json'
CRITERIA = ROOT / 'config/questions.json'
ROWS = ['overall', 'business_commercial', 'civil_negligence', 'other_civil', 'real_estate',
        'labor_employment', 'wills_estates_trusts', 'family', 'criminal', 'tax_agent_bench']
LABEL = {'overall': 'Overall (line unknown)', 'business_commercial': 'Business & Commercial',
         'civil_negligence': 'Civil Negligence', 'other_civil': 'Other Civil', 'real_estate': 'Real Estate',
         'labor_employment': 'Labor & Employment', 'wills_estates_trusts': 'Wills, Estates & Trusts',
         'family': 'Family', 'criminal': 'Criminal', 'tax_agent_bench': 'Tax'}


def servable(policy: dict, snapshot: dict) -> tuple[dict, dict]:
    """Allowed models that OpenRouter can serve under zero data retention, keyed by Vals id."""
    zdr = {m for m, _ in snapshot['zdr_endpoints']}
    ok, dropped = {}, {}
    for m in policy['allowed_models']:
        if m['vals'] in policy['denied']:
            raise SystemExit(f"{m['vals']} is both allowed and denied")
        if m['openrouter'] not in zdr:
            dropped[m['vals']] = f"no zero-data-retention endpoint for {m['openrouter']}"
        else:
            ok[m['vals']] = m
    return ok, dropped


def row(scores: dict, models: dict, policy: dict, knows_law: set, tokens: dict) -> dict:
    ranked = sorted(((v, s) for v, s in scores.items() if v in models),
                    key=lambda vs: (-vs[1]['accuracy'], vs[1]['cost_per_test']))
    if not ranked:
        raise SystemExit('no allowed model has a score on this row')
    pool = ranked[:policy['top_k']]
    top = pool[0][1]['accuracy']

    def cheapest(cands, within):
        return min((vs for vs in cands if vs[1]['accuracy'] >= top - within), key=lambda vs: vs[1]['cost_per_test'])

    lawful = [vs for vs in ranked if vs[0] in knows_law]
    if not lawful:
        raise SystemExit('no allowed model passes law_gate')
    first = lawful[0]
    near = min((vs for vs in lawful if vs[1]['accuracy'] >= first[1]['accuracy'] - policy['best_within_points']),
               key=lambda vs: vs[1]['cost_per_test'])
    saving = 1 - near[1]['cost_per_test'] / first[1]['cost_per_test']
    best = near if saving >= policy['best_min_saving'] else first
    esc = policy['escalation_model']

    def entry(v, s):
        return {'model': models[v]['openrouter'], 'effort': models[v]['effort'], 'vals_id': v,
                'score': round(s['accuracy'], 2), 'cost_per_test': round(s['cost_per_test'], 2),
                'tokens_per_test_m': round(tokens[v] / 1e6, 2)}

    return {
        'pool': [entry(v, s) for v, s in pool],
        'top': entry(*pool[0]),
        'best': entry(*best),
        'efficient': entry(*cheapest(pool, policy['efficient_within_points'])),
        'economy': entry(*min((vs for vs in ranked if vs[1]['accuracy'] >= top - policy['economy_within_points']
                               and tokens[vs[0]] <= tokens[pool[0][0]]),
                              key=lambda vs: (vs[1]['cost_per_test'], tokens[vs[0]]))),
        'escalated': entry(esc, scores[esc]) if esc in scores else {'model': models[esc]['openrouter']},
    }


def build() -> tuple[str, str]:
    policy = yaml.safe_load(POLICY.read_text())
    vals = json.loads((ROOT / policy['benchmark']).read_text())
    snapshot = json.loads((ROOT / policy['servable']).read_text())
    models, dropped = servable(policy, snapshot)
    aa = json.loads((ROOT / policy['capabilities']).read_text())['models']
    # Vals publishes tokens per task for the overall index only; it stands for the model on every line.
    tokens = {v: r['tokens_per_test'] for v, r in vals['lines']['overall'].items()}
    gate = policy['law_gate']
    knows_law = {v for v in models if (aa.get(v, {}).get('legal_knowledge') or 0) >= gate['min_legal_knowledge']
                 and (aa.get(v, {}).get('non_hallucination') or 0) >= gate['min_non_hallucination']}
    if policy['escalation_model'] not in models:
        raise SystemExit(f"escalation model {policy['escalation_model']} is not servable")
    if policy['default_classifier'] not in policy['classifiers']:
        raise SystemExit(f"default classifier {policy['default_classifier']} is not listed")
    missing = set(policy['line_of_practice_area'].values()) - set(ROWS)
    if missing:
        raise SystemExit(f'unknown rows: {missing}')
    table = {
        '_comment': 'GENERATED by scripts/build_routing_table.py from config/routing-policy.yaml. Do not edit.',
        'version': 'routing-table',
        'benchmark_updated': vals['benchmark_updated'],
        'models': {m['openrouter']: {'effort': m['effort'], 'vals_id': v} for v, m in models.items()},
        'dropped': dropped | policy.get('unservable', {}),
        'line_of_practice_area': policy['line_of_practice_area'],
        'classifiers': policy['classifiers'],
        'default_classifier': policy['default_classifier'],
        'rules': policy['rules'],
        'knows_law': sorted(models[v]['openrouter'] for v in knows_law),
        'rows': {r: row(vals['lines'][r], models, policy, knows_law, tokens) for r in ROWS},
    }
    return json.dumps(table, indent=1) + '\n', markdown(table, policy)


def markdown(t: dict, policy: dict) -> str:
    short = lambda e: f"{e['model'].split('/')[1]} {e.get('score', '')} · ${e.get('cost_per_test', '?')} · {e.get('tokens_per_test_m', '?')}M tok"  # noqa: E731
    out = [f"# Where the Legal Model Router sends work (generated, Vals Legal Index {t['benchmark_updated']})", '',
           'Generated by `scripts/build_routing_table.py` from `config/routing-policy.yaml`. Edit the policy, '
           'not this file. Each cell is model, Vals line score, Vals cost per task and tokens per task.', '',
           '## Decision models', '',
           'The model that reads each request. Default: `' + t['default_classifier'] + '`. Choose another with '
           '`--classifier`, `LEGAL_ROUTER_CLASSIFIER` or `legal-router init`.', '',
           '| Name | OpenRouter id |', '|---|---|',
           *[f'| `{n}` | `{m}` |' for n, m in t['classifiers'].items()], '',
           '## Which pick a request gets', '', '| # | When | Row | Pick | Why |', '|---|---|---|---|---|']
    for i, r in enumerate(t['rules'], 1):
        when = ', '.join(f'{k}={v}' for k, v in r['when'].items()) or 'anything else'
        if 'unless' in r:
            when += ', unless ' + ', '.join(f'{k}={v}' for k, v in r['unless'].items())
        out.append(f"| {i} | {when} | {r.get('row', 'the line')} | {r['pick']} | {r['why']} |")
    out += ['', '## The picks on each row', '',
            f"Pool = the {policy['top_k']} best allowed models on the row. Best = for work that turns on the law: the #1 among "
            f"models that know the law ({', '.join(m.split('/')[1] for m in t['knows_law'])}: Artificial Analysis legal knowledge "
            f">= {policy['law_gate']['min_legal_knowledge']} and non-hallucination >= {policy['law_gate']['min_non_hallucination']}), "
            f"or one within {policy['best_within_points']} points that costs at least {policy['best_min_saving']:.0%} less. Efficient = cheapest in the pool within "
            f"{policy['efficient_within_points']} points of #1. Economy = cheapest allowed model using no more tokens per task than #1, within "
            f"{policy['economy_within_points']} points of #1. Escalated = Claude Opus 5.5 ({policy['escalation_model']}) everywhere.", '',
            '| Row | #1 on Vals | Best | Efficient | Economy | Pool |', '|---|---|---|---|---|---|']
    for k, r in t['rows'].items():
        pool = ', '.join(e['model'].split('/')[1] for e in r['pool'])
        out.append(f"| {LABEL[k]} | {short(r['top'])} | {short(r['best'])} | {short(r['efficient'])} | {short(r['economy'])} | {pool} |")
    out += ['', '## Not served', ''] + [f'- `{m}`: {why}' for m, why in t['dropped'].items()]
    out += [f"- Denied by policy: {', '.join(f'`{m}`' for m in policy['denied'])}, and every model from a lab "
            'outside Google, Meta, Anthropic, OpenAI and xAI.', '',
            '## Practice area to row', '', '| Practice area | Row |', '|---|---|']
    out += [f'| {a} | {LABEL[r]} |' for a, r in t['line_of_practice_area'].items()]
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    j, m = build()
    if '--check' in sys.argv:
        c = CRITERIA.read_text()
        stale = [p.name for p, s in ((OUT_JSON, j), (OUT_MD, m), (PKG_TABLE, j), (PKG_CRITERIA, c))
                 if not p.exists() or p.read_text() != s]
        print('stale: ' + ', '.join(stale) if stale else 'up to date')
        sys.exit(1 if stale else 0)
    OUT_JSON.write_text(j)
    OUT_MD.write_text(m)
    PKG_TABLE.write_text(j)
    PKG_CRITERIA.write_text(CRITERIA.read_text())
    print(f'wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}')
