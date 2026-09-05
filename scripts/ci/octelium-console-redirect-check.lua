-- Exercise the actual Envoy Lua source extracted from the manifest.
assert(loadfile(arg[1]))()

local old = "https://stinkyboi.com/login?redirect=https%3A%2F%2Fconsole.octelium.stinkyboi.com%2F"
local new = "https://stinkyboi.com/login?redirect=https%3A%2F%2Fconsole.stinkyboi.com%2F"
local count = 0

local function check(host, status, denied, location, expected, skip_request)
  local values = {
    [":authority"] = host, [":status"] = status,
    ["x-octelium-unauthorized"] = denied, location = location,
    ["set-cookie"] = "unchanged", ["content-type"] = "text/html",
  }
  local before = {}
  for key, value in pairs(values) do before[key] = value end
  local metadata = {}
  local store = {
    set = function(_, ns, key, value) metadata[ns] = {[key] = value} end,
    get = function(_, ns) return metadata[ns] end,
  }
  local headers = {
    get = function(_, key) return values[key] end,
    replace = function(_, key, value) values[key] = value end,
  }
  local handle = {
    headers = function() return headers end,
    streamInfo = function() return {dynamicMetadata = function() return store end} end,
  }
  if not skip_request then envoy_on_request(handle) end
  envoy_on_response(handle)
  assert(values.location == expected, "incorrect redirect")
  for key, value in pairs(before) do
    if key ~= "location" then assert(values[key] == value, "changed unrelated header") end
  end
  count = count + 1
end

for _, suffix in ipairs({"", "logs", "logs%2Faudit%3Fuser%3Dexample%26from%3Dnow-1h"}) do
  check("console.stinkyboi.com", "303", "true", old .. suffix, new .. suffix)
end
for _, host in ipairs({"grafana.stinkyboi.com", "console.stinkyboi.com.evil", "console.stinkyboi.com:444"}) do
  check(host, "303", "true", old, old)
end
for _, status in ipairs({"200", "302", "401", "403"}) do
  check("console.stinkyboi.com", status, "true", old, old)
end
check("console.stinkyboi.com", "303", "false", old, old)
check("console.stinkyboi.com", "303", nil, old, old)
check("console.stinkyboi.com", "303", "true", nil, nil)
check("console.stinkyboi.com", "303", "true", new, new)
local lookalike = "https://stinkyboi.com/login?redirect=https%3A%2F%2Fconsole.octelium.stinkyboi.com.evil%2F"
check("console.stinkyboi.com", "303", "true", lookalike, lookalike)
check("console.stinkyboi.com", "303", "true", old, old, true)
print("Octelium console redirect: " .. count .. " scoped response checks passed")
