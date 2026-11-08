import re, json, itertools, sys, os
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
from collections import defaultdict, Counter

GAMES = ['2026-08-30','2026-09-13','2026-09-20','2026-09-27','2026-10-04','2026-10-18','2026-10-25','2026-10-25b','2026-11-07','2026-11-07b','2026-11-08']
POS = {'pitcher':'P','catcher':'C','first baseman':'1B','second baseman':'2B','third baseman':'3B','shortstop':'SS',
       'left fielder':'LF','center fielder':'CF','right fielder':'RF','left field':'LF','center field':'CF','right field':'RF'}
POSRE = '|'.join(sorted(POS, key=len, reverse=True))
PITCH = set('BICSFUTX')
BASEN = {'1st':1,'2nd':2,'3rd':3,'home':4}

def parse_box(path):
    L = [l.rstrip('\n') for l in open(path)]
    teams = {}; cur = None; mode = None
    for l in L[1:]:
        if ':' not in l and not l.startswith('TEAM') and not re.search(r'\d+ \d+ \d+ \d+ \d+ \d+$', l):
            cur = l.strip(); teams[cur] = {'bat':[], 'pit':[], 'extra':{}}; mode='bat'; continue
        t = teams[cur]
        m = re.match(r'^(.+?)(?: #(\d+))?(?: \(([WLS])\))? (\d+\.\d) (\d+) (\d+) (\d+) (\d+) (\d+)$', l)
        if m and not l.startswith('TEAM'):
            t['pit'].append(dict(name=m[1].strip(), num=m[2], ip=m[4], H=int(m[5]), R=int(m[6]), ER=int(m[7]), BB=int(m[8]), SO=int(m[9]))); continue
        if l.startswith('TEAM'):
            continue
        m = re.match(r'^(.+?)(?: #(\d+))?(?: \(([^)]*)\))? (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)', l)
        if m and ':' not in l:
            t['bat'].append(dict(name=m[1].strip(), num=m[2], pos=m[3], AB=int(m[4]), R=int(m[5]), H=int(m[6]), RBI=int(m[7]), BB=int(m[8]), SO=int(m[9]))); continue
        if ':' in l:
            k, v = l.split(':', 1); t['extra'][k.strip()] = v.strip()
    for t in teams.values():
        for key in ('Pitches-Strikes', 'Batters Faced'):
            d = {}
            for part in t['extra'].get(key, '').split(', '):
                if not part: continue
                m = re.match(r'^(.+?) (\d+)(?:-(\d+))?$', part)
                if m: d[m[1]] = (int(m[2]), int(m[3])) if m[3] else int(m[2])
                else: d[part] = 1
            t[key] = d
    return teams

def toks(p):
    return re.findall(r'\{[^}]*\}|P[123h]?|[BICSFUTX]', p or '')

VERB = r'(strikes out|walks|is intentionally walked|singles|doubles|triples|homers|grounds|flies|lines|pops|hits|bunts|is hit by pitch|is out|out at first|reaches|out on|out \(other\)|sacrifices)'

def batter_of(desc):
    if desc.startswith('Half-inning'): return (None, None)
    m = re.match(r'^(?:(.*?)\s+)?' + VERB + r'(?!\w)', desc)
    return ((m[1] or '').strip(), m[2]) if m else (None, None)

def bb_type(desc, label):
    d = desc
    hard = 'hard ground ball' in d or 'hard line drive' in d
    for k, v in (('ground ball','GB'),('line drive','LD'),('pop fly','PU'),('fly ball','FB'),('bunt','BU')):
        if 'on a ' + ('hard ' if hard and k in ('ground ball','line drive') else '') + k in d or 'hits a ' + k in d or 'on a ' + k in d:
            return v, hard
    if re.search(r' grounds (out|into)', d): return 'GB', hard
    if re.search(r' flies (out|into)', d) or 'sacrifice fly' in d: return 'FB', hard
    if ' lines ' in d: return 'LD', hard
    if ' pops ' in d or 'infield fly' in d: return 'PU', hard
    if ' bunts' in d or 'sacrifices' in d: return 'BU', hard
    if 'homers on a fly ball' in d: return 'FB', hard
    return None, hard

def fielder(desc):
    m = re.search(r'(?:to|by) (' + POSRE + r')(?: ([A-Z][\w\'-]*(?: (?:[A-Z][\w\'-]*|#\d+))?))?', desc)
    if not m: return None, None
    name = m[2]
    if name and name in ('Unknown',): name = None
    return POS[m[1]], name

def load_game(g):
    rows = []
    for l in open(os.path.join(RAW, f'plays_{g}.txt')):
        l = l.rstrip('\n')
        if not l.strip(): continue
        parts = l.split(' ~ ')
        while len(parts) < 4: parts.append('')
        inn, hdr, p, desc = parts[0], parts[1], parts[2], ' ~ '.join(parts[3:]).strip()
        rows.append(dict(inn=inn, hdr=hdr, p=p.strip(), desc=desc))
    return rows

def process(g, box):
    rows = load_game(g)
    us_name = 'NC Wolfpack 11U'
    opp_name = [k for k in box if k != us_name][0]
    our_names = set(b['name'] for b in box[us_name]['bat']) | set(p['name'] for p in box[us_name]['pit'])
    # which half do we bat in
    cnt = Counter()
    for r in rows:
        b, _ = batter_of(r['desc'])
        if b: cnt[(r['inn'][0], b in our_names)] += 1
    our_half = 'T' if cnt[('T', True)] > cnt[('B', True)] else 'B'
    pas = []
    inn_prev = None; bases = {}; outs = 0; score = {'us':0,'opp':0}
    for i, r in enumerate(rows):
        if r['inn'] != inn_prev:
            bases = {}; outs = 0; inn_prev = r['inn']
        half = r['inn'][0]; inning = int(r['inn'][1:])
        batting = 'us' if half == our_half else 'opp'
        label = r['hdr'].split('/')[0].strip()
        mo = re.search(r'(\d) Outs?', r['hdr'])
        T = toks(r['p'])
        pitches = ''.join(t for t in T if t in PITCH)
        b, verb = batter_of(r['desc'])
        incomplete = b is None
        if label.endswith(' at bat'):
            b = label[:-7]; incomplete = True
        start = dict(bases=dict(bases), outs=outs)
        ev = []
        runs_on_pitch = []
        # process in-PA events
        for t in T:
            if not t.startswith('{'): continue
            e = t[1:-1]
            ev.append(e)
            m = re.match(r'^(.*?) ?scores on steal of home$', e)
            if m: _rm(bases, m[1]); runs_on_pitch.append((m[1], 'SBH')); continue
            m = re.match(r'^(.*?) ?scores(?: on (.*))?$', e)
            if m: _rm(bases, m[1]); runs_on_pitch.append((m[1], m[2] or '')); continue
            m = re.match(r'^(.*?) ?steals (2nd|3rd)$', e)
            if m: _mv(bases, m[1], BASEN[m[2]]); continue
            m = re.match(r'^(.*?) ?advances to (1st|2nd|3rd)', e)
            if m: _mv(bases, m[1], BASEN[m[2]]); continue
            m = re.match(r'^(.*?) ?(caught stealing|picked off at) ?(1st|2nd|3rd|home)', e)
            if m: _rm(bases, m[1]); continue
            m = re.match(r'^(.*?) out at (1st|2nd|3rd)$', e)
            if m: _rm(bases, m[1]); continue
            m = re.match(r'^Courtesy runner (.*?) in for (.*)$', e)
            if m:
                for k, v in list(bases.items()):
                    if v == m[2]: bases[k] = m[1]
                continue
        runs_play = []
        rbi_cand = 0
        if not incomplete:
            clauses = r['desc'].rstrip('.').split(', ')
            newloc = {}
            for c in clauses[1:]:
                m = re.match(r'^(.*?) ?scores(?: (.*))?$', c)
                if m:
                    newloc[m[1]] = 4; runs_play.append((m[1], m[2] or ''))
                    if not (m[2] or '').startswith('on error'): rbi_cand += 1
                    continue
                m = re.match(r'^(.*?) ?advances to (2nd|3rd)', c)
                if m: newloc[m[1]] = BASEN[m[2]]; continue
                m = re.match(r'^(.*?) ?(remains at|held up at) (1st|2nd|3rd)', c)
                if m: newloc[m[1]] = BASEN[m[3]]; continue
                m = re.match(r'^(.*?) ?(out advancing to|doubled off at) ', c)
                if m: newloc[m[1]] = 0; continue
            # batter base
            bl = label
            bbase = 0
            if bl == 'Single': bbase = 1
            elif bl == 'Double': bbase = 2
            elif bl == 'Triple': bbase = 3
            elif bl == 'Home Run': bbase = 4
            elif bl in ('Walk','Intentional Walk','Hit By Pitch','Error','Fielder\'s Choice','Catcher\'s Interference'): bbase = 1
            elif bl == 'Dropped 3rd Strike' and 'reaches' in r['desc']: bbase = 1
            if b in newloc:
                bbase = newloc.pop(b)
            if bl == 'Home Run':
                for k, v in bases.items(): newloc.setdefault(v, 4)
                runs_play.append((b, 'HR')); rbi_cand += 1
            nb = {}
            for k, v in bases.items():
                loc = newloc.get(v, k)
                if loc in (1,2,3): nb[loc] = v
            if bbase in (1,2,3): nb[bbase] = b
            bases = nb
        if mo: outs = int(mo[1])
        if incomplete and 'Half-inning ended' in (r['desc'] + r['p']): outs = 3
        nr = len(runs_on_pitch) + len(runs_play)
        score[batting] += nr
        bt, hard = bb_type(r['desc'], label) if not incomplete else (None, False)
        fpos, fname = fielder(r['desc']) if not incomplete else (None, None)
        pas.append(dict(game=g, idx=i, inn=inning, half=half, batting=batting, batter=b, label=label, incomplete=incomplete,
                        seq=pitches, toks=T, desc=r['desc'], ev=ev, start=start, outs_after=outs,
                        runs_play=runs_play, runs_pitch=runs_on_pitch, rbi_cand=rbi_cand, bb=bt, hard=hard, fpos=fpos, fname=fname,
                        pitcher=None))
    return pas, our_half, opp_name

def _rm(bases, name):
    for k, v in list(bases.items()):
        if v == name: del bases[k]; return

def _mv(bases, name, to):
    for k, v in list(bases.items()):
        if v == name: del bases[k]; bases[to] = name; return
    if name: bases[to] = name

def is_bf(pa):
    return not pa['incomplete']

def assign_pitchers(pas, box, team_def, side):
    # side: which batting side faces these pitchers
    seq = [pa for pa in pas if pa['batting'] == side]
    P = box[team_def]['pit']; names = [p['name'] for p in P]
    BF = box[team_def]['Batters Faced']
    anch = {}
    short = {n: n for n in names}
    for j, pa in enumerate(seq):
        d = pa['desc'] + ' ' + ' '.join(pa['ev'])
        for n in names:
            if re.search(re.escape(n) + r' pitching', d) or re.search(r'(to|by) pitcher ' + re.escape(n) + r'\b', d) or ('Balk by pitcher ' + n) in d:
                anch[j] = n
    if 0 not in anch: anch[0] = names[0]
    keys = sorted(anch)
    # segments between differing anchors
    assign = [None] * len(seq)
    gaps = []
    for a, bk in zip(keys, keys[1:]):
        for j in range(a, bk): assign[j] = anch[a]
        if anch[a] != anch[bk]: gaps.append((a, bk))
    for j in range(keys[-1], len(seq)): assign[j] = anch[keys[-1]]
    # brute force change points (change happens at first PA index c in (a, b])
    best = None
    ranges = [range(a + 1, bk + 1) for a, bk in gaps]
    for combo in itertools.product(*ranges) if gaps else [()]:
        asg = list(assign)
        for (a, bk), c in zip(gaps, combo):
            for j in range(a, bk): asg[j] = anch[a] if j < c else anch[bk]
        cnt = Counter(asg[j] for j in range(len(seq)) if is_bf(seq[j]))
        err = sum(abs(cnt.get(n, 0) - BF.get(n, 0)) for n in names)
        # tie-break: incomplete PAs follow
        if best is None or err < best[0]: best = (err, asg)
    err, asg = best
    for pa, n in zip(seq, asg): pa['pitcher'] = n
    return err

def load_all():
    """Parse every game in raw/; returns {game_id: dict(pas, box, opp, our_half)}."""
    out = {}
    for g in GAMES:
        box = parse_box(os.path.join(RAW, f'box_{g}.txt'))
        pas, oh, opp = process(g, box)
        assign_pitchers(pas, box, 'NC Wolfpack 11U', 'opp')
        assign_pitchers(pas, box, opp, 'us')
        if g == '2026-10-25b':
            # opponent relievers never named in the play text: stints from the box score's batters faced
            names = [x['name'] for x in box[opp]['pit']]  # box order: 9, 7, 3, 4, 5 batters faced
            plan = [names[0]]*9 + [names[1]]*7 + [names[2]]*3 + [names[3]]*4 + [names[4]]*5
            k = 0
            for pa in [p for p in pas if p['batting'] == 'us']:
                pa['pitcher'] = plan[min(k, len(plan) - 1)]
                if not pa['incomplete']: k += 1
        out[g] = dict(pas=pas, box=box, opp=opp, our_half=oh)
    return out
