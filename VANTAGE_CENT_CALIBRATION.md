# Vantage Markets CENT Account Calibration

## Status

This QuantVibe build has been validated with a live Vantage Markets MetaTrader 5 CENT account using currency `USC`.

Validation date: 2026-10-30

## Account semantics

For Vantage CENT accounts:

- MT5 may report a balance such as `3792.91 USC`.
- The economic USD equivalent is approximately `37.9291 USD`.
- QuantVibe must NOT interpret `3792.91 USC` as `3792.91 USD`.
- `cent_divider = 100` is applied when the MT5 account currency is `USC`.

The bridge now exposes both representations:

- `balance_raw`: raw MT5 USC balance
- `balance`: normalized economic balance
- `equity_raw`: raw MT5 USC equity
- `equity`: normalized economic equity
- `margin_free_raw`: raw MT5 free margin
- `margin_free`: normalized economic free margin
- `cent_account`
- `cent_divider`

## MT5 sizing

Stock CFD sizing is based on broker-valid MT5 lots and real margin requirements rather than treating account balance as unleveraged stock notional.

The implementation uses MT5 broker metadata including:

- `volume_min`
- `volume_step`
- `volume_max`
- `trade_contract_size`
- `order_calc_margin()`

Validated Vantage symbols include mappings such as:

- `V` -> `VISA`
- `XOM` -> `XOM.24H`
- `NVDA` -> `NVIDIA`
- `GOOGL` -> `GOOGL.24H`
- `AMZN` -> `AMZNUSD`

The adapter fails closed when minimum valid broker volume cannot be supported by available margin.

## Live execution flow

The current live flow is:

Qlib model
-> ranking/signals
-> mathematical/backtest gate
-> order plan
-> MT5 margin/lot adaptation
-> manual confirmation in Order Desk
-> QuantVibe backend queue
-> local MT5 bridge
-> MetaTrader5 `order_send()`
-> Vantage Markets
-> execution ACK / ticket

Qlib does NOT directly send an order to the broker.

Real execution currently requires explicit confirmation from the Order Desk.

## Model validation

Current validated research configuration:

- Qlib
- Alpha158 features
- LinearModel / Ridge
- cross-sectional label normalization
- boundary purge against label lookahead
- explicit research gate

Repeated real-data runs have passed the configured evaluation gate.

## Safety

Live execution includes checks for:

- verified signals
- approved evaluation gate
- real Qlib model/data source
- matching plan/signals checksum
- fresh plan
- explicit MT5 account identity
- matching MT5 server/currency
- live bridge heartbeat
- broker lot units
- real MT5 margin constraints
- duplicate execution journal protection

Runtime journals, artifacts, local market datasets, virtual environments and credentials must not be committed.

## Launcher

`Iniciar_QuantVibe.bat` starts:

1. QuantVibe web/API server
2. local MetaTrader 5 bridge
3. local QuantVibe web interface

The Vantage MT5 terminal must already be installed and authenticated.

## Validation

Latest local automated test result:

`30 passed, 3 warnings`

The remaining warnings are framework deprecation warnings and are not test failures.
