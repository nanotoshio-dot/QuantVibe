from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo


SERVER = "http://127.0.0.1:8000"

# Capital econômico máximo usado no plano PAPER.
CAPITAL_USD = 30.0

# Conta MT5 esperada.
MT5_ACCOUNT = "27897172"

# Sessão de Nova York. ZoneInfo cuida automaticamente de DST.
NY_TZ = ZoneInfo("America/New_York")

# Primeira execução do dia, cinco minutos após a abertura regular.
START_TIME = clock_time(9, 35)

# Não inicia um novo ciclo depois deste horário.
LAST_START_TIME = clock_time(15, 0)

# Frequência de verificação do relógio.
CHECK_INTERVAL = 60

# Em caso de falha, nova tentativa após 15 minutos.
RETRY_SECONDS = 15 * 60

# Limite de tentativas por dia.
MAX_ATTEMPTS = 3

# Tempo máximo para o pipeline terminar.
PIPELINE_TIMEOUT_SECONDS = 60 * 60

# Tempo máximo para confirmar que o pipeline NOVO realmente começou.
PIPELINE_START_TIMEOUT_SECONDS = 30

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

STATE_FILE = ARTIFACTS / "autopilot_state.json"
LOG_FILE = ARTIFACTS / "autopilot_paper_runs.jsonl"


def request_json(
    path: str,
    method: str = "GET",
    payload=None,
    timeout: float = 60.0,
):
    url = SERVER + path
    data = None
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "QuantVibe-Autopilot-Paper/1.0",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} em {path}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Não foi possível conectar à API QuantVibe em {SERVER}: {exc.reason}"
        ) from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Resposta inválida da API em {path}: não é JSON."
        ) from exc


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def append_log(record):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(record, ensure_ascii=False)
            + "\n"
        )


def verify_project_layout():
    expected_api = ROOT / "web" / "api.py"

    if not expected_api.is_file():
        raise RuntimeError(
            "Autopilot está em uma pasta inesperada. "
            "Coloque este arquivo dentro de QuantVibe\\scripts\\."
        )


def verify_api_and_bridge():
    # Confirma que a API está viva.
    request_json("/api/pipeline/logs", timeout=10)

    account_q = urllib.parse.quote(MT5_ACCOUNT, safe="")
    status = request_json(
        f"/api/mt5/status?account={account_q}",
        timeout=10,
    )

    if not status.get("connected"):
        raise RuntimeError(
            f"Bridge MT5 da conta {MT5_ACCOUNT} não está conectado."
        )

    session = status.get("session") or {}
    session_account = str(session.get("account") or "").strip()

    if session_account != MT5_ACCOUNT:
        raise RuntimeError(
            "A conta reportada pelo bridge não coincide com "
            f"a conta esperada: esperado={MT5_ACCOUNT}, recebido={session_account!r}."
        )

    return status


def wait_for_new_pipeline(baseline_logs):
    """
    Espera especificamente o pipeline recém-disparado.

    O código antigo podia ler exit_code=0 de uma execução anterior
    durante a pequena janela entre o POST e a thread nova marcar
    is_running=True. Aqui só aceitamos um estado que mudou em relação
    ao baseline ou que tenha sido observado como running.
    """
    baseline_logs = list(baseline_logs or [])
    start_deadline = time.time() + PIPELINE_START_TIMEOUT_SECONDS
    pipeline_seen = False

    while time.time() < start_deadline:
        status = request_json("/api/pipeline/logs", timeout=10)
        current_logs = list(status.get("logs") or [])

        if status.get("is_running"):
            pipeline_seen = True
            break

        if current_logs != baseline_logs:
            # O novo ciclo começou e talvez tenha terminado muito rápido.
            pipeline_seen = True
            return int(status.get("exit_code", 1))

        time.sleep(0.5)

    if not pipeline_seen:
        raise RuntimeError(
            "A API aceitou o comando, mas o novo pipeline não iniciou "
            f"em {PIPELINE_START_TIMEOUT_SECONDS}s."
        )

    deadline = time.time() + PIPELINE_TIMEOUT_SECONDS

    while time.time() < deadline:
        status = request_json("/api/pipeline/logs", timeout=10)

        if not status.get("is_running"):
            return int(status.get("exit_code", 1))

        time.sleep(2)

    raise RuntimeError(
        f"Pipeline excedeu {PIPELINE_TIMEOUT_SECONDS // 60} minutos."
    )


def run_pipeline_real():
    before = request_json("/api/pipeline/logs", timeout=10)

    if before.get("is_running"):
        raise RuntimeError(
            "Já existe um pipeline QuantVibe em execução. "
            "O autopilot não iniciará outro em paralelo."
        )

    baseline_logs = list(before.get("logs") or [])

    response = request_json(
        "/api/pipeline/run",
        method="POST",
        payload={
            "mode": "real",
            "steps": [
                "prepare",
                "settle",
                "train",
                "export",
                "execute",
            ],
        },
        timeout=15,
    )

    if response.get("status") != "started":
        raise RuntimeError(
            f"A API não confirmou início do pipeline: {response}"
        )

    return wait_for_new_pipeline(baseline_logs)


def validate_recalculated_plan(plan):
    if plan.get("execution_adapter") != "mt5_vantage_margin_v2":
        raise RuntimeError(
            "Plano recusado: execution_adapter não é mt5_vantage_margin_v2."
        )

    planned = [
        order
        for order in plan.get("orders", [])
        if order.get("status") == "PLANNED"
    ]

    skipped = [
        order
        for order in plan.get("orders", [])
        if order.get("status") == "SKIPPED"
    ]

    invalid_units = [
        order
        for order in planned
        if str(order.get("quantity_unit") or "").lower() != "lots"
    ]

    if invalid_units:
        raise RuntimeError(
            "Plano recusado: existe ordem PLANNED que não usa lotes MT5."
        )

    if not planned:
        raise RuntimeError(
            "Nenhuma ordem PLANNED encontrada."
        )

    return planned, skipped


def validate_paper_result(result):
    # Trava forte: este autopilot NÃO aceita qualquer resposta de execução LIVE.
    if result.get("live_submitted") is not False:
        raise RuntimeError(
            "TRAVA PAPER: backend não confirmou live_submitted=false."
        )

    if result.get("execution_route") != "mt5_bridge_paper":
        raise RuntimeError(
            "TRAVA PAPER: rota inesperada. "
            f"Recebido={result.get('execution_route')!r}."
        )

    if int(result.get("queued_orders") or 0) != 0:
        raise RuntimeError(
            "TRAVA PAPER: backend informou ordens reais enfileiradas."
        )

    if int(result.get("return_code") or 0) != 0:
        raise RuntimeError(
            f"Simulação PAPER terminou com return_code={result.get('return_code')}."
        )


def run_cycle():
    now = datetime.now(NY_TZ)

    print()
    print("=" * 65)
    print(
        f"[AUTOPILOT] Iniciando ciclo PAPER "
        f"{now:%Y-%m-%d %H:%M:%S} New York"
    )
    print("=" * 65)

    print("[0/3] Verificando API e bridge MT5...")
    bridge_status = verify_api_and_bridge()
    session = bridge_status.get("session") or {}
    print(
        "[OK] Bridge conectado "
        f"| conta={session.get('account')} "
        f"| servidor={session.get('server')} "
        f"| moeda={session.get('currency')}"
    )

    # 1. Rodar Qlib/pipeline real de pesquisa.
    # "real" aqui significa dados/modelo reais, NÃO envio de ordens.
    print("[1/3] Rodando pipeline Qlib real...")

    exit_code = run_pipeline_real()

    if exit_code != 0:
        raise RuntimeError(
            f"Pipeline terminou com código {exit_code}. "
            "Nenhuma simulação será executada."
        )

    print("[OK] Pipeline concluído com código 0.")

    # 2. Recalcular lotes usando o adaptador MT5/Vantage.
    print("[2/3] Recalculando plano MT5...")

    plan = request_json(
        "/api/orders/recalculate",
        method="POST",
        payload={
            "capital": CAPITAL_USD,
            "broker_id": "mt5",
            "symbol_suffix": "",
            "symbol_prefix": "",
        },
        timeout=60,
    )

    planned, skipped = validate_recalculated_plan(plan)

    print(
        f"[OK] {len(planned)} PLANNED / "
        f"{len(skipped)} SKIPPED"
    )

    # 3. PAPER. allow_live é fixo em False.
    print("[3/3] Executando simulação PAPER...")

    result = request_json(
        "/api/orders/execute",
        method="POST",
        payload={
            "allow_live": False,
            "broker_id": "mt5",
            "credentials": {
                "account": MT5_ACCOUNT
            },
            "account_capital": CAPITAL_USD,
        },
        timeout=30,
    )

    validate_paper_result(result)

    record = {
        "timestamp": datetime.now(NY_TZ).isoformat(),
        "mode": "PAPER",
        "capital_usd": CAPITAL_USD,
        "account": MT5_ACCOUNT,
        "planned_orders": planned,
        "skipped_orders": skipped,
        "execution_result": result,
    }

    append_log(record)

    print("[OK] Simulação PAPER concluída.")
    print(f"[LOG] {LOG_FILE}")

    return record


def main():
    verify_project_layout()

    print("=" * 65)
    print(" QUANTVIBE AUTOPILOT - PAPER ONLY")
    print("=" * 65)
    print()
    print("Modo       : PAPER ONLY")
    print(f"Capital    : ${CAPITAL_USD:.2f}")
    print(f"Conta MT5  : {MT5_ACCOUNT}")
    print("Sessão     : America/New_York")
    print(
        f"Janela     : "
        f"{START_TIME.strftime('%H:%M')} - "
        f"{LAST_START_TIME.strftime('%H:%M')}"
    )
    print("Execuções  : máximo 1 ciclo concluído por dia")
    print()
    print("Esperando janela da sessão...")

    while True:
        now = datetime.now(NY_TZ)
        today = now.date().isoformat()

        # Segunda a sexta. Feriados/mercado fechado serão bloqueados
        # pelas validações do pipeline/MT5 e registrados como falha.
        weekday_ok = now.weekday() < 5

        session_ok = (
            START_TIME
            <= now.time()
            <= LAST_START_TIME
        )

        state = load_state()

        if state.get("date") != today:
            state = {
                "date": today,
                "attempts": 0,
                "completed": False,
                "last_attempt": 0,
            }
            save_state(state)

        if (
            weekday_ok
            and session_ok
            and not state.get("completed")
        ):
            attempts = int(state.get("attempts", 0))
            last_attempt = float(state.get("last_attempt", 0))

            retry_ready = (
                time.time() - last_attempt
                >= RETRY_SECONDS
            )

            if (
                attempts < MAX_ATTEMPTS
                and retry_ready
            ):
                state["attempts"] = attempts + 1
                state["last_attempt"] = time.time()
                save_state(state)

                try:
                    run_cycle()

                    state["completed"] = True
                    state["completed_at"] = (
                        datetime.now(NY_TZ).isoformat()
                    )
                    state["last_error"] = None
                    save_state(state)

                    print()
                    print(
                        "[AUTOPILOT] Trabalho PAPER do dia concluído."
                    )

                except KeyboardInterrupt:
                    print()
                    print("[AUTOPILOT] Encerrado pelo usuário.")
                    raise

                except Exception as exc:
                    error_text = str(exc)

                    state["last_error"] = error_text
                    save_state(state)

                    append_log({
                        "timestamp": datetime.now(NY_TZ).isoformat(),
                        "mode": "PAPER",
                        "status": "FAILED",
                        "attempt": state["attempts"],
                        "error": error_text,
                    })

                    print()
                    print(f"[AUTOPILOT ERRO] {error_text}")

                    if state["attempts"] < MAX_ATTEMPTS:
                        print(
                            "[AUTOPILOT] Nova tentativa em 15 minutos."
                        )
                    else:
                        print(
                            "[AUTOPILOT] Limite diário de tentativas atingido."
                        )

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
