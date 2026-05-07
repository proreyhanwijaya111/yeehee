//+------------------------------------------------------------------+
//|                                                  DextradeEA.mq5  |
//|                                       yeehee / dextrade — v0.2.2 |
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
#property version   "0.2.2"
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
// PollIntervalSec — OnTimer cadence. v0.3.0 audit found 30s was too coarse:
// spot post (5s threshold) and heartbeat (45s threshold) only fired when
// OnTimer ran. With 30s interval, spot effectively posted every 30s (not 5s)
// and heartbeat drifted to 60-180s gaps. 10s = balance: more reliable cadence
// with negligible CPU overhead (OnTimer logic is fast: HTTP polls only when
// thresholds met, not every fire).
input int     PollIntervalSec     = 10;
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
    // v0.3.0: defaults sized for XAUUSD with corrected pip = 10×_Point = 0.01.
    // Old defaults (50/5/100/30) were misinterpreted by EA using raw _Point
    // (0.001), making BEP fire at $0.05 profit and trail at $0.10 with $0.03
    // distance — killed every trade in <10s. New defaults assume pip = $0.01:
    g_config.enable_break_even       = true;
    g_config.break_even_trigger_pips = 200;     // 200 × $0.01 = +$2.00 profit triggers BEP
    g_config.break_even_lock_pips    = 50;      // lock SL +$0.50 above entry
    g_config.enable_trailing         = true;
    g_config.trailing_trigger_pips   = 500;     // trail starts at +$5.00 profit
    g_config.trailing_distance_pips  = 200;     // trail with $2.00 distance
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

// Track which tickets had SL modified after open. 0 = never modified (original SL),
// 1 = BEP-arm move only, 2 = trailing move (any subsequent SL movement). Used by
// OnTradeTransaction to label close_reason granularly: sl_hit / bep_hit / trailing_sl_hit.
ulong   g_sl_modified_keys[];
int     g_sl_modified_vals[];

void SetSlModifiedFlag(ulong ticket, int flag)
{
    int n = ArraySize(g_sl_modified_keys);
    for(int i = 0; i < n; i++)
    {
        if(g_sl_modified_keys[i] == ticket)
        {
            // Promote BEP -> TRAIL if multiple moves happen, never demote.
            if(flag > g_sl_modified_vals[i]) g_sl_modified_vals[i] = flag;
            return;
        }
    }
    ArrayResize(g_sl_modified_keys, n + 1);
    ArrayResize(g_sl_modified_vals, n + 1);
    g_sl_modified_keys[n] = ticket;
    g_sl_modified_vals[n] = flag;
}

int GetSlModifiedFlag(ulong ticket)
{
    int n = ArraySize(g_sl_modified_keys);
    for(int i = 0; i < n; i++)
        if(g_sl_modified_keys[i] == ticket) return g_sl_modified_vals[i];
    return 0;  // never modified
}

// ============================================================================
// INITIALIZATION
// ============================================================================
int OnInit()
{
    Print("[DextradeEA] v0.3.0 init (pip-aware sizing, BEP/trail granular close_reason, realized risk_pct)");
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
// TRADE EVENT HANDLER — close-report (v0.2.2 2026-05-07)
// Without this, broker-side closes (TP/SL/trailing/manual) leave rcs_executions
// rows stuck OPEN forever -> portfolio UI shows phantom positions until manual
// reconciliation. OnTradeTransaction fires per low-level transaction; we filter
// for DEAL_ENTRY_OUT (position close) on our magic number.
// ============================================================================
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
    // Only react to DEAL_ADD transactions (i.e. a deal hit history)
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    if(trans.deal == 0) return;
    if(!HistoryDealSelect(trans.deal)) return;

    // Filter: our magic + DEAL_ENTRY_OUT (position close, not open)
    long deal_magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
    if(deal_magic != (long)MagicNumber) return;
    long entry_type = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
    // DEAL_ENTRY_OUT (1) = closing deal. DEAL_ENTRY_IN (0) = opening (skip — already reported).
    // DEAL_ENTRY_INOUT (2) = reversal (treat as close for previous side).
    if(entry_type != DEAL_ENTRY_OUT && entry_type != DEAL_ENTRY_INOUT) return;

    // Extract close info from history
    ulong  pos_id     = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
    double close_p    = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
    double profit     = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
    double commission = HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
    double swap       = HistoryDealGetDouble(trans.deal, DEAL_SWAP);
    long   reason     = HistoryDealGetInteger(trans.deal, DEAL_REASON);

    // Map MT5 DEAL_REASON_* -> our schema status string. SL hits promoted to
    // bep_hit / trailing_sl_hit when SL was modified post-open (tracked in
    // g_sl_modified_*). DEAL_REASON_SL alone is ambiguous — broker fires SL
    // event regardless of whether SL was original or moved.
    int sl_flag = GetSlModifiedFlag(pos_id);  // 0=never moved, 1=BEP, 2=trail
    string status, close_reason_str;
    switch((int)reason)
    {
        case DEAL_REASON_TP:        status = "CLOSED_TP";       close_reason_str = "tp_hit"; break;
        case DEAL_REASON_SL:
            if(sl_flag == 2)      { status = "CLOSED_TRAILING"; close_reason_str = "trailing_sl_hit"; }
            else if(sl_flag == 1) { status = "CLOSED_TRAILING"; close_reason_str = "bep_hit"; }
            else                  { status = "CLOSED_SL";       close_reason_str = "sl_hit"; }
            break;
        case DEAL_REASON_SO:        status = "CLOSED_SL";       close_reason_str = "stop_out"; break;
        case DEAL_REASON_CLIENT:    status = "CLOSED_MANUAL";   close_reason_str = "manual_client"; break;
        case DEAL_REASON_MOBILE:    status = "CLOSED_MANUAL";   close_reason_str = "manual_mobile"; break;
        case DEAL_REASON_WEB:       status = "CLOSED_MANUAL";   close_reason_str = "manual_web"; break;
        case DEAL_REASON_EXPERT:
            // EA closed via PositionClose (rare); inherit SL-flag semantics if any.
            if(sl_flag == 2)      { status = "CLOSED_TRAILING"; close_reason_str = "trailing_sl_hit"; }
            else if(sl_flag == 1) { status = "CLOSED_TRAILING"; close_reason_str = "bep_hit"; }
            else                  { status = "CLOSED_TRAILING"; close_reason_str = "expert_close"; }
            break;
        default:                    status = "CLOSED_MANUAL";   close_reason_str = StringFormat("reason_%d", (int)reason); break;
    }

    PrintFormat("[DextradeEA] CLOSE detected ticket=%I64u close=%.2f profit=$%.2f reason=%s",
                pos_id, close_p, profit + commission + swap, close_reason_str);
    ReportClosed(pos_id, status, close_p, profit + commission + swap, close_reason_str);
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

    // Heartbeat — only debounce g_last_heartbeat on HTTP success. If POST
    // fails (network blip, FastAPI restart), next OnTimer retries. Previous
    // version updated debounce regardless of result, causing silent drops
    // when heartbeats kept failing (saw 350-549s gaps with 5/100 ratio).
    if(TimeCurrent() - g_last_heartbeat >= 45)
    {
        if(SendHeartbeat(false))
            g_last_heartbeat = TimeCurrent();
        // else: leave g_last_heartbeat stale — next OnTimer retries immediately
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
    // v0.3.0: slippage = |fill - signal_entry| (was |fill - price_now| which
    // always returned ~0 because price_now was just-fetched microseconds ago).
    // Real slippage observed in prod: trade #2309 fill 4749.81 vs entry 4742.25
    // = $7.56 slippage but reported "slip=0". Now reflects truth so
    // /portfolio can flag high-slip trades.
    int    slippage  = (int)MathRound(MathAbs(fill - entry) / SymbolInfoDouble(_Symbol, SYMBOL_POINT));

    PrintFormat("[DextradeEA] LIVE OPEN ticket=%I64u fill=%.2f signal_entry=%.2f slip=%dpts signal=%I64d",
                ticket, fill, entry, slippage, signal_id);
    ReportLiveOpened(signal_id, ticket, fill, lot, sl, tp1, slippage);
}

// ============================================================================
// POSITION MANAGEMENT — break-even + trailing stop (called every tick)
// ============================================================================
void ManageOpenPositions()
{
    // v0.3.0 (2026-05-07): pip-aware sizing + min-tick-distance guard. _Point
    // alone caused trail to trigger on micro-cents on 5-digit XAUUSDm. Now uses
    // standard MQL5 pip = 10*Point on fractional brokers.
    double pip_size = GetPipSize();
    if(pip_size <= 0) return;
    int    digits   = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    int    stops_level = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
    double min_dist = stops_level * SymbolInfoDouble(_Symbol, SYMBOL_POINT);

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
                             ? (price_now - entry) / pip_size
                             : (entry - price_now) / pip_size;
        if(profit_pips <= 0) continue;  // no profit yet, no management

        double new_sl = current_sl;
        bool   bep_armed = false;

        // 1. Break-even — move SL to entry + lock_pips when profit >= trigger
        if(g_config.enable_break_even && profit_pips >= g_config.break_even_trigger_pips)
        {
            double bep_sl = (type == POSITION_TYPE_BUY)
                            ? entry + g_config.break_even_lock_pips * pip_size
                            : entry - g_config.break_even_lock_pips * pip_size;
            // Only move SL forward (never backward — never increase risk)
            if(type == POSITION_TYPE_BUY  && bep_sl > current_sl) { new_sl = bep_sl; bep_armed = true; }
            if(type == POSITION_TYPE_SELL && (current_sl == 0 || bep_sl < current_sl)) { new_sl = bep_sl; bep_armed = true; }
        }

        // 2. Trailing stop — follow price by trailing_distance once trigger hit
        if(g_config.enable_trailing && profit_pips >= g_config.trailing_trigger_pips)
        {
            double trail_sl = (type == POSITION_TYPE_BUY)
                              ? price_now - g_config.trailing_distance_pips * pip_size
                              : price_now + g_config.trailing_distance_pips * pip_size;
            if(type == POSITION_TYPE_BUY  && trail_sl > new_sl) new_sl = trail_sl;
            if(type == POSITION_TYPE_SELL && (new_sl == 0 || trail_sl < new_sl)) new_sl = trail_sl;
        }

        // Min stops-level guard — broker rejects modify if SL too close to current price.
        if(min_dist > 0 && new_sl != current_sl)
        {
            if(type == POSITION_TYPE_BUY  && (price_now - new_sl) < min_dist) continue;
            if(type == POSITION_TYPE_SELL && (new_sl - price_now) < min_dist) continue;
        }

        // De-bouncing: don't fire SL modify unless meaningfully different from current
        // (prevents 7-modifies-in-8-sec storm seen in prod logs trade #2312).
        double sl_change_pips = MathAbs(new_sl - current_sl) / pip_size;
        if(sl_change_pips < 1.0) continue;  // < 1 pip change, not worth a modify

        // Apply if changed
        if(new_sl != current_sl && new_sl > 0)
        {
            new_sl = NormalizeDouble(new_sl, digits);
            if(trade.PositionModify(ticket, new_sl, current_tp))
            {
                PrintFormat("[DextradeEA] SL moved ticket=%I64u %.2f -> %.2f (profit=%.0fpips %s)",
                            ticket, current_sl, new_sl, profit_pips,
                            bep_armed ? "BEP" : "TRAIL");
                SetSlModifiedFlag(ticket, bep_armed ? 1 : 2);
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

// Standard MQL5 pip definition: 1 pip = 10 × _Point on 5-digit/3-digit brokers,
// = 1 × _Point on 4-digit/2-digit. For XAUUSDm Exness (5-digit, point=0.001),
// 1 pip = 0.01 USD. Critical for trail/BEP config to be human-meaningful.
double GetPipSize()
{
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    return (digits == 3 || digits == 5) ? 10.0 * point : point;
}

// Compute pip_value: $ PnL per 1 pip per 1.0 lot.
double GetPipValue()
{
    double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    double pip_size   = GetPipSize();
    if(tick_size <= 0) return 0;
    return (tick_value / tick_size) * pip_size;
}

double ComputeLotSize(double entry, double sl)
{
    if(sl <= 0 || entry <= 0) return 0;
    double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk_amount = balance * (g_config.risk_per_trade_pct / 100.0);
    double sl_distance = MathAbs(entry - sl);
    if(sl_distance <= 0) return 0;

    double pip_size    = GetPipSize();
    if(pip_size <= 0) return 0;
    double sl_pips     = sl_distance / pip_size;             // SL distance in pips
    double pip_value   = GetPipValue();                       // $ per pip per 1 lot
    if(pip_value <= 0) return 0;
    double lot_raw     = risk_amount / (sl_pips * pip_value); // lots needed

    double lot_step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    double lot_min     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double lot_max     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    if(lot_step <= 0) lot_step = 0.01;
    // Round to nearest step (was floor — caused 0.0076 -> 0 fallback to 0.01,
    // overshooting target risk silently). Now: round nearest, but if rounded
    // result would exceed target risk by >50%, reject to caller (return 0).
    double lot_rounded = MathRound(lot_raw / lot_step) * lot_step;
    if(lot_rounded < lot_min) lot_rounded = lot_min;
    if(lot_rounded > lot_max) lot_rounded = lot_max;
    // Hard guard: reject if min lot already overshoots target by 1.5x.
    // Caller will mark signal as 'risk_too_small_for_min_lot' rejection.
    double min_lot_risk = lot_min * sl_pips * pip_value;
    if(lot_rounded == lot_min && min_lot_risk > risk_amount * 1.5)
        return 0;
    return lot_rounded;
}

// Realized risk_pct given filled lot — for accurate reporting back to backend.
double ComputeRealizedRiskPct(double entry, double sl, double lot)
{
    if(lot <= 0 || sl <= 0 || entry <= 0) return 0;
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    if(balance <= 0) return 0;
    double pip_size = GetPipSize();
    double pip_value = GetPipValue();
    if(pip_size <= 0 || pip_value <= 0) return 0;
    double sl_pips = MathAbs(entry - sl) / pip_size;
    double risk_dollar = lot * sl_pips * pip_value;
    return (risk_dollar / balance) * 100.0;
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

// HttpPost with retry: critical for close-report which previously failed
// silently → orphan rcs_executions OPEN row → manual reconciliation needed.
// 3 attempts, exponential backoff (0.5s, 1.5s, 4.5s) = total ≤6.5s wall-clock.
bool HttpPostWithRetry(string url, string body, int max_attempts = 3)
{
    int delay_ms = 500;
    for(int attempt = 1; attempt <= max_attempts; attempt++)
    {
        if(HttpPost(url, body)) return true;
        if(attempt < max_attempts)
        {
            PrintFormat("[DextradeEA] HttpPost retry %d/%d after %dms (last err=%d)",
                        attempt, max_attempts, delay_ms, GetLastError());
            Sleep(delay_ms);
            delay_ms *= 3;
        }
    }
    PrintFormat("[DextradeEA] HttpPost FAILED %d attempts: %s", max_attempts, url);
    return false;
}

// Returns true on success. Caller uses this to gate g_last_heartbeat update —
// only debounce on confirmed success, otherwise next OnTimer retries.
bool SendHeartbeat(bool is_paused)
{
    long leverage = AccountInfoInteger(ACCOUNT_LEVERAGE);
    string body = StringFormat(
        "{\"ea_instance_id\":\"%s\",\"account_login\":%I64d,\"account_balance\":%.2f,\"account_equity\":%.2f,\"open_positions\":%d,\"is_paused\":%s,\"account_leverage\":%I64d}",
        EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN),
        AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
        CountOurPositions(), is_paused ? "true" : "false",
        leverage
    );
    return HttpPost(ApiBaseUrl + "/api/ea/heartbeat", body);
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
    // v0.3.0: report ACTUAL realized risk_pct based on filled lot + actual SL
    // distance from fill price (not config target). Captures the lot-rounding
    // overshoot when min lot > target risk_pct.
    double realized_risk = ComputeRealizedRiskPct(fill, sl, lot);
    string body = StringFormat(
        "{\"signal_id\":%I64d,\"ea_instance_id\":\"%s\",\"mt5_ticket_id\":%I64u,\"mt5_account_login\":%I64d,\"status\":\"OPEN\",\"execution_price\":%.2f,\"execution_lot\":%.2f,\"execution_sl\":%.2f,\"execution_tp\":%.2f,\"slippage_points\":%d,\"account_balance_at_open\":%.2f,\"risk_pct_used\":%.2f}",
        signal_id, EaInstanceId, ticket, AccountInfoInteger(ACCOUNT_LOGIN),
        fill, lot, sl, tp, slip,
        AccountInfoDouble(ACCOUNT_BALANCE), realized_risk
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

// v0.2.2 2026-05-07: report close-by-ticket. Server (execution_api.py) looks
// up signal_id from rcs_executions WHERE mt5_ticket_id = ticket and updates
// the existing OPEN row. Eliminates stuck-OPEN orphans.
void ReportClosed(ulong ticket, string status, double close_price, double pnl_money, string close_reason)
{
    string body = StringFormat(
        "{\"mt5_ticket_id\":%I64u,\"ea_instance_id\":\"%s\",\"mt5_account_login\":%I64d,\"status\":\"%s\",\"execution_lot\":0,\"close_price\":%.2f,\"pnl_money\":%.4f,\"close_reason\":\"%s\",\"closed_at\":\"%s\"}",
        ticket, EaInstanceId, AccountInfoInteger(ACCOUNT_LOGIN),
        status, close_price, pnl_money, close_reason,
        TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)
    );
    // 3-attempt retry — close-report is the most critical post. Silent fail
    // here = orphan OPEN row in rcs_executions = phantom UI position until
    // manual SQL reconciliation. Retry mitigates transient network/server blips.
    HttpPostWithRetry(ApiBaseUrl + "/api/ea/report", body);
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
