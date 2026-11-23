"""What the router costs against sending every request to one model, priced on the Vals Legal Index.

Replays Elephant-1's stored answers for 195 test requests (docs/data/classifier-answers.jsonl, answers
only, no request text) through the current routing table. Each request is priced at the Vals cost per
test of the model it is routed to, on its own Vals line. No network, no API key.

    uv run python scripts/estimate_savings.py
"""
import json
from collections import Counter
from pathlib import Path

from legal_router.core import TABLE, Work, route

ROOT = Path(__file__).resolve().parents[1]
VALS = json.loads((ROOT / 'benchmarks/vals-legal-index.json').read_text())['lines']
ANSWERS = ROOT / 'docs/data/classifier-answers.jsonl'
SINGLE = {'Claude Opus 5.5': 'anthropic/claude-opus-5-5', 'GPT-6.2 Astra': 'openai/gpt-6.2-astra',
          'Gemini 4 Neon': 'google/cobalt-c-high-1p00'}


def work(a: dict) -> Work:
    top = lambda q: (a[q]['choice'], float(a[q]['probabilities'].get(a[q]['choice'], 0.0)))  # noqa: E731
    section, section_p = top('section')
    area = a['practice_area']['choice']
    return Work(a['work_type']['choice'], a['work_type']['probabilities'],
                float(a['drafting_complexity']['probabilities'].get('standard_form', 0.0)), section, section_p,
                area, TABLE['line_of_practice_area'].get(area, 'overall'))


def estimate() -> dict:
    """Average cost and tokens per task for the router and for each single-model setup."""
    cost, tokens, picks = Counter(), Counter(), Counter()
    for line in ANSWERS.read_text().splitlines():
        r = route(work(json.loads(line)['answers']))
        vals_id = TABLE['models'][r.model]['vals_id']
        picks[r.pick] += 1
        cost['Legal Model Router'] += VALS[r.line][vals_id]['cost_per_test']
        tokens['Legal Model Router'] += VALS['overall'][vals_id]['tokens_per_test']
        for name, m in SINGLE.items():
            cost[name] += VALS[r.line][m]['cost_per_test']
            tokens[name] += VALS['overall'][m]['tokens_per_test']
        if r.pick != 'escalated':
            cost['router, no escalations'] += VALS[r.line][vals_id]['cost_per_test']
            for name, m in SINGLE.items():
                cost[f'{name}, no escalations'] += VALS[r.line][m]['cost_per_test']
    n = sum(picks.values())
    return {'requests': n, 'picks': dict(picks.most_common()),
            'cost': {k: v / n for k, v in cost.items()}, 'tokens': {k: v / n for k, v in tokens.items()}}


def main() -> None:
    e = estimate()
    cost, ours = e['cost'], e['cost']['Legal Model Router']
    print(f"{e['requests']} requests: " + ', '.join(f'{p} {c}' for p, c in e['picks'].items()))
    print(f"{'':20} {'per task':>9} {'tokens':>8} {'router saves':>13}")
    for name in ('Legal Model Router', *SINGLE):
        print(f"{name:20} ${cost[name]:8.2f} {e['tokens'][name] / 1e6:7.2f}M {1 - ours / cost[name]:12.0%}")
    rest = cost['router, no escalations']
    print('Without the bespoke drafts it sends to Opus 5.5: ' + ', '.join(
        f'{1 - rest / cost[f"{name}, no escalations"]:.0%} less than {name}' for name in SINGLE))


if __name__ == '__main__':
    main()
