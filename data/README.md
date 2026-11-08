# Wolfpack 11U game database

Every GameChanger box score and play-by-play for NC Wolfpack 11U, fall 2026, in one place.

| File | What it is |
|---|---|
| `wolfpack.db` | SQLite database with every game, plate appearance, pitch and runner event |
| `raw/` | The GameChanger pulls the database is built from (`box_<game>.txt`, `plays_<game>.txt`) |
| `build_db.py` | Rebuilds `wolfpack.db` from `raw/` |
| `parse_gc.py` | Reads the GameChanger text: batters, pitchers, pitch codes, runners, outs |
| `anonymize.py` | Removes kids' names from a new pull before it is saved here |

**Names.** This repo is public, so no child's full name is stored. Our players appear as first initial and
last name (`G Nebo`), the same as on the report. Opposing players appear only as team code and jersey number (`AZBC #21`).

**Coverage.** 10 games, Aug 30 – Nov 7, 2026: 575 plays and 2,066 pitches.
Checked against GameChanger's box scores: every hitter's AB, H, BB and SO and every pitcher's batters faced match.
Runs rebuilt from the plays match every final score except Oct 25 vs High Standards, where the scorer changed the score by hand
(the plays show 11 runs for them, the line score 12).

## Tables

- **games**: one row per game: opponent, home/away, result, R/H/E, runs by inning, GameChanger link
- **batting_box**, **pitching_box**: the box score lines for both teams (pitches, strikes, batters faced, earned runs)
- **box_notes**: the 2B / 3B / TB / SB / CS / E / HBP / WP lines under each box
- **plate_appearances**: one row per play, in order. Batter, pitcher, result, outs before and after, runners on 1st/2nd/3rd
  at the start, pitch sequence, final count, batted-ball type (GB / LD / FB / PU / BU), fielder, runs, RBI, score after,
  and the original GameChanger text
- **pitches**: one row per pitch with the count before it, swing or take, strike or ball
- **runner_events**: steals, caught stealing, pickoffs and pickoff throws, wild pitches, passed balls, defensive
  indifference, balks, courtesy runners, lineup changes
- Views: **our_hitting**, **our_pitching** for quick season totals

Pitch codes: `B` ball, `I` intentional ball, `C` called strike, `S` swinging strike, `F` foul, `U` foul bunt, `T` foul tip, `X` in play.
`batting_team` is `us` or `opp`; `half` is `top` or `bottom`.

## Looking at it

Download `wolfpack.db` and open it in [DB Browser for SQLite](https://sqlitebrowser.org/) or drop it on
[sqliteviewer.app](https://sqliteviewer.app/). Some starting queries:

```sql
-- Whiff rate by hitter
SELECT batter, SUM(code='S')*1.0/SUM(is_swing) AS whiff, COUNT(*) AS pitches
FROM pitches WHERE batting_team='us' GROUP BY batter ORDER BY whiff;

-- How plate appearances end after a 1-0 vs 0-1 count
SELECT p.balls_before||'-'||p.strikes_before AS count, AVG(pa.reached) AS reached
FROM pitches p JOIN plate_appearances pa USING (pa_id)
WHERE pa.batting_team='us' AND pa.complete=1 AND p.pitch_no=2
GROUP BY count;

-- Hitting with runners in scoring position
SELECT batter, SUM(is_hit) AS h, SUM(is_ab) AS ab FROM plate_appearances
WHERE batting_team='us' AND complete=1 AND (on_2b IS NOT NULL OR on_3b IS NOT NULL) GROUP BY batter;
```

## Adding a game

1. Pull the game's box score and play-by-play into `data/incoming/` (full names are fine there; that folder is never committed).
2. `python3 anonymize.py incoming/`: writes name-free copies into `raw/`.
3. Add the game id to `GAMES` in `parse_gc.py`, its GameChanger event id to `GC_EVENTS` in `build_db.py` and, for a new opponent, a code to `OPP_CODES` in `anonymize.py`.
4. `python3 build_db.py`, then commit `raw/` and `wolfpack.db`.
