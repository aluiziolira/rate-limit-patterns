-- Leaky Bucket Rate Limiter (Placeholder)
-- KEYS[1] = rate limit key
-- ARGV[1] = capacity (queue max size)
-- ARGV[2] = leak_rate (items leaked per second)
-- ARGV[3] = current_time

-- TODO: Implement full leaky bucket logic in Phase 4.4
-- This is a stub script that returns deterministic values for backend loading.

-- Return: allowed, remaining, retry_after, reset_at
return {1, 199, 0, 0}
