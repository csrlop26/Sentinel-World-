import logging

import requests

from config.settings import settings
from data.models import ArbOpportunity, MiddleOpportunity, ValueBet

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"

_OUTCOME_EMOJI: dict[str, str] = {
    # 1x2
    "home": "🟢", "1": "🟢",
    "draw": "🟡", "x": "🟡",
    "away": "🔴", "2": "🔴",
    # Over/Under
    "over": "⬆️", "under": "⬇️",
    # BTTS
    "yes": "✅", "no": "❌",
}


def _outcome_emoji(outcome: str) -> str:
    key = outcome.lower().split()[0]
    return _OUTCOME_EMOJI.get(key, "⚪")


def _html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_MARKET_EMOJI: dict[str, str] = {
    "1×2":          "🏆",
    "ambos marcan": "🥅",
}


def _market_header(opp: ArbOpportunity) -> str:
    market = opp.market
    low = market.lower()
    if "más/menos" in low or "totals" in low:
        return f"⚽ <b>ARBITRAJE — {_html(market)}</b>"
    if "ambos" in low or "btts" in low:
        return f"🥅 <b>ARBITRAJE — {_html(market)}</b>"
    return "🏆 <b>ARBITRAJE — 1×2</b>"


def format_alert(opp: ArbOpportunity) -> str:
    lines = [
        f"🎯 {_market_header(opp)}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚽ <b>{_html(opp.event_name)}</b>",
    ]
    if opp.league:
        lines.append(f"🏅 {_html(opp.league)}")
    if opp.commence_time:
        lines.append(f"📅 {_html(opp.commence_time)}")

    lines += [
        "",
        f"📈 <b>MARGEN: +{opp.margin_pct:.2f}% GARANTIZADO</b>",
        "",
        f"💶 <b>APUESTAS  (Bankroll: €{opp.bankroll:.2f})</b>",
    ]

    for i, leg in enumerate(opp.legs):
        is_last = i == len(opp.legs) - 1
        prefix = "└" if is_last else "├"
        emoji = _outcome_emoji(leg.outcome)
        lines.append(f"{prefix} {emoji} <b>{_html(leg.outcome)}</b>")
        lines.append(f"│   Casa: {_html(leg.bookmaker)}  ·  Cuota: {leg.odds}")
        lines.append(f"│   💰 Apostar: <b>€{leg.stake:.2f}</b>")
        if not is_last:
            lines.append("│")

    total_staked = sum(l.stake for l in opp.legs)
    lines += [
        "",
        f"📊 Total invertido: €{total_staked:.2f}",
        f"💵 Ganancia mínima: <b>+€{opp.min_profit:.2f}  (+{opp.margin_pct:.2f}%)</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Actúa en los próximos 5–10 minutos</i>",
    ]

    return "\n".join(lines)


def _send(text: str) -> bool:
    url = f"{_TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


# ── Polling de comandos ───────────────────────────────────────────────────────

_last_update_id: int = 0


def init_command_polling() -> None:
    """
    Descarta todos los mensajes pendientes antes de arrancar el bot,
    para que comandos viejos no se ejecuten al reiniciar.
    """
    global _last_update_id
    url = f"{_TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": -1, "limit": 1}, timeout=5)
        resp.raise_for_status()
        results = resp.json().get("result", [])
        if results:
            _last_update_id = results[-1]["update_id"]
            logger.info(f"Telegram polling inicializado (skip hasta update_id={_last_update_id})")
    except Exception as e:
        logger.debug(f"Telegram init polling: {e}")


def check_commands() -> list[str]:
    """
    Devuelve los comandos (/middle, /arb, etc.) enviados al bot desde el
    último check, solo aceptando mensajes del TELEGRAM_CHAT_ID configurado.
    """
    global _last_update_id
    url = f"{_TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {
        "offset": _last_update_id + 1,
        "limit": 20,
        "timeout": 1,
        "allowed_updates": ["message"],
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except Exception as e:
        logger.debug(f"Telegram getUpdates: {e}")
        return []

    commands: list[str] = []
    for upd in updates:
        _last_update_id = max(_last_update_id, upd["update_id"])
        msg = upd.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id == str(settings.TELEGRAM_CHAT_ID) and text.startswith("/"):
            cmd = text.split()[0].lower().split("@")[0]  # /middle@botname → /middle
            commands.append(cmd)

    return commands


def format_middle_alert(opp: MiddleOpportunity) -> str:
    total_staked = opp.stake_each * 2

    lines = [
        "🎯 <b>MIDDLE — VENTANA DE GOLES</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚽ <b>{_html(opp.event_name)}</b>",
    ]
    if opp.league:
        lines.append(f"🏅 {_html(opp.league)}")
    if opp.commence_time:
        lines.append(f"📅 {_html(opp.commence_time)}")

    lines += [
        "",
        f"🔮 <b>Ventana: exactamente {opp.middle_goal} goles → AMBAS GANAN</b>",
        f"📊 Prob. implícita del middle: <b>{opp.implied_middle_prob}%</b>",
        "",
        f"💶 <b>APUESTAS  (€{opp.stake_each:.2f} por lado)</b>",
        f"├ ⬆️ <b>Over {opp.over_line}</b>",
        f"│   Casa: {_html(opp.over_bookmaker)}  ·  Cuota: {opp.over_odds}",
        f"│   💰 Apostar: <b>€{opp.stake_each:.2f}</b>",
        "│",
        f"└ ⬇️ <b>Under {opp.under_line}</b>",
        f"    Casa: {_html(opp.under_bookmaker)}  ·  Cuota: {opp.under_odds}",
        f"    💰 Apostar: <b>€{opp.stake_each:.2f}</b>",
        "",
        f"📈 <b>ESCENARIOS  (invertido: €{total_staked:.2f})</b>",
        f"  🎯 = {opp.middle_goal} goles:  <b>+€{opp.both_win_profit:.2f}  AMBAS GANAN</b>",
    ]

    ov = opp.over_wins_result
    un = opp.under_wins_result
    lines.append(
        f"  ⬆️ &gt; {opp.under_line} goles: "
        + (f"<b>+€{ov:.2f}</b>" if ov >= 0 else f"-€{abs(ov):.2f}")
    )
    lines.append(
        f"  ⬇️ &lt; {opp.over_line} goles: "
        + (f"<b>+€{un:.2f}</b>" if un >= 0 else f"-€{abs(un):.2f}")
    )

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Apuesta ambos lados antes del partido</i>",
    ]
    return "\n".join(lines)


def format_value_alert(vb: ValueBet) -> str:
    true_pct = round(vb.true_prob * 100, 1)
    implied_pct = round(100 / vb.odds, 1)

    lines = [
        f"📊 <b>VALUE BET +{vb.edge_pct:.1f}% — {_html(vb.market)}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚽ <b>{_html(vb.event_name)}</b>",
    ]
    if vb.league:
        lines.append(f"🏅 {_html(vb.league)}")
    if vb.commence_time:
        lines.append(f"📅 {_html(vb.commence_time)}")

    lines += [
        "",
        f"🎯 Apuesta: <b>{_html(vb.outcome)}</b>",
        f"🏪 Casa: <b>{_html(vb.bookmaker)}</b>",
        f"💲 Cuota: <b>{vb.odds}</b>",
        "",
        "📊 <b>ANÁLISIS DE VALOR</b>",
        f"  Prob. real ({_html(vb.sharp_ref)}): <b>{true_pct}%</b>",
        f"  Prob. implícita en casa: {implied_pct}%",
        f"  Edge: <b>+{vb.edge_pct:.1f}%</b>",
        "",
        f"💰 <b>STAKE (¼ Kelly)</b>",
        f"  Apostar: <b>€{vb.stake:.2f}</b>  ({vb.kelly_pct:.1f}% bankroll)",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Actúa antes del partido</i>",
    ]
    return "\n".join(lines)


def send_alert(opp: ArbOpportunity) -> bool:
    return _send(format_alert(opp))


def send_middle_alert(opp: MiddleOpportunity) -> bool:
    return _send(format_middle_alert(opp))


def send_value_alert(vb: ValueBet) -> bool:
    return _send(format_value_alert(vb))


def send_startup() -> bool:
    text = (
        "🚀 <b>Sentinel World — iniciado</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Monitorizando: <b>{_html(settings.LEAGUE_FILTER or settings.SPORT_FILTER)}</b>\n"
        f"💶 Bankroll: <b>€{settings.BANKROLL:.2f}</b>\n"
        f"📊 Margen mínimo: <b>{settings.MIN_ARB_MARGIN}%</b>\n"
        f"⏱ Intervalo: <b>{settings.SCAN_INTERVAL}s</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📨 <b>Comandos disponibles:</b>\n"
        "  /value  — buscar value bets (+EV) ahora\n"
        "  /middle — buscar ventanas de goles ahora\n"
        "  /arb    — forzar escaneo de arbitrajes\n"
        "  /status — ver estado del bot\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Recibirás alertas automáticas de arbitraje y value bets</i>"
    )
    return _send(text)


def send_text(text: str) -> bool:
    return _send(text)


def send_no_bookmakers_warning() -> bool:
    text = (
        "⚠️ <b>Aviso: plan gratuito limitado</b>\n\n"
        "El plan free de odds-api.net sólo incluye <b>2 casas</b>.\n"
        "Con 2 bookmakers las oportunidades de arb son muy raras.\n\n"
        "💡 <b>Solución recomendada:</b>\n"
        "Consigue también una key gratuita de <b>The Odds API</b>\n"
        "(the-odds-api.com · 500 req/mes gratis · más bookmakers)\n"
        "y añádela al .env como <code>THEODDS_API_KEY</code>"
    )
    return _send(text)
