# Video Converter

A Linux desktop app for converting:

- **WebM → MP4**
- **MP4 → WebM**

The app uses **FFmpeg** in the background and provides a **PyQt6** graphical interface.

---

## Table of Contents

1. [Install FFmpeg](#1-install-ffmpeg)
2. [First Run](#2-first-run)
3. [Using the App](#3-using-the-app)
4. [Choose Conversion](#4-choose-conversion)
5. [Output Location](#5-output-location)
6. [Quality](#6-quality)
7. [Quick Presets](#7-quick-presets)
8. [Start Conversion](#8-start-conversion)
9. [Stop Conversion](#9-stop-conversion)
10. [Conversion Summary](#10-conversion-summary)
11. [Install Permanently](#11-install-permanently)
12. [Add to the Linux Application Menu](#12-add-to-the-linux-application-menu)
13. [File Locations](#13-file-locations)
14. [Uninstall](#14-uninstall)
15. [Troubleshooting](#15-troubleshooting)
16. [Quick Ubuntu/Debian Setup](#16-quick-ubuntudebian-setup)

---

## 1. Install FFmpeg

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv
```

### Fedora / RHEL

```bash
sudo dnf install ffmpeg python3
```

### Arch Linux

```bash
sudo pacman -S ffmpeg python
```

### Check

```bash
ffmpeg -version
ffprobe -version
```

---

## 2. First Run

Extract the ZIP, then open a terminal in the extracted folder.

Example:

```bash
cd ~/Downloads/video_converter_gui
```

Create a Python environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install PyQt6:

```bash
pip install -r requirements.txt
```

Start the app:

```bash
python converter_app.py
```

You should now see the Video Converter window.

---

## 3. Using the App

You can add videos by:

- Clicking **Add Files**
- Clicking **Add Folder**
- Dragging `.mp4` or `.webm` files into the drop area

For folders, you can enable **Scan folders recursively**.

---

## 4. Choose Conversion

Select:

- **WebM → MP4**

or:

- **MP4 → WebM**

The available encoding settings automatically change for the selected format.

---

## 5. Output Location

By default, converted files are saved beside the original files.

Example:

```
Videos/
├── movie.webm
└── movie.mp4
```

To use another location, uncheck **Use source folder** and choose an output directory.

---

## 6. Quality

### CRF

Lower CRF:

- Better quality
- Larger file

Higher CRF:

- More compression
- Smaller file
- Lower quality

| Format | CRF Range |
|--------|-----------|
| MP4 / H.264 | 18–28 |
| WebM / VP9 | 15–35 |

### Encoding Speed

**MP4 / H.264:** `ultrafast` → `veryslow`

- Faster presets finish sooner but generally compress less efficiently.
- Slower presets take longer but generally produce smaller files at a similar quality target.

**WebM / VP9:** `realtime`, `good`, `best`

### Resolution

- Native
- 1080p
- 720p
- 480p

The scaled modes preserve the original aspect ratio.

### Audio

- 128k
- 192k
- 256k
- 320k

Higher audio bitrate usually means higher audio quality and a larger file.

---

## 7. Quick Presets

The app includes:

- **Web Fast**
- **Balanced**
- **Maximum Compression**

These automatically change several encoding settings. You can still adjust the settings afterward.

---

## 8. Start Conversion

Click:

**Start Conversion**

The conversion runs in the background, so the GUI stays responsive.

You can see:

- Progress
- Current file
- FFmpeg speed
- Elapsed time
- Estimated remaining time
- FFmpeg log

Use **Show Log** to display the FFmpeg output.

---

## 9. Stop Conversion

Click:

**Cancel / Stop**

The application asks FFmpeg to terminate cleanly. If it does not stop, a stronger termination method is used.

Incomplete output files are removed.

---

## 10. Conversion Summary

After processing, the app shows:

- Original file size
- Converted file size
- Space saved (%)
- Time taken
- Status

---

## 11. Install Permanently

Once you have confirmed the app works, install it permanently.

From the extracted `video_converter_gui` folder:

```bash
mkdir -p ~/.local/share/video-converter
cp -r . ~/.local/share/video-converter/
```

Then:

```bash
cd ~/.local/share/video-converter
```

Create the permanent environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Make the script use that Python environment:

```bash
sed -i "1c\\#!$HOME/.local/share/video-converter/.venv/bin/python" converter_app.py
```

Install the command:

```bash
sudo install -Dm755 converter_app.py /usr/local/bin/video-converter
```

Test:

```bash
video-converter
```

If the GUI opens, the permanent installation is working.

---

## 12. Add to the Linux Application Menu

Run:

```bash
mkdir -p ~/.local/share/applications
cp video-converter.desktop ~/.local/share/applications/
```

Then search your Linux application menu for:

**Video Converter**

You can launch it like a normal application.

---

## 13. File Locations

| Item | Path |
|------|------|
| Application | `~/.local/share/video-converter/` |
| Configuration | `~/.config/videoconverter/config.json` |
| Command | `/usr/local/bin/video-converter` |
| Desktop launcher | `~/.local/share/applications/video-converter.desktop` |

---

## 14. Uninstall

Remove the application:

```bash
rm -rf ~/.local/share/video-converter
```

Remove the command:

```bash
sudo rm -f /usr/local/bin/video-converter
```

Remove the app-menu entry:

```bash
rm -f ~/.local/share/applications/video-converter.desktop
```

Remove saved settings:

```bash
rm -rf ~/.config/videoconverter
```

---

## 15. Troubleshooting

### FFmpeg is missing

Install it:

```bash
sudo apt install ffmpeg
```

Use the equivalent `dnf` or `pacman` command on other distributions.

### PyQt6 is missing

Activate the environment:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
```

### `video-converter` command is not found

Check:

```bash
ls -l /usr/local/bin/video-converter
```

Then reinstall:

```bash
sudo install -Dm755 converter_app.py /usr/local/bin/video-converter
```

### The app is not in the application menu

Check:

```bash
ls ~/.local/share/applications/video-converter.desktop
```

If necessary, log out and log in again.

---

## 16. Quick Ubuntu/Debian Setup

For a fresh Ubuntu/Debian system:

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv

cd ~/Downloads/video_converter_gui

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

python converter_app.py
```

Once that works, use [Install Permanently](#11-install-permanently) above.

---

## License

See the `LICENSE` file for details.
