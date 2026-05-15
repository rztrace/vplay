# vplay

`vplay` is an advanced CLI video player with a TUI interface for macOS.

It allows queuing files, setting portions to play, organizing video collections, and, crucially, playing different videos on several screens or displays simultaneously while controlling everything from a single terminal interface.

It is lightweight, terminal-native, and built around add-ons and modules that can be added or scripted to enhance functionality.

## Features

- Browse local video collections from a terminal UI.
- Queue videos into playlists and control playback from one interface.
- Save display names and replay selected portions of files.
- Route playback to available macOS displays.
- Play multiple videos or playlists on different screens at the same time.
- Control per-screen playback, volume, mute, loop mode, play-next behavior, and position.
- Extend behavior with system modules or user modules.
- Run optional downloads through `yt-dlp`.

## Requirements

- macOS
- `mpv`
- `yt-dlp` for download features
- Python 3.9+ only when installing from source

## Install With Homebrew

```sh
brew tap rztrace/vplay https://github.com/rztrace/homebrew-vplay
brew install vplay
```

Homebrew installs are managed by Homebrew. Update with:

```sh
brew update && brew upgrade vplay
```

## Portable macOS Binary

Download the latest `vplay-macos-arm64.tar.gz` from:

```text
https://github.com/rztrace/vplay/releases/latest
```

Then unpack and run it:

```sh
tar -xzf vplay-macos-arm64.tar.gz
chmod +x vplay
./vplay
```

The portable binary uses the folder it is stored in as its default video folder. This is intentional so it can be dropped into a media directory and run without setup.

## Install From Source

```sh
git clone https://github.com/rztrace/vplay.git
cd vplay
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/vplay
```

Optional shell setup:

```sh
# zsh or bash
export PATH="$PWD/.venv/bin:$PATH"
vplay
```

```fish
# fish
fish_add_path "$PWD/.venv/bin"
vplay
```

You can also source the fish helper if you use fish:

```fish
source fish/vplay.fish
vplay
```

## Video Folder

Source and Homebrew installs default to `~/movs`. If that folder does not exist on first run, `vplay` asks whether to create it, use another folder, or switch to the terminal working folder.

The folder can later be changed from Settings. Source and Homebrew installs can also opt into using the current terminal folder at launch; portable builds use the binary folder by default.

## Modules

Modules live in `vplay/modules`.

- `vplay/modules/system` contains modules that integrate with core playback, settings, layout, or mpv behavior.
- `vplay/modules/user` is for lightweight add-ons that can be added as simple Python files.

Add-ons can provide panes, settings, or behavior enhancements. See `docs/modules.md` for the module shape and keybinding conventions.
