# vplay

`vplay` is an advanced CLI video player with a TUI interface for macOS.

It can queue files, play selected portions of videos, organize local video collections, and, crucially, play different videos on several screens or displays simultaneously while controlling everything from a single terminal interface.

The goal is a lightweight, robust system that stays fast in the terminal while remaining extensible through add-ons and modules.

## Features

- Terminal-native TUI for browsing and controlling video collections.
- Queue videos into playlists and control playback from one interface.
- Save custom display names for files.
- Mark and replay specific portions of videos.
- Route playback to available macOS displays.
- Play multiple videos or playlists on different screens at the same time.
- Control per-screen playback, volume, mute, loop mode, play-next behavior, and position.
- Add system or user modules to extend the interface and behavior.
- Optional download queue through `yt-dlp`.

## Requirements

- macOS
- Python 3.9+
- `mpv`
- `yt-dlp` for download features

## Install

```fish
git clone https://github.com/rztrace/vplay.git
cd vplay
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## Run

```fish
.venv/bin/vplay
```

For fish users, source the helper:

```fish
source fish/vplay.fish
vplay
```

## Modules

Modules live in `vplay/modules`.

- `vplay/modules/system` contains modules that integrate with core playback, settings, layout, or mpv behavior.
- `vplay/modules/user` is for lightweight add-ons that can be added as simple Python files.

Add-ons can provide panes, settings, or behavior enhancements. See `docs/modules.md` for the module shape.
