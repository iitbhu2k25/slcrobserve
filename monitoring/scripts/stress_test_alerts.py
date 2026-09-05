#!/usr/bin/env python3
"""
Actually load CPU and/or RAM on this machine so the REAL Prometheus rules in
monitoring/rules/node_alerts.yml (HighCPUUsage > 80%, HighMemoryUsage > 80%)
evaluate to true and fire through Alertmanager -> email, end to end.

This is different from test_alert_email.py, which injects a fake alert
straight into Alertmanager and never touches CPU/RAM or Prometheus at all.

Since both alert rules have `for: 5m`, this defaults to a 6-minute hold so
the threshold has time to actually trip before you check your inbox.

WARNING: this genuinely pins CPU cores and commits real RAM on whatever host
you run it on. If this host also runs other services (it looks like it does
- docker-compose with prometheus/grafana/etc.), expect things to feel slow
for the duration. Ctrl+C stops it early and always releases resources.

Usage:
    python3 stress_test_alerts.py                     # stress both, 6 min
    python3 stress_test_alerts.py --cpu-only
    python3 stress_test_alerts.py --ram-only --ram-target 85
    python3 stress_test_alerts.py --duration 400 --yes  # skip confirmation
"""

import argparse
import multiprocessing
import sys
import time

import psutil

CHUNK_BYTES = 100 * 1024 * 1024  # 100MB per allocation step


def cpu_burn(stop_event: multiprocessing.Event) -> None:
    while not stop_event.is_set():
        # cheap arithmetic spin, no syscalls, keeps the core at ~100%
        x = 0
        for _ in range(200000):
            x += 1


def start_cpu_stressors(stop_event: multiprocessing.Event) -> list:
    n = multiprocessing.cpu_count()
    print(f"Starting {n} CPU-burn workers (one per core)...")
    procs = []
    for _ in range(n):
        p = multiprocessing.Process(target=cpu_burn, args=(stop_event,))
        p.start()
        procs.append(p)
    return procs


def grow_memory_to_target(target_percent: float) -> list:
    chunks = []
    print(f"Allocating RAM towards {target_percent:.0f}% system usage...")
    while True:
        vm = psutil.virtual_memory()
        if vm.percent >= target_percent:
            print(f"Reached {vm.percent:.1f}% memory usage.")
            break
        if vm.available < 512 * 1024 * 1024:
            print("Stopping short: less than 512MB available, avoiding OOM risk.")
            break
        chunk = bytearray(CHUNK_BYTES)
        # touch every page so it's actually committed, not just reserved
        for i in range(0, CHUNK_BYTES, 4096):
            chunk[i] = 1
        chunks.append(chunk)
        print(f"  allocated {len(chunks) * CHUNK_BYTES / (1024**3):.2f} GB, "
              f"system now at {psutil.virtual_memory().percent:.1f}%")
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration", type=int, default=360, help="seconds to hold the load (default: 360, i.e. 6 min)")
    parser.add_argument("--ram-target", type=float, default=85.0, help="target overall RAM usage %% (default: 85)")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--ram-only", action="store_true")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    do_cpu = not args.ram_only
    do_ram = not args.cpu_only

    print(f"This machine: {multiprocessing.cpu_count()} cores, "
          f"{psutil.virtual_memory().total / (1024**3):.1f} GB RAM.")
    print(f"Plan: {'CPU ' if do_cpu else ''}{'RAM' if do_ram else ''} load for {args.duration}s.")
    if not args.yes:
        reply = input("Proceed? [y/N]: ").strip().lower()
        if reply != "y":
            print("Aborted.")
            return 1

    stop_event = multiprocessing.Event() if do_cpu else None
    cpu_procs = start_cpu_stressors(stop_event) if do_cpu else []
    mem_chunks = []

    try:
        if do_ram:
            mem_chunks = grow_memory_to_target(args.ram_target)

        print(f"Holding load for {args.duration}s (Ctrl+C to stop early)...")
        end = time.monotonic() + args.duration
        while time.monotonic() < end:
            remaining = int(end - time.monotonic())
            print(f"\r  {remaining}s remaining | CPU {psutil.cpu_percent():.0f}% | "
                  f"RAM {psutil.virtual_memory().percent:.0f}%   ", end="", flush=True)
            time.sleep(2)
        print()
    except KeyboardInterrupt:
        print("\nInterrupted, cleaning up...")
    finally:
        if stop_event is not None:
            stop_event.set()
        for p in cpu_procs:
            p.join(timeout=5)
        mem_chunks.clear()
        print("Load released. If the alert fired, check dssiitbhu@gmail.com "
              "(group_wait 30s, and the rule needs its `for: 5m` window to have elapsed).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
