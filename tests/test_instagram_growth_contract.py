from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def text(name): return (ROOT/name).read_text()

def test_bootstrap_growth_modules():
 b=text('bootstrap.py')
 for name in ['v2_instagram_growth','v2_instagram_growth_attribution','v2_instagram_content','v2_instagram_growth_brain','v2_instagram_growth_report']:
  assert f'import {name}' in b

def test_growth_is_not_cold_outreach_bot():
 g=text('v2_instagram_growth.py').lower()
 assert 'comment_id' in g
 assert 'private_reply' in g
 assert 'scrape' not in g
 assert 'selenium' not in g

def test_content_has_single_cta():
 c=text('v2_instagram_content.py')
 assert 'COMMENT CHAIR' in c
 assert 'WHEN THEY CANCEL, WE FILL THE CHAIR.' in c

def test_milestone_does_not_stop_machine():
 r=text('v2_instagram_growth_report.py')
 assert 'KEEP GOING.' in r
