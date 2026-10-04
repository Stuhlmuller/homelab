-- Fluent Bit 5.1.3 record splitting; configure enable_flb_null and time_as_table.
-- Preserve ordinary records. Large records become reconstructable JSON fragments
-- below Wazuh's 64 KiB TCP message boundary and OpenSearch's 32766-byte keyword
-- term limit, including JSON escaping overhead.
-- This encodes the Lua record, not the original wire formatting. Fluent Bit's Lua
-- boundary uses doubles for numbers; log text remains an unchanged string.
local threshold = 24 * 1024
local fragment_bytes = 8 * 1024
local sequence = 0

local function quote(value)
    return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
        if char == '"' then return '\\"' end
        if char == '\\' then return '\\\\' end
        return string.format('\\u%04x', string.byte(char))
    end) .. '"'
end

local function encode(value)
    if value == flb_null or value == nil then return 'null' end
    local kind = type(value)
    if kind == 'string' then return quote(value) end
    if kind == 'boolean' then return value and 'true' or 'false' end
    if kind == 'number' then
        assert(value == value and value ~= math.huge and value ~= -math.huge,
               'non-finite value is not a JSON event')
        return string.format('%.17g', value)
    end
    assert(kind == 'table', 'unsupported JSON event value')
    local metadata = getmetatable(value)
    -- Pinned Fluent Bit preserves MessagePack array/map type in this metatable:
    -- https://github.com/fluent/fluent-bit/blob/v5.1.3/src/flb_lua.c#L234-L271
    local is_array = metadata and metadata.type == 1
    if not metadata then is_array = #value > 0 end
    local parts = {}
    if is_array then
        for index = 1, #value do parts[#parts + 1] = encode(value[index]) end
        return '[' .. table.concat(parts, ',') .. ']'
    end
    local keys = {}
    for key in pairs(value) do
        assert(type(key) == 'string', 'JSON object keys must be strings')
        keys[#keys + 1] = key
    end
    table.sort(keys)
    for _, key in ipairs(keys) do parts[#parts + 1] = quote(key) .. ':' .. encode(value[key]) end
    return '{' .. table.concat(parts, ',') .. '}'
end

local function utf8_end(value, first, size)
    local last = math.min(first + size - 1, #value)
    -- The next byte must begin a code point; continuation bytes belong to the
    -- fragment's final code point, so move that code point to the next fragment.
    while last < #value do
        local next_byte = string.byte(value, last + 1)
        if next_byte < 128 or next_byte >= 192 then break end
        last = last - 1
    end
    return last
end

local function label(value)
    if type(value) ~= 'string' then return 'unknown' end
    -- Envelope labels are bounded; their complete values remain in the payload.
    return value:sub(1, utf8_end(value, 1, 256))
end

local function event_id(serialized, timestamp)
    local first, second = 5381, 0
    for index = 1, #serialized do
        local byte = string.byte(serialized, index)
        first = (first * 33 + byte) % 4294967296
        second = (second * 65599 + byte) % 4294967296
    end
    sequence = sequence + 1
    -- Correlation identifier, not an authenticity/integrity signature.
    return string.format('%d-%09d-%08x%08x-%d-%d', timestamp.sec, timestamp.nsec,
                         first, second, #serialized, sequence)
end

function wazuh_size(tag, timestamp, record)
    local serialized = encode(record)
    if #serialized <= threshold then return 0, timestamp, record end
    local parts, first = {}, 1
    while first <= #serialized do
        local last = utf8_end(serialized, first, fragment_bytes)
        parts[#parts + 1] = serialized:sub(first, last)
        first = last + 1
    end
    local id = event_id(serialized, timestamp)
    local node = record.node or record.source_address
    if type(record.kubernetes) == 'table' then node = record.kubernetes.host or node end
    local source = label(record.homelab_source or tag)
    local fragments = {}
    for index, payload in ipairs(parts) do
        fragments[index] = {
            homelab_source = 'wazuh.fragment',
            original_source = source,
            node = label(node),
            fragment_event_id = id,
            fragment_index = index,
            fragment_count = #parts,
            fragment_encoding = 'json',
            fragment_payload = payload,
            original_timestamp_seconds = timestamp.sec,
            original_timestamp_nanoseconds = timestamp.nsec,
            original_json_bytes = #serialized,
        }
    end
    return 2, timestamp, fragments
end

-- Return the encoder only to the offline regression harness; Fluent Bit ignores
-- script return values and calls the global wazuh_size callback above.
return {encode = encode}
