-- Leaky Bucket Rate Limiter
-- KEYS[1] = rate limit key
-- ARGV[1] = capacity (queue max size)
-- ARGV[2] = leak_rate (items leaked per second)
-- ARGV[3] = current_time (-1 to use Redis TIME)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local leak_rate = tonumber(ARGV[2])
local supplied_time = tonumber(ARGV[3])

local now = 0

if supplied_time and supplied_time >= 0 then
    now = supplied_time
else
    local time_data = redis.call('TIME')
    now = tonumber(time_data[1]) + (tonumber(time_data[2]) / 1000000)
end

local state = redis.call('HMGET', key, 'queue_size', 'last_leak')
local queue_size = tonumber(state[1]) or 0
local last_leak = tonumber(state[2]) or now

local elapsed = now - last_leak
if elapsed < 0 then
    elapsed = 0
end

local drained = elapsed * leak_rate
local queue_after_leak = queue_size - drained
if queue_after_leak < 0 then
    queue_after_leak = 0
end

local allowed = 0
local retry_after = 0
local new_queue_size = queue_after_leak

if queue_after_leak + 1 <= capacity then
    allowed = 1
    new_queue_size = queue_after_leak + 1
else
    if leak_rate > 0 then
        retry_after = math.ceil(((queue_after_leak + 1) - capacity) / leak_rate)
        if retry_after < 1 then
            retry_after = 1
        end
    else
        retry_after = 1
    end
end

local remaining = math.floor(capacity - new_queue_size)
if remaining < 0 then
    remaining = 0
end

redis.call('HMSET', key, 'queue_size', new_queue_size, 'last_leak', now)

local ttl = 1
if leak_rate > 0 then
    ttl = math.ceil(capacity / leak_rate)
    if ttl < 1 then
        ttl = 1
    end
end
redis.call('EXPIRE', key, ttl)

local reset_at = now
if leak_rate > 0 then
    reset_at = now + (new_queue_size / leak_rate)
end

local request_count = math.floor(new_queue_size)

return {allowed, remaining, retry_after, reset_at, request_count}
