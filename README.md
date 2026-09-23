# Video Converter — Linux GUI

A PyQt6 desktop app for converting:

- WebM → MP4 using H.264 + AAC
- MP4 → WebM using VP9 + Opus

It uses FFmpeg and supports drag-and-drop, batch conversion, quality controls,
resolution scaling, progress reporting, cancellation, and conversion summaries.

## Quick install (Ubuntu / Debian)

### 1. Install FFmpeg and Python

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv
```

Check that FFmpeg is installed:

```bash
ffmpeg -version
ffprobe -version
```

### 2. Put the application in its permanent location

From the extracted project directory, run:

```bash
mkdir -p ~/.local/share/video-converter
cp -r . ~/.local/share/video-converter/
cd ~/.local/share/video-converter
```

If you are already inside `~/.local/share/video-converter`, do not run the
`cp -r` command again.

### 3. Create the virtual environment

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Check PyQt6:

```bash
.venv/bin/python -c "import PyQt6; print('PyQt6 OK')"
```

You should see:

```text
PyQt6 OK
```

### 4. Test the application

```bash
.venv/bin/python converter_app.py
```

If the GUI opens, the application is installed correctly.

## Install the `video-converter` command

Use a small launcher instead of modifying the Python file's shebang. This keeps
the Python source portable and ensures the command always uses the virtual
environment containing PyQt6.

Run:

```bash
cat > /tmp/video-converter <<'EOF'
#!/bin/sh
exec "$HOME/.local/share/video-converter/.venv/bin/python" \
     "$HOME/.local/share/video-converter/converter_app.py" "$@"
EOF

sudo install -Dm755 /tmp/video-converter /usr/local/bin/video-converter
rm /tmp/video-converter
```

Now launch it with:

```bash
video-converter
```

This launcher explicitly uses:

```text
~/.local/share/video-converter/.venv/bin/python
```

That means the application will use the same virtual environment where PyQt6
was installed.

## Desktop application menu

The project includes `video-converter.desktop`.

Install it for your user account:

```bash
mkdir -p ~/.local/share/applications
cp video-converter.desktop ~/.local/share/applications/
```

The desktop entry uses:

```ini
Exec=/usr/local/bin/video-converter
```

After installation, look for **Video Converter** in your application menu.

## If you get `ModuleNotFoundError: No module named 'PyQt6'`

Make sure PyQt6 was installed into this application's virtual environment:

```bash
cd ~/.local/share/video-converter
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import PyQt6; print('PyQt6 OK')"
```

Then try:

```bash
video-converter
```

Do not install PyQt6 only into the system Python and assume the application's
virtual environment will see it. The application uses `.venv/bin/python`.

## If you get `from: command not found` or `import: command not found`

Those errors usually mean the launcher is being interpreted by the shell as a
shell script even though it contains Python code. Recreate the launcher using
the command in **Install the `video-converter` command** above.

The recommended launcher does not put a Python shebang into
`/usr/local/bin/video-converter`; it is a shell wrapper that explicitly starts
the correct virtual-environment Python interpreter.

## Updating the application

If you replace the application files with a newer version, reinstall the
Python dependencies:

```bash
cd ~/.local/share/video-converter
.venv/bin/pip install -r requirements.txt
```

The launcher normally does not need to be recreated because it points to the
same application directory.

## Configuration

The application stores its UI preferences in:

```text
~/.config/videoconverter/config.json
```

## Features

Input:

- Individual MP4/WebM files
- Folders
- Multiple files or folders via drag-and-drop
- Optional recursive folder scanning

Output:

- Use the source folder
- Or choose a separate output folder
- Unique output names prevent accidental overwriting

Quality:

- H.264 CRF: 18–28
- VP9 CRF: 15–35
- Lower CRF generally means higher quality and larger files
- Higher CRF generally means more compression and lower visual quality

Speed:

- H.264 presets from `ultrafast` through `veryslow`
- VP9 modes including `realtime`, `good`, and `best`

Resolution:

- Native
- 1080p
- 720p
- 480p

Conversion:

- Runs FFmpeg in a worker thread so the GUI remains responsive
- Shows conversion progress
- Supports cancellation
- Removes incomplete output after cancellation
- Shows original size, converted size, compression/space saved, and elapsed time

## Other Linux distributions

Fedora/RHEL:

```bash
sudo dnf install ffmpeg python3
```

Arch:

```bash
sudo pacman -S ffmpeg python
```

You still need Python's virtual environment package if your distribution does
not provide `venv` by default.

## Uninstall

Remove the application:

```bash
rm -rf ~/.local/share/video-converter
```

Remove the command:

```bash
sudo rm -f /usr/local/bin/video-converter
```

Remove the desktop entry:

```bash
rm -f ~/.local/share/applications/video-converter.desktop
```

The configuration file is separate. Remove it only if you also want to reset
all saved application settings:

```bash
rm -f ~/.config/videoconverter/config.json
```
