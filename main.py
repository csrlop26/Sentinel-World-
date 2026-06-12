"""
Sentinel World — Bot de Arbitraje Deportivo
Encuentra oportunidades de apuesta sin riesgo en tiempo real.
"""

import argparse
import logging
import sys
import time

from config.bookmakers import is_spain_licensed
from config.settings import settings
from core.fetcher import get_events, get_leagues, get_sports
from core.fetcher_theodds import get_world_cup_events
from core.scanner import scan, scan_middles, scan_value_bets
from data.tracker import ArbitrageTracker
from notifiers.telegram import (
    check_commands,
    init_command_polling,
    send_alert,
    send_middle_alert,
    send_startup,
    send_text,
    send_value_alert,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sentinel.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("sentinel")


def _handle_command(cmd: str, tracker: "ArbitrageTracker") -> None:
    """Ejecuta un comando recibido por Telegram."""
    if cmd == "/middle":
        send_text("🔍 <i>Buscando middles ahora mismo...</i>")
        middles = scan_middles()
        if not middles:
            send_text("ℹ️ No hay middles disponibles en este momento.")
            logger.info("Comando /middle — sin resultados")
            return
        for mid in middles:
            send_middle_alert(mid)
            logger.info(
                f"MIDDLE (manual) | {mid.event_name}"
                f" | Over {mid.over_line} + Under {mid.under_line}"
            )
        send_text(f"✅ <b>{len(middles)} middle(s) encontrados.</b>")

    elif cmd == "/arb":
        send_text("🔍 <i>Forzando escaneo de arbitrajes...</i>")
        opportunities = scan()
        new_opps = [o for o in opportunities if not tracker.seen(o)]
        if not new_opps:
            send_text(
                f"ℹ️ Sin arbitrajes nuevos ahora mismo "
                f"({len(opportunities)} revisados)."
            )
        for opp in new_opps:
            ok = send_alert(opp)
            if ok:
                tracker.mark_seen(opp)

    elif cmd == "/value":
        send_text("🔍 <i>Buscando value bets ahora mismo...</i>")
        value_bets = scan_value_bets()
        if not value_bets:
            send_text("ℹ️ Sin value bets disponibles ahora mismo.")
            logger.info("Comando /value — sin resultados")
            return
        for vb in value_bets[:10]:  # máximo 10 para no saturar
            send_value_alert(vb)
            logger.info(f"VALUE (manual) | {vb.event_name} | {vb.outcome} @ {vb.bookmaker} | edge {vb.edge_pct:.1f}%")
        if len(value_bets) > 10:
            send_text(f"ℹ️ +{len(value_bets) - 10} más — sube MIN_VALUE_EDGE para filtrar.")
        send_text(f"✅ <b>{len(value_bets)} value bet(s) encontradas.</b>")

    elif cmd == "/status":
        from core.fetcher_theodds import _working_markets, _WORLD_CUP_KEY
        wc = list(_working_markets.keys()) or [_WORLD_CUP_KEY]
        send_text(
            "📊 <b>Estado del bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💶 Bankroll: €{settings.BANKROLL:.2f}\n"
            f"📊 Margen mín: {settings.MIN_ARB_MARGIN}%\n"
            f"🏆 Deporte: {settings.LEAGUE_FILTER or settings.SPORT_FILTER}\n"
            f"🔑 Filtro DGOJ: {'✓' if settings.SPAIN_ONLY else '✗'}\n"
            f"⏱ Intervalo: {settings.SCAN_INTERVAL}s\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Edge mínimo: {settings.MIN_VALUE_EDGE}%\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📨 /value · /middle · /arb · /status"
        )

    else:
        send_text(
            f"❓ Comando no reconocido: <code>{cmd}</code>\n\n"
            "Comandos disponibles:\n"
            "  /value  — buscar value bets (+EV)\n"
            "  /middle — buscar ventanas de goles\n"
            "  /arb    — forzar escaneo de arbitrajes\n"
            "  /status — ver estado del bot"
        )


def cmd_run():
    """Main loop: scan and alert on arbitrage opportunities."""
    logger.info("=" * 55)
    logger.info("  SENTINEL WORLD — Bot de Arbitraje Deportivo")
    logger.info("=" * 55)
    logger.info(f"  Bankroll        : €{settings.BANKROLL:.2f}")
    logger.info(f"  Margen mínimo   : {settings.MIN_ARB_MARGIN}%")
    logger.info(f"  Margen máximo   : {settings.MAX_ARB_MARGIN}%")
    logger.info(f"  Deporte/Liga    : {settings.SPORT_FILTER} / {settings.LEAGUE_FILTER}")
    logger.info(f"  Filtro España   : {'✓ Solo casas DGOJ' if settings.SPAIN_ONLY else '✗ Todas las casas'}")
    logger.info(f"  Intervalo       : {settings.SCAN_INTERVAL}s")
    logger.info("=" * 55)

    init_command_polling()
    send_startup()
    tracker = ArbitrageTracker()

    scan_n = 0
    total_alerts = 0

    while True:
        scan_n += 1
        logger.info(f"--- Scan #{scan_n} ---")

        try:
            # ── Comandos del usuario vía Telegram ───────────────────────────
            for cmd in check_commands():
                logger.info(f"Comando recibido: {cmd}")
                _handle_command(cmd, tracker)

            # ── Arbitrajes garantizados (automáticos) ───────────────────────
            opportunities = scan()
            new_opps = [o for o in opportunities if not tracker.seen(o)]

            for opp in new_opps:
                ok = send_alert(opp)
                if ok:
                    tracker.mark_seen(opp)
                    total_alerts += 1
                    logger.info(
                        f"ARB ENVIADO | {opp.event_name}"
                        f" | +{opp.margin_pct:.2f}%"
                        f" | ganancia ≥ +€{opp.min_profit:.2f}"
                    )

            # ── Value bets (+EV, automáticas) ──────────────────────────────
            value_bets = scan_value_bets()
            new_values = [v for v in value_bets if not tracker.seen(v)]

            for vb in new_values:
                ok = send_value_alert(vb)
                if ok:
                    tracker.mark_seen(vb)
                    total_alerts += 1
                    logger.info(
                        f"VALUE ENVIADO | {vb.event_name}"
                        f" | {vb.outcome} @ {vb.bookmaker}"
                        f" | edge +{vb.edge_pct:.1f}%  stake €{vb.stake:.2f}"
                    )

            if not new_opps and not new_values:
                logger.info(
                    f"Sin alertas nuevas "
                    f"(arb: {len(opportunities)}, value: {len(value_bets)})"
                )

        except KeyboardInterrupt:
            logger.info("Detenido por el usuario (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Error en ciclo principal: {e}", exc_info=True)

        # Limpieza diaria del tracker
        if scan_n % max(1, 86400 // settings.SCAN_INTERVAL) == 0:
            tracker.cleanup_old()

        try:
            time.sleep(settings.SCAN_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Detenido por el usuario (Ctrl+C)")
            break


def cmd_info():
    """Diagnóstico: lista deportes, ligas y eventos disponibles en la API."""
    print("\n=== DIAGNÓSTICO DE LA API ===\n")

    print("📋 Deportes disponibles:")
    try:
        sports = get_sports()
        for s in sports:
            print(f"  • {s}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n📋 Ligas de '{settings.SPORT_FILTER}':")
    try:
        leagues = get_leagues(sport=settings.SPORT_FILTER)
        for league in leagues:
            wc = " ← MUNDIAL" if "world" in str(league).lower() else ""
            print(f"  • {league}{wc}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n📋 Próximos eventos (filtro: '{settings.LEAGUE_FILTER}'):")
    try:
        events = get_events(
            sport=settings.SPORT_FILTER,
            league=settings.LEAGUE_FILTER,
            limit=20,
        )
        for ev in events:
            home = ev.get("home_team") or ev.get("home") or ""
            away = ev.get("away_team") or ev.get("away") or ""
            name = f"{home} vs {away}" if home and away else ev.get("name", ev.get("id", "?"))
            league = ev.get("league", "")
            print(f"  • [{ev.get('id', '?')}] {name}  ({league})")
    except Exception as e:
        print(f"  ERROR: {e}")

    print()


def cmd_bookmakers():
    """Lista todas las casas que devuelve The Odds API y marca cuáles pasan el filtro español."""
    print(f"\n=== CASAS DE APUESTAS DISPONIBLES ===")
    print(f"    Filtro España (SPAIN_ONLY): {'✓ ACTIVO' if settings.SPAIN_ONLY else '✗ DESACTIVADO'}\n")

    if not settings.THEODDS_API_KEY:
        print("  ERROR: THEODDS_API_KEY no configurada en .env")
        return

    try:
        events = get_world_cup_events()
    except Exception as e:
        print(f"  ERROR al conectar con The Odds API: {e}")
        return

    if not events:
        print("  Sin eventos disponibles ahora mismo.")
        return

    # Recopilar todas las casas únicas del primer evento con bookmakers
    all_bookmakers: dict[str, str] = {}  # key → title
    for event in events:
        for bm in event.get("bookmakers", []):
            key = bm.get("key", "")
            title = bm.get("title", key)
            if key:
                all_bookmakers[key] = title
        if len(all_bookmakers) >= 5:
            break

    # Usar el evento con más bookmakers para la muestra completa
    best_event = max(events, key=lambda e: len(e.get("bookmakers", [])))
    all_bookmakers = {
        bm["key"]: bm.get("title", bm["key"])
        for bm in best_event.get("bookmakers", [])
        if bm.get("key")
    }

    spain_ok = []
    spain_no = []
    for key, title in sorted(all_bookmakers.items(), key=lambda x: x[1]):
        if is_spain_licensed(title) or is_spain_licensed(key):
            spain_ok.append((key, title))
        else:
            spain_no.append((key, title))

    print(f"  ✅ INCLUIDAS en alertas ({len(spain_ok)} casas con licencia DGOJ):")
    for key, title in spain_ok:
        print(f"     • {title:25s}  [{key}]")

    print(f"\n  ❌ EXCLUIDAS del filtro España ({len(spain_no)} casas sin DGOJ):")
    for key, title in spain_no:
        print(f"     • {title:25s}  [{key}]")

    print(f"\n  Total en API: {len(all_bookmakers)} casas")
    print(f"  Usando partido: {best_event.get('home_team')} vs {best_event.get('away_team')}\n")
    print("  Para desactivar el filtro: SPAIN_ONLY=False en .env")
    print("  Para añadir una casa: edita config/bookmakers.py\n")


def cmd_sports():
    """Lista los deportes activos de The Odds API, resaltando los de fútbol."""
    from core.fetcher_theodds import find_world_cup_key, get_theodds_sports

    if not settings.THEODDS_API_KEY:
        print("  ERROR: THEODDS_API_KEY no configurada en .env")
        return

    print("\n=== DEPORTES DISPONIBLES EN THE ODDS API ===\n")
    try:
        sports = get_theodds_sports()
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    wc_key = find_world_cup_key()

    soccer = [s for s in sports if (s.get("group") or "").lower() == "soccer"]
    other  = [s for s in sports if (s.get("group") or "").lower() != "soccer"]

    print(f"  ⚽ Fútbol ({len(soccer)} competiciones):")
    for s in soccer:
        active = "✅" if s.get("active") else "💤"
        wc     = " ← MUNDIAL DETECTADO" if s["key"] == wc_key else ""
        print(f"     {active} {s.get('title', '?'):35s}  [{s['key']}]{wc}")

    print(f"\n  🏅 Otros deportes ({len(other)} total — muestra de los activos):")
    for s in [x for x in other if x.get("active")][:15]:
        grp = s.get("group", "?")
        print(f"     ✅ [{grp:20s}] {s.get('title', '?'):30s}  [{s['key']}]")

    print(f"\n  ℹ️  Key del Mundial en uso: {wc_key}")
    print("  Para escanear un deporte extra: EXTRA_SPORTS=<key> en .env\n")


def main():
    parser = argparse.ArgumentParser(description="Sentinel World — Arbitrage Bot")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run",         help="Iniciar el bot (loop continuo)")
    sub.add_parser("info",        help="Mostrar deportes, ligas y eventos disponibles")
    sub.add_parser("bookmakers",  help="Ver qué casas devuelve la API y cuáles pasan el filtro España")
    sub.add_parser("sports",      help="Listar deportes activos en The Odds API")

    args = parser.parse_args()

    if args.cmd == "info":
        cmd_info()
    elif args.cmd == "bookmakers":
        cmd_bookmakers()
    elif args.cmd == "sports":
        cmd_sports()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
