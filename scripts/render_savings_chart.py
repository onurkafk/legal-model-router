"""Draw the README's savings chart from scripts/estimate_savings.py: HTML, then PNG in light and dark.

    uv run python scripts/render_savings_chart.py

Writes docs/assets/savings.html and, if Google Chrome is installed, docs/assets/savings-{light,dark}.png.
"""
import html
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estimate_savings import estimate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets'
BARS = ('Claude Opus 5.5', 'GPT-6.2 Astra', 'Legal Model Router')
WIDTH, HEIGHT = 960, 400
CHROME = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 'google-chrome', 'chromium', 'chrome']

THEMES = {
    'light': {'bg': '#ffffff', 'ink': '#0a0a0a', 'muted': '#737373', 'faint': '#a3a3a3', 'rule': '#ededed',
              'bar': '#e5e5e5', 'accent': '#0a0a0a'},
    'dark': {'bg': '#0d1117', 'ink': '#f5f5f5', 'muted': '#9ca3af', 'faint': '#6b7280', 'rule': '#1f2630',
             'bar': '#262c36', 'accent': '#f5f5f5'},
}


def page(theme: str) -> str:
    e = estimate()
    cost, tokens = e['cost'], e['tokens']
    top = max(cost[b] for b in BARS)
    t = THEMES[theme]
    rows = []
    for name in BARS:
        mine = name == 'Legal Model Router'
        rows.append(f'''
      <div class="row{' mine' if mine else ''}">
        <div class="label">{html.escape(name)}</div>
        <div class="track"><div class="bar" style="width:{cost[name] / top * 100:.2f}%"></div></div>
        <div class="value">${cost[name]:.2f}<span>{tokens[name] / 1e6:.1f}M tokens</span></div>
      </div>''')
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Legal Model Router: cost per legal task</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  html, body {{ width: {WIDTH}px; height: {HEIGHT}px; background: {t['bg']}; }}
  body {{
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: {t['ink']}; padding: 48px 56px; -webkit-font-smoothing: antialiased;
    font-feature-settings: "tnum" 1, "cv11" 1;
  }}
  .eyebrow {{ font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: {t['muted']}; font-weight: 500; }}
  h1 {{ font-size: 40px; line-height: 1.1; letter-spacing: -.025em; font-weight: 600; margin-top: 10px; }}
  .chart {{ margin-top: 40px; display: grid; gap: 18px; }}
  .row {{ display: grid; grid-template-columns: 180px 1fr 190px; align-items: center; gap: 20px; }}
  .label {{ font-size: 16px; color: {t['muted']}; }}
  .track {{ height: 28px; }}
  .bar {{ height: 100%; border-radius: 6px; background: {t['bar']}; }}
  .value {{ font-size: 20px; font-weight: 600; letter-spacing: -.01em; display: flex; align-items: baseline; gap: 10px; }}
  .value span {{ white-space: nowrap; font-size: 13px; font-weight: 400; color: {t['faint']}; letter-spacing: 0; }}
  .mine .label {{ color: {t['ink']}; font-weight: 600; }}
  .mine .bar {{ background: {t['accent']}; }}
  footer {{ margin-top: 40px; padding-top: 16px;
           border-top: 1px solid {t['rule']}; font-size: 13px; color: {t['faint']}; }}
</style>
</head>
<body>
  <div class="eyebrow">Average cost per legal task</div>
  <h1>Nearly half the cost of Claude Opus 5.5</h1>
  <div class="chart">{''.join(rows)}
  </div>
  <footer>{e['requests']} legal requests read by d1-ultra, at Vals Legal Index prices (19 Nov 2026). Bespoke drafting still goes to Opus 5.5.</footer>
</body>
</html>
'''


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    chrome = next((c for c in CHROME if shutil.which(c) or Path(c).exists()), None)
    for theme in THEMES:
        src = OUT / f'savings-{theme}.html'
        src.write_text(page(theme))
        if chrome:
            subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                            '--force-device-scale-factor=2', f'--window-size={WIDTH},{HEIGHT}',
                            f'--screenshot={OUT / f"savings-{theme}.png"}', src.as_uri()],
                           check=True, capture_output=True)
        print(f'wrote {src.relative_to(ROOT)}' + (f' and savings-{theme}.png' if chrome else ''))
    if not chrome:
        print('Google Chrome not found: open the HTML files and screenshot them at 2x')


if __name__ == '__main__':
    main()
