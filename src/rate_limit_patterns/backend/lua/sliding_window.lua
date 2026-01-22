-- Sliding Window Counter Rate Limiter
-- KEYS[1] = window zset key
-- KEYS[2] = sequence key for uniqueness
-- ARGV[1] = limit (max requests per window)
-- ARGV[2] = period_seconds
-- ARGV[3] = current_time (-1 to use Redis TIME)

local key = KEYS[1]
local seq_key = KEYS[2]
local limit = tonumber(ARGV[1])
local period_seconds = tonumber(ARGV[2])
local supplied_time = tonumber(ARGV[3])

local now_ms = 0

if supplied_time and supplied_time >= 0 then
    now_ms = supplied_time * 1000
else
    local time_data = redis.call('TIME')
    now_ms = (tonumber(time_data[1]) * 1000) + math.floor(tonumber(time_data[2]) / 1000)
end

local window_ms = period_seconds * 1000
local window_start = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

local count = tonumber(redis.call('ZCARD', key))
local allowed = 0
local remaining = 0
local retry_after = 0
local reset_at = 0

if count < limit then
    allowed = 1
    local seq = redis.call('INCR', seq_key)
    local member = tostring(now_ms) .. ':' .. tostring(seq)
    redis.call('ZADD', key, now_ms, member)
    count = count + 1
    remaining = limit - count
else
    remaining = 0
end

local ttl = math.ceil(period_seconds)
if ttl < 1 then
    ttl = 1
end
redis.call('EXPIRE', key, ttl)
redis.call('EXPIRE', seq_key, ttl)

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if oldest[2] ~= nil then
    local oldest_ms = tonumber(oldest[2])
    reset_at = (oldest_ms + window_ms) / 1000
    if allowed == 0 then
        local wait_ms = oldest_ms + window_ms - now_ms
        if wait_ms < 0 then
            wait_ms = 0
        end
        retry_after = math.ceil(wait_ms / 1000)
    end
else
    reset_at = (now_ms + window_ms) / 1000
end

local request_count = count

return {allowed, remaining, retry_after, reset_at, request_count}
