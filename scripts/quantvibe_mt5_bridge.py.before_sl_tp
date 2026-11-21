#!/usr/bin/env python3
"""
QuantVibe Local MetaTrader 5 Bridge
Runs directly on the trader's Windows PC where MetaTrader 5 terminal is active.
Bridges QuantVibe Cloud Web Platform (https://quantvibeapp.com/) with native local MT5.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="QuantVibe 1-Click MetaTrader 5 Local Bridge")
    parser.add_argument("--server", default="https://quantvibeapp.com", help="QuantVibe Server URL")
    parser.add_argument("--account", default=None, help="Bridge account identifier")
    parser.add_argument("--terminal", default=None, help="Explicit path to MT5 terminal64.exe")
    parser.add_argument("--expected-login", type=int, default=None, help="Expected MT5 login; reject if different")
    parser.add_argument("--expected-server", default=None, help="Expected MT5 server; reject if different")
    parser.add_argument("--expected-currency", default=None, help="Expected account currency; reject if different")
    parser.add_argument("--suffix", default="", help="Symbol suffix in broker (e.g. .US, .pro, _m, .sc)")
    parser.add_argument("--prefix", default="", help="Symbol prefix in broker (e.g. #)")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval in seconds")
    parser.add_argument("--max-tick-age", type=float, default=30.0, help="Maximum accepted MT5 tick age in seconds")
    parser.add_argument(
        "--journal",
        default="artifacts/mt5_execution_journal.jsonl",
        help="Persistent journal used to prevent duplicate MT5 executions",
    )
    parser.add_argument("--magic", type=int, default=202609, help="QuantVibe Magic Number")
    return parser.parse_args()


def resolve_symbol(mt5, base_symbol: str, prefix: str = "", suffix: str = "") -> str | None:
    # 1. Exact match
    if mt5.symbol_info(base_symbol) is not None:
        mt5.symbol_select(base_symbol, True)
        return base_symbol

    # 2. Custom prefix/suffix
    custom = f"{prefix}{base_symbol}{suffix}"
    if mt5.symbol_info(custom) is not None:
        mt5.symbol_select(custom, True)
        return custom

    # 3. Common broker naming conventions (FTMO, IC Markets, XM, Tickmill)
    candidates = [
        f"{base_symbol}.US",
        f"{base_symbol}.us",
        f"#{base_symbol}",
        f"{base_symbol}_CFD",
        f"{base_symbol}.cfd",
        f"{base_symbol}.pro",
        f"{base_symbol}_m",
        f"{base_symbol}.m",
        f"{base_symbol}.cash",
    ]
    for cand in candidates:
        if mt5.symbol_info(cand) is not None:
            mt5.symbol_select(cand, True)
            return cand

    return None


def normalize_volume(symbol_info, desired_qty: float) -> float:
    import math
    from decimal import Decimal

    min_vol = float(symbol_info.volume_min)
    max_vol = float(symbol_info.volume_max)
    step = float(symbol_info.volume_step or 0.01)

    if not math.isfinite(desired_qty) or desired_qty <= 0:
        raise ValueError(f"volume invalido: {desired_qty!r}")

    if desired_qty < min_vol or desired_qty > max_vol:
        raise ValueError(
            f"volume {desired_qty} fuera de limites MT5 "
            f"[{min_vol}, {max_vol}]"
        )

    steps = round((desired_qty - min_vol) / step)
    normalized = min_vol + steps * step

    tolerance = max(1e-12, step * 1e-6)
    if not math.isclose(desired_qty, normalized, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(
            f"volume {desired_qty} no respeta volume_step={step}"
        )

    digits = max(0, -Decimal(str(step)).as_tuple().exponent)
    return round(normalized, digits)


def get_filling_type(mt5, symbol_info):
    filling_mode = int(symbol_info.filling_mode)

    # SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2
    if filling_mode & 1:
        return mt5.ORDER_FILLING_FOK

    if filling_mode & 2:
        return mt5.ORDER_FILLING_IOC

    trade_exemode = getattr(symbol_info, "trade_exemode", None)
    market_execution = getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", None)

    if trade_exemode is None or market_execution is None:
        raise ValueError(
            "No se puede validar la pol?tica de filling del s?mbolo"
        )

    # ORDER_FILLING_RETURN is forbidden under Market Execution.
    if int(trade_exemode) == int(market_execution):
        raise ValueError(
            f"S?mbolo en Market Execution sin FOK/IOC permitido "
            f"(filling_mode={filling_mode})"
        )

    return mt5.ORDER_FILLING_RETURN



def load_execution_journal(path: Path) -> dict:
    executed = {}

    if not path.exists():
        return executed

    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Journal corrupto en linea {line_number}: {exc}"
                ) from exc

            order_id = str(record.get("order_id", "")).strip()

            if order_id and record.get("status") == "FILLED":
                executed[order_id] = record

    return executed


def record_filled_execution(
    path: Path,
    order_id: str,
    account: str,
    symbol: str,
    action: str,
    volume: float,
    ticket: int,
    deal: int,
    fill_price: float,
) -> dict:
    record = {
        "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "order_id": order_id,
        "account": account,
        "symbol": symbol,
        "action": action,
        "volume_lots": volume,
        "status": "FILLED",
        "ticket": int(ticket or 0),
        "deal": int(deal or 0),
        "fill_price": float(fill_price),
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    return record


def main():
    args = parse_args()
    print("=" * 65)
    print("   QUANTVIBE INSTITUTIONAL ENGINE · MT5 LOCAL DESKTOP BRIDGE")
    print("   https://quantvibeapp.com/ · Conexión Nativa MetaTrader 5")
    print("=" * 65)

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("[ERROR] El paquete MetaTrader5 no está instalado en este Python.")
        print("        Instálalo ejecutando: pip install MetaTrader5")
        sys.exit(1)

    # Fail-closed MT5 identity binding
    required_identity = {
        "--terminal": args.terminal,
        "--expected-login": args.expected_login,
        "--expected-server": args.expected_server,
        "--expected-currency": args.expected_currency,
    }

    missing = [
        name for name, value in required_identity.items()
        if value in (None, "")
    ]
    if missing:
        print(f"[ERROR] Identidad MT5 incompleta. Faltan: {', '.join(missing)}")
        sys.exit(1)

    terminal_path = Path(args.terminal).expanduser().resolve()
    if not terminal_path.is_file():
        print(f"[ERROR] terminal64.exe no encontrado: {terminal_path}")
        sys.exit(1)

    print(f"\n[1/3] Conectando exclusivamente a: {terminal_path}")
    if not mt5.initialize(str(terminal_path)):
        print(f"[ERROR] No se pudo inicializar MetaTrader 5: {mt5.last_error()}")
        sys.exit(1)

    account_info = mt5.account_info()
    if account_info is None:
        print(f"[ERROR] No hay cuenta conectada en MT5: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    identity_errors = []

    if int(account_info.login) != int(args.expected_login):
        identity_errors.append(
            f"login real={account_info.login} esperado={args.expected_login}"
        )

    if str(account_info.server).strip().lower() != str(args.expected_server).strip().lower():
        identity_errors.append(
            f"server real={account_info.server!r} esperado={args.expected_server!r}"
        )

    if str(account_info.currency).strip().upper() != str(args.expected_currency).strip().upper():
        identity_errors.append(
            f"currency real={account_info.currency!r} esperado={args.expected_currency!r}"
        )

    if args.account is not None and str(args.account) != str(account_info.login):
        identity_errors.append(
            f"account bridge={args.account!r} no coincide con login MT5={account_info.login}"
        )

    if identity_errors:
        print("[ERROR] IDENTIDAD MT5 RECHAZADA:")
        for err in identity_errors:
            print(f"        - {err}")
        mt5.shutdown()
        sys.exit(1)

    account_id = str(account_info.login)

    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        print(f"[ERROR] No se pudo leer terminal_info: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    print("[2/3] Conexión MT5 Establecida:")
    print(f"      • Cuenta Login : {account_info.login} ({account_info.currency})")
    print(f"      • Broker / Firm: {account_info.company}")
    print(f"      • Servidor MT5 : {account_info.server}")
    initial_currency = str(account_info.currency or "USD").upper()
    initial_cent_divider = 100.0 if initial_currency == "USC" else 1.0
    print(f"      Balance Real : {account_info.balance:,.2f} {initial_currency} (equiv. ${account_info.balance / initial_cent_divider:,.2f} USD)")
    print(f"      Equidad Libre: {account_info.equity:,.2f} {initial_currency} (equiv. ${account_info.equity / initial_cent_divider:,.2f} USD)")
    print(f"      • Apalancamiento: 1:{account_info.leverage}")
    print(f"      • Algo Trading : {'ACTIVO (Permitido)' if terminal_info.trade_allowed else 'DESACTIVADO (Activa el botón Algo Trading en MT5)'}")

    print(f"\n[3/3] Enlazando con QuantVibe Cloud Server: {args.server}")
    print("      Escuchando órdenes institucionales en tiempo real... (Ctrl+C para salir)\n")

    last_heartbeat = 0
    poll_count = 0

    journal_path = Path(args.journal).expanduser().resolve()

    try:
        executed_orders = load_execution_journal(journal_path)
    except Exception as exc:
        print(f"[ERROR] No se puede cargar journal de ejecucion: {exc}")
        mt5.shutdown()
        sys.exit(1)

    print(
        f"[SAFETY] Journal MT5: {journal_path} "
        f"({len(executed_orders)} ordenes FILLED conocidas)"
    )

    while True:
        try:
            now = time.time()

            # Refresh MT5 state every cycle; never trust stale identity/trading state
            acc = mt5.account_info()
            terminal_info = mt5.terminal_info()

            if acc is None or terminal_info is None:
                print(f"[ERROR] Estado MT5 no disponible: {mt5.last_error()}")
                mt5.shutdown()
                sys.exit(1)

            if int(acc.login) != int(args.expected_login):
                print(f"[ERROR] Login MT5 cambi?: real={acc.login} esperado={args.expected_login}")
                mt5.shutdown()
                sys.exit(1)

            if str(acc.server).strip().lower() != str(args.expected_server).strip().lower():
                print(f"[ERROR] Servidor MT5 cambi?: real={acc.server!r} esperado={args.expected_server!r}")
                mt5.shutdown()
                sys.exit(1)

            if str(acc.currency).strip().upper() != str(args.expected_currency).strip().upper():
                print(f"[ERROR] Moneda MT5 cambi?: real={acc.currency!r} esperado={args.expected_currency!r}")
                mt5.shutdown()
                sys.exit(1)

            currency = str(acc.currency or "USD").upper()
            cent_divider = 100.0 if currency == "USC" else 1.0
            cent_account = cent_divider == 100.0

            balance_raw = float(acc.balance)
            equity_raw = float(acc.equity)
            margin_free_raw = float(acc.margin_free)

            balance = balance_raw / cent_divider
            equity = equity_raw / cent_divider
            margin_free = margin_free_raw / cent_divider

            # 1. Send Heartbeat every 10 seconds
            if now - last_heartbeat > 10:
                heartbeat_payload = json.dumps({
                    "account": account_id,
                    "broker": acc.company if acc else "Unknown",
                    "server": acc.server if acc else "Unknown",
                    "currency": currency,
                    "balance": balance,
                    "equity": equity,
                    "margin_free": margin_free,
                    "balance_raw": balance_raw,
                    "equity_raw": equity_raw,
                    "margin_free_raw": margin_free_raw,
                    "cent_account": cent_account,
                    "cent_divider": cent_divider,
                    "leverage": acc.leverage if acc else 100,
                    "algo_trading": bool(terminal_info.trade_allowed)
                }).encode("utf-8")

                try:
                    hb_req = urllib.request.Request(
                        f"{args.server}/api/mt5/heartbeat",
                        data=heartbeat_payload,
                        headers={"Content-Type": "application/json", "User-Agent": "QuantVibe-Bridge-Python/2.0"},
                        method="POST"
                    )
                    with urllib.request.urlopen(hb_req, timeout=4) as resp:
                        pass
                except Exception as exc:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                        f"[HEARTBEAT ERROR] {exc}"
                    )
                last_heartbeat = now

            # Fail closed: never fetch executable orders while Algo Trading is disabled
            if not terminal_info.trade_allowed:
                time.sleep(args.interval)
                continue

            # 2. Poll for pending orders
            poll_url = f"{args.server}/api/mt5/orders?account={account_id}&balance={balance}"
            poll_req = urllib.request.Request(poll_url, headers={"User-Agent": "QuantVibe-Bridge-Python/2.0"})
            with urllib.request.urlopen(poll_req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            orders = data.get("orders", [])
            if orders:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Recibidas {len(orders)} órdenes desde QuantVibe!")

                for ord_item in orders:
                    order_id = ord_item.get("id") or ord_item.get("order_id")

                    if order_id is None or not str(order_id).strip():
                        print("  [RECHAZO] Orden sin identificador ?nico; no se ejecutar?.")
                        continue

                    order_id = str(order_id).strip()
                    base_sym = ord_item.get("instrument") or ord_item.get("symbol")

                    prior_execution = executed_orders.get(order_id)

                    if prior_execution is not None:
                        print(
                            f"  [DUPLICADO BLOQUEADO] order_id={order_id} "
                            f"ya fue ejecutada; ticket={prior_execution.get('ticket', 0)}"
                        )

                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            prior_execution.get("symbol") or base_sym,
                            "FILLED",
                            int(prior_execution.get("ticket", 0) or 0),
                            float(prior_execution.get("fill_price", 0.0) or 0.0),
                            "ACK reenviado desde journal local; orden NO reejecutada.",
                        )
                        continue
                    action_raw = ord_item.get("action")
                    qty_raw = ord_item.get("qty")
                    quantity_unit = str(ord_item.get("quantity_unit", "")).lower()

                    if action_raw is None:
                        err_msg = "Orden sin action explicita."
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    action = str(action_raw).upper()
                    if action not in {"BUY", "SELL"}:
                        err_msg = f"Action invalida: {action!r}. Solo BUY/SELL."
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    if quantity_unit != "lots":
                        err_msg = (
                            f"Unidad de cantidad insegura: {quantity_unit!r}. "
                            "MT5 requiere quantity_unit='lots'."
                        )
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    if qty_raw is None:
                        err_msg = "Orden MT5 sin qty."
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    try:
                        volume = float(qty_raw)
                    except (TypeError, ValueError):
                        err_msg = f"qty MT5 invalido: {qty_raw!r}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    if volume <= 0:
                        err_msg = f"Volume MT5 deve ser > 0; recebido {volume}."
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    est_price = float(ord_item.get("est_price", 0.0))

                    # Resolve symbol
                    broker_sym = resolve_symbol(mt5, base_sym, args.prefix, args.suffix)
                    if not broker_sym:
                        err_msg = f"Símbolo '{base_sym}' no encontrado en broker MT5. Revisa prefijo/sufijo."
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, base_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    sym_info = mt5.symbol_info(broker_sym)

                    if sym_info is None:
                        err_msg = f"No se pudo leer symbol_info para {broker_sym}: {mt5.last_error()}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    if not sym_info.visible:
                        if not mt5.symbol_select(broker_sym, True):
                            err_msg = f"No se pudo activar {broker_sym} en Market Watch: {mt5.last_error()}"
                            print(f"  [RECHAZO] {err_msg}")
                            send_ack(
                                args.server,
                                order_id,
                                account_id,
                                broker_sym,
                                "REJECTED",
                                0,
                                0,
                                err_msg,
                            )
                            continue

                        sym_info = mt5.symbol_info(broker_sym)
                        if sym_info is None:
                            err_msg = f"symbol_info no disponible despu?s de symbol_select para {broker_sym}"
                            print(f"  [RECHAZO] {err_msg}")
                            send_ack(
                                args.server,
                                order_id,
                                account_id,
                                broker_sym,
                                "REJECTED",
                                0,
                                0,
                                err_msg,
                            )
                            continue

                    trade_mode = int(sym_info.trade_mode)

                    if action == "BUY":
                        allowed_trade_modes = {
                            int(mt5.SYMBOL_TRADE_MODE_FULL),
                            int(mt5.SYMBOL_TRADE_MODE_LONGONLY),
                        }
                    else:
                        allowed_trade_modes = {
                            int(mt5.SYMBOL_TRADE_MODE_FULL),
                            int(mt5.SYMBOL_TRADE_MODE_SHORTONLY),
                        }

                    if trade_mode not in allowed_trade_modes:
                        err_msg = (
                            f"Trading no permitido para {action} {broker_sym}: "
                            f"trade_mode={trade_mode}"
                        )
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    try:
                        final_vol = normalize_volume(sym_info, volume)
                    except ValueError as exc:
                        err_msg = f"Volume MT5 rechazado: {exc}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(args.server, order_id, account_id, broker_sym, "REJECTED", 0, 0, err_msg)
                        continue

                    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                    tick = mt5.symbol_info_tick(broker_sym)

                    if tick is None:
                        err_msg = f"Sin tick MT5 v?lido para {broker_sym}: {mt5.last_error()}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    tick_time_msc = getattr(tick, "time_msc", None)
                    tick_time = getattr(tick, "time", None)

                    if tick_time_msc:
                        tick_epoch = float(tick_time_msc) / 1000.0
                    elif tick_time:
                        tick_epoch = float(tick_time)
                    else:
                        err_msg = f"Tick sin timestamp v?lido para {broker_sym}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    tick_age = time.time() - tick_epoch

                    if (
                        not math.isfinite(tick_age)
                        or tick_age < -5.0
                        or tick_age > args.max_tick_age
                    ):
                        err_msg = (
                            f"Tick MT5 obsoleto para {broker_sym}: "
                            f"edad={tick_age:.1f}s, m?ximo={args.max_tick_age:.1f}s"
                        )
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    price = float(tick.ask if action == "BUY" else tick.bid)

                    if not math.isfinite(price) or price <= 0:
                        err_msg = f"Precio MT5 inv?lido para {broker_sym}: {price!r}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    try:
                        filling_type = get_filling_type(mt5, sym_info)
                    except ValueError as exc:
                        err_msg = f"Filling MT5 rechazado para {broker_sym}: {exc}"
                        print(f"  [RECHAZO] {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": broker_sym,
                        "volume": final_vol,
                        "type": order_type,
                        "price": price,
                        "deviation": 10,
                        "magic": args.magic,
                        "comment": "QuantVibe Alpha158",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": filling_type,
                    }

                    # Pre-flight MT5 validation: never send an unchecked request
                    check = mt5.order_check(request)

                    if check is None:
                        err_msg = f"order_check sin respuesta: {mt5.last_error()}"
                        print(f"  [RECHAZO PRECHECK] {broker_sym}: {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    check_retcode = getattr(check, "retcode", -1)
                    check_comment = getattr(check, "comment", "Sin comentario")

                    if check_retcode != 0:
                        err_msg = (
                            f"order_check rechazado: "
                            f"retcode={check_retcode}, comment={check_comment}"
                        )
                        print(f"  [RECHAZO PRECHECK] {broker_sym}: {err_msg}")
                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "REJECTED",
                            0,
                            0,
                            err_msg,
                        )
                        continue

                    result = mt5.order_send(request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(
                            f"  [EXITO MT5] {action} {broker_sym} x {final_vol} lotes "
                            f"@ {result.price:.2f} (Ticket #{result.order})"
                        )

                        try:
                            execution_record = record_filled_execution(
                                journal_path,
                                order_id,
                                account_id,
                                broker_sym,
                                action,
                                final_vol,
                                getattr(result, "order", 0),
                                getattr(result, "deal", 0),
                                result.price,
                            )
                        except Exception as exc:
                            print(
                                f"  [CRITICO] La orden fue ejecutada pero no se pudo "
                                f"persistir order_id={order_id}: {exc}"
                            )
                            mt5.shutdown()
                            sys.exit(2)

                        executed_orders[order_id] = execution_record

                        send_ack(
                            args.server,
                            order_id,
                            account_id,
                            broker_sym,
                            "FILLED",
                            result.order,
                            result.price,
                            "Orden ejecutada con exito",
                        )
                    else:
                        ret_comment = result.comment if result else mt5.last_error()
                        ret_code = result.retcode if result else -1
                        print(f"  [ERROR MT5] Fallo al ejecutar {broker_sym}: code={ret_code} ({ret_comment})")
                        send_ack(args.server, order_id, account_id, broker_sym, "REJECTED", 0, 0, f"MT5 retcode={ret_code}: {ret_comment}")

            poll_count += 1
            if poll_count % 20 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Puente activo · Sincronizado con MT5 ({account_info.company}) · Balance: ${balance:,.2f}")

        except urllib.error.URLError as exc:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"[NETWORK ERROR] No se pudo consultar QuantVibe: {exc}"
            )
        except KeyboardInterrupt:
            print("\n[QuantVibe] Deteniendo puente local...")
            break
        except Exception as exc:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Aviso puente: {exc}")

        time.sleep(args.interval)

    mt5.shutdown()
    print("[QuantVibe] Conexión cerrada.")



def send_ack(
    server: str,
    order_id: str,
    account: str,
    symbol: str,
    status: str,
    ticket: int,
    fill_price: float,
    notes: str,
) -> bool:
    payload = json.dumps({
        "order_id": order_id,
        "account": account,
        "symbol": symbol,
        "status": status,
        "ticket": ticket,
        "fill_price": fill_price,
        "notes": notes,
    }).encode("utf-8")

    url = f"{server}/api/mt5/ack"
    last_error = None

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "QuantVibe-Bridge-Python/2.0",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=4) as resp:
                status_code = getattr(resp, "status", 200)

                if not 200 <= int(status_code) < 300:
                    raise RuntimeError(
                        f"ACK HTTP inesperado: {status_code}"
                    )

            if attempt > 1:
                print(
                    f"  [ACK RECUPERADO] order_id={order_id} "
                    f"en intento {attempt}"
                )

            return True

        except Exception as exc:
            last_error = exc

            print(
                f"  [ACK ERROR] order_id={order_id} "
                f"intento={attempt}/3: {exc}"
            )

            if attempt < 3:
                time.sleep(0.5 * attempt)

    print(
        f"  [ACK PENDIENTE] order_id={order_id}; "
        f"journal/idempotencia evita reejecucion. "
        f"ultimo_error={last_error}"
    )

    return False


if __name__ == "__main__":
    main()
