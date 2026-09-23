# Video Converter — Linux PyQt6 GUI

A standalone desktop GUI for bidirectional conversion:

- WebM -> MP4: `libx264` + AAC, `yuv420p`, `+faststart`
- MP4 -> WebM: `libvpx-vp9` + Opus, `-b:v 0` + CRF constant-quality mode

## 1. System dependencies

Debian/Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv
```

Fedora/RHEL:

```bash
sudo dnf install ffmpeg python3
```

Arch:

```bash
sudo pacman -S ffmpeg python
```

Verify:

```bash
ffmpeg -version
ffprobe -version
```

The application also checks at startup that the required FFmpeg encoders
(`libx264`, `libvpx-vp9`, `libopus`, and AAC) are available.

## 2. Python environment

From the directory containing `converter_app.py`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run:

```bash
python converter_app.py
```

Optional:

```bash
chmod +x converter_app.py
./converter_app.py
```

## 3. Install as a system command

For a machine-wide installation, copy the script:

```bash
sudo install -Dm755 converter_app.py /usr/local/bin/video-converter
```

The Python package still needs to be installed in the Python environment used by
the script. One straightforward approach is to use a dedicated virtualenv and
change the first line to that environment's Python interpreter.

For example:

```bash
python3 -m venv ~/.local/share/video-converter/venv
~/.local/share/video-converter/venv/bin/pip install -r requirements.txt
sed -i "1c\\#!$(realpath ~/.local/share/video-converter/venv/bin/python)" converter_app.py
sudo install -Dm755 converter_app.py /usr/local/bin/video-converter
```

Then launch:

```bash
video-converter
```

## 4. Desktop application menu

Create:

```bash
mkdir -p ~/.local/share/applications
nano ~/.local/share/applications/video-converter.desktop
```

Use:

```ini
[Desktop Entry]
Type=Application
Name=Video Converter
GenericName=Video Converter
Comment=Convert WebM and MP4 using FFmpeg
Exec=/usr/local/bin/video-converter
Icon=multimedia-video-player
Terminal=false
Categories=AudioVideo;Video;Utility;
StartupNotify=true
```

Or install the provided file system-wide:

```bash
sudo install -Dm644 video-converter.desktop \
  /usr/share/applications/video-converter.desktop
```

Log out/in only if your desktop environment does not refresh its application
database automatically.

## 5. Configuration

The application automatically saves UI preferences to:

```text
~/.config/videoconverter/config.json
```

The file is recreated automatically if it does not exist.

## 6. GUI behavior

Input:
- Add individual MP4/WebM files.
- Add a folder.
- Drag multiple files or a folder into the drop area.
- Optional recursive folder scanning.

Output:
- Use the source folder, or select another output folder.

Quality:
- H.264 CRF: 18–28 UI range.
- VP9 CRF: 15–35 UI range.
- Lower CRF generally means higher quality and larger files.
- Higher CRF generally means more compression and lower visual quality.

Speed:
- H.264 exposes x264 presets from `ultrafast` through `veryslow`.
- VP9 exposes `realtime`, `good`, and `best`.
- Slower modes spend more CPU time to improve compression efficiency.

Resolution:
- Native
- 1080p
- 720p
- 480p

The 1080p/720p/480p options use an FFmpeg `-2` dimension so the other
dimension is calculated to maintain the source aspect ratio while keeping a
dimension compatible with common 4:2:0 encoders.

Cancellation:
- Stop requests call `terminate()` on FFmpeg.
- If FFmpeg does not exit promptly, the worker escalates to `kill()`.
- Incomplete output files are removed.

## 7. Important output behavior

To prevent accidental data loss, FFmpeg runs with `-n` by default and the GUI
creates a unique output name such as:

```text
video.mp4
video (1).mp4
video (2).mp4
```

When using "source folder", every converted file is written beside its own
source file. This remains true even when dropped files come from different
directories. A chosen output directory instead sends every result to that
directory.
