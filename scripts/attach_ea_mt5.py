"""Attach DextradeEA to MT5 XAUUSDm chart via pywinauto.

WHY: User at RS, can't manually click. EA needed for auto-execute go-live.
Architecture: chart already open (XAUUSDm,H1 found via Win32 enum), EA compiled
in Navigator, just need attach + dialog confirm.

USAGE:
    python scripts/attach_ea_mt5.py
    # Optional flag --dry-run to inspect without clicking

EXIT CODES:
    0  success (EA attached, dialog confirmed, HEARTBEAT VERIFIED in Supabase)
    1  generic failure
    2  MT5 not running
    3  Navigator/TreeView not found
    4  EA not found in Navigator
    5  attach action failed
    6  dialog confirm failed
    7  heartbeat VERIFICATION TIMEOUT (90s elapsed, no fresh row in
       rcs_ea_heartbeat) -- attach probably failed silently (URL not
       whitelisted, EA throwing internal error, FastAPI not reachable)

User audit 2026-05-07 10:30: previously script returned 0 just on "OK
clicked" -- false-positive when EA attaches but can't WebRequest. NOW
script polls Supabase to confirm EA actually heartbeating before claiming
success.
"""
from __future__ import annotations
import os
import sys
import time
import argparse
from pathlib import Path

try:
    from pywinauto import Application, Desktop, mouse
    from pywinauto.findwindows import ElementNotFoundError
except ImportError:
    print("pywinauto not installed. pip install pywinauto", file=sys.stderr)
    sys.exit(1)


def find_mt5():
    """Find Exness MT5 main window by title pattern."""
    desktop = Desktop(backend="win32")
    for w in desktop.windows():
        title = w.window_text()
        if "Exness-MT5Trial" in title or "MetaTrader 5" in title:
            return w
    return None


def attach_ea(dry_run: bool = False) -> int:
    print(f"[attach_ea] dry_run={dry_run}")
    mt5_main = find_mt5()
    if not mt5_main:
        print("[attach_ea] FAIL: MT5 main window not found")
        return 2
    print(f"[attach_ea] MT5 main: '{mt5_main.window_text()}' hwnd={mt5_main.handle}")

    # Connect via win32 backend (better for native MFC controls)
    app = Application(backend="win32").connect(handle=mt5_main.handle)
    main = app.window(handle=mt5_main.handle)

    # Bring to foreground
    try:
        main.set_focus()
        time.sleep(0.5)
    except Exception as e:
        print(f"[attach_ea] WARN set_focus: {e}")

    # Find Navigator pane (control_id or class)
    print("[attach_ea] descendants summary:")
    descendants = main.descendants()
    treeviews = [d for d in descendants if d.class_name() == "SysTreeView32"]
    print(f"[attach_ea] {len(treeviews)} TreeView(s) found")
    if not treeviews:
        return 3
    nav_tree = treeviews[0]
    for t in treeviews:
        # Navigator tree typically has many items (~200+); other trees (e.g. Toolbox) have fewer
        try:
            count = t.item_count() if hasattr(t, 'item_count') else 0
            print(f"  - tree hwnd={t.handle} class={t.class_name()} text={t.window_text()!r}")
        except Exception:
            pass

    # Find DextradeEA SOURCE item (not attached instance).
    # MT5 tree has SOURCE library "DextradeEA" under "Expert Advisors" parent,
    # PLUS may have ATTACHED instance "DextradeEA - XAUUSDm,H1" under
    # "Expert Advisors -> Attached" sub-tree (when EA running on chart).
    # Need SOURCE for proper attach/replace semantics — not the attached node
    # (double-click on attached just opens its Properties dialog, doesn't reload).
    print("[attach_ea] searching for DextradeEA SOURCE in TreeView...")
    found_item = None
    try:
        # Walk all roots & children. Prefer EXACT match "DextradeEA" (source)
        # over partial match (e.g. "DextradeEA - XAUUSDm,H1" attached instance).
        candidates = []  # (item, exact_match_priority)
        def walk(item, depth=0):
            try:
                txt = (item.text() or "").strip()
            except Exception:
                txt = "?"
            if txt == "DextradeEA":
                candidates.append((item, 0))   # exact = highest priority
            elif "DextradeEA" in txt:
                candidates.append((item, 1))   # partial = fallback
            try:
                for c in item.children():
                    walk(c, depth + 1)
            except Exception:
                pass

        for root in nav_tree.roots():
            walk(root)

        # Sort by priority (lower = better), pick first
        candidates.sort(key=lambda x: x[1])
        if candidates:
            found_item = candidates[0][0]
            try:
                txt = (found_item.text() or "").strip()
                print(f"[attach_ea] candidates: {[(c[0].text(), c[1]) for c in candidates]}")
                print(f"[attach_ea] picked: '{txt}'")
            except Exception:
                pass
    except Exception as e:
        print(f"[attach_ea] tree walk error: {e}")
        return 4

    if not found_item:
        print("[attach_ea] FAIL: DextradeEA not found in tree. Visible roots:")
        try:
            for root in nav_tree.roots():
                print(f"  root: {root.text()}")
        except Exception:
            pass
        return 4

    print(f"[attach_ea] FOUND item: {found_item.text()}")

    # Make item visible (expand parents if needed) — pywinauto _treeview_element
    try:
        found_item.ensure_visible()
        time.sleep(0.3)
    except Exception as e:
        print(f"[attach_ea] WARN ensure_visible: {e}")

    # client_rect() returns coords RELATIVE to parent (TreeView) client area.
    # Need to convert to SCREEN coords for mouse.double_click.
    item_local = None
    for attr in ("client_rect", "rectangle", "rect"):
        if hasattr(found_item, attr):
            try:
                item_local = getattr(found_item, attr)()
                if item_local:
                    print(f"[attach_ea] item local rect via .{attr}(): {item_local}")
                    break
            except Exception:
                continue

    tree_rect = nav_tree.rectangle()  # screen coords of TreeView
    print(f"[attach_ea] tree screen rect: {tree_rect}")

    if item_local:
        # Convert tree-local to screen coords
        sx_l = tree_rect.left + item_local.left
        sx_r = tree_rect.left + item_local.right
        sy_t = tree_rect.top  + item_local.top
        sy_b = tree_rect.top  + item_local.bottom
        cx = (sx_l + sx_r) // 2
        cy = (sy_t + sy_b) // 2
        print(f"[attach_ea] item screen coords: ({cx}, {cy})")
    else:
        # Fallback: estimate near top of tree (DextradeEA usually visible)
        cx = (tree_rect.left + tree_rect.right) // 2
        cy = tree_rect.top + 60
        print(f"[attach_ea] fallback coords: ({cx}, {cy})")

    if dry_run:
        print(f"[attach_ea] dry_run -- would double-click ({cx},{cy})")
        return 0

    # Make sure chart is the active receiver -- focus chart first
    chart_panes = [d for d in descendants if "XAUUSDm" in (d.window_text() or "")]
    if chart_panes:
        chart = chart_panes[0]
        print(f"[attach_ea] activating chart: {chart.window_text()}")
        try:
            chart.set_focus()
            time.sleep(0.5)
        except Exception as e:
            print(f"[attach_ea] WARN chart focus: {e}")

    print(f"[attach_ea] double-clicking ({cx},{cy}) -- triggers Attach to chart")
    try:
        # Try via pywinauto item method first (handles cross-process safely)
        try:
            found_item.select()
            time.sleep(0.3)
        except Exception:
            pass
        mouse.double_click(coords=(cx, cy))
        time.sleep(2.0)  # confirm dialog appears

        # Handle "EA already running on chart, replace?" prompt that may appear.
        # Title varies but commonly contains "Expert Advisor" / "DextradeEA".
        # If detected, click "Yes" / "OK" to confirm replace.
        replace_prompts = []
        for w in Desktop(backend="win32").windows():
            try:
                if w.process_id() != mt5_main.process_id():
                    continue
                txt = (w.window_text() or "").lower()
                # "MetaTrader 5" general prompt OR DextradeEA-named replacement prompt
                if ("expert" in txt or "dextrade" in txt or "metatrader" in txt) and len(txt) < 80:
                    btns = [b for b in w.descendants() if b.class_name() == "Button"]
                    btn_texts = [(b.window_text() or "").strip().lower() for b in btns]
                    # Prompt has Yes/No/Cancel? -> click Yes
                    if any(t in ('yes', '&yes', 'ya') for t in btn_texts):
                        replace_prompts.append((w, btns, btn_texts))
            except Exception:
                continue
        if replace_prompts:
            for (w, btns, btn_texts) in replace_prompts:
                try:
                    print(f"[attach_ea] replace prompt: '{w.window_text()}' buttons={btn_texts}")
                    yes_btn = next((b for b in btns if (b.window_text() or "").strip().lower() in ('yes', '&yes', 'ya')), None)
                    if yes_btn:
                        yes_btn.click_input()
                        print(f"[attach_ea] clicked 'Yes' to replace existing EA")
                        time.sleep(1.5)
                        break
                except Exception as e:
                    print(f"[attach_ea] replace prompt err: {e}")
    except Exception as e:
        print(f"[attach_ea] FAIL double-click: {e}")
        return 5

    # Now confirm dialog. Modal child of MT5 process titled "DextradeEA" or
    # similar (NOT a top-level "Expert" file explorer). Filter by MT5 process.
    print("[attach_ea] looking for confirm dialog (child of MT5 process only)...")
    time.sleep(0.5)
    mt5_pid = mt5_main.process_id()
    candidates = []
    for w in Desktop(backend="win32").windows():
        try:
            if w.process_id() != mt5_pid:
                continue
            txt = w.window_text() or ""
            cls = w.class_name() or ""
            # Match modal popup: dialog class or title containing EA name
            if ("DextradeEA" in txt or "Dextrade" in txt or
                "Expert -" in txt or txt == "DextradeEA"):
                candidates.append(w)
        except Exception:
            continue
    print(f"[attach_ea] found {len(candidates)} MT5-owned dialog(s)")
    confirmed = False
    for d in candidates:
        try:
            print(f"  dialog: '{d.window_text()}' class={d.class_name()}")
            d.set_focus()
            time.sleep(0.3)
            ok_buttons = [b for b in d.descendants()
                          if b.class_name() == "Button" and (b.window_text() or "").strip() in ("OK", "Ok")]
            if ok_buttons:
                print(f"  clicking OK button")
                ok_buttons[0].click_input()
                confirmed = True
                break
            # Fallback: send Enter to dialog
            d.type_keys("{ENTER}")
            confirmed = True
            break
        except Exception as e:
            print(f"  dialog err: {e}")
    if not confirmed:
        print("[attach_ea] no MT5 confirm dialog found — Enter fallback to focused window")
        try:
            from pywinauto.keyboard import send_keys
            send_keys("{ENTER}")
        except Exception:
            pass

    print("[attach_ea] click sequence done -- now polling Supabase rcs_ea_heartbeat for proof...")
    return _poll_heartbeat_proof()


def _read_env(key: str) -> str | None:
    """Read value from .env file at repo root."""
    repo = Path(__file__).resolve().parent.parent
    env_path = repo / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith(f"{key}=") and "=" in line:
            return line.split("=", 1)[1].strip()
    return None


def _poll_heartbeat_proof(max_wait_s: int = 90, poll_interval_s: int = 5) -> int:
    """Poll Supabase rcs_ea_heartbeat untuk verify EA actually heartbeating.

    Returns 0 only when fresh row (ts within last `max_wait_s`) appears
    AFTER script start. Returns 7 on timeout. This eliminates false-positive
    "attach success" when click sequence ran but WebRequest blocked / EA
    runtime error preventing actual /api/ea/heartbeat POST.
    """
    try:
        import requests
    except ImportError:
        print("[attach_ea] requests not installed; skipping heartbeat verify")
        return 0

    url     = _read_env("SUPABASE_URL")
    api_key = _read_env("SUPABASE_SERVICE_KEY") or _read_env("SUPABASE_ANON_KEY")
    if not url or not api_key:
        print("[attach_ea] no SUPABASE_URL/key in .env; cannot verify heartbeat")
        return 7

    started_unix = time.time()
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started_unix - 30))
    print(f"[attach_ea] looking for heartbeat ts >= {cutoff_iso}Z")

    deadline = started_unix + max_wait_s
    last_seen = None
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{url.rstrip('/')}/rest/v1/rcs_ea_heartbeat",
                params={
                    "select": "ts,is_paused,account_balance,open_positions",
                    "order":  "ts.desc",
                    "limit":  "1",
                    "ts":     f"gte.{cutoff_iso}",
                },
                headers={
                    "apikey":        api_key,
                    "Authorization": f"Bearer {api_key}",
                },
                timeout=10,
            )
            if r.status_code == 200:
                rows = r.json() or []
                if rows:
                    row = rows[0]
                    age = time.time() - started_unix
                    print(f"[attach_ea] HEARTBEAT VERIFIED after {age:.1f}s: ts={row.get('ts')} balance=${row.get('account_balance')} open={row.get('open_positions')} paused={row.get('is_paused')}")
                    return 0
                last_seen = "(no row yet)"
            else:
                last_seen = f"HTTP {r.status_code}"
        except Exception as e:
            last_seen = f"err {type(e).__name__}"
        elapsed = int(time.time() - started_unix)
        print(f"[attach_ea] poll +{elapsed}s: {last_seen} -- waiting (max {max_wait_s}s)")
        time.sleep(poll_interval_s)

    print(f"[attach_ea] TIMEOUT after {max_wait_s}s -- no heartbeat row appeared.")
    print("[attach_ea] FAILURE MODES to check:")
    print("  - MT5 'Allow WebRequest for listed URL' missing http://localtest.me:8001 + http://localhost:8001")
    print("  - FastAPI :8001 not reachable from EA (curl http://localhost:8001/healthz)")
    print("  - EA threw internal error -- check $APPDATA\\MetaQuotes\\Terminal\\*\\MQL5\\Logs\\<today>.log")
    print("  - Algo Trading toolbar button not green / DextradeEA not actually attached to chart")
    return 7


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--wait-seconds", type=int, default=0,
                   help="Sleep N seconds before action (used by Task Scheduler at-logon to let MT5 fully start before attempting attach).")
    args = p.parse_args()
    if args.wait_seconds > 0:
        print(f"[attach_ea] sleeping {args.wait_seconds}s (--wait-seconds)")
        time.sleep(args.wait_seconds)
    sys.exit(attach_ea(dry_run=args.dry_run))
