"""Build wolfpack.db (SQLite) from the GameChanger pulls in raw/.

Run:  python3 build_db.py
Rebuilds the database from scratch every time, so raw/ stays the source of truth.
To add a game: save its box score and play-by-play to raw/ (box_<id>.txt, plays_<id>.txt),
add the id and GameChanger event id to GAMES in parse_gc.py and GC_EVENTS below, then re-run.
"""
import json, os, re, sqlite3
from parse_gc import load_all, parse_box, RAW, GAMES

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'wolfpack.db')
TEAM = 'NC Wolfpack 11U'
GC_TEAM = 'OwSvihc7OvBS'
GC_EVENTS = {
    '2026-08-30': '3442f081-5654-4e59-a142-a8be164555c2', '2026-09-13': 'f57f440f-ec9b-4f76-9c38-84ed19b70c1d',
    '2026-09-20': '4999755f-e07a-43ac-b2f0-45db0f4dc633', '2026-09-27': '685184dd-f4c8-4779-b6cf-e8aeda7d887d',
    '2026-10-04': '922fc7b9-f56e-4340-bbd0-5344d3b1f838', '2026-10-18': 'dd9edbc8-a3bf-44db-9c4a-01e3eed083e1',
    '2026-10-25': '9e991d32-71b1-4a2c-b9b6-8276e9a230af', '2026-10-25b': '3605b691-0410-4694-8631-f9d8db07271a',
    '2026-11-07': '11960856-54f9-435f-859a-7da2bbbd9b1b', '2026-11-07b': '852ea087-4692-4e1f-afdb-e78d2b8e6a40',
}
PITCH_NAMES = {'B': 'Ball', 'I': 'Intentional ball', 'C': 'Called strike', 'S': 'Swinging strike', 'F': 'Foul',
               'U': 'Foul bunt', 'T': 'Foul tip', 'X': 'In play'}
HITS = {'Single', 'Double', 'Triple', 'Home Run'}

SCHEMA = """
CREATE TABLE games (
  game_id TEXT PRIMARY KEY,          -- e.g. 2026-11-07b (b = second game that day)
  date TEXT, opponent TEXT, home_away TEXT, result TEXT,
  runs_us INTEGER, runs_opp INTEGER, hits_us INTEGER, hits_opp INTEGER, errors_us INTEGER, errors_opp INTEGER,
  innings INTEGER, line_us TEXT, line_opp TEXT,   -- runs by inning, JSON arrays
  gc_event_id TEXT, gc_url TEXT, pulled_at TEXT
);
CREATE TABLE batting_box (           -- GameChanger box score, both teams
  game_id TEXT, team TEXT, player TEXT, jersey TEXT, positions TEXT,
  ab INTEGER, r INTEGER, h INTEGER, rbi INTEGER, bb INTEGER, so INTEGER, batting_order INTEGER
);
CREATE TABLE pitching_box (
  game_id TEXT, team TEXT, pitcher TEXT, jersey TEXT, decision TEXT, ip REAL, outs INTEGER,
  h INTEGER, r INTEGER, er INTEGER, bb INTEGER, so INTEGER, pitches INTEGER, strikes INTEGER, batters_faced INTEGER
);
CREATE TABLE box_notes (             -- the 2B/3B/TB/SB/CS/E/HBP/WP lines under each box
  game_id TEXT, team TEXT, section TEXT, note TEXT, value TEXT
);
CREATE TABLE plate_appearances (     -- one row per play in the GameChanger log, in game order
  pa_id INTEGER PRIMARY KEY, game_id TEXT, seq INTEGER, inning INTEGER, half TEXT,
  batting_team TEXT, batter TEXT, pitcher TEXT,
  result TEXT,                       -- GameChanger's label: Single, Walk, Strikeout, Fly Out, Runner Out ...
  complete INTEGER,                  -- 0 = no finished plate appearance (inning ended on the bases, game ended)
  is_ab INTEGER, is_hit INTEGER, is_k INTEGER, k_type TEXT,  -- k_type L = looking, S = swinging
  reached INTEGER,
  outs_before INTEGER, outs_after INTEGER,
  on_1b TEXT, on_2b TEXT, on_3b TEXT,  -- runners when the plate appearance began
  pitch_seq TEXT, pitches INTEGER, balls INTEGER, strikes INTEGER, final_count TEXT,
  batted_ball TEXT, hard_hit INTEGER, fielder_pos TEXT, fielder TEXT,
  runs_scored INTEGER, rbi INTEGER, score_us_after INTEGER, score_opp_after INTEGER,
  description TEXT, raw_line TEXT
);
CREATE TABLE pitches (               -- one row per pitch
  pa_id INTEGER, game_id TEXT, pitch_no INTEGER, code TEXT, pitch TEXT,
  balls_before INTEGER, strikes_before INTEGER, is_swing INTEGER, is_strike INTEGER,
  batter TEXT, pitcher TEXT, batting_team TEXT
);
CREATE TABLE runner_events (         -- steals, wild pitches, pickoffs, courtesy runners ... between pitches
  pa_id INTEGER, game_id TEXT, after_pitch INTEGER, event TEXT, kind TEXT, runner TEXT
);
CREATE VIEW our_hitting AS
  SELECT batter, COUNT(*) pa, SUM(is_ab) ab, SUM(is_hit) h, SUM(result='Walk') bb, SUM(is_k) so,
         SUM(k_type='L') k_looking, SUM(pitches) pitches_seen
  FROM plate_appearances WHERE batting_team='us' AND complete=1 GROUP BY batter;
CREATE VIEW our_pitching AS
  SELECT pitcher, COUNT(*) bf, SUM(is_hit) h, SUM(result='Walk') bb, SUM(is_k) so, SUM(pitches) pitches
  FROM plate_appearances WHERE batting_team='opp' AND complete=1 GROUP BY pitcher;
"""

def kind_of(e):
    for pat, k in ((r'steals', 'stolen_base'), (r'scores on steal of home', 'stolen_base'), (r'caught stealing', 'caught_stealing'),
                   (r'picked off', 'picked_off'), (r'wild pitch', 'wild_pitch'), (r'passed ball', 'passed_ball'),
                   (r'defensive indifference', 'defensive_indifference'), (r'on error', 'error'), (r'^Balk', 'balk'),
                   (r'^Courtesy runner', 'courtesy_runner'), (r'^Lineup changed', 'lineup_change'), (r'scores', 'run_scored'),
                   (r'advances', 'advance'), (r'^(catcher|pitcher|first baseman|second baseman|third baseman|shortstop|left fielder|center fielder|right fielder)', 'fielder'),
                   (r'Score changed', 'score_change')):
        if re.search(pat, e): return k
    return 'other'

def runner_of(e):
    m = re.match(r'^(.*?) ?(steals|scores|caught stealing|picked off|advances|out at)', e)
    return m[1] if m and m[1] else None

def main():
    data = load_all()
    if os.path.exists(DB): os.remove(DB)
    con = sqlite3.connect(DB); con.executescript(SCHEMA)
    pa_id = 0
    for g in GAMES:
        v = data[g]; box = v['box']; pas = v['pas']; opp = v['opp']
        hdr = open(os.path.join(RAW, f'box_{g}.txt')).readline()
        rhe = re.findall(r'R\tH\tE (\d+)\t(\d+)\t(\d+) (\d+)\t(\d+)\t(\d+)', hdr)[0]
        us_first = hdr.index(TEAM) < hdr.index(opp) if opp in hdr else True
        a, b = (rhe[:3], rhe[3:]) if us_first else (rhe[3:], rhe[:3])
        lines = re.findall(r'((?:\d+|X)(?:\t(?:\d+|X))+)', hdr.split('R\tH\tE')[0])
        inn_row = lines[0].split('\t'); l1 = lines[1].split('\t'); l2 = lines[2].split('\t')
        lu, lo = (l1, l2) if us_first else (l2, l1)
        ru, ro = int(a[0]), int(b[0])
        con.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            g, g[:10], opp, 'home' if v['our_half'] == 'B' else 'away', 'W' if ru > ro else 'L' if ru < ro else 'T',
            ru, ro, int(a[1]), int(b[1]), int(a[2]), int(b[2]), len(inn_row), json.dumps([int(x) if x.isdigit() else x for x in lu]), json.dumps([int(x) if x.isdigit() else x for x in lo]),
            GC_EVENTS[g], f'https://web.gc.com/teams/{GC_TEAM}/schedule/{GC_EVENTS[g]}/plays', '2026-11-08'))
        # batting order = order of first plate appearance
        first = {}
        for pa in pas:
            if pa['batter'] and not pa['incomplete']:
                first.setdefault((pa['batting'], pa['batter']), len([k for k in first if k[0] == pa['batting']]) + 1)
        for team in (TEAM, opp):
            side = 'us' if team == TEAM else 'opp'
            for x in box[team]['bat']:
                con.execute('INSERT INTO batting_box VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (g, team, x['name'], x['num'], x['pos'],
                            x['AB'], x['R'], x['H'], x['RBI'], x['BB'], x['SO'], first.get((side, x['name']))))
            for x in box[team]['pit']:
                ps = box[team]['Pitches-Strikes'].get(x['name']); bf = box[team]['Batters Faced'].get(x['name'])
                w = int(round(float(x['ip']) * 10))
                con.execute('INSERT INTO pitching_box VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (g, team, x['name'], x['num'], None,
                            float(x['ip']), (w // 10) * 3 + w % 10, x['H'], x['R'], x['ER'], x['BB'], x['SO'],
                            ps[0] if ps else None, ps[1] if ps else None, bf))
            for k, val in box[team]['extra'].items():
                con.execute('INSERT INTO box_notes VALUES (?,?,?,?,?)', (g, team, 'box', k, val))
        raw = [l.rstrip('\n') for l in open(os.path.join(RAW, f'plays_{g}.txt')) if l.strip()]
        su = so = 0
        for pa in pas:
            pa_id += 1
            L = pa['label']; seq = pa['seq']; done = not pa['incomplete']
            k = None
            if L in ('Strikeout', 'Dropped 3rd Strike'):
                k = 'L' if 'looking' in pa['desc'] else 'S' if ('swinging' in pa['desc'] or 'foul tip' in pa['desc']) else ('L' if seq[-1:] == 'C' else 'S')
            is_ab = done and L not in ('Walk', 'Intentional Walk', 'Hit By Pitch', 'Sacrifice Fly', 'Sacrifice Bunt', "Catcher's Interference")
            reached = done and (L in HITS or L in ('Walk', 'Intentional Walk', 'Hit By Pitch', 'Error', "Fielder's Choice", "Catcher's Interference")
                                or (L == 'Dropped 3rd Strike' and 'reaches' in pa['desc']))
            runs = len(pa['runs_play']) + len(pa['runs_pitch'])
            if pa['batting'] == 'us': su += runs
            else: so += runs
            bb_ = s_ = 0; states = []
            for ch in seq:
                states.append((bb_, s_))
                if ch in 'BI': bb_ += 1
                elif ch in 'CS': s_ += 1
                elif ch in 'FUT' and s_ < 2: s_ += 1
            st = {int(kk): vv for kk, vv in pa['start']['bases'].items()}
            con.execute('INSERT INTO plate_appearances VALUES (' + ','.join('?' * 35) + ')', (
                pa_id, g, pa['idx'] + 1, pa['inn'], 'top' if pa['half'] == 'T' else 'bottom', pa['batting'], pa['batter'] or None, pa['pitcher'],
                L, int(done), int(is_ab), int(done and L in HITS), int(k is not None), k, int(reached),
                pa['start']['outs'], pa['outs_after'], st.get(1), st.get(2), st.get(3),
                seq, len(seq), min(bb_, 4), min(s_, 3), f'{min(bb_, 4)}-{min(s_, 3)}',
                pa['bb'], int(pa['hard']), pa['fpos'], pa['fname'], runs, pa['rbi_cand'] if done else 0, su, so,
                pa['desc'], raw[pa['idx']]))
            n = 0
            for t in pa['toks']:
                if t in PITCH_NAMES:
                    b0, s0 = states[n]; n += 1
                    con.execute('INSERT INTO pitches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (pa_id, g, n, t, PITCH_NAMES[t], b0, s0,
                                int(t in 'SFUTX'), int(t != 'B' and t != 'I'), pa['batter'] or None, pa['pitcher'], pa['batting']))
                elif t.startswith('P') and len(t) <= 2:
                    con.execute('INSERT INTO runner_events VALUES (?,?,?,?,?,?)', (pa_id, g, n, 'Pickoff attempt at ' + {'1': '1st', '2': '2nd', '3': '3rd'}.get(t[1:], t[1:]), 'pickoff_attempt', None))
                elif t.startswith('{'):
                    e = t[1:-1]
                    con.execute('INSERT INTO runner_events VALUES (?,?,?,?,?,?)', (pa_id, g, n, e, kind_of(e), runner_of(e)))
    con.commit()
    for t in ('games', 'batting_box', 'pitching_box', 'plate_appearances', 'pitches', 'runner_events'):
        print(t, con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
    con.close()

if __name__ == '__main__':
    main()
