"""
One-command reproduction of the XAUUSD research behind XAUUSD_EDGE_REPORT.md.

    python research/run_all.py            # full study (~10-15 min)
    python research/run_all.py quick      # skip the heavy 21-year walk-forward

Prerequisite (once): python research/fetch_data.py && python research/xau_data.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

STEPS = [
    ("strategy regression tests", "tests/test_gold_trend.py",
     "closed-bar handling, one-signal-per-bar, and the disabled-by-NaN-MA failure mode"),
    ("market map tests", "tests/test_market_map.py",
     "profile/value-area maths, heatmap grid alignment, clustering"),
    ("config parity", "research/check_config_parity.py",
     "research/stub_config.py must mirror config.py or the numbers describe a different system"),
    ("build dataset", "research/xau_data.py", "M1 -> M5/H1/H4 with true UTC + NY/London clocks"),
    ("setup mining (why the old strategies lose)", "research/setups.py",
     "enumerates every sweep/FVG/displacement setup and measures what price did next"),
    ("family search (what has edge)", "research/family_search.py",
     "20+ entry families vs a matched random-entry null model"),
    ("edge testing (skill vs cost drag)", "research/edge_test.py",
     "isolates directional skill from spread/commission friction"),
    ("gold edge (drift, trend following)", "research/gold_edge.py",
     "intraday drift by hour + Donchian trend system"),
    ("long history walk-forward", "research/long_history.py",
     "21 years, params chosen on prior 4y only, then traded out-of-sample"),
    ("live module validation", "research/validate_live.py",
     "replays the SHIPPING strategy module through the bot's own pipeline"),
    ("map level validation", "research/map_validation.py",
     "do POC / value area / liquidity pools / HVN / round numbers beat "
     "distance-matched controls? (~30s)"),
    ("map filter test", "research/map_filter_test.py",
     "do map-context filters improve the trend system? (permutation null)"),
    ("challenge simulation", "research/challenge_sim.py",
     "can an 8%-in-30-days funded challenge be passed with a real edge?"),
]


def main() -> int:
    quick = len(sys.argv) > 1 and sys.argv[1] == "quick"
    failed = []
    for name, script, why in STEPS:
        if quick and name in ("long history walk-forward", "family search (what has edge)"):
            print(f"\n=== SKIPPED (quick): {name} ===")
            continue
        print("\n" + "=" * 92)
        print(f"  {name}")
        print(f"  {script}  --  {why}")
        print("=" * 92, flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, os.path.join(ROOT, script)], cwd=ROOT)
        status = "ok" if r.returncode == 0 else f"FAILED rc={r.returncode}"
        if r.returncode != 0:
            failed.append(script)
        print(f"  -> {status} in {time.time()-t0:.1f}s", flush=True)

    print("\n" + "=" * 92)
    if failed:
        print("FAILED steps:", ", ".join(failed))
        return 1
    print("All research steps completed. Outputs in research/out/")
    print("Key artefacts: family_search.txt, live_validation_trades.csv, ")
    print("               long_history_walkforward.csv, challenge_sim.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
