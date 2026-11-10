#!/usr/bin/env python3
# Futbol Champain Scores — interfaz Pygame + datos deportivos de 365Scores
# Instalar: python -m pip install pygame
# Ejecutar: python Futbol_Champain_Scores.py
# Todas las secciones deportivas consultan 365Scores; el catálogo y las consultas toleran envoltorios JSON variables.
# Build: feed /games/current + /games/allscores, estado EN VIVO robusto, tablas y goleadores.

import os, json, webbrowser, threading, queue, urllib.request, urllib.parse, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

APP_NAME="Futbol Champain Scores"
WIDTH,HEIGHT=1240,820
# Paleta inspirada en el logo del canal: césped, blanco, negro y dorado.
BG=(7,25,13); PANEL=(13,39,21); PANEL2=(20,53,29); BORDER=(43,91,49)
WHITE=(250,252,247); MUTED=(174,195,174); GREEN=(52,184,75); GOLD=(251,212,57); CYAN=(191,232,193); RED=(255,103,120)

TABS=["Resultados","En vivo","Clasificaciones","Buscar","Favoritos"]

# Fuente deportiva única: 365Scores (webws público, sin clave API).
SCORES365_BASE = "https://webws.365scores.com/web/"
SCORES365_PARAMS = {
    "appTypeId": "5",
    "langId": "14",
    "timezoneName": "America/Argentina/Buenos_Aires",
    "userCountryId": "382",
}
SCORES365_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
    "Origin": "https://www.365scores.com",
    "Referer": "https://www.365scores.com/",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.7",
    "Accept-Encoding": "gzip",
}

def scores365_request(endpoint, params=None, timeout=7):
    query = dict(SCORES365_PARAMS)
    if params:
        query.update({k: str(v) for k, v in params.items() if v is not None})
    url = SCORES365_BASE + endpoint.strip("/") + "/?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers=SCORES365_HEADERS)
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                if response.info().get("Content-Encoding", "").lower() == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            last_error = exc
            if attempt < 1:
                time.sleep(0.2)
    raise RuntimeError(f"365Scores no respondió: {last_error}")


_COMPETITIONS_CACHE = {"time": 0.0, "items": []}
_COMPETITIONS_LOCK = threading.Lock()

def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # Algunos endpoints agrupan las colecciones por país/deporte.
        for key in ("items", "competitions", "rows", "data"):
            if isinstance(value.get(key), list):
                return value[key]
        return list(value.values())
    return []

def _walk_dicts(value):
    """Recorre envoltorios variables de la API sin perder colecciones anidadas."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _extract_games(payload):
    """Extrae partidos aunque 365Scores cambie el nivel del envoltorio JSON."""
    found = []
    seen_objects = set()
    for obj in _walk_dicts(payload):
        if obj.get("homeCompetitor") and obj.get("awayCompetitor"):
            marker = str(obj.get("id") or id(obj))
            if marker not in seen_objects:
                seen_objects.add(marker)
                found.append(obj)
    return found


def _extract_competitions(payload):
    """Extrae competiciones desde sports/competitions aunque falten flags opcionales."""
    found, seen = [], set()
    for obj in _walk_dicts(payload):
        cid, name = obj.get("id"), obj.get("name")
        # Los objetos de competición suelen incluir nameForURL, countryId o season.
        looks_like_comp = bool(cid and name and (
            "nameForURL" in obj or "countryId" in obj or "currentSeasonNum" in obj
            or "hasStandings" in obj or "hasStats" in obj or "sportId" in obj
        ))
        if looks_like_comp:
            sid = obj.get("sportId", 1)
            if sid not in (None, 1, "1"):
                continue
            marker = str(cid)
            if marker not in seen:
                seen.add(marker)
                found.append(obj)
    return found


def scores365_competitions(force=False):
    """Catálogo de fútbol completo disponible en 365Scores, no solo destacados."""
    now = time.time()
    with _COMPETITIONS_LOCK:
        if not force and _COMPETITIONS_CACHE["items"] and now - _COMPETITIONS_CACHE["time"] < 3600:
            return list(_COMPETITIONS_CACHE["items"])

    competitions = []
    # /sports devuelve deportes, países y competiciones; /competitions aporta el catálogo.
    for endpoint, params in (
        ("sports", {"withSeasons": "true"}),
        ("competitions/featured", {"sports": 1, "withSeasons": "true"}),
    ):
        try:
            payload = scores365_request(endpoint, params)
            competitions.extend(_extract_competitions(payload))
        except Exception:
            continue

    unique = {}
    for comp in competitions:
        sport_id = comp.get("sportId")
        if sport_id not in (None, 1, "1"):
            continue
        unique[str(comp["id"])] = comp
    result = sorted(
        unique.values(),
        key=lambda c: (-(c.get("popularityRank") or 0), (c.get("name") or "").casefold())
    )
    with _COMPETITIONS_LOCK:
        if result:
            _COMPETITIONS_CACHE.update(time=now, items=result)
        cached = list(_COMPETITIONS_CACHE["items"])
    return result or cached

def scores365_logo(competitor):
    """Obtiene el escudo desde la URL entregada por 365Scores o su CDN."""
    if not isinstance(competitor, dict):
        return ""
    for key in ("imageUrl", "imageURL", "logo", "image", "url"):
        value = competitor.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    cid = competitor.get("id")
    version = competitor.get("imageVersion", 1)
    if cid:
        return f"https://imagecache.365scores.com/image/upload/f_png,w_100,h_100,c_limit,q_auto:eco,d_Competitors:default1.png/v{version}/Competitors/{cid}"
    return ""


def scores365_game_to_match(game):
    home = game.get("homeCompetitor") or {}
    away = game.get("awayCompetitor") or {}
    status_obj = game.get("status") if isinstance(game.get("status"), dict) else {}
    raw_group = game.get("statusGroup", game.get("status_group", status_obj.get("group", 2)))
    try:
        status_group = int(raw_group)
    except (TypeError, ValueError):
        status_group = -1
    status_text_raw = " ".join(str(game.get(k) or "") for k in
        ("statusText", "shortStatusText", "gameTimeDisplay", "periodName", "statusDescription"))
    status_text_fold = status_text_raw.casefold()
    live_words = (
        "live", "in progress", "1st half", "2nd half", "first half", "second half",
        "half time", "halftime", "extra time", "penalties", "en vivo",
        "primer tiempo", "segundo tiempo", "entretiempo", "descanso",
        "1er tiempo", "2do tiempo", "prórroga", "penales", "penaltis",
    )
    live_flag = game.get("isLive") is True or game.get("live") is True
    # La API usa statusGroup=1 para directo. También se reconocen los textos de estado.
    if status_group == 1 or live_flag or any(word in status_text_fold for word in live_words):
        state = "in"
    elif status_group in (2, 3) or status_group < 0:
        state = "pre"
    else:
        state = "post"
    home_score = home.get("score")
    away_score = away.get("score")
    if home_score is None:
        home_score = game.get("homeScore", game.get("home_score"))
    if away_score is None:
        away_score = game.get("awayScore", game.get("away_score"))
    score_block = game.get("scores") or game.get("score") or {}
    if isinstance(score_block, dict):
        home_score = home_score if home_score is not None else score_block.get("home", score_block.get("homeScore"))
        away_score = away_score if away_score is not None else score_block.get("away", score_block.get("awayScore"))
    def clean_score(value):
        # 365Scores usa -1 como valor centinela cuando todavía no hay marcador.
        # Un gol real nunca puede ser negativo: no mostrar ese -1 en pantalla.
        if value is None or value == "":
            return None
        try:
            number = float(value)
            if number < 0:
                return None
            return str(int(number)) if number.is_integer() else str(number)
        except (TypeError, ValueError):
            text = str(value).strip()
            return None if text in ("-1", "-1.0") else text
    if state == "pre":
        home_score = away_score = None
    else:
        home_score = clean_score(home_score)
        away_score = clean_score(away_score)
    start_time = game.get("startTime", "")
    try:
        parsed = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        local_time = parsed.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M")
    except Exception:
        local_time = game.get("gameTimeDisplay") or ""
    competition = game.get("competitionDisplayName") or game.get("competitionName") or (game.get("competition") or {}).get("name") or "Fútbol"
    status = game.get("gameTimeDisplay") or game.get("shortStatusText") or game.get("statusText") or ""
    if state == "in" and not status:
        status = "EN VIVO"
    return {
        "kind": "score",
        "title": f"{home.get('name', 'Local')} {home_score if home_score is not None else ''} - {away_score if away_score is not None else ''} {away.get('name', 'Visitante')}",
        "home": home.get("name") or "Local",
        "away": away.get("name") or "Visitante",
        "home_score": home_score, "away_score": away_score,
        "status": status, "state": state, "status_group": status_group,
        "league": competition, "time": local_time,
        "home_logo": scores365_logo(home), "away_logo": scores365_logo(away),
        "game_id": game.get("id"), "competition_id": game.get("competitionId"),
        "season_num": game.get("seasonNum"), "stage_num": game.get("stageNum"),
        "url": f"https://www.365scores.com/es/football/match?id={game.get('id')}" if game.get("id") else "",
        "snippet": f"{competition} · {status}", "display": competition,
    }


def football_scores(day, live_only=False, team_filter=""):
    """Combina el calendario diario y el feed actual de 365Scores para no perder partidos en vivo."""
    raw_games = []
    errors = []
    date_text = day.strftime("%d/%m/%Y")

    # El feed de fecha aporta partidos programados y finalizados de todas las ligas.
    try:
        payload = scores365_request("games/allscores", {
            "sports": 1,
            "startDate": date_text,
            "endDate": date_text,
            "showOdds": "false",
            "onlyMajorGames": "false",
            "withTop": "true",
        })
        raw_games.extend(_extract_games(payload))
    except Exception as exc:
        errors.append(str(exc))

    # /games/current es el feed de partidos actuales y próximos; es esencial para En vivo.
    today_local = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    if day == today_local:
        try:
            current_payload = scores365_request("games/current", {
                "sports": 1,
                "showOdds": "false",
                "onlyMajorGames": "false",
                "withTop": "true",
                "numberOfGames": 500,
            })
            raw_games.extend(_extract_games(current_payload))
        except Exception as exc:
            errors.append(str(exc))

    matches = []
    seen = set()
    for game in raw_games:
        item = scores365_game_to_match(game)
        game_id = item.get("game_id")
        marker = str(game_id) if game_id is not None else (
            item["home"], item["away"], item["time"], item["league"]
        )
        if marker in seen:
            continue
        seen.add(marker)
        if live_only and item["state"] != "in":
            continue
        if team_filter and team_filter.casefold() not in (
            item["home"] + " " + item["away"] + " " + item["league"]
        ).casefold():
            continue
        matches.append(item)
    matches.sort(key=lambda x: (0 if x["state"] == "in" else 1, x["time"], x["league"], x["home"]))
    # Si fallaron ambas fuentes, informa el error en vez de simular una lista vacía.
    if not matches and errors and len(errors) >= (2 if day == today_local else 1):
        raise RuntimeError("No se pudo consultar el feed de partidos de 365Scores: " + errors[-1])
    return matches, len(errors)


def _norm_text(value):
    import unicodedata, re
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def football_scores_range(start_day, end_day, team_filter=""):
    """Busca por nombre normalizado en bloques de 7 días; un fallo no cancela los demás."""
    combined, errors = {}, []
    cursor = start_day
    needle = _norm_text(team_filter)
    while cursor <= end_day:
        chunk_end = min(end_day, cursor + timedelta(days=6))
        try:
            payload = scores365_request("games/allscores", {
                "sports": 1, "startDate": cursor.strftime("%d/%m/%Y"),
                "endDate": chunk_end.strftime("%d/%m/%Y"),
                "showOdds": "false", "onlyMajorGames": "false", "withTop": "true",
            })
            for game in _extract_games(payload):
                item = scores365_game_to_match(game)
                searchable = _norm_text(" ".join((item["home"], item["away"], item["league"])))
                if needle and needle not in searchable:
                    # admite búsqueda por palabras en distinto orden
                    tokens = [t for t in needle.split() if len(t) > 1]
                    if not tokens or not all(t in searchable for t in tokens):
                        continue
                key = str(item.get("game_id") or (item["home"], item["away"], item["time"], item["league"]))
                combined[key] = item
        except Exception as exc:
            errors.append(str(exc))
        cursor = chunk_end + timedelta(days=1)
        if cursor <= end_day:
            time.sleep(0.15)
    ordered = sorted(combined.values(), key=lambda x: (x["time"], x["league"], x["home"]))
    return ordered, len(errors)


def search_365scores(query, reference_day):
    """Busca partidos, equipos, competiciones y jugadores con datos disponibles en 365Scores."""
    needle = _norm_text(query)
    results, errors = [], 0
    # Primero partidos del período; permite buscar clubes aunque no jueguen hoy.
    matches, err = football_scores_range(reference_day - timedelta(days=30), reference_day + timedelta(days=90), query)
    results.extend(matches); errors += err

    # Competiciones: catálogo de 365Scores, no un buscador web externo.
    try:
        for comp in scores365_competitions():
            name = comp.get("name") or ""
            if needle and needle in _norm_text(name):
                results.append({"kind":"info", "title":name, "display":"Competición de 365Scores",
                    "snippet":f"ID {comp.get('id')} · {comp.get('countryName') or comp.get('countryId') or 'Fútbol'}",
                    "url":f"https://www.365scores.com/es/football/league/{comp.get('nameForURL','')}?competitions={comp.get('id')}"})
    except Exception:
        errors += 1

    # Equipos destacados/nacionales del catálogo oficial de competidores.
    try:
        payload = scores365_request("competitors/top", {"limit":100, "promoteNational":"true", "withSeasons":"true", "isDashboard":"true"})
        for obj in _walk_dicts(payload):
            name = obj.get("name")
            cid = obj.get("id")
            if name and cid and needle in _norm_text(name):
                results.append({"kind":"info", "title":name, "display":"Equipo de 365Scores",
                    "snippet":f"Equipo ID {cid}", "url":f"https://www.365scores.com/es/football/team/{cid}"})
    except Exception:
        errors += 1

    unique, seen = [], set()
    for row in results:
        key = row.get("game_id") or row.get("url") or row.get("title")
        if key not in seen:
            seen.add(key); unique.append(row)
    return unique, errors


def _competition_sort_key(comp):
    rank = comp.get("popularityRank") or 0
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = 0
    return (not bool(comp.get("isActive", False)), -rank, (comp.get("name") or "").casefold())


def league_standings(competition_filter=""):
    """Obtiene las tablas completas de las competiciones disponibles en 365Scores."""
    competitions = scores365_competitions()
    try:
        todays, _ = football_scores(datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date())
        by_id = {str(c.get("id")): c for c in competitions}
        for match in todays:
            cid = match.get("competition_id")
            if cid and str(cid) not in by_id:
                by_id[str(cid)] = {
                    "id": cid, "name": match.get("league") or "Competición",
                    "currentSeasonNum": match.get("season_num"),
                    "currentStageNum": match.get("stage_num"),
                    "hasStandings": True
                }
        competitions = list(by_id.values())
    except Exception:
        pass

    competitions = [
        c for c in competitions
        if c.get("hasStandings") is not False
        and (c.get("hasStandings") or c.get("currentSeasonNum") or c.get("seasons"))
    ]
    if competition_filter:
        needle = _norm_text(competition_filter)
        competitions = [c for c in competitions if needle in _norm_text(c.get("name", ""))]
    competitions.sort(key=_competition_sort_key)

    rows, errors = [], 0
    # No truncar a 35: así se recuperan todas las filas de las ligas disponibles.
    for comp in competitions:
        cid = comp.get("id")
        if not cid:
            continue
        try:
            params = {
                "competitions": cid,
                "live": "false",
                "isPreview": "true",
                "stageNum": comp.get("currentStageNum") or 1,
                "seasonNum": comp.get("currentSeasonNum"),
            }
            payload = scores365_request("standings", params)
            tables = payload.get("standings", []) if isinstance(payload, dict) else []
            if isinstance(tables, dict):
                tables = list(tables.values())
            if not isinstance(tables, list):
                tables = []
            if not tables:
                tables = [
                    obj for obj in _walk_dicts(payload)
                    if isinstance(obj.get("rows"), (list, dict))
                ]

            for table in tables:
                if not isinstance(table, dict):
                    continue
                table_name = (
                    table.get("displayName") or table.get("name")
                    or table.get("groupName") or comp.get("name") or "Liga"
                )
                table_rows = table.get("rows", [])
                if isinstance(table_rows, dict):
                    table_rows = list(table_rows.values())
                if not isinstance(table_rows, list):
                    continue

                for index, row in enumerate(table_rows, 1):
                    if not isinstance(row, dict):
                        continue
                    team = row.get("competitor") or row.get("entity") or {}
                    if not isinstance(team, dict):
                        team = {}

                    def first_value(*values, default="-"):
                        for value in values:
                            if value is not None and value != "":
                                return value
                        return default

                    name = first_value(
                        team.get("name"), team.get("displayName"),
                        row.get("competitorName"), row.get("name"), default="Equipo"
                    )
                    position = first_value(row.get("position"), row.get("rank"), default=index)
                    played = first_value(row.get("gamePlayed"), row.get("gamesPlayed"), row.get("played"), row.get("matchesPlayed"))
                    won = first_value(row.get("gamesWon"), row.get("won"), row.get("wins"))
                    drawn = first_value(row.get("gamesEven"), row.get("drawn"), row.get("draws"))
                    lost = first_value(row.get("gamesLost"), row.get("lost"), row.get("losses"))
                    gf = first_value(row.get("goalsFor"), row.get("for"), row.get("goalsScored"))
                    ga = first_value(row.get("goalsAgainst"), row.get("against"), row.get("goalsConceded"))
                    gd = first_value(row.get("goalDifference"), row.get("goalsDiff"), row.get("difference"), row.get("ratio"))
                    points = first_value(row.get("points"), row.get("totalPoints"), row.get("score"))
                    rows.append({
                        "kind": "standing",
                        "position": position,
                        "team": str(name),
                        "played": played, "won": won, "drawn": drawn, "lost": lost,
                        "gf": gf, "ga": ga, "gd": gd, "points": points,
                        "display": str(comp.get("name") or table_name),
                        "group": str(table_name) if table_name and table_name != comp.get("name") else "",
                        "team_logo": scores365_logo(team),
                        "url": f"https://www.365scores.com/es/football/league/{comp.get('nameForURL','')}?competitions={cid}",
                    })
        except Exception:
            errors += 1
        time.sleep(0.12)

    # Elimina equipos repetidos entre tablas/grupos y construye una numeración
    # continua para toda la competición (365Scores reinicia POS en cada grupo).
    unique, seen = [], set()
    for row in rows:
        key = (row["display"], _norm_text(row["team"]))
        if key not in seen:
            seen.add(key)
            unique.append(row)

    def as_number(value):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return 0.0

    by_league = {}
    for row in unique:
        by_league.setdefault(row["display"], []).append(row)
    ranked = []
    for league_name, league_rows in by_league.items():
        # Orden de tabla: puntos, diferencia de gol, goles a favor y victorias.
        league_rows.sort(key=lambda r: (
            -as_number(r.get("points")), -as_number(r.get("gd")),
            -as_number(r.get("gf")), -as_number(r.get("won")),
            as_number(r.get("position")), _norm_text(r.get("team", ""))
        ))
        for rank, row in enumerate(league_rows, 1):
            row["position"] = rank
            ranked.append(row)
    return ranked, errors


