-- Token Bucket Rate Limiter
-- KEYS[1] = rate limit key
-- ARGV[1] = burst_size
-- ARGV[2] = tokens_per_second
-- ARGV[3] = current_time (-1 to use Redis TIME)

local key = KEYS[1]
local burst_size = tonumber(ARGV[1])
local tokens_per_second = tonumber(ARGV[2])
local supplied_time = tonumber(ARGV[3])
local now = 0

if supplied_time and supplied_time >= 0 then
    now = supplied_time
else
    local time_data = redis.call('TIME')
    now = tonumber(time_data[1]) + (tonumber(time_data[2]) / 1000000)
end

-- Get current state
local state = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(state[1]) or burst_size
local last_refill = tonumber(state[2]) or now

-- Calculate token refill
local elapsed = now - last_refill
if elapsed < 0 then
    elapsed = 0
end
local tokens_to_add = elapsed * tokens_per_second
tokens = math.min(tokens + tokens_to_add, burst_size)

-- Check if allowed
local allowed = 0
local retry_after = 0

if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    local tokens_needed = 1 - tokens
    retry_after = math.ceil(tokens_needed / tokens_per_second)
end

-- Update state
redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)

local ttl = math.ceil(burst_size / tokens_per_second)
if ttl < 1 then
    ttl = 1
end
redis.call('EXPIRE', key, ttl)

-- Return: allowed, remaining, retry_after, reset_at
local remaining = math.floor(tokens)
local reset_at = now + (burst_size - tokens) / tokens_per_second
local request_count = math.floor(burst_size - tokens)

return {allowed, remaining, retry_after, reset_at, request_count}
