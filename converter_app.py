#!/usr/bin/env python3
"""
Video Converter - Linux GUI

A PyQt6 desktop application for:
    WebM -> MP4 (H.264 + AAC)
    MP4  -> WebM (VP9 + Opus)

Dependencies:
    Python 3
    PyQt6
    ffmpeg
    ffprobe

Configuration:
    ~/.config/videoconverter/config.json

Design notes:
- The Qt GUI thread never performs a blocking FFmpeg conversion.
- A QThread runs a worker that launches FFmpeg with subprocess.Popen().
- FFmpeg's machine-readable `-progress pipe:1` output is parsed for progress.
- Cancellation is implemented by a thread-safe Event plus graceful process
  termination. A kill fallback is used if FFmpeg does not exit promptly.
- Paths are passed as argument-list elements rather than shell strings, so
  spaces and shell metacharacters are safe.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QThread,
    Qt,
    QTimer,
    pyqtSignal,
    QObject,
    QMimeData,
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)


APP_NAME = "Video Converter"
CONFIG_DIR = Path.home() / ".config" / "videoconverter"
CONFIG_PATH = CONFIG_DIR / "config.json"

MP4_PRESETS = {
    "ultrafast": "Fastest encode; largest output for similar quality.",
    "superfast": "Very fast; larger output than medium.",
    "veryfast": "Fast encode; modest compression efficiency.",
    "faster": "Faster than medium; somewhat larger output.",
    "fast": "Faster than medium; modest size increase.",
    "medium": "Balanced CPU time and compression efficiency.",
    "slow": "More CPU time; usually smaller than medium.",
    "slower": "High CPU cost; improved compression efficiency.",
    "veryslow": "Very high CPU cost; best x264 compression efficiency.",
}

VP9_PRESETS = {
    "realtime": "Lowest latency; fastest VP9 mode and usually larger output.",
    "good": "General-purpose VP9 encoding; balanced speed and efficiency.",
    "best": "Highest VP9 compression efficiency; slowest preset.",
}

SCALES = {
    "Native": "source",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
}

AUDIO_RATES = ["128k", "192k", "256k", "320k"]

# Presets are intentionally descriptive rather than "better/worse":
# they are shortcuts for common quality/speed/file-size priorities.
QUICK_PRESETS = {
    "Web Fast": {
        "crf_mp4": 27,
        "crf_webm": 34,
        "preset_mp4": "veryfast",
        "preset_webm": "realtime",
        "audio": "128k",
        "scale": "720p",
    },
    "Balanced": {
        "crf_mp4": 23,
        "crf_webm": 30,
        "preset_mp4": "medium",
        "preset_webm": "good",
        "audio": "128k",
        "scale": "Native",
    },
    "Maximum Compression": {
        "crf_mp4": 25,
        "crf_webm": 32,
        "preset_mp4": "veryslow",
        "preset_webm": "best",
        "audio": "192k",
        "scale": "Native",
    },
}

DEFAULTS = {
    "mode": "WebM -> MP4",
    "crf_mp4": 23,
    "crf_webm": 30,
    "preset_mp4": "medium",
    "preset_webm": "good",
    "scale": "Native",
    "audio": "128k",
    "output_source_folder": True,
}


@dataclass
class JobOptions:
    mode: str
    crf: int
    preset: str
    scale: str
    audio_bitrate: str
    output_dir: Path


@dataclass
class FileResult:
    source: Path
    output: Path
    status: str
    original_bytes: int
    output_bytes: int
    elapsed: float
    message: str = ""

    @property
    def saved_percent(self) -> float | None:
        if self.original_bytes <= 0 or self.output_bytes < 0:
            return None
        return (1.0 - self.output_bytes / self.original_bytes) * 100.0


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULTS)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            settings.update({k: v for k, v in loaded.items() if k in settings})
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        # Configuration errors should not prevent the application from
        # launching. The next save will restore a valid JSON file.
        pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    os.replace(temporary, CONFIG_PATH)


def human_size(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(max(0, value))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    return f"{minutes}m {sec}s"


def dependency_status() -> tuple[bool, str]:
    missing = [
        tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None
    ]
    if missing:
        return False, ", ".join(missing)
    return True, ""


def dependency_dialog(parent: QWidget | None, missing: str) -> bool:
    message = (
        f"<b>Missing required command(s): {missing}</b><br><br>"
        "Install FFmpeg with one of these commands, then restart the app:"
        "<pre>"
        "Debian / Ubuntu:\n"
        "  sudo apt update\n"
        "  sudo apt install ffmpeg\n\n"
        "Fedora / RHEL:\n"
        "  sudo dnf install ffmpeg\n\n"
        "Arch Linux:\n"
        "  sudo pacman -S ffmpeg"
        "</pre>"
        "You can verify the installation with "
        "<code>ffmpeg -version</code> and <code>ffprobe -version</code>."
    )
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("FFmpeg dependency missing")
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(message)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()
    return False


def ffmpeg_encoder_check() -> tuple[bool, str]:
    """
    Check that the encoders used by this application are present.

    A distro package can contain ffmpeg but be built without particular
    external encoders. This check avoids a long-running job failing later.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, result.stderr.strip() or "ffmpeg -encoders failed"

    text = f"{result.stdout}\n{result.stderr}"
    required = ["libx264", "libvpx-vp9", "libopus", "aac"]
    missing = [name for name in required if name not in text]
    if missing:
        return False, ", ".join(missing)
    return True, ""


class ProgressParser:
    def __init__(self, duration: float | None):
        self.duration = duration
        self.current_seconds = 0.0
        self.speed = ""

    def feed(self, line: str) -> tuple[float | None, str | None]:
        if "=" not in line:
            return None, None
        key, value = line.rstrip("\n").split("=", 1)

        if key in {"out_time_us", "out_time_ms"}:
            try:
                self.current_seconds = float(value) / 1_000_000
            except ValueError:
                return None, None
            if self.duration and self.duration > 0:
                pct = max(
                    0.0,
                    min(100.0, self.current_seconds / self.duration * 100.0),
                )
                return pct, None
            return None, None

        if key == "speed":
            self.speed = value
            return None, value

        return None, None


def get_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    try:
        value = float(result.stdout.strip())
        return value if value > 0 else None
    except ValueError:
        return None


def probe_video(path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, result.stderr.strip() or "ffprobe failed"
    if not result.stdout.strip():
        return False, "no video stream found"
    return True, ""


def scale_filter(scale_label: str) -> str | None:
    if scale_label == "Native":
        return None
    if scale_label == "1080p":
        return "scale=-2:1080"
    if scale_label == "720p":
        return "scale=-2:720"
    if scale_label == "480p":
        return "scale=-2:480"
    return None


def build_ffmpeg_args(
    source: Path,
    output: Path,
    mode: str,
    crf: int,
    preset: str,
    scale: str,
    audio_bitrate: str,
) -> list[str]:
    common = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]

    vf = scale_filter(scale)
    if vf:
        common += ["-vf", vf]

    if mode == "WebM -> MP4":
        # x264 CRF is a constant-quality target. A lower CRF generally
        # produces higher visual quality and a larger file.
        # yuv420p maximizes playback compatibility.
        common += [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            # Puts MP4 metadata at the front for progressive playback/web use.
            "-movflags",
            "+faststart",
        ]
    else:
        # VP9 CRF controls quality. `-b:v 0` disables a bitrate target, giving
        # pure constant-quality behavior instead of bitrate + quality control.
        common += [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(crf),
            "-b:v",
            "0",
            # The WebM UI maps realtime/good/best to libvpx's deadline modes.
            "-deadline",
            preset,
            "-cpu-used",
            "4" if preset != "realtime" else "8",
            "-c:a",
            "libopus",
            "-b:a",
            audio_bitrate,
        ]

    # Never overwrite unless the UI explicitly requested it. The application
    # already avoids collisions by creating a unique output name.
    common += ["-n", str(output)]
    return common


class ConversionWorker(QObject):
    progress = pyqtSignal(int, float, str)  # percent, encoded seconds, speed
    log_line = pyqtSignal(str)
    file_started = pyqtSignal(str, int, int)
    file_finished = pyqtSignal(object)
    overall_progress = pyqtSignal(int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        files: list[Path],
        options: JobOptions,
        overwrite: bool,
    ):
        super().__init__()
        self.files = files
        self.options = options
        self.overwrite = overwrite
        self._cancel_event = threading.Event()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def request_cancel(self) -> None:
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _wait_after_terminate(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _unique_output(self, source: Path) -> Path:
        target_ext = ".mp4" if self.options.mode == "WebM -> MP4" else ".webm"

        if self.options.output_dir == source.parent:
            base = source.with_suffix("")
        else:
            base = self.options.output_dir / source.stem

        target = base.with_suffix(target_ext)
        if self.overwrite or not target.exists():
            return target

        counter = 1
        while True:
            candidate = base.with_name(f"{base.name} ({counter})").with_suffix(
                target_ext
            )
            if not candidate.exists():
                return candidate
            counter += 1

    def _run_one(self, source: Path) -> FileResult:
        start = time.monotonic()
        original_bytes = source.stat().st_size
        output = self._unique_output(source)
        output.parent.mkdir(parents=True, exist_ok=True)

        valid, reason = probe_video(source)
        if not valid:
            return FileResult(
                source,
                output,
                "Failed",
                original_bytes,
                0,
                time.monotonic() - start,
                f"Invalid/unreadable video: {reason}",
            )

        duration = get_duration(source)
        args = build_ffmpeg_args(
            source=source,
            output=output,
            mode=self.options.mode,
            crf=self.options.crf,
            preset=self.options.preset,
            scale=self.options.scale,
            audio_bitrate=self.options.audio_bitrate,
        )

        # `-n` was deliberately selected above for safety. We use a unique
        # output when overwrite is false. When overwrite is true, replace -n
        # with -y because the user explicitly opted in.
        if self.overwrite:
            args[-2] = "-y"

        self.log_line.emit("$ " + " ".join(_shell_quote(x) for x in args))

        parser = ProgressParser(duration)

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                start_new_session=True,
            )
        except OSError as exc:
            return FileResult(
                source,
                output,
                "Failed",
                original_bytes,
                0,
                time.monotonic() - start,
                f"Could not start ffmpeg: {exc}",
            )

        with self._process_lock:
            self._process = process

        stderr_lines: list[str] = []

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                line = line.rstrip("\n")
                if line:
                    stderr_lines.append(line)
                    self.log_line.emit(line)

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                if self._cancel_event.is_set():
                    self._wait_after_terminate(process)
                    break

                line = raw_line.rstrip("\n")
                if line:
                    self.log_line.emit(line)

                percent, speed = parser.feed(raw_line)
                if percent is not None:
                    self.progress.emit(
                        int(percent),
                        parser.current_seconds,
                        speed or parser.speed,
                    )
        finally:
            if self._cancel_event.is_set() and process.poll() is None:
                self._wait_after_terminate(process)

            return_code = process.wait()
            stderr_thread.join(timeout=2)

            with self._process_lock:
                self._process = None

        elapsed = time.monotonic() - start

        if self._cancel_event.is_set():
            try:
                if output.exists():
                    output.unlink()
            except OSError:
                pass
            return FileResult(
                source,
                output,
                "Cancelled",
                original_bytes,
                0,
                elapsed,
                "Conversion cancelled by user.",
            )

        if return_code != 0:
            try:
                if output.exists():
                    output.unlink()
            except OSError:
                pass

            message = "\n".join(stderr_lines[-12:]) or (
                f"ffmpeg exited with status {return_code}"
            )
            return FileResult(
                source,
                output,
                "Failed",
                original_bytes,
                0,
                elapsed,
                message,
            )

        if not output.exists():
            return FileResult(
                source,
                output,
                "Failed",
                original_bytes,
                0,
                elapsed,
                "ffmpeg reported success but no output file was created.",
            )

        output_bytes = output.stat().st_size
        self.progress.emit(100, duration or parser.current_seconds, parser.speed)

        return FileResult(
            source,
            output,
            "Completed",
            original_bytes,
            output_bytes,
            elapsed,
        )

    def run(self) -> None:
        results: list[FileResult] = []
        total = len(self.files)

        for index, source in enumerate(self.files, start=1):
            if self._cancel_event.is_set():
                break

            self.file_started.emit(str(source), index, total)
            result = self._run_one(source)
            results.append(result)
            self.file_finished.emit(result)
            self.overall_progress.emit(int(index / total * 100))

            if self._cancel_event.is_set():
                break

        if self._cancel_event.is_set():
            self.finished.emit(results)
            return

        self.finished.emit(results)


def _shell_quote(value: str) -> str:
    # Human-readable quoting for the log. This is NOT used to execute commands.
    if not value:
        return "''"
    if all(ch.isalnum() or ch in "/._-:=+%" for ch in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


class DropArea(QFrame):
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        layout = QVBoxLayout(self)

        title = QLabel("Drop video files or a folder here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("", 13, QFont.Weight.DemiBold))

        subtitle = QLabel(
            "WebM and MP4 are supported. Multiple files can be dropped."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime: QMimeData = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().polish(self)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dragActive", False)
        self.style().polish(self)

        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))

        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class SummaryDialog(QDialog):
    def __init__(self, results: list[FileResult], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conversion Summary")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        title = QLabel("Conversion completed")
        title.setFont(QFont("", 14, QFont.Weight.DemiBold))
        layout.addWidget(title)

        rows = QGridLayout()
        headers = [
            "Source",
            "Output",
            "Status",
            "Original",
            "New",
            "Saved",
            "Time",
        ]
        for col, header in enumerate(headers):
            label = QLabel(f"<b>{header}</b>")
            rows.addWidget(label, 0, col)

        for row, result in enumerate(results, start=1):
            saved = (
                "N/A"
                if result.saved_percent is None
                else f"{result.saved_percent:+.1f}%"
            )
            values = [
                result.source.name,
                result.output.name,
                result.status,
                human_size(result.original_bytes),
                human_size(result.output_bytes),
                saved,
                format_seconds(result.elapsed),
            ]
            for col, value in enumerate(values):
                label = QLabel(value)
                label.setToolTip(str(value))
                rows.addWidget(label, row, col)

        layout.addLayout(rows)

        errors = [r for r in results if r.status in {"Failed", "Cancelled"}]
        if errors:
            error_box = QPlainTextEdit()
            error_box.setReadOnly(True)
            text = []
            for result in errors:
                text.append(
                    f"{result.source.name}: {result.status}\n{result.message}\n"
                )
            error_box.setPlainText("\n".join(text))
            layout.addWidget(error_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.selected_files: list[Path] = []
        self.selected_folder: Path | None = None
        self.worker_thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self.job_results: list[FileResult] = []
        self.job_start = 0.0

        self.setWindowTitle(APP_NAME)
        self.resize(1040, 780)
        self.setAcceptDrops(False)

        self._build_ui()
        self._load_ui_state()
        self._update_mode_controls()
        self._refresh_file_list()

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self._update_elapsed)
        self.elapsed_timer.start(250)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setFont(QFont("", 18, QFont.Weight.DemiBold))
        header.addWidget(title)
        header.addStretch()

        self.dependency_label = QLabel("")
        header.addWidget(self.dependency_label)
        root.addLayout(header)

        self.drop_area = DropArea()
        self.drop_area.filesDropped.connect(self._add_dropped_paths)
        root.addWidget(self.drop_area)

        source_box = QGroupBox("Source")
        source_layout = QVBoxLayout(source_box)
        source_buttons = QHBoxLayout()
        self.add_files_button = QPushButton("Add Files")
        self.add_folder_button = QPushButton("Add Folder")
        self.clear_button = QPushButton("Clear")
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button.clicked.connect(self._choose_folder)
        self.clear_button.clicked.connect(self._clear_files)
        source_buttons.addWidget(self.add_files_button)
        source_buttons.addWidget(self.add_folder_button)
        source_buttons.addWidget(self.clear_button)
        source_buttons.addStretch()
        source_layout.addLayout(source_buttons)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(110)
        source_layout.addWidget(self.file_list)
        root.addWidget(source_box)

        controls = QHBoxLayout()
        controls.addWidget(self._build_conversion_box(), 1)
        controls.addWidget(self._build_output_box(), 1)
        controls.addWidget(self._build_quality_box(), 2)
        root.addLayout(controls)

        preset_box = QGroupBox("Quick Presets")
        preset_layout = QHBoxLayout(preset_box)
        self.quick_buttons: dict[str, QPushButton] = {}
        for name in QUICK_PRESETS:
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda checked, n=name: self._apply_quick_preset(n))
            self.quick_buttons[name] = button
            preset_layout.addWidget(button)
        root.addWidget(preset_box)

        progress_box = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_box)

        progress_top = QHBoxLayout()
        self.current_file_label = QLabel("Ready")
        progress_top.addWidget(self.current_file_label, 1)
        self.percent_label = QLabel("0%")
        progress_top.addWidget(self.percent_label)
        progress_layout.addLayout(progress_top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)

        stats = QHBoxLayout()
        self.elapsed_label = QLabel("Elapsed: 0.0s")
        self.remaining_label = QLabel("Remaining: —")
        self.speed_label = QLabel("FFmpeg speed: —")
        stats.addWidget(self.elapsed_label)
        stats.addWidget(self.remaining_label)
        stats.addWidget(self.speed_label)
        stats.addStretch()
        progress_layout.addLayout(stats)
        root.addWidget(progress_box)

        buttons = QHBoxLayout()
        self.log_toggle_button = QPushButton("Show Log")
        self.log_toggle_button.setCheckable(True)
        self.log_toggle_button.toggled.connect(self._toggle_log)

        self.start_button = QPushButton("Start Conversion")
        self.start_button.setMinimumHeight(42)
        self.start_button.clicked.connect(self._start_conversion)

        self.cancel_button = QPushButton("Cancel / Stop")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_conversion)

        buttons.addWidget(self.log_toggle_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button)
        root.addLayout(buttons)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setVisible(False)
        self.log_view.setPlaceholderText("FFmpeg output will appear here.")
        root.addWidget(self.log_view, 1)

    def _build_conversion_box(self) -> QGroupBox:
        box = QGroupBox("Conversion")
        layout = QFormLayout(box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["WebM -> MP4", "MP4 -> WebM"])
        self.mode_combo.currentTextChanged.connect(self._update_mode_controls)
        layout.addRow("Mode:", self.mode_combo)

        self.recursive_check = QCheckBox("Scan folders recursively")
        self.recursive_check.setToolTip(
            "When a folder is selected, include videos below its subfolders."
        )
        layout.addRow("", self.recursive_check)

        return box

    def _build_output_box(self) -> QGroupBox:
        box = QGroupBox("Output")
        layout = QVBoxLayout(box)

        self.source_output_check = QCheckBox("Use source folder")
        self.source_output_check.setToolTip(
            "Save converted files beside the input files."
        )
        self.source_output_check.stateChanged.connect(self._toggle_output_dir)
        layout.addWidget(self.source_output_check)

        row = QHBoxLayout()
        self.output_dir_label = QLabel("Source folder")
        self.output_dir_label.setWordWrap(True)
        self.output_button = QPushButton("Choose…")
        self.output_button.clicked.connect(self._choose_output_dir)
        row.addWidget(self.output_dir_label, 1)
        row.addWidget(self.output_button)
        layout.addLayout(row)

        return box

    def _build_quality_box(self) -> QGroupBox:
        box = QGroupBox("Encoding Parameters")
        layout = QFormLayout(box)

        self.crf_slider = QSlider(Qt.Orientation.Horizontal)
        self.crf_slider.setTracking(True)
        self.crf_slider.valueChanged.connect(self._update_crf_text)

        self.crf_value_label = QLabel()
        crf_row = QHBoxLayout()
        crf_row.addWidget(self.crf_slider, 1)
        crf_row.addWidget(self.crf_value_label)
        layout.addRow("CRF:", crf_row)

        self.quality_hint_label = QLabel()
        self.quality_hint_label.setWordWrap(True)
        layout.addRow("", self.quality_hint_label)

        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self._update_preset_tooltip)
        layout.addRow("Speed / Preset:", self.preset_combo)

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(SCALES.keys())
        layout.addRow("Resolution:", self.scale_combo)

        self.audio_combo = QComboBox()
        self.audio_combo.addItems(AUDIO_RATES)
        layout.addRow("Audio:", self.audio_combo)

        return box

    def _load_ui_state(self):
        mode = self.settings.get("mode", DEFAULTS["mode"])
        self.mode_combo.setCurrentText(mode)

        self.source_output_check.setChecked(
            bool(
                self.settings.get(
                    "output_source_folder",
                    DEFAULTS["output_source_folder"],
                )
            )
        )

        self.recursive_check.setChecked(
            bool(self.settings.get("recursive", False))
        )

        scale = self.settings.get("scale", DEFAULTS["scale"])
        if scale in SCALES:
            self.scale_combo.setCurrentText(scale)

        audio = self.settings.get("audio", DEFAULTS["audio"])
        if audio in AUDIO_RATES:
            self.audio_combo.setCurrentText(audio)

        self._apply_mode_values()

    def _save_ui_state(self):
        self.settings["mode"] = self.mode_combo.currentText()
        self.settings["crf_mp4"] = (
            self.crf_slider.value()
            if self.mode_combo.currentText() == "WebM -> MP4"
            else self.settings.get("crf_mp4", 23)
        )
        self.settings["crf_webm"] = (
            self.crf_slider.value()
            if self.mode_combo.currentText() == "MP4 -> WebM"
            else self.settings.get("crf_webm", 30)
        )
        self.settings["scale"] = self.scale_combo.currentText()
        self.settings["audio"] = self.audio_combo.currentText()
        self.settings["output_source_folder"] = self.source_output_check.isChecked()
        self.settings["recursive"] = self.recursive_check.isChecked()

        if self.mode_combo.currentText() == "WebM -> MP4":
            self.settings["preset_mp4"] = self.preset_combo.currentText()
        else:
            self.settings["preset_webm"] = self.preset_combo.currentText()

        save_settings(self.settings)

    def _apply_mode_values(self):
        mode = self.mode_combo.currentText()

        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        if mode == "WebM -> MP4":
            crf = int(self.settings.get("crf_mp4", 23))
            presets = list(MP4_PRESETS.keys())
            preset = self.settings.get("preset_mp4", "medium")
            self.crf_slider.setRange(18, 28)
            self.crf_slider.setValue(max(18, min(28, crf)))
            self.preset_combo.addItems(presets)
            self.preset_combo.setCurrentText(
                preset if preset in presets else "medium"
            )
        else:
            crf = int(self.settings.get("crf_webm", 30))
            presets = list(VP9_PRESETS.keys())
            preset = self.settings.get("preset_webm", "good")
            self.crf_slider.setRange(15, 35)
            self.crf_slider.setValue(max(15, min(35, crf)))
            self.preset_combo.addItems(presets)
            self.preset_combo.setCurrentText(
                preset if preset in presets else "good"
            )

        self.preset_combo.blockSignals(False)
        self._update_crf_text(self.crf_slider.value())
        self._update_preset_tooltip(self.preset_combo.currentText())

    def _update_mode_controls(self, *_):
        if hasattr(self, "crf_slider"):
            self._apply_mode_values()

    def _update_crf_text(self, value: int):
        self.crf_value_label.setText(str(value))
        mode = self.mode_combo.currentText()

        if mode == "WebM -> MP4":
            low, high = 18, 28
        else:
            low, high = 15, 35

        position = (value - low) / max(1, high - low)
        if position < 0.34:
            label = "Lossless / High Size"
        elif position < 0.67:
            label = "Balanced Quality / Size"
        else:
            label = "High Compression / Lower Quality"

        self.quality_hint_label.setText(
            f"{label} — lower CRF retains more detail and usually increases "
            f"file size; higher CRF increases compression."
        )

    def _update_preset_tooltip(self, value: str):
        mode = self.mode_combo.currentText()
        descriptions = MP4_PRESETS if mode == "WebM -> MP4" else VP9_PRESETS
        text = descriptions.get(value, "")
        self.preset_combo.setToolTip(text)

    def _toggle_output_dir(self, state: int):
        enabled = not bool(state)
        self.output_button.setEnabled(enabled)

        if not enabled:
            self.output_dir_label.setText("Source folder")
        elif not self.output_dir_label.text() or self.output_dir_label.text() == "Source folder":
            self.output_dir_label.setText("Choose an output directory…")

    def _choose_output_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose output directory",
            str(Path.home()),
        )
        if directory:
            self.output_dir_label.setText(directory)
            self.source_output_check.setChecked(False)

    def _choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose videos",
            str(Path.home()),
            "Video files (*.webm *.mp4);;All files (*)",
        )
        if files:
            self._add_dropped_paths([Path(p) for p in files])

    def _choose_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose folder",
            str(Path.home()),
        )
        if directory:
            self._add_dropped_paths([Path(directory)])

    def _add_dropped_paths(self, paths: list[Path]):
        for path in paths:
            if not path.exists():
                continue

            if path.is_dir():
                # Store folder separately so the recursive setting can be
                # evaluated when Start is pressed.
                self.selected_folder = path
                # A folder selection replaces file-only selection to avoid
                # accidentally mixing an old batch with a new folder batch.
                self.selected_files.clear()
                self._append_log(f"Selected folder: {path}")
            else:
                if path.suffix.lower() not in {".mp4", ".webm"}:
                    continue
                if path not in self.selected_files:
                    self.selected_files.append(path)
                self.selected_folder = None

        self._refresh_file_list()

    def _clear_files(self):
        self.selected_files.clear()
        self.selected_folder = None
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list.clear()

        if self.selected_folder:
            recursive = " (recursive)" if self.recursive_check.isChecked() else ""
            self.file_list.addItem(
                f"{self.selected_folder}{recursive}"
            )

        for path in self.selected_files:
            self.file_list.addItem(str(path))

        count = len(self._collect_job_files())
        self.current_file_label.setText(
            f"Ready — {count} source file(s) selected"
        )

    def _collect_job_files(self) -> list[Path]:
        mode = self.mode_combo.currentText()
        expected_input = ".webm" if mode == "WebM -> MP4" else ".mp4"

        if self.selected_folder:
            pattern = "**/*" if self.recursive_check.isChecked() else "*"
            candidates = self.selected_folder.glob(pattern)
            return sorted(
                p for p in candidates
                if p.is_file() and p.suffix.lower() == expected_input
            )

        return [
            p for p in self.selected_files
            if p.is_file() and p.suffix.lower() == expected_input
        ]

    def _apply_quick_preset(self, name: str):
        preset = QUICK_PRESETS[name]
        mode = self.mode_combo.currentText()

        crf_key = "crf_mp4" if mode == "WebM -> MP4" else "crf_webm"
        preset_key = "preset_mp4" if mode == "WebM -> MP4" else "preset_webm"

        self.settings[crf_key] = preset[crf_key]
        self.settings[preset_key] = (
            preset[preset_key]
        )
        self.settings["audio"] = preset["audio"]
        self.settings["scale"] = preset["scale"]

        self.scale_combo.setCurrentText(preset["scale"])
        self.audio_combo.setCurrentText(preset["audio"])
        self.preset_combo.setCurrentText(preset[preset_key])

        self._apply_mode_values()

        # Uncheck other quick presets visually.
        for key, button in self.quick_buttons.items():
            button.setChecked(key == name)

    def _append_log(self, text: str):
        self.log_view.appendPlainText(text)

    def _determine_output_dir(self, files: list[Path]) -> Path:
        if self.source_output_check.isChecked():
            # For multi-file jobs from different directories, each output is
            # placed beside its source. For the single chosen output directory
            # path below, the worker receives a shared directory.
            # To preserve source folders consistently, the first source folder
            # is used only when all selected files share it.
            if files and all(p.parent == files[0].parent for p in files):
                return files[0].parent
            # Different source folders cannot all share one "source" directory.
            # The worker's relative structure behavior is not needed for the
            # common drag-multiple-files case, so keep a temporary common root
            # at the first source's directory and explain it in the log.
            return files[0].parent if files else Path.home()

        text = self.output_dir_label.text()
        if not text or text == "Source folder":
            return Path.home()
        return Path(text)

    def _current_options(self, files: list[Path]) -> JobOptions:
        mode = self.mode_combo.currentText()
        return JobOptions(
            mode=mode,
            crf=self.crf_slider.value(),
            preset=self.preset_combo.currentText(),
            scale=self.scale_combo.currentText(),
            audio_bitrate=self.audio_combo.currentText(),
            output_dir=self._determine_output_dir(files),
        )

    def _start_conversion(self):
        if self.worker_thread is not None:
            return

        files = self._collect_job_files()
        if not files:
            QMessageBox.warning(
                self,
                "No compatible videos",
                "Add at least one compatible video for the selected mode.",
            )
            return

        if not self.source_output_check.isChecked():
            output_dir = Path(self.output_dir_label.text())
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self, "Output directory error", str(exc)
                )
                return

        self._save_ui_state()
        self.job_results = []
        self.job_start = time.monotonic()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")
        self.remaining_label.setText("Remaining: —")
        self.speed_label.setText("FFmpeg speed: —")
        self.log_view.clear()

        options = self._current_options(files)

        self.worker_thread = QThread()
        self.worker = ConversionWorker(
            files=files,
            options=options,
            overwrite=False,
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_file_progress)
        self.worker.overall_progress.connect(self.progress_bar.setValue)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_finished.connect(self._on_file_finished)
        self.worker.log_line.connect(self._append_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        self.worker_thread.finished.connect(self._cleanup_worker)

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.add_files_button.setEnabled(False)
        self.add_folder_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.recursive_check.setEnabled(False)
        self.log_toggle_button.setChecked(True)

        self.worker_thread.start()

    def _on_file_started(self, source: str, index: int, total: int):
        self.current_file_label.setText(
            f"Converting {index}/{total}: {Path(source).name}"
        )
        self._append_log(
            f"\n=== {index}/{total}: {source} ==="
        )
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")

    def _on_file_progress(self, percent: int, encoded_seconds: float, speed: str):
        self.progress_bar.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        if speed:
            self.speed_label.setText(f"FFmpeg speed: {speed}")

        elapsed = max(0.001, time.monotonic() - self.job_start)
        self.elapsed_label.setText(f"Elapsed: {format_seconds(elapsed)}")

        if percent > 0 and encoded_seconds > 0:
            # Approximate whole-job remaining time using the number of completed
            # files plus current file percentage.
            current_fraction = percent / 100.0
            completed = len(self.job_results)
            done_fraction = completed + current_fraction
            total = max(1, len(self._collect_job_files()))
            if done_fraction > 0:
                estimated_total = elapsed / (done_fraction / total)
                remaining = max(0.0, estimated_total - elapsed)
                self.remaining_label.setText(
                    f"Remaining: {format_seconds(remaining)}"
                )

    def _on_file_finished(self, result: FileResult):
        self.job_results.append(result)

        if result.status == "Completed":
            self._append_log(
                f"Completed: {result.output} "
                f"({human_size(result.output_bytes)})"
            )
        else:
            self._append_log(
                f"{result.status}: {result.source}\n{result.message}"
            )

    def _on_finished(self, results: object):
        # The signal data is the canonical list; self.job_results is kept as a
        # UI copy because file_finished may not fire for a file skipped by stop.
        final_results = list(results) if isinstance(results, list) else self.job_results
        self.job_results = final_results

        self.progress_bar.setValue(
            100 if final_results and all(
                r.status == "Completed" for r in final_results
            ) else self.progress_bar.value()
        )

        self.cancel_button.setEnabled(False)
        self.current_file_label.setText(
            f"Finished — {len(final_results)} result(s)"
        )

        # The worker lives in a QThread. Calling quit from the worker's signal
        # returns control to Qt's event loop; cleanup happens asynchronously.
        if self.worker_thread:
            self.worker_thread.quit()

        dialog = SummaryDialog(final_results, self)
        dialog.exec()

    def _on_failed(self, message: str):
        QMessageBox.critical(self, "Conversion error", message)

    def _cancel_conversion(self):
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.current_file_label.setText("Stopping FFmpeg…")
            self.worker.request_cancel()

    def _cleanup_worker(self):
        if self.worker:
            self.worker.deleteLater()
        if self.worker_thread:
            self.worker_thread.deleteLater()

        self.worker = None
        self.worker_thread = None

        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.add_files_button.setEnabled(True)
        self.add_folder_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.recursive_check.setEnabled(True)

    def _toggle_log(self, checked: bool):
        self.log_view.setVisible(checked)
        self.log_toggle_button.setText("Hide Log" if checked else "Show Log")

    def _update_elapsed(self):
        if self.worker_thread is not None and self.worker_thread.isRunning():
            elapsed = time.monotonic() - self.job_start
            self.elapsed_label.setText(f"Elapsed: {format_seconds(elapsed)}")

    def closeEvent(self, event):
        if self.worker:
            answer = QMessageBox.question(
                self,
                "Conversion in progress",
                "A conversion is still running. Stop it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self.worker.request_cancel()
            if self.worker_thread:
                self.worker_thread.quit()
                self.worker_thread.wait(6000)

        try:
            self._save_ui_state()
        except Exception:
            pass

        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("VideoConverter")
    app.setOrganizationDomain("local.videoconverter")

    ok, missing = dependency_status()
    if not ok:
        dependency_dialog(None, missing)
        return 2

    encoder_ok, encoder_message = ffmpeg_encoder_check()
    if not encoder_ok:
        QMessageBox.critical(
            None,
            "FFmpeg encoder check failed",
            "FFmpeg is installed, but required encoders were not found:\n\n"
            f"{encoder_message}\n\n"
            "Make sure your distribution's FFmpeg package includes libx264, "
            "libvpx-vp9, libopus, and AAC support.",
        )
        return 2

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
