"""
Sentinel World — Bot de Arbitraje Deportivo
Encuentra oportunidades de apuesta sin riesgo en tiempo real.
"""

import argparse
import logging
import sys
import time

from config.settings import settings
from core.fetcher import get_events, get_leagues, get_sports
from core.scanner import scan
from data.tracker import ArbitrageTracker
from notifiers.telegram import send_alert, send_startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sentinel.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("sentinel")


def cmd_run():
    """Main loop: scan and alert on arbitrage opportunities."""
    logger.info("=" * 55)
    logger.info("  SENTINEL WORLD — Bot de Arbitraje Deportivo")
    logger.info("=" * 55)
    logger.info(f"  Bankroll        : €{settings.BANKROLL:.2f}")
    logger.info(f"  Margen mínimo   : {settings.MIN_ARB_MARGIN}%")
    logger.info(f"  Margen máximo   : {settings.MAX_ARB_MARGIN}%")
    logger.info(f"  Deporte/Liga    : {settings.SPORT_FILTER} / {settings.LEAGUE_FILTER}")
    logger.info(f"  Intervalo       : {settings.SCAN_INTERVAL}s")
    logger.info("=" * 55)

    send_startup()
    tracker = ArbitrageTracker()

    scan_n = 0
    total_alerts = 0

    while True:
        scan_n += 1
        logger.info(f"--- Scan #{scan_n} ---")

        try:
            opportunities = scan()
            new_opps = [o for o in opportunities if not tracker.seen(o)]

            for opp in new_opps:
                ok = send_alert(opp)
                if ok:
                    tracker.mark_seen(opp)
                    total_alerts += 1
                    logger.info(
                        f"ALERTA ENVIADA | {opp.event_name}"
                        f" | +{opp.margin_pct:.2f}%"
                        f" | ganancia ≥ +€{opp.min_profit:.2f}"
                    )

            if not new_opps:
                logger.info(f"Sin oportunidades nuevas (evaluadas: {len(opportunities)})")

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


def main():
    parser = argparse.ArgumentParser(description="Sentinel World — Arbitrage Bot")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Iniciar el bot (loop continuo)")
    sub.add_parser("info", help="Mostrar deportes, ligas y eventos disponibles")

    args = parser.parse_args()

    if args.cmd == "info":
        cmd_info()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
