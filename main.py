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


def _digest_today() -> str:
    """Resumen del día: partidos próximos + mejores value bets."""
    from datetime import datetime, timedelta, timezone

    from core.fetcher_theodds import (
        extract_event_meta,
        find_world_cup_key,
        get_events_for_sport,
    )

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=24)

    try:
        events = get_events_for_sport(find_world_cup_key())
    except Exception:
        events = []

    todays: list[tuple] = []
    for ev in events:
        try:
            dt = datetime.fromisoformat(ev.get("commence_time", "").replace("Z", "+00:00"))
        except Exception:
            continue
        if now <= dt <= cutoff:
            todays.append((dt, ev))
    todays.sort(key=lambda x: x[0])

    lines = [
        "📅 <b>DIGEST — PRÓXIMAS 24H</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if todays:
        lines.append(f"⚽ <b>{len(todays)} partido(s):</b>")
        for dt, ev in todays[:12]:
            meta = extract_event_meta(ev)
            hora = dt.strftime("%H:%M")
            lines.append(f"  • {hora} UTC — {meta['home_team']} vs {meta['away_team']}")
        if len(todays) > 12:
            lines.append(f"  … y {len(todays) - 12} más")
    else:
        lines.append("⚽ Sin partidos en las próximas 24h.")

    value_bets = scan_value_bets()
    lines.append("")
    if value_bets:
        lines.append(f"📊 <b>Top value bets ({len(value_bets)} encontradas):</b>")
        for vb in value_bets[:5]:
            badge = " 🟢" if vb.confidence == "high" else ""
            lines.append(
                f"  • {vb.event_name} — <b>{vb.outcome}</b> @ {vb.odds} "
                f"({vb.bookmaker}) +{vb.edge_pct:.1f}%{badge}"
            )
        lines.append("  → /value para ver los detalles y stakes")
    else:
        lines.append("📊 Sin value bets dentro de la ventana ahora mismo.")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "📨 /value · /middle · /arb · /bank",
    ]
    return "\n".join(lines)


def _handle_command(raw_cmd: str, tracker: "ArbitrageTracker") -> None:
    """Ejecuta un comando recibido por Telegram. Soporta args: '/win 5.50'."""
    from data.bankroll import get_bankroll, record_result, set_balance
    from notifiers.telegram import format_bank_message

    parts = raw_cmd.split()
    cmd = parts[0]
    args = parts[1:]

    def _parse_amount() -> float | None:
        if not args:
            return None
        try:
            return float(args[0].replace(",", ".").replace("€", ""))
        except ValueError:
            return None

    if cmd == "/bank":
        send_text(format_bank_message())

    elif cmd == "/win":
        amount = _parse_amount()
        if amount is None or amount <= 0:
            send_text("Uso: <code>/win 5.50</code> — registra una ganancia en €")
            return
        balance = record_result(amount, "win")
        send_text(f"✅ +€{amount:.2f} registrado · Balance: <b>€{balance:.2f}</b>")

    elif cmd == "/loss":
        amount = _parse_amount()
        if amount is None or amount <= 0:
            send_text("Uso: <code>/loss 2</code> — registra una pérdida en €")
            return
        balance = record_result(-amount, "loss")
        send_text(f"❌ -€{amount:.2f} registrado · Balance: <b>€{balance:.2f}</b>")

    elif cmd == "/setbank":
        amount = _parse_amount()
        if amount is None or amount <= 0:
            send_text("Uso: <code>/setbank 120</code> — fija el balance en €")
            return
        balance = set_balance(amount)
        send_text(f"🏦 Balance fijado en <b>€{balance:.2f}</b>")

    elif cmd == "/hoy":
        send_text("🔍 <i>Preparando el digest del día...</i>")
        send_text(_digest_today())

    elif cmd == "/middle":
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
        send_text(
            "📊 <b>Estado del bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💶 Bankroll: €{get_bankroll():.2f}\n"
            f"📊 Margen mín arb: {settings.MIN_ARB_MARGIN}%\n"
            f"📊 Edge mín value: {settings.MIN_VALUE_EDGE}%\n"
            f"⏳ Ventana value: {settings.VALUE_MAX_HOURS}h\n"
            f"🏆 Deporte: {settings.LEAGUE_FILTER or settings.SPORT_FILTER}\n"
            f"🔑 Filtro DGOJ: {'✓' if settings.SPAIN_ONLY else '✗'}\n"
            f"⏱ Intervalo: {settings.SCAN_INTERVAL}s\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📨 /hoy · /value · /middle · /arb · /bank"
        )

    else:
        send_text(
            f"❓ Comando no reconocido: <code>{cmd}</code>\n\n"
            "Comandos disponibles:\n"
            "  /hoy    — digest del día\n"
            "  /value  — buscar value bets (+EV)\n"
            "  /middle — buscar ventanas de goles\n"
            "  /arb    — forzar escaneo de arbitrajes\n"
            "  /bank   — balance, P&amp;L y ROI\n"
            "  /win X · /loss X · /setbank X\n"
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
    """Diagnóstico: lista deportes y partidos disponibles en The Odds API."""
    from core.fetcher_theodds import find_world_cup_key, get_events_for_sport, get_theodds_sports, extract_event_meta

    print("\n=== DIAGNÓSTICO DE LA API ===\n")

    if not settings.THEODDS_API_KEY:
        print("  ERROR: THEODDS_API_KEY no configurada en .env")
        return

    print("📋 Deportes de fútbol disponibles (The Odds API):")
    try:
        sports = get_theodds_sports()
        soccer = [s for s in sports if (s.get("group") or "").lower() == "soccer" and s.get("active")]
        for s in soccer[:15]:
            print(f"  • {s.get('title', '?')}  [{s['key']}]")
        if len(soccer) > 15:
            print(f"  … y {len(soccer) - 15} más. Usa 'python main.py sports' para verlos todos.")
    except Exception as e:
        print(f"  ERROR: {e}")

    wc_key = find_world_cup_key()
    print(f"\n📋 Partidos del Mundial ({wc_key}):")
    try:
        events = get_events_for_sport(wc_key)
        for ev in events[:20]:
            meta = extract_event_meta(ev)
            name = f"{meta['home_team']} vs {meta['away_team']}"
            books = len(ev.get("bookmakers", []))
            print(f"  • {name}  ({meta.get('commence_time', '')[:10]})  [{books} casas]")
        if len(events) > 20:
            print(f"  … y {len(events) - 20} partidos más.")
        print(f"\n  Total: {len(events)} partidos con cuotas disponibles")
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


def cmd_footapi():
    """Diagnóstico de FootApi: conectividad, torneos y próximos partidos del Mundial."""
    from core.fetcher_footapi import diagnose, get_team_recent_matches, get_upcoming_events
    from core.poisson import calc_probs, estimate_lambdas, stats_from_recent_matches

    print("\n=== FOOTAPI — DIAGNÓSTICO ===\n")

    if not settings.RAPIDAPI_KEY:
        print("  ERROR: RAPIDAPI_KEY no configurada en .env")
        print("  Añade: RAPIDAPI_KEY=tu_key en el .env")
        return

    result = diagnose()
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    print(f"  Torneo   : {result.get('tournament', '?')}")
    print(f"  Season ID: {result.get('season_id', '?')}")
    print(f"  Próximos : {result.get('upcoming_matches', 0)} partidos")
    print(f"  Recientes: {result.get('recent_matches', 0)} partidos")

    if result.get("next_match"):
        print(f"\n  Próximo partido: {result['next_match']}")
        home_id = result.get("home_team_id")
        away_id = result.get("away_team_id")

        if home_id and away_id:
            home_name, away_name = result["next_match"].split(" vs ")
            print(f"  Team IDs: {home_id} (local) / {away_id} (visitante)")

            # Intentar calcular Poisson con últimos partidos de cada equipo
            print(f"\n  Calculando modelo Poisson para {result['next_match']}...")
            home_matches = get_team_recent_matches(home_id)
            away_matches = get_team_recent_matches(away_id)

            home_stats = stats_from_recent_matches(home_id, home_name, home_matches)
            away_stats = stats_from_recent_matches(away_id, away_name, away_matches)

            if home_stats and away_stats:
                lh, la = estimate_lambdas(home_stats, away_stats)
                probs = calc_probs(lh, la)
                print(f"\n  λ local={lh:.2f}  λ visitante={la:.2f}")
                print(f"  1×2: {home_name}={probs.home_win:.1%}  X={probs.draw:.1%}  {away_name}={probs.away_win:.1%}")
                print(f"  Over 1.5: {probs.over[1.5]:.1%}  Over 2.5: {probs.over[2.5]:.1%}  Over 3.5: {probs.over[3.5]:.1%}")
            else:
                print(f"  Sin datos suficientes para el modelo Poisson")
                print(f"  Home: {len(home_matches)} partidos encontrados")
                print(f"  Away: {len(away_matches)} partidos encontrados")

    print("\n  Si todo es correcto, el bot usará Poisson como segunda capa de confirmación.")
    print("  Si season_id es None, FootApi puede no tener el WC 2026 aún.\n")


def main():
    parser = argparse.ArgumentParser(description="Sentinel World — Arbitrage Bot")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run",         help="Iniciar el bot (loop continuo)")
    sub.add_parser("info",        help="Mostrar deportes, ligas y eventos disponibles")
    sub.add_parser("bookmakers",  help="Ver qué casas devuelve la API y cuáles pasan el filtro España")
    sub.add_parser("sports",      help="Listar deportes activos en The Odds API")
    sub.add_parser("footapi",     help="Diagnóstico de FootApi y modelo Poisson")

    args = parser.parse_args()

    if args.cmd == "info":
        cmd_info()
    elif args.cmd == "bookmakers":
        cmd_bookmakers()
    elif args.cmd == "sports":
        cmd_sports()
    elif args.cmd == "footapi":
        cmd_footapi()
    else:
        cmd_run()


if __name__ == "__main__":
    main()
