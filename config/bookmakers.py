"""
Casas de apuestas con licencia DGOJ activa en España.
Solo estas aparecerán en las alertas cuando SPAIN_ONLY=True.

Fuente: DGOJ (Dirección General de Ordenación del Juego)
https://www.ordenacionjuego.es/es/operadores-juego

Los nombres están en minúsculas y se comparan contra la clave (key)
y el título (title) que devuelve The Odds API.
Puedes añadir o quitar casas editando este archivo.
"""

# ── Casas confirmadas con licencia DGOJ ───────────────────────────────────────
DGOJ_LICENSED: set[str] = {
    # Grandes internacionales con licencia española
    "bet365",
    "william hill",
    "williamhill",
    "bwin",
    "betfair",
    "betfair exchange",
    "betfair_ex_eu",
    "betway",
    "unibet",
    "unibet_eu",
    "888sport",
    "sport888",
    "winamax",
    "betsson",
    "casumo",
    "leovegas",
    "mr green",
    "mrgreen",
    "pokerstars",
    "pokerstars sports",
    "interwetten",
    "betclic",
    "marathonbet",     # tiene licencia DGOJ desde 2015
    "ladbrokes",
    "coral",
    "paddy power",
    "paddypower",

    # Casas específicamente españolas (pueden no aparecer en The Odds API)
    "codere",
    "sportium",
    "luckia",
    "paston",
    "wanabet",
    "marca apuestas",
    "retabet",
    "betobet",
    "paf",
    "coolbet",
}

# ── Casas SIN licencia española — EXCLUIDAS aunque aparezcan en la API ────────
# (Se muestran aquí para referencia / documentación)
_NOT_SPAIN: set[str] = {
    "pinnacle",          # Curaçao — no opera en España
    "nordicbet",         # Sin DGOJ
    "suprabets",         # Sin DGOJ
    "draftkings",        # Solo EEUU
    "fanduel",           # Solo EEUU
    "bovada",            # Solo EEUU
    "mybookieag",        # Sin DGOJ
    "betonlineag",       # Sin DGOJ
    "lowvig",            # Sin DGOJ
    "gtbets",            # Sin DGOJ
    "intertops",         # Sin DGOJ
}


def is_spain_licensed(bookmaker_name: str) -> bool:
    """Devuelve True si la casa tiene licencia DGOJ."""
    name_low = bookmaker_name.lower().strip()
    return any(licensed in name_low or name_low in licensed for licensed in DGOJ_LICENSED)
