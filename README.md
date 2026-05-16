# vplay

<p align="center">
  <img src="assets/vplay.jpg" width="160" alt="vplay logo">
</p>

<p align="center">
  <a href="https://github.com/rztrace/vplay/releases/latest"><img alt="latest release" src="https://img.shields.io/github/v/release/rztrace/vplay?include_prereleases&label=release"></a>
  <a href="https://github.com/rztrace/vplay/blob/main/Formula/vplay.rb"><img alt="Homebrew tap" src="https://img.shields.io/badge/Homebrew-rztrace%2Fvplay-fbbf24"></a>
  <img alt="macOS" src="https://img.shields.io/badge/macOS-required-fbbf24">
</p>

`vplay` is an easy, fast, lightweight terminal video player for people who need to run videos on multiple screens and control each screen independently.

It is built for a very real 2026 problem: you have local video files, several screens or projectors, and you need playback to be easy, fast, stable, and controllable from one place. Most players are made for one video window. Tools that handle many outputs often become heavy production suites, media-center apps, browser dashboards, or signage systems. `vplay` sits in the useful middle: local, terminal-native, mpv-based, and focused on reliable multi-screen operation.

[Website](https://vplay.rztrace.com/) · [Latest release](https://github.com/rztrace/vplay/releases/latest) · [Discussions](https://github.com/rztrace/vplay/discussions)

```sh
brew tap rztrace/vplay https://github.com/rztrace/vplay
brew install vplay
vplay
```

## Features

- Browse local video collections from a terminal UI.
- Queue videos into playlists and control playback from one interface.
- Save display names and replay selected portions of files.
- Route playback to available screens.
- Play multiple videos or playlists on different screens at the same time.
- Control each screen independently: play/pause, volume, mute, loop mode, play-next behavior, and position.
- Extend behavior with system modules or user modules.
- Run optional downloads through `yt-dlp`.

## Why It Exists

Most video software makes the simple case easy: open one file, watch it, close it. The awkward case is still awkward: send different files to different screens, keep them stable, pause one without touching the others, adjust volume per screen, jump position live, and keep moving without building a whole show-control system.

`vplay` is for that awkward case. It keeps the interface small, local, and keyboard-first while giving each active screen its own playback session.

## Use Cases

- Galleries, classrooms, studios, rehearsal rooms, screenings, installations, and event setups.
- Several TVs, projectors, or screens controlled from one machine.
- Side-by-side references, loops, playlists, clipped sections, and quick swaps.
- Local video collections where a web dashboard, media center, or signage platform is too much.
- People who want a fast TUI rather than a heavy app.

## Requirements

- macOS
- `mpv`
- `yt-dlp` for download features
- Python 3.9+ only when installing from source

## Install With Homebrew

```sh
brew tap rztrace/vplay https://github.com/rztrace/vplay
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

The archive unpacks `vplay` plus its `_internal` runtime folder. Keep them together. The portable binary uses the folder it is stored in as its default video folder, so it can be unpacked into a media directory and run without setup.

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
