"""Strip kids' names from a GameChanger pull before it is saved to this public repo.

Our players become first initial + last name ("Gunnar Nebo" -> "G Nebo", the same form the report uses).
Opposing players become team code + jersey ("Liam V" -> "AZBC #21"), so no opposing kid is named.

Usage:  python3 anonymize.py <folder with full-name box_<id>.txt / plays_<id>.txt>
Writes the cleaned files into raw/. Never commit the full-name originals (data/incoming/ is git-ignored).
"""
import os, re, sys
from parse_gc import parse_box

HERE = os.path.dirname(os.path.abspath(__file__))
TEAM = 'NC Wolfpack 11U'
OPP_CODES = {  # short code per opponent, used in place of opposing players' names
    'Sox 11U': 'SOX', 'OutKast Baseball Club 10U': 'OTKS', 'Carlsbad Crew - Stanford 11U': 'CRLS',
    'San Marcos Impact 11U': 'SNMR', '11U (OG) - San Diego Hawks': 'HAWKS', 'Owls 11u': 'OWLS',
    'High Standards 11U': 'HGHS', 'AZBC 2034 DF 11U': 'AZBC', 'Dynasty Baseball 11U Moody': 'DYNS',
}
SPELLING = {'N Koletsou': 'N Koletsos'}  # roster spelling

def ours(full):
    f = full.split()
    n = f[0][0] + ' ' + ' '.join(f[1:]) if len(f) > 1 else full
    return SPELLING.get(n, n)

def mapping(box_path, roster=()):
    box = parse_box(box_path)
    opp = [k for k in box if k != TEAM][0]
    code = OPP_CODES.get(opp) or re.sub(r'[^A-Z]', '', opp.upper())[:5]
    m = {n: ours(n) for n in roster}  # whole-season roster: covers kids who only appear fielding
    for x in box[TEAM]['bat'] + box[TEAM]['pit']:
        m[x['name']] = ours(x['name'])
    for x in box[opp]['bat'] + box[opp]['pit']:
        if x['name'] and not x['name'].startswith('#'):
            m[x['name']] = f"{code} #{x['num']}" if x['num'] else f'{code} player'
    return m

def scrub(text, m):
    for full in sorted(m, key=len, reverse=True):
        text = re.sub(r'(?<![\w#])' + re.escape(full) + r'(?![\w])', m[full], text)
    return text

def main(src):
    out = os.path.join(HERE, 'raw'); os.makedirs(out, exist_ok=True)
    roster = set()
    for f in os.listdir(src):
        if f.startswith('box_'):
            b = parse_box(os.path.join(src, f))
            roster |= {x['name'] for x in b[TEAM]['bat'] + b[TEAM]['pit']}
    for f in sorted(os.listdir(src)):
        mm = re.match(r'^box_(.+)\.txt$', f)
        if not mm: continue
        g = mm[1]; m = mapping(os.path.join(src, f), roster)
        for kind in ('box', 'plays'):
            p = os.path.join(src, f'{kind}_{g}.txt')
            if os.path.exists(p):
                open(os.path.join(out, f'{kind}_{g}.txt'), 'w').write(scrub(open(p).read(), m))
        print(g, len(m), 'names replaced')

if __name__ == '__main__':
    main(sys.argv[1])
