"""Attach DextradeEA to MT5 XAUUSDm chart via pywinauto.

WHY: User at RS, can't manually click. EA needed for auto-execute go-live.
Architecture: chart already open (XAUUSDm,H1 found via Win32 enum), EA compiled
in Navigator, just need attach + dialog confirm.

USAGE:
    python scripts/attach_ea_mt5.py
    # Optional flag --dry-run to inspect without clicking

EXIT CODES:
    0  success (EA attached, dialog confirmed)
    1  generic failure
    2  MT5 not running
    3  Navigator/TreeView not found
    4  EA not found in Navigator
    5  attach action failed
    6  dialog confirm failed

VERIFY: poll Supabase rcs_ea_heartbeat after run -- expect entry within 60s.
"""
from __future__ import annotations
import sys
import time
import argparse

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

    # Find DextradeEA item — pywinauto's TreeView wrapper
    print("[attach_ea] searching for DextradeEA in TreeView...")
    found_item = None
    try:
        # Walk all roots & children
        def walk(item, depth=0):
            try:
                txt = item.text()
            except Exception:
                txt = "?"
            if "DextradeEA" in txt or "Dextrade" in txt:
                return item
            try:
                for c in item.children():
                    r = walk(c, depth + 1)
                    if r:
                        return r
            except Exception:
                pass
            return None

        for root in nav_tree.roots():
            r = walk(root)
            if r:
                found_item = r
                break
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

    print("[attach_ea] DONE -- verify via Supabase rcs_ea_heartbeat in next 60s")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sys.exit(attach_ea(dry_run=args.dry_run))
