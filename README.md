# vplay

`vplay` is a reorganized copy of the fish `vplay` program. It keeps the same basic workflow:

- scan a video folder,
- build and persist a playlist,
- launch/control `mpv` through JSON IPC,
- show a Textual TUI,
- store display renames and playback chunks,
- download new videos through `yt-dlp`.

The original live files are untouched:

- `/Users/razdawson/.config/fish/config.fish`
- `/Users/razdawson/.config/fish/vplay_tui.py`
- `/Users/razdawson/.config/fish/vplay.lua`

## Run

```fish
cd vplay
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/vplay
```

Or source the fish wrapper in `fish/vplay.fish`.

## Layout

- `vplay/app.py` - Textual app and UI orchestration.
- `vplay/config.py` - paths, themes, runtime locations, defaults.
- `vplay/state.py` - atomic JSON persistence and legacy-state import.
- `vplay/media.py` - video scanning, filename formatting, cached ffprobe metadata.
- `vplay/mpv.py` - mpv process lifecycle and JSON IPC.
- `vplay/downloads.py` - yt-dlp download queue.
- `vplay/commands.py` - command-mode parsing helpers.
- `vplay/displays.py` - live macOS display discovery for screen routing.
- `vplay/ui/screens.py` - reusable modal screens.
- `vplay/modules/system` - core/system pane, enhancer, and settings module specs.
- `vplay/modules/user` - user module drop-ins.
- `vplay/mpv/vplay.lua` - mpv overlay and key bindings.
