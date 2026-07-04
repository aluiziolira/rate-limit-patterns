# @title: Benchmark Proof
# @description: Live run of the rate-limit-patterns benchmark suite:
#   in-process latency, distributed Redis Lua latency, and multi-instance
#   correctness verification. Regenerate with `make demo-gif` (requires
#   vhs, docker, and an installed .venv).

Output docs/assets/benchmark-proof.gif

Require docker

Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 920
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set Padding 14
Set WindowBar Colorful
Set BorderRadius 8
Set Framerate 24

# --- hidden setup: venv + Redis (db 15, same as the test suite) ---
Hide
Type "source .venv/bin/activate && docker compose up -d redis && sleep 2 && clear"
Enter
Sleep 5s
Show

# --- 1/3: in-process latency ---
Type "# [1/3] In-process latency — 3 algorithms, up to 5,000 concurrent calls"
Enter
Sleep 800ms
Type "python -m benchmarks.scenarios.latency"
Enter
Sleep 9s

Hide
Type "clear"
Enter
Show

# --- 2/3: distributed latency over Redis Lua ---
Type "# [2/3] Distributed latency — atomic Redis Lua backend (EVALSHA)"
Enter
Sleep 800ms
Type "REDIS_URL=redis://localhost:6379/15 python -m benchmarks.scenarios.redis_latency"
Enter
Sleep 9s

Hide
Type "clear"
Enter
Show

# --- 3/3: multi-instance correctness ---
Type "# [3/3] Correctness — 2 independent instances, shared global limit of 100"
Enter
Sleep 800ms
Type "REDIS_URL=redis://localhost:6379/15 python -m benchmarks.scenarios.multi_instance"
Enter
Sleep 10s
