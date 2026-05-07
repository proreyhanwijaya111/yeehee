//+------------------------------------------------------------------+
//|                                                  DextradeEA.mq5  |
//|                                       yeehee / dextrade — v0.2.1 |
//|                                                                  |
//| RCS auto-executor with:                                          |
//|  - Dynamic config polling from FastAPI (no EA restart for tweak) |
//|  - Break-even SL automation                                      |
//|  - Trailing stop                                                 |
//|  - Max trades per day cap                                        |
//|  - Daily loss kill switch                                        |
//|  - Multi-source confluence gating (signal must be PENDING_PICKUP)|
//|                                                                  |
//| SAFETY DEFAULTS:                                                 |
//|   EnableExecution = false (must be flipped ON via UI)            |
//|   EnablePaperMode = true  (logs only)                            |
//+------------------------------------------------------------------+
#property copyright "yeehee / dextrade"
#property link      "https://yeehee.vercel.app"
#property version   "0.2.1"
#property strict

#include <Trade\Trade.mqh>

// ============================================================================
// USER INPUTS (initial values — overridden by API config every poll)
// ============================================================================
// Note: MT5 WebRequest whitelist requires URL with valid TLD (.com/.me/etc).
// localtest.me is a PUBLIC DNS that always resolves to 127.0.0.1, so requests
// hit local FastAPI on port 8001. Whitelist URL di MT5: http://localtest.me:8001
input string  ApiBaseUrl          = "http://localtest.me:8001";
input string  EaInstanceId        = "ea-mt5-pcrumah-1";
input int     PollIntervalSec     = 30;
input ulong   MagicNumber         = 20260505;
input int     SlippagePoints      = 30;

// ============================================================================
// DYNAMIC CONFIG (refreshed from API every poll)
// ============================================================================
struct ApiConfig {
    bool   enable_execution;
    bool   enable_paper;
    int    max_open_positions;
    int    max_trades_per_day;
    int    trades_today;
    int    trades_remaining;
    double daily_loss_pct;
    int    min_confidence_pct;
    double risk_per_trade_pct;
    bool   enable_break_even;
    int    break_even_trigger_pips;
    int    break_even_lock_pips;
    bool   enable_trailing;
    int    trailing_trigger_pips;
    int    trailing_distance_pips;
};

ApiConfig g_config;

// Defaults if API unreachable on first poll
void SetSafeDefaults()
{
    g_config.enable_execution        = false;   // MUST be explicitly enabled via UI
    g_config.enable_paper            = true;
    g_config.max_open_positions      = 1;
    g_config.max_trades_per_day      = 5;
    g_config.trades_today            = 0;
    g_config.trades_remaining        = 5;
    g_config.daily_loss_pct          = 5.0;
    g_config.min_confidence_pct      = 65;
    g_config.risk_per_trade_pct      = 1.0;
    g_config.enable_break_even       = true;
    g_config.break_even_trigger_pips = 50;
    g_config.break_even_lock_pips    = 5;
    g_config.enable_trailing         = true;
    g_config.trailing_trigger_pips   = 100;
    g_config.trailing_distance_pips  = 30;
}

// ============================================================================
// GLOBAL STATE
// ============================================================================
CTrade   trade;
datetime g_starting_balance_date = 0;
double   g_starting_balance      = 0;
bool     g_kill_switch_active    = false;
datetime g_last_heartbeat        = 0;
datetime g_last_config_poll      = 0;
datetime g_last_spot_post        = 0;
int      g_config_poll_interval  = 60;   // refresh API config every 60s

// ============================================================================
// INITIALIZATION
// ============================================================================
int OnInit()
{
    Print("[DextradeEA] v0.2.1 init");
    SetSafeDefaults();
    PollConfig();   // initial fetch

    PrintFormat("[DextradeEA] config: exec=%s paper=%s max_open=%d max_per_day=%d risk=%.2f%% BEP=%s trail=%s",
                g_config.enable_execution ? "true" : "false",
                g_config.enable_paper ? "true" : "false",
                g_config.max_open_positions, g_config.max_trades_per_day,
                g_config.risk_per_trade_pct,
                g_config.enable_break_even ? "true" : "false",
                g_config.enable_trailing ? "true" : "false");

    trade.SetExpertMagicNumber(MagicNumber);
    trade.SetDeviationInPoints(SlippagePoints);
    trade.SetTypeFilling(ORDER_FILLING_IOC);

    g_starting_balance      = AccountInfoDouble(ACCOUNT_BALANCE);
    g_starting_balance_date = TimeCurrent();
    PrintFormat("[DextradeEA] starting_balance=$%.2f account=%I64d",
                g_starting_balance, AccountInfoInteger(ACCOUNT_LOGIN));

    if(!SymbolSelect(_Symbol, true))
    {
        Print("[DextradeEA] FAIL: symbol ", _Symbol, " not selectable");
        return INIT_FAILED;
    }

    EventSetTimer(PollIntervalSec);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
    EventKillTimer();
    PrintFormat("[DextradeEA] shutdown reason=%d", reason);
}

// ============================================================================
// TICK LOOP — manage open positions (BEP + trailing every tick)
// ============================================================================
void OnTick()
{
    if(g_config.enable_break_even || g_config.enable_trailing)
    {
        ManageOpenPositions();
    }
}

// ============================================================================
// TIMER LOOP — poll API for new signals + refresh config
// ============================================================================
void OnTimer()
{
    // Refresh config from API periodically (no EA restart needed)
    if(TimeCurrent() - g_last_config_poll > g_config_poll_interval)
    {
        PollConfig();
        g_last_config_poll = TimeCurrent();
    }

    // Daily reset
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

    // Kill switch (daily loss)
    if(g_kill_switch_active) return;
    double daily_pnl_pct = ((AccountInfoDouble(ACCOUNT_BALANCE) - g_starting_balance) / g_starting_balance) * 100.0;
    if(daily_pnl_pct <= -g_config.daily_loss_pct)
    {
        PrintFormat("[DextradeEA] DAILY LOSS LIMIT (%.1f%%) — KILL SWITCH ACTIVE", daily_pnl_pct);
        g_kill_switch_active = true;
        SendHeartbeat(true);
        return;
    }

    // Heartbeat every 60s
    if(TimeCurrent() - g_last_heartbeat > 60)
    {
        SendHeartbeat(false);
        g_last_heartbeat = TimeCurrent();
    }

    // Mirror broker spot every 5s — daemon uses this as Tier 0 spot source
    // (most accurate, zero gap from broker quote).
    if(TimeCurrent() - g_last_spot_post >= 5)
    {
        PostSpot();
        g_last_spot_post = TimeCurrent();
    }

    // Daily trade cap check
    if(g_config.trades_remaining <= 0)
    {
        // Already hit cap, skip poll
        return;
    }

    // Max open positions check
    if(CountOurPositions() >= g_config.max_open_positions)
    {
        return;
    }

    // Poll for next signal
    string body = HttpGet(ApiBaseUrl + "/api/ea/next-signal?ea=" + EaInstanceId);
    if(StringLen(body) < 5) return;
    if(StringFind(body, "\"signal\":null") >= 0) return;

    // Parse signal
    long   signal_id     = (long)JsonGetNumber(body, "id");
    string direction     = JsonGetString(body, "direction");
    double entry         = JsonGetNumber(body, "entry");
    double sl            = JsonGetNumber(body, "sl");
    double tp1           = JsonGetNumber(body, "tp1");
    double tp2           = JsonGetNumber(body, "tp2");
    int    confidence    = (int)JsonGetNumber(body, "confidence_pct");

    if(signal_id <= 0)
    {
        Print("[DextradeEA] failed to parse signal_id");
        return;
    }

    PrintFormat("[DextradeEA] signal #%I64d %s @%.2f SL=%.2f TP1=%.2f conf=%d%% (today %d/%d)",
                signal_id, direction, entry, sl, tp1, confidence,
                g_config.trades_today, g_config.max_trades_per_day);

    if(confidence < g_config.min_confidence_pct)
    {
        PrintFormat("[DextradeEA] skip — conf %d%% < min %d%%", confidence, g_config.min_confidence_pct);
        ReportRejected(signal_id, "confidence_below_threshold");
        return;
    }

    if(direction != "LONG" && direction != "SHORT")
    {
        ReportRejected(signal_id, "non_directional");
        return;
    }

    if(entry <= 0 || sl <= 0)
    {
        ReportRejected(signal_id, "invalid_levels");
        return;
    }

    double lot = ComputeLotSize(entry, sl);
    if(lot <= 0)
    {
        ReportRejected(signal_id, "invalid_lot_size");
        return;
    }

    // Paper mode
    if(g_config.enable_paper || !g_config.enable_execution)
    {
        PrintFormat("[DextradeEA] PAPER %s %.2f @%.2f SL=%.2f TP1=%.2f (signal=%I64d)",
                    direction, lot, entry, sl, tp1, signal_id);
        ReportPaperExecuted(signal_id, direction, lot, entry, sl, tp1);
        return;
    }

    // LIVE
    bool ok = false;
    double price_now = direction == "LONG" ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                           : SymbolInfoDouble(_Symbol, SYMBOL_BID);

    if(direction == "LONG")
        ok = trade.Buy(lot, _Symbol, 0, sl, tp1, StringFormat("yeehee #%I64d", signal_id));
    else
        ok = trade.Sell(lot, _Symbol, 0, sl, tp1, StringFormat("yeehee #%I64d", signal_id));

    if(!ok)
    {
        uint err = trade.ResultRetcode();
        string desc = trade.ResultRetcodeDescription();
        PrintFormat("[DextradeEA] OrderSend FAILED ret=%u (%s)", err, desc);
        ReportRejected(signal_id, StringFormat("broker_ret_%u", err));
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
// POSITION MANAGEMENT — break-even + trailing stop (called every tick)
// ============================================================================
void ManageOpenPositions()
{
    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    if(point <= 0) return;

    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetInteger(POSITION_MAGIC) != (long)MagicNumber) continue;

        long   type        = PositionGetInteger(POSITION_TYPE);   // 0=BUY, 1=SELL
        double entry       = PositionGetDouble(POSITION_PRICE_OPEN);
        double current_sl  = PositionGetDouble(POSITION_SL);
        double current_tp  = PositionGetDouble(POSITION_TP);
        double price_now   = (type == POSITION_TYPE_BUY)
                             ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                             : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

        double profit_pips = (type == POSITION_TYPE_BUY)
                             ? (price_now - entry) / point
                             : (entry - price_now) / point;
        if(profit_pips <= 0) continue;  // no profit yet, no management

        double new_sl = current_sl;

        // 1. Break-even — move SL to entry + lock_pips when profit >= trigger
        if(g_config.enable_break_even && profit_pips >= g_config.break_even_trigger_pips)
        {
            double bep_sl = (type == POSITION_TYPE_BUY)
                            ? entry + g_config.break_even_lock_pips * point
                            : entry - g_config.break_even_lock_pips * point;
            // Only move SL forward (never backward — never increase risk)
            if(type == POSITION_TYPE_BUY  && bep_sl > current_sl) new_sl = bep_sl;
            if(type == POSITION_TYPE_SELL && (current_sl == 0 || bep_sl < current_sl)) new_sl = bep_sl;
        }

        // 2. Trailing stop — follow price by trailing_distance once trigger hit
        if(g_config.enable_trailing && profit_pips >= g_config.trailing_trigger_pips)
        {
            double trail_sl = (type == POSITION_TYPE_BUY)
                              ? price_now - g_config.trailing_distance_pips * point
                              : price_now + g_config.trailing_distance_pips * point;
            if(type == POSITION_TYPE_BUY  && trail_sl > new_sl) new_sl = trail_sl;
            if(type == POSITION_TYPE_SELL && (new_sl == 0 || trail_sl < new_sl)) new_sl = trail_sl;
        }

        // Apply if changed
        if(new_sl != current_sl && new_sl > 0)
        {
            int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
            new_sl = NormalizeDouble(new_sl, digits);
            if(trade.PositionModify(ticket, new_sl, current_tp))
            {
                PrintFormat("[DextradeEA] SL moved ticket=%I64u %.2f -> %.2f (profit=%.0fpips)",
                            ticket, current_sl, new_sl, profit_pips);
            }
        }
    }
}

// ============================================================================
// CONFIG POLLING
// ============================================================================
void PollConfig()
{
    string body = HttpGet(ApiBaseUrl + "/api/ea/config?ea=" + EaInstanceId);
    if(StringLen(body) < 10) return;

    g_config.enable_execution        = JsonGetBool(body, "enable_execution");
    g_config.enable_paper            = JsonGetBool(body, "enable_paper");
    g_config.max_open_positions      = (int)JsonGetNumber(body, "max_open_positions");
    g_config.max_trades_per_day      = (int)JsonGetNumber(body, "max_trades_per_day");
    g_config.trades_today            = (int)JsonGetNumber(body, "trades_today");
    g_config.trades_remaining        = (int)JsonGetNumber(body, "trades_remaining");
    g_config.daily_loss_pct          = JsonGetNumber(body, "daily_loss_pct");
    g_config.min_confidence_pct      = (int)JsonGetNumber(body, "min_confidence_pct");
    g_config.risk_per_trade_pct      = JsonGetNumber(body, "risk_per_trade_pct");
    g_config.enable_break_even       = JsonGetBool(body, "enable_break_even");
    g_config.break_even_trigger_pips = (int)JsonGetNumber(body, "break_even_trigger_pips");
    g_config.break_even_lock_pips    = (int)JsonGetNumber(body, "break_even_lock_pips");
    g_config.enable_trailing         = JsonGetBool(body, "enable_trailing");
    g_config.trailing_trigger_pips   = (int)JsonGetNumber(body, "trailing_trigger_pips");
    g_config.trailing_distance_pips  = (int)JsonGetNumber(body, "trailing_distance_pips");
}

// ============================================================================
// HELPERS
// ============================================================================

double ComputeLotSize(double entry, double sl)
{
    if(sl <= 0 || entry <= 0) return 0;
    double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk_amount = balance * (g_config.risk_per_trade_pct / 100.0);
    double sl_distance = MathAbs(entry - sl);
    if(sl_distance <= 0) return 0;

    double tick_value  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tick_size <= 0) return 0;
    double pip_value   = tick_value / tick_size;
    double lot_raw     = risk_amount / (sl_distance * pip_value);

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
            if(PositionGetInteger(POSITION_MAGIC) == (long)MagicNumber) count++;
    }
    return count;
}

string HttpGet(string url)
{
    char post[]; char result[]; string headers = ""; string result_headers;
    int res = WebRequest("GET", url, headers, 5000, post, result, result_headers);
    if(res == -1)
    {
        if(GetLastError() == 4014)
            PrintFormat("[DextradeEA] WebRequest blocked: add %s in Tools->Options->Expert Advisors", ApiBaseUrl);
        return "";
    }
    return CharArrayToString(result);
}

bool HttpPost(string url, string body)
{
    char post[]; StringToCharArray(body, post, 0, StringLen(body));
    char result[]; string headers = "Content-Type: application/json\r\n"; string result_headers;
    int res = WebRequest("POST", url, headers, 5000, post, result, result_headers);
    return res != -1;
}

void SendHeartbeat(bool is_paused)
{
    // v0.2.1 (2026-05-07): added account_leverage so /portfolio panel shows
    // dynamic leverage matching Exness setting (e.g. 1:500, 1:1000, 1:Unlimited)
    // instead of hardcoded "1:Unlimited" label. Backend graceful fallback if
    // migration 012 not yet applied -- field dropped, payload still accepted.
    long leverage = AccountInfoInteger(ACCOUNT_LEVERAGE);
    string body = StringFormat(
        "{\"ea_instance_id\":\"%s\",\"account_login\":%I64d,\"account_balance\":%.2f,\"account_equity\":%.2f,\"open_positions\":%d,\"is_paused\":%s,\"account_leverage\":%I64d}",
        EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN),
        AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
        CountOurPositions(), is_paused ? "true" : "false",
        leverage
    );
    HttpPost(ApiBaseUrl + "/api/ea/heartbeat", body);
}

// Mirror broker bid/ask to daemon's spot endpoint. Daemon uses this as Tier 0
// spot source (broker-grade, zero gap, beats Twelve Data + Yahoo + adaptive).
void PostSpot()
{
    string sym = Symbol();
    double bid = SymbolInfoDouble(sym, SYMBOL_BID);
    double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
    if(bid <= 0 || ask <= 0) return;
    string body = StringFormat(
        "{\"bid\":%.3f,\"ask\":%.3f,\"symbol\":\"%s\",\"ea_id\":\"%s\"}",
        bid, ask, sym, EaInstanceId
    );
    HttpPost(ApiBaseUrl + "/api/spot/post", body);
}

void ReportPaperExecuted(long signal_id, string direction, double lot, double entry, double sl, double tp)
{
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_account_login\":%I64d,\"status\":\"OPEN\",\"execution_price\":%.2f,\"execution_lot\":%.2f,\"execution_sl\":%.2f,\"execution_tp\":%.2f,\"slippage_points\":0,\"account_balance_at_open\":%.2f,\"risk_pct_used\":%.2f,\"rejected_reason\":\"paper_mode\"}",
        signal_id, EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN),
        entry, lot, sl, tp,
        AccountInfoDouble(ACCOUNT_BALANCE), g_config.risk_per_trade_pct
    );
    HttpPost(ApiBaseUrl + "/api/ea/report", body);
}

void ReportLiveOpened(long signal_id, ulong ticket, double fill, double lot, double sl, double tp, int slip)
{
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_ticket_id\":%I64u,\"mt5_account_login\":%I64d,\"status\":\"OPEN\",\"execution_price\":%.2f,\"execution_lot\":%.2f,\"execution_sl\":%.2f,\"execution_tp\":%.2f,\"slippage_points\":%d,\"account_balance_at_open\":%.2f,\"risk_pct_used\":%.2f}",
        signal_id, EaInstanceId, ticket, AccountInfoInteger(ACCOUNT_LOGIN),
        fill, lot, sl, tp, slip,
        AccountInfoDouble(ACCOUNT_BALANCE), g_config.risk_per_trade_pct
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
// JSON parsers (regex-style — MQL5 has no JSON lib)
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
    string needle = "\"" + key + "\":";
    int pos = StringFind(json, needle);
    if(pos < 0) return 0;
    int start = pos + StringLen(needle);
    while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' || StringGetCharacter(json, start) == '\t')) start++;
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

bool JsonGetBool(string json, string key)
{
    string needle = "\"" + key + "\":";
    int pos = StringFind(json, needle);
    if(pos < 0) return false;
    int start = pos + StringLen(needle);
    while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' || StringGetCharacter(json, start) == '\t')) start++;
    return StringSubstr(json, start, 4) == "true";
}
//+------------------------------------------------------------------+
