import logging

import requests

from config.settings import settings
from data.models import ArbOpportunity

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


def send_alert(opp: ArbOpportunity) -> bool:
    return _send(format_alert(opp))


def send_startup() -> bool:
    text = (
        "🚀 <b>Sentinel World — iniciado</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Monitorizando: <b>{_html(settings.LEAGUE_FILTER or settings.SPORT_FILTER)}</b>\n"
        f"💶 Bankroll: <b>€{settings.BANKROLL:.2f}</b>\n"
        f"📊 Margen mínimo: <b>{settings.MIN_ARB_MARGIN}%</b>\n"
        f"⏱ Intervalo: <b>{settings.SCAN_INTERVAL}s</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Recibirás alertas cuando detecte oportunidades de arbitraje</i>"
    )
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
