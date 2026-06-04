import urllib.request, re

POSITIONS = ["QB", "WR", "RB", "TE"]
TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "LVR": "LV"}

def parse_adp_html(html):
    """
    Parse FantasyPros ADP HTML (both current and Wayback Machine versions).
    Row structure:
      <tr>
        <td>OVERALL_RANK</td>
        <td ...><a ... fp-player-name="NAME" ...>NAME</a> <small>TEAM</small> <small>(BYE)</small></td>
        <td>POS+RANK e.g. RB1</td>
        ... several expert columns ...
        <td>ADP_FLOAT</td>
      </tr>
    """
    # Match each <tr> block
    row_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
    name_pattern = re.compile(r'fp-player-name="([^"]+)"')
    team_pattern = re.compile(r'</a>\s*<small>([A-Z]+)</small>')
    pos_rank_pattern = re.compile(r'<td>([A-Z]+)(\d+)</td>')

    players = []
    seen = set()

    for row_m in row_pattern.finditer(html):
        row = row_m.group(1)

        name_m = name_pattern.search(row)
        if not name_m:
            continue
        name = name_m.group(1)

        team_m = team_pattern.search(row)
        if not team_m:
            continue
        team = TEAM_FIX.get(team_m.group(1), team_m.group(1))

        pos_rank_m = pos_rank_pattern.search(row)
        if not pos_rank_m:
            continue
        pos = pos_rank_m.group(1)
        pos_rank = int(pos_rank_m.group(2))

        if pos not in POSITIONS:
            continue

        # Last float <td> is the ADP
        tds = re.findall(r'<td[^>]*>([\d.]+)</td>', row)
        if not tds:
            continue
        adp = float(tds[-1])

        norm_name = name.lower().replace("'","").replace(".","").replace("-","").replace(" ","")
        if norm_name in seen:
            continue
        seen.add(norm_name)

        players.append({
            "name": name,
            "team": team,
            "position": pos,
            "overall_adp": adp,
            "pos_adp_rank": pos_rank,
        })

    return players

url = 'https://web.archive.org/web/20240901120000/https://www.fantasypros.com/nfl/adp/ppr-overall.php'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=30) as resp:
    html = resp.read().decode('utf-8', errors='replace')

players = parse_adp_html(html)
print(f"Parsed {len(players)} players")
for p in players[:10]:
    print(p)
