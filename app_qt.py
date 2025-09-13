import sys
import os
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QTextEdit,
    QMenuBar,
    QStatusBar,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QDialogButtonBox,
    QProgressBar,
    QDockWidget,
)
from PySide6.QtGui import QFont, QTextCursor, QImage, QTextImageFormat, QTextDocument
from PySide6.QtCore import Qt, QTimer, QUrl, QThread, Signal, Slot, QObject
import queue
import re
from datetime import datetime
import time
import wave
import numpy as np
import pyaudio
import torch
import whisper


class RichTextEditor(QTextEdit):
    """
    QTextEdit-based editor with helper methods compatible with previous interface:
    - insertPlainText(text)
    - setText(text)
    - scrollToBottom()
    Includes simple image insertion helper.
    """

    def __init__(self, on_change=None, parent=None):
        super().__init__(parent)
        self.on_change = on_change
        if self.on_change:
            self.textChanged.connect(self.on_change)

        # Default font
        self.setFont(QFont("微软雅黑", 11))

        # Track embedded images: name -> {image: QImage, src: Optional[str]}
        self._image_counter = 0
        self._images = {}

    # Keep the method name identical to QTextEdit API
    def insertPlainText(self, text: str) -> None:  # type: ignore[override]
        super().insertPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.End)

    # Provide a convenience setText (QTextEdit has setPlainText)
    def setText(self, text: str) -> None:  # type: ignore[override]
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def scrollToBottom(self) -> None:
        self.moveCursor(QTextCursor.MoveOperation.End)
        bar = self.verticalScrollBar()
        if bar:
            bar.setValue(bar.maximum())

    # ---- Image helpers (basic) ----
    def insert_image_from_path(self, image_path: str) -> None:
        try:
            img = QImage(image_path)
            if img.isNull():
                QMessageBox.warning(self, "图片错误", f"无法加载图片: {os.path.basename(image_path)}")
                return
            # Register as resource with a unique name
            self._image_counter += 1
            name = f"image_{self._image_counter}"
            self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
            fmt = QTextImageFormat()
            fmt.setName(name)
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertImage(fmt)
            self.setTextCursor(cursor)
            self._images[name] = {"image": img, "src": image_path}
        except Exception as e:
            QMessageBox.critical(self, "插入图片失败", str(e))

    def export_markdown_with_images(self, attachments_dir: str) -> tuple[str, dict]:
        """
        Walk the document; output text as-is and replace inline images with Obsidian placeholders.
        Save images into attachments_dir with filename like "Pasted image <timestamp>.png".
        Returns (markdown_text, name_to_filename_map).
        """
        if not os.path.isdir(attachments_dir):
            os.makedirs(attachments_dir, exist_ok=True)

        parts: list[str] = []
        image_map: dict[str, str] = {}
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    if cf.isImageFormat():
                        img_fmt = QTextImageFormat(cf)
                        name = img_fmt.name()
                        meta = self._images.get(name)
                        if meta:
                            qimg: QImage = meta["image"]
                            # Build filename
                            timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]
                            filename = f"Pasted image {timestamp}.png"
                            out_path = os.path.join(attachments_dir, filename)
                            qimg.save(out_path, "PNG")
                            image_map[name] = filename
                            parts.append(f"![[{filename}]]")
                        else:
                            parts.append("[图片]")
                    else:
                        parts.append(frag.text())
                it += 1
            parts.append("\n")
            block = block.next()
        return ("".join(parts).strip(), image_map)

    def render_markdown_with_images(self, md_text: str, attachments_dir: str | None) -> None:
        """Parse Obsidian placeholders and reinsert images; other text is inserted as plain text."""
        self.clear()
        if not md_text:
            return
        pattern = re.compile(r"!\[\[(.*?)\]\]")
        last_end = 0
        for m in pattern.finditer(md_text):
            if last_end < m.start():
                self.insertPlainText(md_text[last_end:m.start()])
            filename = m.group(1)
            img_path = os.path.join(attachments_dir, filename) if attachments_dir else None
            if img_path and os.path.isfile(img_path):
                self.insert_image_from_path(img_path)
            else:
                # keep placeholder if not found
                self.insertPlainText(m.group(0))
            last_end = m.end()
        if last_end < len(md_text):
            self.insertPlainText(md_text[last_end:])


class TranscriptionAppQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时语音转写及总结工具 (Qt 版)")
        self.resize(1200, 700)

        # UI setup
        self.current_md_path: str | None = None
        self.attachments_dir: str | None = None
        self.selected_device_index: int | None = None
        self._setup_ui()

        # Transcription queue and timer
        self.transcription_queue: "queue.Queue[str]" = queue.Queue()
        self.transcription_timer = QTimer(self)
        self.transcription_timer.timeout.connect(self._flush_transcription_queue)
        self.transcription_timer.start(100)

        # Threads & workers (B3)
        self._rec_thread: QThread | None = None
        self._rec_worker: AudioRecorderWorker | None = None
        self._tr_thread: QThread | None = None
        self._tr_worker: TranscriberWorker | None = None

    # ---- UI ----
    def _setup_ui(self):
        # Menu bar
        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("文件(&F)")
        act_new = file_menu.addAction("新建(&N)")
        act_new.triggered.connect(self.file_new)
        act_open = file_menu.addAction("打开…(&O)")
        act_open.triggered.connect(self.file_open)
        file_menu.addSeparator()
        act_save = file_menu.addAction("保存(&S)")
        act_save.triggered.connect(self.file_save)
        act_save_as = file_menu.addAction("另存为…(&A)")
        act_save_as.triggered.connect(self.file_save_as)
        file_menu.addSeparator()
        act_exit = file_menu.addAction("退出(&X)")
        act_exit.triggered.connect(self.close)
        # Settings menu
        settings_menu = menubar.addMenu("设置(&S)")
        act_pick_device = settings_menu.addAction("选择输入设备…")
        act_pick_device.triggered.connect(self.choose_input_device)

        # Logs menu
        log_menu = menubar.addMenu("日志(&L)")
        act_show_log = log_menu.addAction("显示日志面板")
        act_show_log.triggered.connect(self.show_log_dock)
        act_clear_log = log_menu.addAction("清空日志")
        act_clear_log.triggered.connect(self.clear_log)
        act_save_log = log_menu.addAction("保存日志…")
        act_save_log.triggered.connect(self.save_log)
        self.setMenuBar(menubar)

        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # Top buttons
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("开始录制")
        self.btn_start.setToolTip("开始音频录制并实时转写")
        self.btn_start.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止录制")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self.btn_stop)

        self.btn_save = QPushButton("保存笔记")
        self.btn_save.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self.btn_save)

        self.btn_summary = QPushButton("手动总结")
        self.btn_summary.clicked.connect(self._on_summarize_clicked)
        btn_row.addWidget(self.btn_summary)

        btn_row.addStretch()

        self.btn_insert_image = QPushButton("插入图片到摘要…")
        self.btn_insert_image.clicked.connect(self._on_insert_image_clicked)
        btn_row.addWidget(self.btn_insert_image)

        root_layout.addLayout(btn_row)

        # Splitter with two editors
        splitter = QSplitter(Qt.Orientation.Vertical)
        root_layout.addWidget(splitter)

        # Summary panel
        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        lbl_summary = QLabel("笔记总结")
        lbl_summary.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        summary_layout.addWidget(lbl_summary)
        self.summary_area = RichTextEditor(on_change=self._on_editor_changed)
        self.summary_area.setFont(QFont("微软雅黑", 12))
        summary_layout.addWidget(self.summary_area)
        splitter.addWidget(summary_panel)

        # Transcription panel
        trans_panel = QWidget()
        trans_layout = QVBoxLayout(trans_panel)
        lbl_trans = QLabel("实时语音转文字")
        lbl_trans.setFont(QFont("微软雅黑", 10))
        trans_layout.addWidget(lbl_trans)
        self.transcription_area = RichTextEditor()
        self.transcription_area.setReadOnly(True)
        self.transcription_area.setFont(QFont("微软雅黑", 10))
        trans_layout.addWidget(self.transcription_area)
        splitter.addWidget(trans_panel)

        splitter.setSizes([450, 250])

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)
        # VU meter
        self.vu = QProgressBar()
        self.vu.setRange(0, 100)
        self.vu.setTextVisible(False)
        self.vu.setFixedWidth(160)
        self.statusBar().addPermanentWidget(QLabel("音量"))
        self.statusBar().addPermanentWidget(self.vu)

        # Log dock
        self.log_dock = QDockWidget("日志", self)
        self.log_dock.setObjectName("LogDock")
        self.log_view = QTextEdit(self.log_dock)
        self.log_view.setReadOnly(True)
        self.log_dock.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

    # ---- File operations ----
    def set_current_document(self, md_path: str) -> None:
        self.current_md_path = md_path
        base_dir = os.path.dirname(md_path)
        self.attachments_dir = os.path.join(base_dir, "attachments")
        os.makedirs(self.attachments_dir, exist_ok=True)
        self.status_label.setText(f"当前文档: {os.path.basename(md_path)}")

    def build_markdown(self) -> str:
        # Export summary with images
        summary_md, _ = self.summary_area.export_markdown_with_images(self.attachments_dir or os.getcwd())
        transcription_content = self.transcription_area.toPlainText().strip()
        markdown_content = f"# 笔记总结\n\n{summary_md}\n\n---\n\n# 原始语音转文字\n\n{transcription_content}"
        return markdown_content

    def file_new(self) -> None:
        # Clear editors and reset paths
        self.summary_area.clear()
        self.transcription_area.clear()
        self.current_md_path = None
        self.attachments_dir = None
        self.status_label.setText("新建文档")

    def file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 Markdown", os.getcwd(), "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            # Split sections
            summary_text = ""
            transcript_text = ""
            if "# 原始语音转文字" in data:
                parts = data.partition("# 原始语音转文字")
                summary_text = parts[0].strip()
                transcript_text = parts[2].strip()
                if summary_text.startswith("# 笔记总结"):
                    first_nl = summary_text.find('\n')
                    if first_nl != -1:
                        summary_text = summary_text[first_nl+1:].lstrip()
                summary_text = summary_text.replace('---', '').strip()
            else:
                summary_text = data.strip()

            self.set_current_document(path)
            # Render to editors
            self.summary_area.render_markdown_with_images(summary_text, self.attachments_dir)
            self.transcription_area.setText(transcript_text)
            self.transcription_area.scrollToBottom()
            self.status_label.setText(f"已打开: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))

    def file_save(self) -> None:
        if not self.current_md_path:
            self.file_save_as()
            return
        try:
            content = self.build_markdown()
            with open(self.current_md_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.status_label.setText(f"已保存: {os.path.basename(self.current_md_path)}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def file_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "另存为 Markdown", os.getcwd(), "Markdown (*.md)")
        if not path:
            return
        self.set_current_document(path)
        self.file_save()

    # ---- Slots / placeholders ----
    def _on_start_clicked(self):
        # Start recorder and transcriber threads
        if self._rec_thread or self._tr_thread:
            return
        # Ensure a document is targeted; if none, prompt Save As
        if not self.current_md_path:
            self.file_save_as()
        # Create transcriber first (loads Whisper)
        self._tr_thread = QThread(self)
        self._tr_worker = TranscriberWorker(model_size="large-v2")
        self._tr_worker.moveToThread(self._tr_thread)
        self._tr_thread.started.connect(self._tr_worker.start)
        self._tr_worker.textReady.connect(self.add_transcription_text)
        self._tr_worker.status.connect(self._set_status)
        self._tr_worker.finished.connect(self._tr_thread.quit)
        self._tr_worker.finished.connect(lambda: self._cleanup_tr())
        self._tr_thread.finished.connect(lambda: self._set_status("转写线程结束"))
        self._tr_thread.start()

        # Then recorder
        self._rec_thread = QThread(self)
        self._rec_worker = AudioRecorderWorker(device_index=self.selected_device_index)
        self._rec_worker.moveToThread(self._rec_thread)
        self._rec_thread.started.connect(self._rec_worker.start)
        self._rec_worker.segmentReady.connect(self._on_segment_ready)
        self._rec_worker.status.connect(self._set_status)
        self._rec_worker.peakLevel.connect(self._on_peak_level)
        self._rec_worker.finished.connect(self._rec_thread.quit)
        self._rec_worker.finished.connect(lambda: self._cleanup_rec())
        self._rec_thread.finished.connect(lambda: self._set_status("录音线程结束"))
        self._rec_thread.start()

        self.status_label.setText("正在录制...")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _on_stop_clicked(self):
        # Stop workers gracefully
        if self._rec_worker:
            self._rec_worker.stop()
        if self._tr_worker:
            self._tr_worker.stop()
        self.status_label.setText("正在停止...")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_save_clicked(self):
        # Use unified file_save logic
        self.file_save()

    def _on_summarize_clicked(self):
        # TODO: Plug in LLM summarization logic
        QMessageBox.information(self, "手动总结", "尚未接入总结逻辑。")

    def _on_insert_image_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", os.getcwd(), "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if path:
            self.summary_area.insert_image_from_path(path)

    def _on_editor_changed(self):
        # TODO: debounce + autosave logic
        pass

    # ---- Transcription queue API (B1) ----
    def add_transcription_text(self, text: str) -> None:
        """Thread-safe: producers call this to enqueue transcribed text."""
        if not text:
            return
        try:
            self.transcription_queue.put_nowait(text)
        except Exception:
            # As a fallback, append immediately on UI thread
            self.transcription_area.insertPlainText(text + " ")
            self.transcription_area.scrollToBottom()

    def _flush_transcription_queue(self) -> None:
        """Drain the queue and append to the transcription area efficiently."""
        if self.transcription_queue.empty():
            return
        chunk_list = []
        try:
            while not self.transcription_queue.empty():
                chunk_list.append(self.transcription_queue.get_nowait())
        except Exception:
            pass
        if not chunk_list:
            return
        full_text_chunk = " ".join(chunk_list) + " "
        # Append and auto-scroll
        self.transcription_area.insertPlainText(full_text_chunk)
        self.transcription_area.scrollToBottom()

    # ---- Status helper ----
    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.log(msg)

    # ---- Cleanup helpers ----
    def _cleanup_rec(self):
        self._rec_worker = None
        self._rec_thread = None

    def _cleanup_tr(self):
        self._tr_worker = None
        self._tr_thread = None

    # ---- Close handling ----
    def closeEvent(self, event):
        # Attempt to stop threads
        try:
            if self._rec_worker:
                self._rec_worker.stop()
            if self._tr_worker:
                self._tr_worker.stop()
        except Exception:
            pass
        super().closeEvent(event)

    # ---- Logs ----
    def show_log_dock(self):
        self.log_dock.show()

    def clear_log(self):
        self.log_view.clear()

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", os.getcwd(), "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_view.toPlainText())
            self._set_status(f"日志已保存: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def log(self, message: str):
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{ts}] {message}")

    @Slot(str)
    def _on_segment_ready(self, filepath: str):
        self.log(f"已入队: {os.path.basename(filepath)}")
        try:
            self._tr_worker.enqueue_file(filepath)
        except Exception as e:
            self.log(f"入队失败: {e}")

    # ---- VU meter ----
    @Slot(float)
    def _on_peak_level(self, peak: float):
        # peak in 0..1, map to 0..100
        val = max(0, min(100, int(peak * 100)))
        self.vu.setValue(val)

    # ---- Device selection ----
    def choose_input_device(self):
        dlg = DeviceLevelDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            idx = dlg.selected_device_index()
            label = dlg.selected_device_label()
            if idx is not None:
                self.selected_device_index = idx
                self.status_label.setText(f"已选择设备: {label}")


# ===== Device level monitor dialog =====
class DeviceMonitorWorker(QObject):
    levelUpdated = Signal(int, float)  # (device_index, peak[0..1])
    listReady = Signal(list)           # list of tuples (index, label)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self._stop = False
        self._indices: list[int] = []

    @Slot()
    def start(self):
        try:
            try:
                p = pyaudio.PyAudio()
            except Exception:
                self.listReady.emit([])
                self.finished.emit()
                return
            items = []
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", f"设备{i}")
                    rate = int(info.get("defaultSampleRate", 0))
                    items.append((i, f"[{i}] {name}  ch={info.get('maxInputChannels',0)}  {rate}Hz"))
            self._indices = [i for i, _ in items]
            self.listReady.emit(items)
            # Poll levels in a loop
            while not self._stop:
                for idx in list(self._indices):
                    peak = 0.0
                    stream = None
                    try:
                        info = p.get_device_info_by_index(idx)
                        use_rate = int(info.get("defaultSampleRate", RATE)) or RATE
                        use_channels = min(max(1, int(info.get("maxInputChannels", 1))), CHANNELS) or 1
                        stream = p.open(format=FORMAT, channels=use_channels, rate=use_rate, input=True,
                                        frames_per_buffer=CHUNK, input_device_index=idx)
                        data = stream.read(CHUNK, exception_on_overflow=False)
                        audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        if audio_np.size:
                            peak = float(np.max(np.abs(audio_np)))
                    except Exception:
                        peak = 0.0
                    finally:
                        try:
                            if stream:
                                stream.stop_stream(); stream.close()
                        except Exception:
                            pass
                    self.levelUpdated.emit(idx, peak)
                    if self._stop:
                        break
                # small rest to avoid hammering the system
                time.sleep(0.3)
        finally:
            try:
                p.terminate()
            except Exception:
                pass
            self.finished.emit()

    def stop(self):
        self._stop = True


class DeviceLevelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择输入设备（含电平）")
        self.resize(560, 480)
        self._selected_idx: int | None = None
        self._selected_label: str | None = None
        self._bars: dict[int, QProgressBar] = {}
        self._labels: dict[int, str] = {}

        v = QVBoxLayout(self)
        self.lst = QListWidget(self)
        v.addWidget(self.lst)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(self.bb)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)

        # Thread setup
        self._thr = QThread(self)
        self._worker = DeviceMonitorWorker()
        self._worker.moveToThread(self._thr)
        self._thr.started.connect(self._worker.start)
        self._worker.listReady.connect(self._on_list_ready)
        self._worker.levelUpdated.connect(self._on_level_update)
        self._worker.finished.connect(self._thr.quit)
        self._thr.start()

    def _on_list_ready(self, items: list):
        self.lst.clear()
        for idx, label in items:
            item = QListWidgetItem()
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 4, 8, 4)
            lab = QLabel(label)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedWidth(160)
            h.addWidget(lab)
            h.addStretch(1)
            h.addWidget(bar)
            item.setSizeHint(w.sizeHint())
            self.lst.addItem(item)
            self.lst.setItemWidget(item, w)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self._bars[idx] = bar
            self._labels[idx] = label

    @Slot(int, float)
    def _on_level_update(self, idx: int, peak: float):
        bar = self._bars.get(idx)
        if bar:
            val = max(0, min(100, int(peak * 100)))
            bar.setValue(val)

    def accept(self):
        it = self.lst.currentItem()
        if it is not None:
            idx = int(it.data(Qt.ItemDataRole.UserRole))
            self._selected_idx = idx
            self._selected_label = self._labels.get(idx)
        # stop worker before closing dialog to avoid resource contention/crash
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().accept()

    def reject(self):
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().reject()

    def selected_device_index(self) -> int | None:
        return self._selected_idx

    def selected_device_label(self) -> str | None:
        return self._selected_label

    def closeEvent(self, e):
        try:
            self._worker.stop()
        except Exception:
            pass
        try:
            self._thr.quit()
            self._thr.wait(2000)
        except Exception:
            pass
        super().closeEvent(e)


# ====== B3 Workers ======

# Audio capture parameters (aligned with original app)
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
DEVICE_INDEX_KEYWORD = "CABLE Output"  # If not found, will fall back to default input device
OUTPUT_DIR = "recorded_audio_segments"
SILENCE_THRESHOLD = 0.001  # lower threshold to detect quieter inputs
SILENCE_SECONDS = 1.5
MAX_RECORD_SECONDS = 30


class AudioRecorderWorker(QObject):
    segmentReady = Signal(str)  # filepath
    status = Signal(str)
    peakLevel = Signal(float)   # 0..1 peak for UI VU meter
    finished = Signal()

    def __init__(self, device_index: int | None = None):
        super().__init__()
        self._stop = False
        self._device_index = device_index

    @Slot()
    def start(self):
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            p = pyaudio.PyAudio()
            device_index = self._device_index if self._device_index is not None else self._find_device_index(p, DEVICE_INDEX_KEYWORD)
            if device_index is None:
                # Fallback to default input device
                try:
                    def_dev = p.get_default_input_device_info()
                    device_index = int(def_dev.get('index', 0))
                    self.status.emit(f"使用默认输入设备: {def_dev.get('name', '未知设备')}")
                except Exception:
                    self.status.emit(f"未找到音频输入设备: 关键字 '{DEVICE_INDEX_KEYWORD}'，且无默认输入设备")
                    self.finished.emit()
                    return
            dev_info = p.get_device_info_by_index(device_index)
            dev_name = dev_info.get("name", "未知设备")
            # Prefer device default sample rate to avoid incompatibilities
            use_rate = int(dev_info.get("defaultSampleRate", RATE)) or RATE
            use_channels = min(max(1, int(dev_info.get("maxInputChannels", 1))), CHANNELS) or 1
            self.status.emit(f"准备监听设备: {dev_name} (index={device_index}, rate={use_rate})")
            stream = p.open(format=FORMAT, channels=use_channels, rate=use_rate, input=True,
                            frames_per_buffer=CHUNK, input_device_index=device_index)
            frames = []
            silence_frames = 0
            is_recording_segment = False
            tick = 0
            while not self._stop:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                peak = float(np.max(np.abs(audio_np))) if audio_np.size else 0.0
                is_silent = peak < SILENCE_THRESHOLD
                # Debug status every ~1s
                tick += 1
                if (tick % max(1, int(use_rate / CHUNK))) == 0:
                    self.status.emit(f"录音中 峰值={peak:.4f} 阈值={SILENCE_THRESHOLD:.4f}")
                # Emit VU level frequently
                try:
                    self.peakLevel.emit(peak)
                except Exception:
                    pass
                if is_silent:
                    if is_recording_segment:
                        silence_frames += 1
                    if is_recording_segment and silence_frames >= int(SILENCE_SECONDS * use_rate / CHUNK) and len(frames) > 0:
                        filename = os.path.join(OUTPUT_DIR, f"segment_{int(time.time())}.wav")
                        with wave.open(filename, "wb") as wf:
                            wf.setnchannels(CHANNELS)
                            wf.setsampwidth(p.get_sample_size(FORMAT))
                            wf.setframerate(use_rate)
                            wf.writeframes(b"".join(frames))
                        self.segmentReady.emit(filename)
                        frames = []
                        is_recording_segment = False
                        silence_frames = 0
                else:
                    is_recording_segment = True
                    silence_frames = 0
                    frames.append(data)
                if len(frames) >= int(MAX_RECORD_SECONDS * use_rate / CHUNK):
                    filename = os.path.join(OUTPUT_DIR, f"segment_force_{int(time.time())}.wav")
                    with wave.open(filename, "wb") as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(use_rate)
                        wf.writeframes(b"".join(frames))
                    self.segmentReady.emit(filename)
                    frames = []
                    is_recording_segment = False
                    silence_frames = 0
        except Exception as e:
            self.status.emit(f"录音错误: {e}")
        finally:
            try:
                stream.stop_stream(); stream.close()
            except Exception:
                pass
            try:
                p.terminate()
            except Exception:
                pass
            self.finished.emit()

    def stop(self):
        self._stop = True

    def _find_device_index(self, p: pyaudio.PyAudio, keyword: str):
        for i in range(p.get_device_count()):
            dev_info = p.get_device_info_by_index(i)
            if keyword.lower() in dev_info.get("name", "").lower() and dev_info.get("maxInputChannels", 0) > 0:
                return i
        return None


class TranscriberWorker(QObject):
    textReady = Signal(str)
    status = Signal(str)
    finished = Signal()

    def __init__(self, model_size: str = "small", language_setting: str = "auto"):
        super().__init__()
        self._stop = False
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._model = None
        self._model_size = model_size
        self._language_setting = language_setting

    @Slot()
    def start(self):
        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.status.emit(f"正在加载 Whisper 模型: {self._model_size} ({device}) ...")
            self._model = whisper.load_model(self._model_size, device=device)
            self.status.emit("模型加载完成。等待音频...")
            while not self._stop:
                try:
                    filepath = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not filepath:
                    continue
                try:
                    self.status.emit(f"开始转写: {os.path.basename(filepath)}")
                    language = None if self._language_setting == "auto" else self._language_setting
                    result = self._model.transcribe(
                        filepath,
                        language=language,
                        fp16=torch.cuda.is_available(),
                        task="transcribe",
                    )
                    text = result.get("text", "").strip()
                    if text:
                        self.textReady.emit(text)
                        self.status.emit(f"完成转写: {len(text)} 字符")
                    else:
                        self.status.emit("转写结果为空")
                except Exception as e:
                    self.status.emit(f"转写错误: {e}")
        except Exception as e:
            self.status.emit(f"模型加载失败: {e}")
        finally:
            self.finished.emit()

    @Slot(str)
    def enqueue_file(self, filepath: str):
        try:
            self._queue.put_nowait(filepath)
            self.status.emit(f"已入队: {os.path.basename(filepath)}")
        except Exception:
            pass

    def stop(self):
        self._stop = True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TranscriptionAppQt()
    win.show()
    sys.exit(app.exec())
