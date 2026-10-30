//+------------------------------------------------------------------+
//|                         QuantVibe_Bridge_SAFE_CENT_v3.mq5        |
//|        Hardened MT5 execution bridge for QuantVibe / cent acct   |
//+------------------------------------------------------------------+
#property copyright "QuantVibe Technologies / hardened build"
#property version   "3.00"
#property description "QuantVibe MT5 bridge hardened for explicit lots, cent accounts and fail-closed execution."
#property description "Default server is local QuantVibe: http://127.0.0.1:8000"
#property description "Keep InpAllowTrading=false until heartbeat/account mapping is verified."

//--- Inputs
input group "=== Conexion QuantVibe ==="
input string   InpServerUrl            = "http://127.0.0.1:8000"; // Add this URL to MT5 WebRequest whitelist
input string   InpAccountToken         = "";                      // Optional API alias; blank = MT5 login
input int      InpPollIntervalSec      = 2;                       // Order polling interval
input int      InpHeartbeatIntervalSec = 10;                      // Heartbeat interval

input group "=== Cuenta / Seguridad ==="
input ulong    InpExpectedLogin        = 0;                       // 0 = bind current login at startup
input string   InpExpectedServer       = "";                      // Blank = bind current server at startup
input string   InpExpectedCurrency     = "";                      // Blank = bind current currency at startup
input bool     InpCentAccount          = true;                    // TRUE for cent account
input double   InpCentDivider          = 100.0;                   // 100 account cents = 1 base currency unit
input bool     InpAllowTrading         = false;                   // LIVE execution switch - OFF by default

input group "=== Simbolos / Broker ==="
input string   InpSymbolPrefix         = "";
input string   InpSymbolSuffix         = "";                      // Example: .sc
input bool     InpAutoDetectSym        = false;                   // Fail closed by default

input group "=== Orden / Riesgo ==="
input ulong    InpMagicNumber          = 202609;
input ulong    InpDeviation            = 10;
input double   InpMaxLotsPerOrder      = 1.00;                    // Hard local ceiling
input int      InpMaxTickAgeSec        = 15;                      // Reject stale quotes
input string   InpComment              = "QuantVibe SAFE v3";

//--- Bound account identity
string   g_AccountID = "";
ulong    g_BoundLogin = 0;
string   g_BoundServer = "";
string   g_BoundCurrency = "";
datetime g_LastHeartbeatTime = 0;
string   g_LastExecutionStatus = "Inicializando...";
ulong    g_LastTicket = 0;

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
double ReportMoney(double rawValue)
{
   if(InpCentAccount)
   {
      if(InpCentDivider <= 0.0)
         return 0.0;
      return rawValue / InpCentDivider;
   }
   return rawValue;
}

string BoolJson(bool value)
{
   return value ? "true" : "false";
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
}

bool ValidateBoundAccount(string &reason)
{
   ulong currentLogin = (ulong)AccountInfoInteger(ACCOUNT_LOGIN);
   string currentServer = AccountInfoString(ACCOUNT_SERVER);
   string currentCurrency = AccountInfoString(ACCOUNT_CURRENCY);

   if(currentLogin != g_BoundLogin)
   {
      reason = StringFormat("Login cambio: esperado %I64u, actual %I64u", g_BoundLogin, currentLogin);
      return false;
   }
   if(currentServer != g_BoundServer)
   {
      reason = "Servidor cambio: esperado '" + g_BoundServer + "', actual '" + currentServer + "'";
      return false;
   }
   if(currentCurrency != g_BoundCurrency)
   {
      reason = "Moneda cambio: esperada '" + g_BoundCurrency + "', actual '" + currentCurrency + "'";
      return false;
   }
   reason = "";
   return true;
}

bool TradingEnvironmentReady(string &reason)
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      reason = "Terminal MT5 sin conexion.";
      return false;
   }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
   {
      reason = "Algo Trading desactivado en terminal.";
      return false;
   }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      reason = "Trading no permitido para este EA.";
      return false;
   }
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   {
      reason = "Trading no permitido en la cuenta.";
      return false;
   }
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
   {
      reason = "La cuenta no permite trading por Expert Advisor.";
      return false;
   }
   return ValidateBoundAccount(reason);
}

ulong HashOrderId(string text)
{
   ulong hash = 1469598103934665603;
   for(int i = 0; i < StringLen(text); i++)
   {
      hash ^= (ulong)StringGetCharacter(text, i);
      hash *= 1099511628211;
   }
   return hash;
}

string ProcessedKey(string orderId)
{
   return "QV3_" + StringFormat("%I64u", g_BoundLogin) + "_" + StringFormat("%I64u", HashOrderId(orderId));
}

bool WasProcessed(string orderId)
{
   if(orderId == "") return false;
   return GlobalVariableCheck(ProcessedKey(orderId));
}

void MarkProcessed(string orderId)
{
   if(orderId == "") return;
   GlobalVariableSet(ProcessedKey(orderId), (double)TimeCurrent());
}

int LotDigits(double stepLot)
{
   int digits = 0;
   double scaled = stepLot;
   while(digits < 8 && MathAbs(scaled - MathRound(scaled)) > 1e-9)
   {
      scaled *= 10.0;
      digits++;
   }
   return digits;
}

bool ValidateVolume(string symbol, double desiredQty, double &finalLot, string &reason)
{
   finalLot = 0.0;
   if(!MathIsValidNumber(desiredQty) || desiredQty <= 0.0)
   {
      reason = "qty/lotes debe ser numerico y > 0.";
      return false;
   }

   double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

   if(minLot <= 0.0 || maxLot <= 0.0 || stepLot <= 0.0)
   {
      reason = "Broker devolvio limites de volumen invalidos.";
      return false;
   }

   double eps = MathMax(1e-9, stepLot * 1e-7);
   if(desiredQty < minLot - eps)
   {
      reason = StringFormat("Volumen %.8f menor al minimo broker %.8f; se RECHAZA, no se aumenta.", desiredQty, minLot);
      return false;
   }
   if(desiredQty > maxLot + eps)
   {
      reason = StringFormat("Volumen %.8f mayor al maximo broker %.8f.", desiredQty, maxLot);
      return false;
   }
   if(InpMaxLotsPerOrder > 0.0 && desiredQty > InpMaxLotsPerOrder + eps)
   {
      reason = StringFormat("Volumen %.8f supera limite local %.8f lotes.", desiredQty, InpMaxLotsPerOrder);
      return false;
   }

   double steps = desiredQty / stepLot;
   double nearestSteps = MathRound(steps);
   if(MathAbs(steps - nearestSteps) > 1e-7)
   {
      reason = StringFormat("Volumen %.8f no respeta step broker %.8f; se RECHAZA, no se redondea.", desiredQty, stepLot);
      return false;
   }

   finalLot = NormalizeDouble(nearestSteps * stepLot, LotDigits(stepLot));
   if(finalLot < minLot - eps || finalLot > maxLot + eps)
   {
      reason = "Volumen final fuera de limites despues de normalizacion numerica.";
      return false;
   }
   reason = "";
   return true;
}

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_BoundLogin = (ulong)AccountInfoInteger(ACCOUNT_LOGIN);
   g_BoundServer = AccountInfoString(ACCOUNT_SERVER);
   g_BoundCurrency = AccountInfoString(ACCOUNT_CURRENCY);

   if(InpExpectedLogin != 0 && g_BoundLogin != InpExpectedLogin)
   {
      Print("[QuantVibe BLOQUEO] Login inesperado. Esperado=", InpExpectedLogin, " actual=", g_BoundLogin);
      return INIT_FAILED;
   }
   if(InpExpectedServer != "" && g_BoundServer != InpExpectedServer)
   {
      Print("[QuantVibe BLOQUEO] Servidor inesperado. Esperado=", InpExpectedServer, " actual=", g_BoundServer);
      return INIT_FAILED;
   }
   if(InpExpectedCurrency != "" && g_BoundCurrency != InpExpectedCurrency)
   {
      Print("[QuantVibe BLOQUEO] Moneda inesperada. Esperada=", InpExpectedCurrency, " actual=", g_BoundCurrency);
      return INIT_FAILED;
   }
   if(InpCentAccount && InpCentDivider <= 0.0)
   {
      Print("[QuantVibe BLOQUEO] InpCentDivider debe ser > 0.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpPollIntervalSec < 1 || InpHeartbeatIntervalSec < 1)
   {
      Print("[QuantVibe BLOQUEO] Intervalos deben ser >= 1 segundo.");
      return INIT_PARAMETERS_INCORRECT;
   }

   g_AccountID = (InpAccountToken != "") ? InpAccountToken : StringFormat("%I64u", g_BoundLogin);
   EventSetTimer(InpPollIntervalSec);

   g_LastExecutionStatus = InpAllowTrading ? "LIVE habilitado - esperando orden" : "SAFE: ejecucion real desactivada";
   SendHeartbeat();
   g_LastHeartbeatTime = TimeCurrent();
   DrawDashboard();

   Print("[QuantVibe SAFE v3] Inicializado. Cuenta=", g_AccountID,
         " login=", g_BoundLogin,
         " server=", g_BoundServer,
         " currency=", g_BoundCurrency,
         " cent=", InpCentAccount ? "true" : "false",
         " allowTrading=", InpAllowTrading ? "true" : "false");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, "QV_");
   ChartRedraw();
   Print("[QuantVibe SAFE v3] EA detenido.");
}

void OnTimer()
{
   string identityReason = "";
   if(!ValidateBoundAccount(identityReason))
   {
      g_LastExecutionStatus = "BLOQUEADO: " + identityReason;
      DrawDashboard();
      return;
   }

   if((TimeCurrent() - g_LastHeartbeatTime) >= InpHeartbeatIntervalSec)
   {
      SendHeartbeat();
      g_LastHeartbeatTime = TimeCurrent();
   }

   if(InpAllowTrading)
      PollOrders();
   else
      g_LastExecutionStatus = "SAFE: conectado; InpAllowTrading=false";

   DrawDashboard();
}

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
void PollOrders()
{
   double reportBalance = ReportMoney(AccountInfoDouble(ACCOUNT_BALANCE));
   string url = InpServerUrl + "/api/mt5/orders?account=" + g_AccountID + "&balance=" + DoubleToString(reportBalance, 2);
   char post[], result[];
   string headers = "User-Agent: QuantVibe-MT5-EA/3.0\r\nAccept: application/json\r\n";
   string result_headers;
   ResetLastError();
   int res = WebRequest("GET", url, headers, 3000, post, result, result_headers);

   if(res == -1)
   {
      int err = GetLastError();
      g_LastExecutionStatus = "HTTP GET fallo (" + IntegerToString(err) + ")";
      if(err == 4014)
         Print("[QuantVibe ERROR 4014] Agrega a WebRequest: ", InpServerUrl);
      else
         Print("[QuantVibe HTTP] GET fallo err=", err);
      return;
   }

   if(res != 200)
   {
      g_LastExecutionStatus = "Servidor respondio HTTP " + IntegerToString(res);
      Print("[QuantVibe HTTP] GET ", url, " -> ", res);
      return;
   }

   ProcessOrderJson(CharArrayToString(result));
}

void SendHeartbeat()
{
   double rawBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   double rawEquity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = ReportMoney(rawBalance);
   double equity  = ReportMoney(rawEquity);

   string payload = StringFormat(
      "{\"account\":\"%s\",\"login\":%I64u,\"broker\":\"%s\",\"server\":\"%s\",\"currency\":\"%s\",\"balance\":%.2f,\"equity\":%.2f,\"balance_raw\":%.2f,\"equity_raw\":%.2f,\"cent_account\":%s,\"cent_divider\":%.2f,\"leverage\":%d,\"algo_trading\":%s,\"allow_trading\":%s,\"magic\":%I64u}",
      JsonEscape(g_AccountID),
      g_BoundLogin,
      JsonEscape(AccountInfoString(ACCOUNT_COMPANY)),
      JsonEscape(g_BoundServer),
      JsonEscape(g_BoundCurrency),
      balance,
      equity,
      rawBalance,
      rawEquity,
      BoolJson(InpCentAccount),
      InpCentDivider,
      (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
      BoolJson((bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)),
      BoolJson(InpAllowTrading),
      InpMagicNumber
   );

   string url = InpServerUrl + "/api/mt5/heartbeat";
   char post[], result[];
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);
   string headers = "Content-Type: application/json\r\nUser-Agent: QuantVibe-MT5-EA/3.0\r\n";
   string result_headers;
   ResetLastError();
   int res = WebRequest("POST", url, headers, 3000, post, result, result_headers);
   if(res < 200 || res >= 300)
      Print("[QuantVibe HEARTBEAT] HTTP=", res, " err=", GetLastError());
}

void SendAck(string orderId, string symbol, string status, ulong ticket, double fillPrice, string notes)
{
   string url = InpServerUrl + "/api/mt5/ack";
   string payload = StringFormat(
      "{\"order_id\":\"%s\",\"account\":\"%s\",\"symbol\":\"%s\",\"status\":\"%s\",\"ticket\":%I64u,\"fill_price\":%.8f,\"balance\":%.2f,\"notes\":\"%s\"}",
      JsonEscape(orderId), JsonEscape(g_AccountID), JsonEscape(symbol), JsonEscape(status), ticket,
      fillPrice, ReportMoney(AccountInfoDouble(ACCOUNT_BALANCE)), JsonEscape(notes)
   );

   char post[], result[];
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);
   string headers = "Content-Type: application/json\r\nUser-Agent: QuantVibe-MT5-EA/3.0\r\n";
   string result_headers;
   ResetLastError();
   int res = WebRequest("POST", url, headers, 3000, post, result, result_headers);
   if(res < 200 || res >= 300)
      Print("[QuantVibe ACK] HTTP=", res, " order=", orderId, " err=", GetLastError());
}

//+------------------------------------------------------------------+
//| Symbol / execution                                               |
//+------------------------------------------------------------------+
string ResolveSymbol(string baseSymbol)
{
   bool isCustom = false;

   // Explicit prefix/suffix has priority when configured.
   if(InpSymbolPrefix != "" || InpSymbolSuffix != "")
   {
      string explicitCandidate = InpSymbolPrefix + baseSymbol + InpSymbolSuffix;
      if(SymbolExist(explicitCandidate, isCustom))
      {
         SymbolSelect(explicitCandidate, true);
         return explicitCandidate;
      }
      return ""; // fail closed: user configured explicit mapping and it does not exist
   }

   if(SymbolExist(baseSymbol, isCustom))
   {
      SymbolSelect(baseSymbol, true);
      return baseSymbol;
   }

   if(InpAutoDetectSym)
   {
      string candidates[] = {
         baseSymbol + ".US", baseSymbol + ".us", "#" + baseSymbol,
         baseSymbol + "_CFD", baseSymbol + ".cfd", baseSymbol + ".pro",
         baseSymbol + "_m", baseSymbol + ".m", baseSymbol + ".cash", baseSymbol + ".sc"
      };
      for(int i = 0; i < ArraySize(candidates); i++)
      {
         isCustom = false;
         if(SymbolExist(candidates[i], isCustom))
         {
            SymbolSelect(candidates[i], true);
            Print("[QuantVibe AUTO-MAP] ", baseSymbol, " -> ", candidates[i]);
            return candidates[i];
         }
      }
   }
   return "";
}

ENUM_ORDER_TYPE_FILLING GetSymbolFilling(string symbol)
{
   uint fillingMode = (uint)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((fillingMode & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((fillingMode & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

bool SymbolAllowsAction(string symbol, string action, string &reason)
{
   ENUM_SYMBOL_TRADE_MODE mode = (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED || mode == SYMBOL_TRADE_MODE_CLOSEONLY)
   {
      reason = "Simbolo no permite nuevas operaciones.";
      return false;
   }
   if(action == "BUY" && mode == SYMBOL_TRADE_MODE_SHORTONLY)
   {
      reason = "Simbolo permite solo posiciones short.";
      return false;
   }
   if(action == "SELL" && mode == SYMBOL_TRADE_MODE_LONGONLY)
   {
      reason = "Simbolo permite solo posiciones long.";
      return false;
   }
   return true;
}

bool ExecuteOrder(string orderId, string baseSymbol, string action, double volume, double estPrice)
{
   if(!InpAllowTrading)
   {
      g_LastExecutionStatus = "SAFE: orden recibida pero trading desactivado";
      return false;
   }

   if(orderId == "")
   {
      g_LastExecutionStatus = "RECHAZO: order_id vacio";
      Print("[QuantVibe RECHAZO] order_id obligatorio.");
      return false;
   }
   if(WasProcessed(orderId))
   {
      string msg = "order_id ya ejecutado anteriormente; no se repite.";
      g_LastExecutionStatus = "DUPLICADO: " + orderId;
      Print("[QuantVibe IDEMPOTENCIA] ", msg, " id=", orderId);
      SendAck(orderId, baseSymbol, "DUPLICATE_IGNORED", g_LastTicket, 0, msg);
      return false;
   }

   StringToUpper(action);
   if(action != "BUY" && action != "SELL")
   {
      string msg = "Action invalida '" + action + "'. Solo BUY/SELL.";
      g_LastExecutionStatus = "RECHAZO: action invalida";
      SendAck(orderId, baseSymbol, "REJECTED", 0, 0, msg);
      return false;
   }

   string envReason = "";
   if(!TradingEnvironmentReady(envReason))
   {
      g_LastExecutionStatus = "BLOQUEADO: " + envReason;
      SendAck(orderId, baseSymbol, "REJECTED_ENVIRONMENT", 0, 0, envReason);
      return false;
   }

   string brokerSymbol = ResolveSymbol(baseSymbol);
   if(brokerSymbol == "")
   {
      string msg = "Simbolo '" + baseSymbol + "' no encontrado con el mapeo permitido.";
      g_LastExecutionStatus = "RECHAZO: simbolo";
      SendAck(orderId, baseSymbol, "REJECTED_SYMBOL", 0, 0, msg);
      return false;
   }

   string modeReason = "";
   if(!SymbolAllowsAction(brokerSymbol, action, modeReason))
   {
      g_LastExecutionStatus = "RECHAZO: " + modeReason;
      SendAck(orderId, brokerSymbol, "REJECTED_SYMBOL_MODE", 0, 0, modeReason);
      return false;
   }

   double finalLot = 0.0;
   string volumeReason = "";
   if(!ValidateVolume(brokerSymbol, volume, finalLot, volumeReason))
   {
      g_LastExecutionStatus = "RECHAZO VOLUMEN: " + volumeReason;
      Print("[QuantVibe RECHAZO VOLUMEN] ", volumeReason);
      SendAck(orderId, brokerSymbol, "REJECTED_VOLUME", 0, 0, volumeReason);
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(brokerSymbol, tick) || tick.time <= 0)
   {
      string msg = "No hay tick valido para " + brokerSymbol;
      g_LastExecutionStatus = "RECHAZO: sin tick";
      SendAck(orderId, brokerSymbol, "REJECTED_NO_TICK", 0, 0, msg);
      return false;
   }
   long tickAge = (long)TimeCurrent() - (long)tick.time;
   if(InpMaxTickAgeSec > 0 && tickAge > InpMaxTickAgeSec)
   {
      string msg = StringFormat("Tick obsoleto: %I64d s > max %d s", tickAge, InpMaxTickAgeSec);
      g_LastExecutionStatus = "RECHAZO: tick obsoleto";
      SendAck(orderId, brokerSymbol, "REJECTED_STALE_TICK", 0, 0, msg);
      return false;
   }

   ENUM_ORDER_TYPE orderType = (action == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price = (orderType == ORDER_TYPE_BUY) ? tick.ask : tick.bid;
   if(price <= 0.0)
   {
      string msg = "Cotizacion no disponible para " + brokerSymbol;
      g_LastExecutionStatus = "RECHAZO: mercado/cotizacion";
      SendAck(orderId, brokerSymbol, "REJECTED_MARKET_CLOSED", 0, 0, msg);
      return false;
   }

   MqlTradeRequest request;
   MqlTradeResult result;
   MqlTradeCheckResult check;
   ZeroMemory(request);
   ZeroMemory(result);
   ZeroMemory(check);

   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = brokerSymbol;
   request.volume       = finalLot;
   request.type         = orderType;
   request.price        = price;
   request.deviation    = InpDeviation;
   request.magic        = InpMagicNumber;
   request.comment      = InpComment;
   request.type_filling = GetSymbolFilling(brokerSymbol);
   request.type_time    = ORDER_TIME_GTC;

   ResetLastError();
   if(!OrderCheck(request, check))
   {
      string msg = StringFormat("OrderCheck fallo: err=%d retcode=%u comment=%s", GetLastError(), check.retcode, check.comment);
      g_LastExecutionStatus = "RECHAZO OrderCheck";
      SendAck(orderId, brokerSymbol, "REJECTED_ORDER_CHECK", 0, 0, msg);
      return false;
   }
   if(check.retcode != 0 && check.retcode != TRADE_RETCODE_DONE)
   {
      string msg = StringFormat("OrderCheck rechazo: retcode=%u comment=%s", check.retcode, check.comment);
      g_LastExecutionStatus = "RECHAZO OrderCheck";
      SendAck(orderId, brokerSymbol, "REJECTED_ORDER_CHECK", 0, 0, msg);
      return false;
   }

   ResetLastError();
   if(!OrderSend(request, result))
   {
      string msg = StringFormat("OrderSend fallo: err=%d retcode=%u comment=%s", GetLastError(), result.retcode, result.comment);
      g_LastExecutionStatus = "ERROR OrderSend";
      SendAck(orderId, brokerSymbol, "ERROR", 0, 0, msg);
      return false;
   }

   if(result.retcode == TRADE_RETCODE_DONE ||
      result.retcode == TRADE_RETCODE_PLACED ||
      result.retcode == TRADE_RETCODE_DONE_PARTIAL)
   {
      ulong ticket = (result.order != 0) ? result.order : result.deal;
      MarkProcessed(orderId); // persistent terminal GlobalVariable protects against replay after restart
      g_LastTicket = ticket;
      g_LastExecutionStatus = StringFormat("FILLED: %s %s %.4f lot @ %.5f ticket=%I64u", action, brokerSymbol, finalLot, result.price, ticket);
      Print("[QuantVibe FILLED] ", g_LastExecutionStatus);
      SendAck(orderId, brokerSymbol, "FILLED", ticket, result.price, "Ejecutada por SAFE v3");
      return true;
   }

   string rejectReason = StringFormat("Broker rechazo: retcode=%u comment=%s", result.retcode, result.comment);
   g_LastExecutionStatus = "RECHAZO BROKER: " + result.comment;
   SendAck(orderId, brokerSymbol, "REJECTED", 0, 0, rejectReason);
   return false;
}

//+------------------------------------------------------------------+
//| JSON parser for flat order objects                               |
//+------------------------------------------------------------------+
string ExtractJsonValue(string json, string key)
{
   string searchKey = "\"" + key + "\":";
   int pos = StringFind(json, searchKey);
   if(pos < 0) return "";

   int valStart = pos + StringLen(searchKey);
   while(valStart < StringLen(json) &&
         (StringGetCharacter(json, valStart) == ' ' || StringGetCharacter(json, valStart) == '"'))
      valStart++;

   int valEnd = valStart;
   while(valEnd < StringLen(json) &&
         StringGetCharacter(json, valEnd) != ',' &&
         StringGetCharacter(json, valEnd) != '}' &&
         StringGetCharacter(json, valEnd) != '"' &&
         StringGetCharacter(json, valEnd) != '\r' &&
         StringGetCharacter(json, valEnd) != '\n')
      valEnd++;

   return StringSubstr(json, valStart, valEnd - valStart);
}

void ProcessOrderJson(string json)
{
   if(StringFind(json, "\"orders\":") < 0) return;
   int ordersStart = StringFind(json, "\"orders\":[");
   if(ordersStart < 0) return;

   int startPos = ordersStart + 10;
   int endPos = StringFind(json, "]", startPos);
   if(endPos <= startPos) return;

   string ordersArray = StringSubstr(json, startPos, endPos - startPos);
   string rawOrders[];
   int count = StringSplit(ordersArray, '}', rawOrders);

   for(int i = 0; i < count; i++)
   {
      string item = rawOrders[i];
      if(StringFind(item, "\"instrument\":") < 0 && StringFind(item, "\"symbol\":") < 0)
         continue;

      string orderId = ExtractJsonValue(item, "id");
      if(orderId == "") orderId = ExtractJsonValue(item, "order_id");
      string symbol = ExtractJsonValue(item, "instrument");
      if(symbol == "") symbol = ExtractJsonValue(item, "symbol");
      string action = ExtractJsonValue(item, "action");
      string qtyStr = ExtractJsonValue(item, "qty");
      string quantityUnit = ExtractJsonValue(item, "quantity_unit");
      string prcStr = ExtractJsonValue(item, "est_price");

      StringToUpper(action);
      StringToLower(quantityUnit);

      if(orderId == "")
      {
         Print("[QuantVibe RECHAZO] Orden sin id/order_id.");
         continue;
      }
      if(symbol == "")
      {
         SendAck(orderId, "", "REJECTED", 0, 0, "Orden sin instrument/symbol.");
         continue;
      }
      if(action != "BUY" && action != "SELL")
      {
         SendAck(orderId, symbol, "REJECTED", 0, 0, "Action obligatoria BUY/SELL; recibido '" + action + "'.");
         continue;
      }
      if(quantityUnit != "lots")
      {
         SendAck(orderId, symbol, "REJECTED_UNIT", 0, 0, "MT5 exige quantity_unit='lots'; recibido '" + quantityUnit + "'.");
         continue;
      }
      if(qtyStr == "")
      {
         SendAck(orderId, symbol, "REJECTED_VOLUME", 0, 0, "Orden sin qty.");
         continue;
      }

      double volume = StringToDouble(qtyStr);
      if(!MathIsValidNumber(volume) || volume <= 0.0)
      {
         SendAck(orderId, symbol, "REJECTED_VOLUME", 0, 0, "qty invalido: '" + qtyStr + "'.");
         continue;
      }

      double price = (prcStr == "") ? 0.0 : StringToDouble(prcStr);
      Print("[QuantVibe] Orden valida recibida: id=", orderId, " ", action, " ", symbol, " ", DoubleToString(volume, 8), " lots");
      ExecuteOrder(orderId, symbol, action, volume, price);
   }
}

//+------------------------------------------------------------------+
//| Dashboard                                                        |
//+------------------------------------------------------------------+
void DrawDashboard()
{
   int x = 20;
   int y = 30;
   int lineGap = 18;

   CreateLabel("QV_TITLE", "QUANTVIBE MT5 BRIDGE SAFE v3.0 - CENT READY", x, y, clrWhite, 10, true);
   y += lineGap + 4;

   color statusCol = InpAllowTrading ? clrLimeGreen : clrGold;
   string mode = InpAllowTrading ? "LIVE ARMADO" : "SAFE / SOLO HEARTBEAT";
   CreateLabel("QV_STATUS", "MODO: " + mode, x, y, statusCol, 8, true);
   y += lineGap;

   CreateLabel("QV_SERVER", "API: " + InpServerUrl + " | MT5: " + g_BoundServer, x, y, clrSilver, 8, false);
   y += lineGap;

   string accInfo = StringFormat(
      "Cuenta: %I64u (%s) | Raw: %.2f | Reportado: %.2f | Equity: %.2f | CENT=%s",
      g_BoundLogin,
      g_BoundCurrency,
      AccountInfoDouble(ACCOUNT_BALANCE),
      ReportMoney(AccountInfoDouble(ACCOUNT_BALANCE)),
      ReportMoney(AccountInfoDouble(ACCOUNT_EQUITY)),
      InpCentAccount ? "SI" : "NO"
   );
   CreateLabel("QV_ACC", accInfo, x, y, clrWhite, 8, false);
   y += lineGap;

   CreateLabel("QV_LAST", "Ultimo estado: " + g_LastExecutionStatus, x, y, clrSkyBlue, 8, false);
   y += lineGap;

   CreateLabel("QV_RULES", StringFormat("Magic=%I64u | MaxLot=%.4f | AutoMap=%s", InpMagicNumber, InpMaxLotsPerOrder, InpAutoDetectSym ? "ON" : "OFF"), x, y, clrDimGray, 7, false);
   ChartRedraw();
}

void CreateLabel(string name, string text, int x, int y, color col, int fontSize=8, bool isBold=false)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetString(0, name, OBJPROP_FONT, isBold ? "Arial Bold" : "Consolas");
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}
