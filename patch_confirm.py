#!/usr/bin/env python3
"""Remember a clean impulse while the index is 1/3.
Enter only after the index confirms 2/3 and the move still holds."""
import os
import shutil
import py_compile

TARGET = "main.py"
BACKUP = "main.py.bak_confirm"

PLAIN = """        ok_idx, why_idx = index_entry_allowed(idx_now, side)
        if not ok_idx:
            logger.info(f"🚫 IMPULSE index {symbol} | {why_idx}")
            return
"""

LEAN = """        ok_idx, why_idx = index_entry_allowed(idx_now, side)
        if not ok_idx:
            direction = str((idx_now or {}).get("direction") or "NEUTRAL").upper()
            agree = int((idx_now or {}).get("agree") or 0)
            lean_ok = agree == 1 and (
                (side == "BUY" and direction == "BULL")
                or (side == "SELL" and direction == "BEAR")
            )
            if not lean_ok:
                logger.info(f"🚫 IMPULSE index {symbol} | {why_idx}")
                return
            logger.info(f"⚡ IMPULSE lean {symbol} | {direction} {agree}/3 {side}")
"""

WAIT = """        ok_idx, why_idx = index_entry_allowed(idx_now, side)
        if not ok_idx:
            direction = str((idx_now or {}).get("direction") or "NEUTRAL").upper()
            agree = int((idx_now or {}).get("agree") or 0)
            same = agree == 1 and (
                (side == "BUY" and direction == "BULL")
                or (side == "SELL" and direction == "BEAR")
            )
            if same:
                _impulse_wait[symbol] = {
                    "side": side,
                    "px": float(price),
                    "pre": float(pre or 0),
                    "chg": float(chg),
                    "volx": float(volx),
                    "ts": time.time(),
                }
                logger.info(
                    f"⏳ IMPULSE wait {symbol} | {direction} {agree}/3 {side} {float(chg):+.2f}%"
                )
                return
            logger.info(f"🚫 IMPULSE index {symbol} | {why_idx}")
            return
"""

HELPERS = '''
_impulse_wait = {}
_impulse_confirm_at = 0.0
_impulse_confirming = False

def impulse_arm_confirm(now: float) -> None:
    global _impulse_confirm_at
    if not _impulse_wait or now < _impulse_confirm_at:
        return
    _impulse_confirm_at = now + 5.0
    asyncio.create_task(impulse_confirm_saved())

async def impulse_confirm_saved() -> None:
    """The burst was saved at 1/3. Enter only after 2/3 if the move still holds."""
    global _impulse_busy, _impulse_confirming
    if _impulse_confirming or _impulse_busy or not _impulse_wait:
        return
    _impulse_confirming = True
    try:
        now = time.time()
        idx = None
        for sym, rec in list(_impulse_wait.items()):
            age = now - float(rec.get("ts") or 0)
            if age > 15.0 * 60.0:
                _impulse_wait.pop(sym, None)
                logger.info(f"⏳ IMPULSE wait expired {sym}")
                continue
            hist = _impulse_hist.get(sym)
            last = float(hist[-1][1]) if hist else 0.0
            anchor = float(rec.get("pre") or 0)
            side = rec.get("side")
            if last <= 0 or anchor <= 0:
                continue
            move = (last - anchor) / anchor * 100.0
            faded = (side == "BUY" and (move < 1.0 or move > 6.0)) or (
                side == "SELL" and (move > -1.0 or move < -6.0)
            )
            if faded:
                _impulse_wait.pop(sym, None)
                logger.info(f"🚫 IMPULSE wait drop {sym} | move={move:+.2f}%")
                continue
            if idx is None:
                idx = await get_index_direction()
            direction = str((idx or {}).get("direction") or "NEUTRAL").upper()
            agree = int((idx or {}).get("agree") or 0)
            same = (side == "BUY" and direction == "BULL") or (side == "SELL" and direction == "BEAR")
            if not same:
                _impulse_wait.pop(sym, None)
                logger.info(f"🚫 IMPULSE wait drop {sym} | {direction} {agree}/3")
                continue
            if agree < 2:
                continue
            if impulse_open_count() >= int(getattr(config, "IMPULSE_MAX_POSITIONS", 1)):
                return
            if any(sym in trades for trades in active_trades.values()):
                _impulse_wait.pop(sym, None)
                continue
            _impulse_wait.pop(sym, None)
            _impulse_busy = True
            _impulse_pending.add(sym)
            logger.info(f"✅ IMPULSE confirmed {sym} | {direction} {agree}/3 move={move:+.2f}%")
            await impulse_enter(sym, side, last, float(rec.get("chg") or move), float(rec.get("volx") or 0), anchor)
            return
    finally:
        _impulse_confirming = False

'''

REPLACEMENTS = [
(
"""async def impulse_enter(symbol: str, side: str, price: float, chg: float, volx: float) -> None:
""",
HELPERS + """async def impulse_enter(symbol: str, side: str, price: float, chg: float, volx: float, pre: float = 0.0) -> None:
"""
),
(
"""    asyncio.create_task(impulse_enter(sym, side, px, chg, volx))
""",
"""    asyncio.create_task(impulse_enter(sym, side, px, chg, volx, prev[1]))
"""
),
(
"""                        for row in data:
                            impulse_scan_row(row, now)
                        touch_activity()
""",
"""                        for row in data:
                            impulse_scan_row(row, now)
                        impulse_arm_confirm(now)
                        touch_activity()
"""
),
]


def main():
    if not os.path.exists(TARGET):
        print(f"STOPPED missing {TARGET}")
        return
    shutil.copy2(TARGET, BACKUP)
    text = open(TARGET, encoding="utf-8").read()
    n_lean = text.count(LEAN)
    n_plain = text.count(PLAIN)
    if n_lean + n_plain != 1:
        shutil.copy2(BACKUP, TARGET)
        print(f"STOPPED index block lean={n_lean} plain={n_plain}")
        print(f"restored from {BACKUP} — bot file was not changed")
        return
    text = text.replace(LEAN if n_lean else PLAIN, WAIT, 1)
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        n = text.count(old)
        if n != 1:
            shutil.copy2(BACKUP, TARGET)
            print(f"STOPPED piece {i} count={n}")
            print(f"restored from {BACKUP} — bot file was not changed")
            return
        text = text.replace(old, new, 1)
    if "IMPULSE lean" in text or "IMPULSE confirmed" not in text:
        shutil.copy2(BACKUP, TARGET)
        print("STOPPED result check failed")
        print(f"restored from {BACKUP} — bot file was not changed")
        return
    open(TARGET, "w", encoding="utf-8").write(text)
    try:
        py_compile.compile(TARGET, doraise=True)
    except Exception as e:
        shutil.copy2(BACKUP, TARGET)
        print(f"STOPPED compile: {e}")
        print(f"restored from {BACKUP} — bot file was not changed")
        return
    print("DONE pieces=4")
    print(f"backup={BACKUP}")


if __name__ == "__main__":
    main()
