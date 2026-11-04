import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

try:
    from starlette.testclient import TestClient
    from web.api import app, mt5_bridge_state, mt5_integration_state
    HAS_WEB_DEPS = True
except ImportError:
    HAS_WEB_DEPS = False


@unittest.skipUnless(HAS_WEB_DEPS, "web dependencies (fastapi/starlette) not installed")
class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        mt5_integration_state.clear()
        mt5_bridge_state["queues"].clear()
        mt5_bridge_state["history"].clear()

    def test_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIn("artifacts", data)
        self.assertIn("pipeline", data)
        self.assertIn("mcp_server", data)

    def test_signals_endpoint_verified(self):
        res = self.client.get("/api/signals")
        # May be 200 if artifacts exist, or 404 if not
        if res.status_code == 200:
            data = res.json()
            self.assertTrue(data.get("verified"))
            self.assertEqual(data["checksum"], data["computed_checksum"])

    def test_evaluation_endpoint(self):
        res = self.client.get("/api/evaluation")
        if res.status_code == 200:
            data = res.json()
            self.assertIn("mean_ic", data)
            self.assertIn("passed", data)

    def test_orders_endpoint(self):
        res = self.client.get("/api/orders")
        if res.status_code == 200:
            data = res.json()
            self.assertIn("orders", data)
            self.assertIn("totals", data)

    def test_spa_root_served(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("QuantVibe", res.text)

    def test_mt5_bridge_endpoints(self):
        # 1. Download EA
        res_ea = self.client.get("/api/mt5/download-ea")
        self.assertEqual(res_ea.status_code, 200)
        self.assertIn("QuantVibe_Bridge", res_ea.headers.get("content-disposition", ""))

        # 2. Heartbeat registration
        hb_payload = {
            "account": "998877",
            "broker": "IC Markets Demo",
            "server": "ICMarketsSC",
            "currency": "USD",
            "balance": 10000.0,
            "equity": 10000.0,
            "leverage": 500,
            "algo_trading": True
        }
        res_hb = self.client.post("/api/mt5/heartbeat", json=hb_payload)
        self.assertEqual(res_hb.status_code, 200)

        # 3. Status
        res_status = self.client.get("/api/mt5/status?account=998877")
        self.assertEqual(res_status.status_code, 200)
        self.assertTrue(res_status.json()["connected"])

        # 4. Ack
        ack_payload = {
            "order_id": "ORD-1",
            "account": "998877",
            "symbol": "TSLA.US",
            "status": "FILLED",
            "ticket": 123456,
            "fill_price": 60.50,
            "balance": 10000.0,
            "notes": "Test fill"
        }
        res_ack = self.client.post("/api/mt5/ack", json=ack_payload)
        self.assertEqual(res_ack.status_code, 200)

    def test_mt5_closed_never_reports_live_or_serves_orders(self):
        """A backend/browser refresh starts UNKNOWN, never from an old cache."""
        status = self.client.get("/api/mt5/status?account=closed-account")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertEqual(body["status"], "UNKNOWN")
        self.assertFalse(body["connected"])
        self.assertFalse(body["isLive"])
        self.assertEqual(body["dataSource"], "unavailable")

        orders = self.client.get("/api/mt5/orders?account=closed-account&consumer=python-bridge-v1")
        self.assertEqual(orders.status_code, 503)
        detail = orders.json()["detail"]
        self.assertEqual(detail["code"], "MT5_INTEGRATION_UNAVAILABLE")
        self.assertFalse(detail["isLive"])

        broker_test = self.client.post(
            "/api/brokers/test",
            json={"broker_id": "mt5", "environment": "live", "credentials": {"account": "closed-account"}},
        )
        self.assertEqual(broker_test.status_code, 200)
        self.assertFalse(broker_test.json()["ok"])
        self.assertEqual(broker_test.json()["mt5_status"]["code"], "MT5_INTEGRATION_UNAVAILABLE")

    def test_expired_heartbeat_and_cache_are_not_live(self):
        payload = {
            "account": "expired", "broker": "Test", "server": "TestServer", "currency": "USD",
            "balance": 100.0, "equity": 100.0, "leverage": 100,
        }
        self.assertEqual(self.client.post("/api/mt5/heartbeat", json=payload).status_code, 200)
        # Simulates MT5/bridge being stopped while its old account snapshot remains in memory.
        mt5_integration_state["expired"]["_heartbeatAt"] = 0
        mt5_integration_state["expired"]["_dataReadAt"] = 0
        status = self.client.get("/api/mt5/status?account=expired").json()
        self.assertEqual(status["status"], "DISCONNECTED")
        self.assertFalse(status["isLive"])
        self.assertEqual(status["dataSource"], "unavailable")
        self.assertIsNotNone(status["lastSuccessfulDataReadAt"])
        self.assertEqual(
            self.client.get("/api/mt5/orders?account=expired&consumer=python-bridge-v1").status_code,
            503,
        )

    def test_reconnect_requires_a_new_validated_terminal_read(self):
        bad = self.client.post("/api/mt5/heartbeat", json={"account": "reconnect"})
        self.assertEqual(bad.status_code, 503)
        self.assertEqual(self.client.get("/api/mt5/status?account=reconnect").json()["status"], "DEGRADED")

        good = self.client.post("/api/mt5/heartbeat", json={
            "account": "reconnect", "broker": "Test", "server": "TestServer", "currency": "USD",
            "balance": 100.0, "equity": 99.0, "leverage": 100,
        })
        self.assertEqual(good.status_code, 200)
        status = self.client.get("/api/mt5/status?account=reconnect").json()
        self.assertEqual(status["status"], "CONNECTED")
        self.assertTrue(status["isLive"])
        self.assertEqual(status["dataSource"], "live")

    def test_terminal_collection_timestamp_is_preserved(self):
        collected_at = "2026-11-03T12:00:00+00:00"
        heartbeat = self.client.post("/api/mt5/heartbeat", json={
            "account": "timestamped", "broker": "Test", "server": "TestServer", "currency": "USD",
            "balance": 100.0, "equity": 100.0, "leverage": 100, "collectedAt": collected_at,
        })
        self.assertEqual(heartbeat.status_code, 200)
        status = self.client.get("/api/mt5/status?account=timestamped").json()
        self.assertEqual(status["dataCollectedAt"], collected_at)

    def test_recalculate_orders_plan(self):
        res = self.client.post(
            "/api/orders/recalculate",
            json={
                "capital": 5000.0,
                "symbol_suffix": ".US",
                "symbol_prefix": "",
                "broker_id": "alpaca",
            }
        )
        if res.status_code == 200:
            data = res.json()
            self.assertEqual(data["total_notional_target"], 5000.0)
            for ord_item in data["orders"]:
                if ord_item["status"] == "PLANNED":
                    self.assertTrue(ord_item["broker_symbol"].endswith(".US"))


    def test_recalculate_orders_plan_mt5_vantage(self):
        def fake_symbol_info(symbol):
            if symbol == "AMZNUSD":
                min_lot = 1.0
                step = 1.0
                max_lot = 1000.0
            else:
                min_lot = 0.1
                step = 0.1
                max_lot = 1500.0

            return SimpleNamespace(
                visible=True,
                volume_min=min_lot,
                volume_step=step,
                volume_max=max_lot,
                trade_contract_size=1.0,
                digits=2,
            )

        fake_mt5 = SimpleNamespace(
            ORDER_TYPE_BUY=0,
            ORDER_TYPE_SELL=1,

            initialize=lambda: True,
            shutdown=lambda: None,
            last_error=lambda: (0, "OK"),

            account_info=lambda: SimpleNamespace(
                currency="USC",
                balance=4_462.76,
                margin_free=1_000_000.0,
            ),

            symbol_info=fake_symbol_info,

            symbol_select=lambda symbol, visible: True,

            symbol_info_tick=lambda symbol: SimpleNamespace(
                ask=200.0,
                bid=199.0,
            ),

            order_calc_margin=lambda order_type, symbol, lot, price: 100.0,
            order_calc_profit=lambda order_type, symbol, lot, price_open, price_close: -100.0 * lot,
        )

        with patch.dict(
            sys.modules,
            {"MetaTrader5": fake_mt5},
        ):
            res = self.client.post(
                "/api/orders/recalculate",
                json={
                    "capital": 5000.0,
                    "symbol_suffix": "",
                    "symbol_prefix": "",
                    "broker_id": "mt5",
                },
            )

        self.assertEqual(res.status_code, 200, res.text)

        data = res.json()

        self.assertEqual(
            data.get("execution_adapter"),
            "mt5_vantage_margin_v2",
        )

        self.assertIn(
            "mt5_margin",
            data,
        )

        self.assertTrue(
            data["mt5_margin"]["cent_account"]
        )

        self.assertEqual(
            data["mt5_margin"]["cent_divider"],
            100.0,
        )

        self.assertAlmostEqual(
            data["mt5_margin"]["risk_policy"]["risk_per_trade_raw"],
            19.524575,
            places=5,
        )

        orders = data.get("orders", [])

        self.assertTrue(orders)

        for ord_item in orders:
            if ord_item.get("status") in {
                "PLANNED",
                "SKIPPED",
            }:
                self.assertEqual(
                    ord_item.get("quantity_unit"),
                    "lots",
                    msg=(
                        "MT5 order leaked non-lot unit: "
                        f"{ord_item}"
                    ),
                )

                self.assertNotEqual(
                    ord_item.get("quantity_unit"),
                    "shares",
                )


    def test_recalculate_orders_plan_injection_rejected(self):
        # Invalid capital
        res_neg = self.client.post(
            "/api/orders/recalculate",
            json={"capital": -100.0, "symbol_suffix": "", "symbol_prefix": ""}
        )
        self.assertEqual(res_neg.status_code, 400)

        # Disallowed characters in symbol suffix (command injection attempt)
        res_inj = self.client.post(
            "/api/orders/recalculate",
            json={"capital": 5000.0, "symbol_suffix": "; rm -rf /", "symbol_prefix": ""}
        )
        self.assertEqual(res_inj.status_code, 400)

    def test_ssrf_webhook_rejected(self):
        # Localhost attempt
        res_local = self.client.post(
            "/api/brokers/test",
            json={"broker_id": "webhook", "credentials": {"webhook_url": "http://127.0.0.1:8000/api/status"}}
        )
        self.assertEqual(res_local.status_code, 400)
        self.assertIn("anti-SSRF", res_local.json().get("detail", ""))

        # Alibaba Cloud ECS metadata service attempt
        res_alicloud = self.client.post(
            "/api/brokers/test",
            json={"broker_id": "webhook", "credentials": {"webhook_url": "http://100.100.100.200/latest/meta-data/"}}
        )
        self.assertEqual(res_alicloud.status_code, 400)

        # AWS/GCP metadata service attempt
        res_meta = self.client.post(
            "/api/brokers/test",
            json={"broker_id": "webhook", "credentials": {"webhook_url": "http://169.254.169.254/latest/meta-data/"}}
        )
        self.assertEqual(res_meta.status_code, 400)

        # Private RFC1918 VPC subnet attempt
        res_priv = self.client.post(
            "/api/brokers/test",
            json={"broker_id": "webhook", "credentials": {"webhook_url": "http://172.24.233.233:80/"}}
        )
        self.assertEqual(res_priv.status_code, 400)

    def test_pipeline_run_validation(self):
        # Disallowed mode
        res_mode = self.client.post(
            "/api/pipeline/run",
            json={"mode": "evil_mode"}
        )
        self.assertEqual(res_mode.status_code, 400)

        # Disallowed steps
        res_step = self.client.post(
            "/api/pipeline/run",
            json={"mode": "demo", "steps": ["prepare", "malicious_step"]}
        )
        self.assertEqual(res_step.status_code, 400)


if __name__ == "__main__":
    unittest.main()
