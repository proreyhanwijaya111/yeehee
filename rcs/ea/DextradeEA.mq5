//+------------------------------------------------------------------+
//|                                                  DextradeEA.mq5  |
//|                                       yeehee / dextrade — v0.0.1 |
//|                                                                  |
//| RCS auto-executor — STUB, not functional yet.                    |
//|                                                                  |
//| Status: SCAFFOLD ONLY. Logic kerangka, no live execution.        |
//| Semua TODO marked dengan // TODO. Build berlanjut di Phase v1.0  |
//| setelah RCS v0.1 stable + paper-tested 30 hari.                  |
//|                                                                  |
//| Spec full: RCS_MULTI_TF_ML_SPEC.md Phase 10                      |
//+------------------------------------------------------------------+
#property copyright "yeehee / dextrade"
#property link      "https://yeehee.vercel.app"
#property version   "0.0.1"
#property strict

// ============================================================================
// USER INPUTS (visible in MT5 EA properties dialog)
// ============================================================================
input string  ApiBaseUrl       = "http://localhost:8001";  // Home PC FastAPI
input string  EaInstanceId     = "ea-mt5-pcrumah-1";
input double  RiskPercentPerTrade = 1.0;                  // % of account balance
input int     MinConfidencePct = 65;                      // Skip signals below this
input bool    EnableExecution  = false;                   // SAFETY: false by default
input bool    EnablePaperMode  = true;                    // Log only, no real orders
input int     PollIntervalSec  = 30;
input int     MaxOpenPositions = 1;                       // Hard cap on concurrent
input double  DailyLossPct     = 5.0;                     // Kill switch threshold

// ============================================================================
// GLOBAL STATE
// ============================================================================
datetime g_last_poll = 0;
double   g_starting_balance = 0;
bool     g_kill_switch_active = false;

// ============================================================================
// INITIALIZATION
// ============================================================================
int OnInit()
{
    Print("[DextradeEA] v0.0.1 starting up");
    Print("[DextradeEA] EnableExecution=", EnableExecution, " EnablePaperMode=", EnablePaperMode);

    if(EnableExecution && EnablePaperMode)
    {
        Print("[DextradeEA] CONFLICT: both EnableExecution and EnablePaperMode true. Paper takes precedence.");
    }

    g_starting_balance = AccountInfoDouble(ACCOUNT_BALANCE);
    Print("[DextradeEA] Starting balance: $", DoubleToString(g_starting_balance, 2));

    // TODO: register with home PC API as alive (POST /api/ea/register)
    // TODO: setup heartbeat timer

    EventSetTimer(PollIntervalSec);
    return INIT_SUCCEEDED;
}

// ============================================================================
// DEINITIALIZATION
// ============================================================================
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("[DextradeEA] shutdown reason=", reason);
    // TODO: notify home PC API (POST /api/ea/shutdown)
}

// ============================================================================
// TIMER LOOP — polling RCS signal endpoint
// ============================================================================
void OnTimer()
{
    // 1. Kill switch check (daily loss)
    if(g_kill_switch_active)
    {
        Print("[DextradeEA] kill switch active — skip poll");
        return;
    }

    double current_balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double daily_pnl_pct = ((current_balance - g_starting_balance) / g_starting_balance) * 100;
    if(daily_pnl_pct <= -DailyLossPct)
    {
        Print("[DextradeEA] DAILY LOSS LIMIT HIT (", daily_pnl_pct, "%) — activating kill switch");
        g_kill_switch_active = true;
        // TODO: close all open positions
        // TODO: notify Telegram
        return;
    }

    // 2. Fetch latest signal from home PC
    string signal_json = FetchPendingSignal();
    if(signal_json == "") return;

    // TODO: parse JSON properly (MQL5 has limited JSON support — use custom parser or string scan)
    // TODO: extract direction, entry, sl, tp1, tp2, confidence_pct, signal_id

    int confidence_pct = 0;  // TODO: parse from signal_json
    string direction   = ""; // TODO: parse
    double entry       = 0;  // TODO: parse
    double sl          = 0;  // TODO: parse
    double tp          = 0;  // TODO: parse (tp1)
    long   signal_id   = 0;  // TODO: parse

    if(confidence_pct < MinConfidencePct)
    {
        Print("[DextradeEA] skip signal_id=", signal_id, " conf=", confidence_pct, "% < ", MinConfidencePct, "%");
        return;
    }

    // 3. Validation: open positions cap
    int open_count = PositionsTotal();
    if(open_count >= MaxOpenPositions)
    {
        Print("[DextradeEA] skip — already ", open_count, " open positions (max=", MaxOpenPositions, ")");
        return;
    }

    // 4. Compute lot size from risk % + SL distance
    double lot = ComputeLotSize(entry, sl);
    if(lot <= 0)
    {
        Print("[DextradeEA] invalid lot size for entry=", entry, " sl=", sl);
        return;
    }

    // 5. Execute (or paper log)
    if(EnablePaperMode)
    {
        Print("[DextradeEA] PAPER ", direction, " ", lot, " @ ", entry, " SL=", sl, " TP=", tp, " (signal=", signal_id, ")");
        // TODO: POST execution result to /api/ea/report (status=EXECUTED, paper=true)
        return;
    }

    if(!EnableExecution)
    {
        Print("[DextradeEA] EnableExecution=false — skip live order. Set to true to go live.");
        return;
    }

    // TODO: build MqlTradeRequest, OrderSend, parse result
    // TODO: POST execution result to /api/ea/report (mt5_ticket_id, fill_price, slippage)
}

// ============================================================================
// HELPERS — all stubs
// ============================================================================

string FetchPendingSignal()
{
    // TODO: WebRequest GET ApiBaseUrl + "/api/ea/next-signal?ea=" + EaInstanceId
    // TODO: return body string atau "" kalau no signal
    return "";
}

double ComputeLotSize(double entry, double sl)
{
    // Risk-based sizing: lot = (balance * risk%) / (sl_distance * point_value)
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

// ============================================================================
// BUILD INSTRUCTIONS
// ============================================================================
//
// Saat siap dipakai (Phase v1.0):
//   1. Buka MT5 client → klik kanan "Expert Advisors" di Navigator → "New"
//   2. Pilih "Expert Advisor (template)" → next → save sebagai DextradeEA.mq5
//   3. Replace isinya dengan file ini
//   4. F7 untuk compile (cek tab Errors di bottom panel)
//   5. Saat hijau (no errors): drag DextradeEA dari Navigator ke chart XAU/USD
//   6. Allow WebRequest URL: Tools → Options → Expert Advisors → Allow URL "http://localhost:8001"
//   7. Inputs: SET EnableExecution=false + EnablePaperMode=true awalnya
//   8. Run paper mode 1-2 minggu di demo account, observe logs
//   9. Setelah confidence: switch EnablePaperMode=false + EnableExecution=true
//
// Pre-requisites yang harus ada di home PC:
//   - FastAPI service di port 8001 (build di rcs/src/execution_api.py — STUB belum ada)
//   - rcs_signals di Supabase punya beberapa rows dengan execution_status='PENDING_PICKUP'
//   - Daemon flip-eligible signals to PENDING_PICKUP based on confidence threshold
//
// LIVE TRADE WARNINGS:
//   - JANGAN run di account live sebelum 2-4 minggu paper test PASS
//   - JANGAN naikin RiskPercentPerTrade > 1% sebelum 100+ executed signals
//   - Always have manual kill switch + 24h profit/loss alert
//   - Telegram notif untuk every order open + close
//+------------------------------------------------------------------+
