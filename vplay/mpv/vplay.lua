-- vplay mpv helper: OSD, chunk markers, volume sync, and file IPC.

local utils = require("mp.utils")
local assdraw = require("mp.assdraw")

local state_file = os.getenv("VPLAY_MPV_STATE") or "/tmp/vplay-state.json"
local events_file = os.getenv("VPLAY_MPV_EVENTS") or "/tmp/vplay-events.json"

local osd_visible = false
local osd_timer = nil
local chunk_start = nil
local chunk_end = nil
local chunk_step = 0
local state_mtime = nil
local state_cache = nil

local function read_json_cached(path)
    local info = utils.file_info(path)
    if not info then
        state_mtime = nil
        state_cache = nil
        return nil
    end
    if state_cache and state_mtime == info.mtime then
        return state_cache
    end
    local file = io.open(path, "r")
    if not file then return nil end
    local data = file:read("*all")
    file:close()
    if not data or data == "" then return nil end
    local ok, parsed = pcall(utils.parse_json, data)
    if not ok then return nil end
    state_mtime = info.mtime
    state_cache = parsed
    return parsed
end

local function write_json(path, value)
    local data = utils.format_json(value)
    if not data then return end
    local file = io.open(path, "w")
    if not file then return end
    file:write(data)
    file:close()
end

local function format_time(secs)
    if not secs or secs < 0 then return "0:00" end
    local total = math.floor(secs)
    local minutes = math.floor(total / 60)
    local seconds = total % 60
    local hours = math.floor(minutes / 60)
    minutes = minutes % 60
    if hours > 0 then
        return string.format("%d:%02d:%02d", hours, minutes, seconds)
    end
    return string.format("%d:%02d", minutes, seconds)
end

local function draw_osd()
    if not osd_visible then
        mp.set_osd_ass(0, 0, "")
        return
    end

    local width = mp.get_property_number("osd-width", 1920)
    local height = mp.get_property_number("osd-height", 1080)
    local pos = mp.get_property_number("time-pos", 0)
    local dur = mp.get_property_number("duration", 0)
    local vol = mp.get_property_number("volume", 10)
    local muted = mp.get_property_bool("mute", false)
    local paused = mp.get_property_bool("pause", false)
    local fname = mp.get_property("filename", "")
    local state = read_json_cached(state_file)
    local display = fname
    local chunk_s = nil
    local chunk_e = nil

    if state then
        if state.names and state.names[fname] then
            display = state.names[fname]
        end
        if state.chunks and state.chunks[fname] then
            chunk_s = state.chunks[fname][1]
            chunk_e = state.chunks[fname][2]
        end
    end
    if #display > 64 then
        display = display:sub(1, 61) .. "..."
    end

    local bar_h = 82
    local bar_y = height - bar_h
    local pad = 22
    local prog_x = pad + 82
    local prog_y = bar_y + 48
    local prog_h = 8
    local prog_w = width - (pad * 2) - 168
    local pct = dur > 0 and math.max(0, math.min(1, pos / dur)) or 0
    local fill_w = math.floor(pct * prog_w)
    local icon = paused and "PAUSE" or "PLAY"
    local a = assdraw.ass_new()

    a:new_event()
    a:append(string.format("{\\pos(0,0)\\an7\\bord0\\shad0\\1c&H000000&\\1a&H45&\\p1}m 0 %d l %d %d l %d %d l 0 %d{\\p0}",
        bar_y, width, bar_y, width, bar_y + bar_h, bar_y + bar_h))

    a:new_event()
    a:append(string.format("{\\pos(%d,%d)\\an4\\fs18\\bord0\\shad0\\1c&HFFFFFF&}%s",
        pad, bar_y + 24, icon))
    a:new_event()
    a:append(string.format("{\\pos(%d,%d)\\an4\\fs20\\bord0\\shad0\\1c&HFFFFFF&}%s",
        pad + 62, bar_y + 24, display))
    a:new_event()
    a:append(string.format("{\\pos(%d,%d)\\an4\\fs16\\bord0\\shad0\\1c&HCCCCCC&}%s / %s",
        pad, bar_y + 62, format_time(pos), format_time(dur)))
    a:new_event()
    local vol_text = muted and string.format("Muted %d%%", vol) or string.format("Vol %d%%", vol)
    a:append(string.format("{\\pos(%d,%d)\\an6\\fs16\\bord0\\shad0\\1c&HCCCCCC&}%s",
        width - pad, bar_y + 62, vol_text))

    a:new_event()
    a:append(string.format("{\\pos(0,0)\\an7\\bord0\\shad0\\1c&H444444&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
        prog_x, prog_y, prog_x + prog_w, prog_y, prog_x + prog_w, prog_y + prog_h, prog_x, prog_y + prog_h))
    if fill_w > 0 then
        a:new_event()
        a:append(string.format("{\\pos(0,0)\\an7\\bord0\\shad0\\1c&HFFFFFF&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
            prog_x, prog_y, prog_x + fill_w, prog_y, prog_x + fill_w, prog_y + prog_h, prog_x, prog_y + prog_h))
    end

    if chunk_s and chunk_e and dur > 0 then
        local cs_x = prog_x + math.floor((chunk_s / dur) * prog_w)
        local ce_x = prog_x + math.floor((chunk_e / dur) * prog_w)
        a:new_event()
        a:append(string.format("{\\pos(0,0)\\an7\\bord0\\shad0\\1c&H00AA00&\\1a&H77&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
            cs_x, prog_y - 2, ce_x, prog_y - 2, ce_x, prog_y + prog_h + 2, cs_x, prog_y + prog_h + 2))
    end

    if chunk_step == 1 and chunk_start and dur > 0 then
        local cx = prog_x + math.floor((chunk_start / dur) * prog_w)
        a:new_event()
        a:append(string.format("{\\pos(0,0)\\an7\\bord0\\shad0\\1c&H00FF00&\\p1}m %d %d l %d %d l %d %d l %d %d{\\p0}",
            cx - 2, prog_y - 6, cx + 2, prog_y - 6, cx + 2, prog_y + prog_h + 6, cx - 2, prog_y + prog_h + 6))
    end

    if chunk_step == 1 then
        a:new_event()
        a:append(string.format("{\\pos(%d,%d)\\an5\\fs16\\bord1\\shad0\\1c&H00FF00&}CHUNK start set - press s for end",
            width / 2, bar_y - 20))
    elseif chunk_step == 2 then
        a:new_event()
        a:append(string.format("{\\pos(%d,%d)\\an5\\fs16\\bord1\\shad0\\1c&H00FFFF&}CHUNK %s - %s",
            width / 2, bar_y - 20, format_time(chunk_start), format_time(chunk_end)))
    end

    mp.set_osd_ass(width, height, a.text)
end

local function reset_osd_timer()
    if osd_timer then osd_timer:kill() end
    osd_timer = mp.add_timeout(5, function()
        osd_visible = false
        draw_osd()
    end)
end

local function show_osd()
    osd_visible = true
    draw_osd()
    reset_osd_timer()
end

local function hide_osd()
    osd_visible = false
    draw_osd()
    if osd_timer then
        osd_timer:kill()
        osd_timer = nil
    end
end

mp.add_forced_key_binding("o", "vplay-toggle-osd", function()
    if osd_visible then hide_osd() else show_osd() end
end)

mp.add_forced_key_binding("ESC", "vplay-hide-osd", function()
    if osd_visible then hide_osd() end
end)

mp.add_forced_key_binding("`", "vplay-terminal", function()
    mp.commandv("run", "/usr/bin/osascript", "-e", 'tell application "iTerm2" to activate')
end)

mp.add_forced_key_binding("s", "vplay-chunk", function()
    local pos = mp.get_property_number("time-pos")
    if not pos then return end
    if chunk_step == 0 then
        chunk_start = pos
        chunk_step = 1
        show_osd()
        mp.osd_message("Chunk start: " .. format_time(pos), 2)
    elseif chunk_step == 1 then
        chunk_end = pos
        if chunk_end < chunk_start then
            chunk_start, chunk_end = chunk_end, chunk_start
        end
        chunk_step = 2
        show_osd()
        write_json(events_file, {
            event = "chunk_set",
            file = mp.get_property("filename", ""),
            start = chunk_start,
            ["end"] = chunk_end,
        })
        mp.add_timeout(2.5, function()
            chunk_step = 0
            chunk_start = nil
            chunk_end = nil
            draw_osd()
        end)
    end
end)

local function adjust_volume(delta)
    mp.commandv("add", "volume", tostring(delta))
    local vol = mp.get_property_number("volume", 10)
    write_json(events_file, { event = "volume", volume = vol })
    show_osd()
end

local function toggle_mute()
    mp.commandv("cycle", "mute")
    local muted_now = mp.get_property_bool("mute", false)
    write_json(events_file, { event = "mute", muted = muted_now })
    show_osd()
end

mp.add_forced_key_binding("m", "vplay-mute", toggle_mute)
mp.add_forced_key_binding("+", "vplay-vol-up", function() adjust_volume(5) end)
mp.add_forced_key_binding("=", "vplay-vol-up-eq", function() adjust_volume(5) end)
mp.add_forced_key_binding("-", "vplay-vol-down", function() adjust_volume(-5) end)

mp.add_forced_key_binding("MOUSE_MOVE", "vplay-mouse-osd", function()
    local y = mp.get_property_number("mouse-pos/y", 0)
    local height = mp.get_property_number("osd-height", 1080)
    if y > height * 0.85 then show_osd() end
end)

mp.add_periodic_timer(0.5, function()
    if osd_visible then draw_osd() end
end)

mp.register_event("file-loaded", function()
    chunk_step = 0
    chunk_start = nil
    chunk_end = nil
    show_osd()
end)
