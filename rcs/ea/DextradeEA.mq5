//+------------------------------------------------------------------+
//|                                                  DextradeEA.mq5  |
//|                                       yeehee / dextrade — v0.1.0 |
//|                                                                  |
//| RCS auto-executor for XAU/USD (and related symbols).             |
//|                                                                  |
//| Polls home PC FastAPI for PENDING_PICKUP signals, executes via   |
//| OrderSend, reports result back to /api/ea/report.                |
//|                                                                  |
//| SAFETY DEFAULTS:                                                 |
//|   EnableExecution = false  (no real orders until explicitly on)  |
//|   EnablePaperMode = true   (logs only)                           |
//|   MaxOpenPositions = 1     (cap concurrent trades)               |
//|   DailyLossPct = 5%        (kill switch)                         |
//+------------------------------------------------------------------+
#property copyright "yeehee / dextrade"
#property link      "https://yeehee.vercel.app"
#property version   "0.1.0"
#property strict

#include <Trade\Trade.mqh>

// ============================================================================
// USER INPUTS
// ============================================================================
input string  ApiBaseUrl          = "http://localhost:8001";  // home PC FastAPI
input string  EaInstanceId        = "ea-mt5-pcrumah-1";
input double  RiskPercentPerTrade = 1.0;
input int     MinConfidencePct    = 65;
input bool    EnableExecution     = false;       // SAFETY: false default
input bool    EnablePaperMode     = true;        // SAFETY: true default
input int     PollIntervalSec     = 30;
input int     MaxOpenPositions    = 1;
input double  DailyLossPct        = 5.0;
input int     SlippagePoints      = 30;          // max acceptable slippage
input ulong   MagicNumber         = 20260505;    // unique magic for this EA

// ============================================================================
// GLOBAL STATE
// ============================================================================
CTrade   trade;
datetime g_starting_balance_date = 0;
double   g_starting_balance      = 0;
bool     g_kill_switch_active    = false;
datetime g_last_heartbeat        = 0;

// ============================================================================
// INITIALIZATION
// ============================================================================
int OnInit()
{
    PrintFormat("[DextradeEA] v0.1.0 init | EnableExecution=%s EnablePaperMode=%s",
                EnableExecution ? "true" : "false",
                EnablePaperMode ? "true" : "false");

    // Set magic for trade tracking
    trade.SetExpertMagicNumber(MagicNumber);
    trade.SetDeviationInPoints(SlippagePoints);
    trade.SetTypeFilling(ORDER_FILLING_IOC);   // immediate-or-cancel for liquid pairs

    g_starting_balance      = AccountInfoDouble(ACCOUNT_BALANCE);
    g_starting_balance_date = TimeCurrent();
    PrintFormat("[DextradeEA] starting_balance=$%.2f account=%I64d",
                g_starting_balance, AccountInfoInteger(ACCOUNT_LOGIN));

    // Verify symbol available
    if(!SymbolSelect(_Symbol, true))
    {
        Print("[DextradeEA] FAIL: symbol ", _Symbol, " not selectable");
        return INIT_FAILED;
    }

    EventSetTimer(PollIntervalSec);
    return INIT_SUCCEEDED;
}

// ============================================================================
// DEINITIALIZATION
// ============================================================================
void OnDeinit(const int reason)
{
    EventKillTimer();
    PrintFormat("[DextradeEA] shutdown reason=%d", reason);
}

// ============================================================================
// MAIN POLLING LOOP
// ============================================================================
void OnTimer()
{
    // 1. Reset starting_balance daily (so DailyLossPct measures within day)
    MqlDateTime today, start_dt;
    TimeToStruct(TimeCurrent(), today);
    TimeToStruct(g_starting_balance_date, start_dt);
    if(today.day != start_dt.day)
    {
        g_starting_balance      = AccountInfoDouble(ACCOUNT_BALANCE);
        g_starting_balance_date = TimeCurrent();
        g_kill_switch_active    = false;
        PrintFormat("[DextradeEA] new day — reset starting_balance=$%.2f", g_starting_balance);
    }

    // 2. Kill switch check
    if(g_kill_switch_active)
    {
        return;
    }
    double current_balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double daily_pnl_pct   = ((current_balance - g_starting_balance) / g_starting_balance) * 100.0;
    if(daily_pnl_pct <= -DailyLossPct)
    {
        PrintFormat("[DextradeEA] DAILY LOSS LIMIT (%.1f%%) — KILL SWITCH ACTIVE", daily_pnl_pct);
        g_kill_switch_active = true;
        SendHeartbeat(true);
        return;
    }

    // 3. Periodic heartbeat (every 60s)
    if(TimeCurrent() - g_last_heartbeat > 60)
    {
        SendHeartbeat(false);
        g_last_heartbeat = TimeCurrent();
    }

    // 4. Already at max open? Skip poll.
    if(CountOurPositions() >= MaxOpenPositions)
    {
        return;
    }

    // 5. Poll for next signal
    string body = HttpGet(ApiBaseUrl + "/api/ea/next-signal?ea=" + EaInstanceId);
    if(StringLen(body) < 5) return;

    // No signal available
    if(StringFind(body, "\"signal\":null") >= 0) return;

    // Parse signal fields (regex-style — MQL5 has no JSON parser built-in)
    long   signal_id     = (long)JsonGetNumber(body, "id");
    string direction     = JsonGetString(body, "direction");
    double entry         = JsonGetNumber(body, "entry");
    double sl            = JsonGetNumber(body, "sl");
    double tp1           = JsonGetNumber(body, "tp1");
    double tp2           = JsonGetNumber(body, "tp2");
    int    confidence    = (int)JsonGetNumber(body, "confidence_pct");
    string broker_symbol = JsonGetString(body, "broker_symbol");

    if(signal_id <= 0)
    {
        Print("[DextradeEA] failed to parse signal_id from response: ", StringSubstr(body, 0, 200));
        return;
    }

    PrintFormat("[DextradeEA] signal #%I64d %s @%.2f SL=%.2f TP1=%.2f conf=%d%%",
                signal_id, direction, entry, sl, tp1, confidence);

    if(confidence < MinConfidencePct)
    {
        PrintFormat("[DextradeEA] skip — conf %d%% < min %d%%", confidence, MinConfidencePct);
        ReportRejected(signal_id, "confidence_below_threshold");
        return;
    }

    if(direction != "LONG" && direction != "SHORT")
    {
        PrintFormat("[DextradeEA] skip — non-directional: %s", direction);
        ReportRejected(signal_id, "non_directional_signal");
        return;
    }

    if(entry <= 0 || sl <= 0)
    {
        Print("[DextradeEA] skip — invalid levels");
        ReportRejected(signal_id, "invalid_levels");
        return;
    }

    // 6. Compute lot size
    double lot = ComputeLotSize(entry, sl);
    if(lot <= 0)
    {
        Print("[DextradeEA] skip — invalid lot size");
        ReportRejected(signal_id, "invalid_lot_size");
        return;
    }

    // 7. Execute
    if(EnablePaperMode || !EnableExecution)
    {
        PrintFormat("[DextradeEA] PAPER %s %.2f @%.2f SL=%.2f TP1=%.2f (signal=%I64d)",
                    direction, lot, entry, sl, tp1, signal_id);
        ReportPaperExecuted(signal_id, direction, lot, entry, sl, tp1);
        return;
    }

    // LIVE EXECUTION
    bool ok = false;
    double price_now = direction == "LONG" ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                           : SymbolInfoDouble(_Symbol, SYMBOL_BID);

    if(direction == "LONG")
    {
        ok = trade.Buy(lot, _Symbol, 0, sl, tp1,
                       StringFormat("yeehee #%I64d", signal_id));
    }
    else
    {
        ok = trade.Sell(lot, _Symbol, 0, sl, tp1,
                        StringFormat("yeehee #%I64d", signal_id));
    }

    if(!ok)
    {
        uint err = trade.ResultRetcode();
        string desc = trade.ResultRetcodeDescription();
        PrintFormat("[DextradeEA] OrderSend FAILED signal=%I64d ret=%u (%s)", signal_id, err, desc);
        ReportRejected(signal_id, StringFormat("broker_ret_%u_%s", err, desc));
        return;
    }

    ulong  ticket    = trade.ResultOrder();
    double fill      = trade.ResultPrice();
    int    slippage  = (int)MathRound(MathAbs(fill - price_now) / SymbolInfoDouble(_Symbol, SYMBOL_POINT));

    PrintFormat("[DextradeEA] LIVE OPEN ticket=%I64u fill=%.2f slip=%d signal=%I64d",
                ticket, fill, slippage, signal_id);
    ReportLiveOpened(signal_id, ticket, fill, lot, sl, tp1, slippage);
}

// ============================================================================
// HELPERS
// ============================================================================

double ComputeLotSize(double entry, double sl)
{
    if(sl <= 0 || entry <= 0) return 0;
    double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk_amount = balance * (RiskPercentPerTrade / 100.0);
    double sl_distance = MathAbs(entry - sl);
    if(sl_distance <= 0) return 0;

    double tick_value  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tick_size <= 0) return 0;
    double pip_value   = tick_value / tick_size;
    double lot_raw     = risk_amount / (sl_distance * pip_value);

    // Round to broker lot step
    double lot_step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    double lot_min     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double lot_max     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    double lot_rounded = MathFloor(lot_raw / lot_step) * lot_step;
    return MathMax(lot_min, MathMin(lot_max, lot_rounded));
}

int CountOurPositions()
{
    int count = 0;
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(PositionSelectByTicket(ticket))
        {
            if(PositionGetInteger(POSITION_MAGIC) == (long)MagicNumber) count++;
        }
    }
    return count;
}

string HttpGet(string url)
{
    char post[];
    char result[];
    string headers = "";
    string result_headers;
    int timeout = 5000;

    int res = WebRequest("GET", url, headers, timeout, post, result, result_headers);
    if(res == -1)
    {
        int err = GetLastError();
        if(err == 4014)
        {
            // ERR_NOT_PERMITTED — URL not whitelisted in MT5 settings
            PrintFormat("[DextradeEA] WebRequest blocked: add %s to Tools→Options→Expert Advisors→Allow URL", ApiBaseUrl);
        }
        return "";
    }
    return CharArrayToString(result);
}

bool HttpPost(string url, string body)
{
    char post[];
    StringToCharArray(body, post, 0, StringLen(body));
    char result[];
    string headers = "Content-Type: application/json\r\n";
    string result_headers;
    int timeout = 5000;
    int res = WebRequest("POST", url, headers, timeout, post, result, result_headers);
    if(res == -1)
    {
        PrintFormat("[DextradeEA] HttpPost FAILED url=%s err=%d", url, GetLastError());
        return false;
    }
    return res == 200;
}

void SendHeartbeat(bool is_paused)
{
    string body = StringFormat(
        "{\"ea_instance_id\":\"%s\",\"account_login\":%I64d,\"account_balance\":%.2f,\"account_equity\":%.2f,\"open_positions\":%d,\"is_paused\":%s}",
        EaInstanceId,
        AccountInfoInteger(ACCOUNT_LOGIN),
        AccountInfoDouble(ACCOUNT_BALANCE),
        AccountInfoDouble(ACCOUNT_EQUITY),
        CountOurPositions(),
        is_paused ? "true" : "false"
    );
    HttpPost(ApiBaseUrl + "/api/ea/heartbeat", body);
}

void ReportPaperExecuted(long signal_id, string direction, double lot, double entry, double sl, double tp)
{
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_account_login\":%I64d,\"status\":\"OPEN\",\"execution_price\":%.2f,\"execution_lot\":%.2f,\"execution_sl\":%.2f,\"execution_tp\":%.2f,\"slippage_points\":0,\"account_balance_at_open\":%.2f,\"risk_pct_used\":%.2f,\"rejected_reason\":\"paper_mode\"}",
        signal_id, EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN),
        entry, lot, sl, tp,
        AccountInfoDouble(ACCOUNT_BALANCE), RiskPercentPerTrade
    );
    HttpPost(ApiBaseUrl + "/api/ea/report", body);
}

void ReportLiveOpened(long signal_id, ulong ticket, double fill, double lot, double sl, double tp, int slip)
{
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_ticket_id\":%I64u,\"mt5_account_login\":%I64d,\"status\":\"OPEN\",\"execution_price\":%.2f,\"execution_lot\":%.2f,\"execution_sl\":%.2f,\"execution_tp\":%.2f,\"slippage_points\":%d,\"account_balance_at_open\":%.2f,\"risk_pct_used\":%.2f}",
        signal_id, EaInstanceId, ticket, AccountInfoInteger(ACCOUNT_LOGIN),
        fill, lot, sl, tp, slip,
        AccountInfoDouble(ACCOUNT_BALANCE), RiskPercentPerTrade
    );
    HttpPost(ApiBaseUrl + "/api/ea/report", body);
}

void ReportRejected(long signal_id, string reason)
{
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_account_login\":%I64d,\"status\":\"REJECTED\",\"execution_lot\":0,\"rejected_reason\":\"%s\"}",
        signal_id, EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN), reason
    );
    HttpPost(ApiBaseUrl + "/api/ea/report", body);
}

// ============================================================================
// JSON helpers — minimal regex-style parsers (MQL5 has no JSON lib)
// Only handles top-level scalar fields. Sufficient for our schema.
// ============================================================================

string JsonGetString(string json, string key)
{
    string needle = "\"" + key + "\":\"";
    int pos = StringFind(json, needle);
    if(pos < 0) return "";
    int start = pos + StringLen(needle);
    int end = StringFind(json, "\"", start);
    if(end < 0) return "";
    return StringSubstr(json, start, end - start);
}

double JsonGetNumber(string json, string key)
{
    // Try numeric (no quotes)
    string needle = "\"" + key + "\":";
    int pos = StringFind(json, needle);
    if(pos < 0) return 0;
    int start = pos + StringLen(needle);
    // Skip optional whitespace
    while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' || StringGetCharacter(json, start) == '\t')) start++;
    // Find end of number (comma, brace, or whitespace)
    int end = start;
    while(end < StringLen(json))
    {
        ushort ch = StringGetCharacter(json, end);
        if(ch == ',' || ch == '}' || ch == ']' || ch == ' ' || ch == '\n' || ch == '\r') break;
        end++;
    }
    string num_str = StringSubstr(json, start, end - start);
    StringReplace(num_str, "\"", "");
    return StringToDouble(num_str);
}
//+------------------------------------------------------------------+
