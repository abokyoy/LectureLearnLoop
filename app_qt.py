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
    QLineEdit,
    QComboBox,
    QSpinBox,
    QFormLayout,
    QGroupBox,
    QRadioButton,
    QTextBrowser,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtGui import (
    QFont, QTextCursor, QImage, QTextImageFormat, QTextDocument, QColor,
    QTextCharFormat, QPalette, QPixmap, QPainter, QPen, QBrush, QAction,
    QSyntaxHighlighter
)
from PySide6.QtCore import Qt, QTimer, QUrl, QThread, Signal, Slot, QObject, QRect, QPoint, QByteArray, QRegularExpression

import queue
import re
from datetime import datetime
import time
import wave
import numpy as np
import pyaudio
import torch
import whisper
from config import load_config, save_config, SUMMARY_PROMPT
import requests
from practice_panel import PracticePanel

try:
    import markdown  # pip install markdown
except Exception:
    markdown = None

class RichTextEditor(QTextEdit):
    """
    QTextEdit-based editor with helper methods compatible with previous interface:
    - insertPlainText(text)
    - setText(text)
    - scrollToBottom()
    Includes simple image insertion helper.
    """

    def __init__(self, on_change=None, parent=None, enable_image_context: bool = False):
        super().__init__(parent)
        self.on_change = on_change
        if self.on_change:
            self.textChanged.connect(self.on_change)

        # Default font
        self.setFont(QFont("微软雅黑", 11))

        # Track embedded images: name -> {image: QImage, src: Optional[str]}
        self._image_counter = 0
        self._images = {}
        self._enable_image_context = enable_image_context

        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.document().setDocumentMargin(4)    

        # Add logging method for debugging
        self.log = lambda msg: self.parent().log(msg) if self.parent() and hasattr(self.parent(), 'log') else print(msg)

    def _highlight_with_html(self, ranges: list[tuple[int, int]], color_name: str):
        """
        Apply HTML highlighting to multiple ranges, preserving all highlights.
        ranges: List of (start, length) tuples.
        color_name: CSS color name (e.g., "green").
        """
        full_text = self.toPlainText()
        self.log(f"[DEBUG] Applying HTML highlights: ranges={ranges}, color={color_name}, text_length={len(full_text)}")
        
        # Sort ranges by start position to avoid overlap issues
        ranges = sorted(ranges, key=lambda x: x[0])
        # Validate and adjust ranges
        valid_ranges = []
        for start, length in ranges:
            if start < 0 or length <= 0 or start >= len(full_text):
                self.log(f"[DEBUG] Skipping invalid range: start={start}, length={length}")
                continue
            if start + length > len(full_text):
                length = len(full_text) - start
            valid_ranges.append((start, length))
        
        if not valid_ranges:
            self.log("[DEBUG] No valid ranges to highlight")
            return
        
        # Build HTML by splitting text and inserting <span> tags
        html_parts = []
        last_end = 0
        for start, length in valid_ranges:
            if start < last_end:
                self.log(f"[DEBUG] Overlapping range skipped: start={start}, length={length}")
                continue  # Skip overlapping ranges
            html_parts.append(full_text[last_end:start])  # Unhighlighted text
            selected = full_text[start:start + length]
            html_parts.append(f'<span style="color:{color_name}">{selected}</span>')
            last_end = start + length
        html_parts.append(full_text[last_end:])  # Text after last highlight
        
        new_html = "".join(html_parts)
        self.log(f"[DEBUG] Setting HTML: {new_html[:100]}...")  # Log first 100 chars for brevity
        self.setHtml(new_html)
        self.update()
        self.repaint()

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

    # ---- Formatting helpers ----
    def text_length(self) -> int:
        return len(self.toPlainText())

    def selection_range(self) -> tuple[int, int]:
        """Return (start, length) of current selection; if none, (pos, 0)."""
        c = self.textCursor()
        self.log(f"[DEBUG] selection_range: position={c.position()}, selectionStart={c.selectionStart()}, selectionEnd={c.selectionEnd()}")
        if not c.hasSelection():
            return (c.position(), 0)
        start = min(c.selectionStart(), c.selectionEnd())
        end = max(c.selectionStart(), c.selectionEnd())
        return (start, max(0, end - start))

    def selected_text(self) -> str:
        return self.textCursor().selectedText()

    def apply_color(self, start: int, length: int, color: QColor) -> None:
        self.log(f"[DEBUG] apply_color: start={start}, length={length}, color={color.name()}")
        if length <= 0:
            self.log("[DEBUG] length <=0, skipping")
            return
        c = self.textCursor()
        self.log(f"[DEBUG] Cursor before: position={c.position()}, hasSelection={c.hasSelection()}")
        c.beginEditBlock()
        # Apply color to the exact range
        c.setPosition(start)
        c.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self.log(f"[DEBUG] Selection set: start={c.selectionStart()}, end={c.selectionEnd()}")
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self.log(f"[DEBUG] Format created: foreground={fmt.foreground().color().name()}")
        c.mergeCharFormat(fmt)
        self.log("[DEBUG] mergeCharFormat called")
        # Reset format at the end position so subsequent inserted text is default (black)
        default_color = self.palette().color(QPalette.ColorRole.Text)
        self.log(f"[DEBUG] Default color: {default_color.name()}")
        reset_fmt = QTextCharFormat()
        reset_fmt.setForeground(default_color)
        c.clearSelection()
        c.setPosition(start + length)
        c.setCharFormat(reset_fmt)
        self.log("[DEBUG] Reset char format applied")
        c.endEditBlock()
        # Also reset the widget's current format to default to avoid carry-over
        self.reset_current_format_to_default()
        self.log("[DEBUG] apply_color completed, forcing update")
        self.update()
        self.repaint()

    def reset_current_format_to_default(self) -> None:
        default_color = self.palette().color(QPalette.ColorRole.Text)
        fmt = QTextCharFormat()
        fmt.setForeground(default_color)
        self.setCurrentCharFormat(fmt)

    # ---- Image helpers (basic) ----
    def insert_image_from_path(self, image_path: str) -> None:
        try:
            img = QImage(image_path)
            if img.isNull():
                QMessageBox.warning(self, "图片错误", f"无法加载图片: {os.path.basename(image_path)}")
                return
            
            # Scale image to fit editor width while preserving aspect ratio
            max_width = self.viewport().width() - 10  # Account for margins/padding
            if img.width() > max_width:
                img = img.scaled(
                    max_width,
                    img.height() * max_width // img.width(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            
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

    def insert_image_from_qimage(self, qimg: QImage) -> None:
        try:
            if qimg.isNull():
                QMessageBox.warning(self, "图片错误", "无法插入空图片")
                return
            
            # Scale image to fit editor width while preserving aspect ratio
            max_width = self.viewport().width() - 10  # Account for margins/padding
            if qimg.width() > max_width:
                qimg = qimg.scaled(
                    max_width,
                    qimg.height() * max_width // qimg.width(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            # Register as resource with a unique name
            self._image_counter += 1
            name = f"image_{self._image_counter}"
            self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), qimg)
            fmt = QTextImageFormat()
            fmt.setName(name)
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertImage(fmt)
            self.setTextCursor(cursor)
            self._images[name] = {"image": qimg, "src": None}
        except Exception as e:
            QMessageBox.critical(self, "插入图片失败", str(e))

    def contextMenuEvent(self, event):
        self.log("[右键菜单] 用户右键点击了文本编辑器")
        menu = self.createStandardContextMenu()
        
        # Add deep learning option if text is selected
        cursor = self.textCursor()
        has_selection = cursor.hasSelection()
        self.log(f"[右键菜单] 是否有选中文本: {has_selection}")
        
        if has_selection:
            selected_text = cursor.selectedText()
            self.log(f"[右键菜单] 选中文本长度: {len(selected_text)}")
            menu.addSeparator()
            deep_learn_action = QAction("继续深入学习", self)
            deep_learn_action.triggered.connect(self._on_deep_learning_requested)
            menu.addAction(deep_learn_action)
            
            practice_action = QAction("开启练习", self)
            practice_action.triggered.connect(self._on_practice_requested)
            menu.addAction(practice_action)
            
            knowledge_action = QAction("知识点提取", self)
            knowledge_action.triggered.connect(self._on_knowledge_extraction_requested)
            menu.addAction(knowledge_action)
            self.log("[右键菜单] 已添加'继续深入学习'、'开启练习'和'知识点提取'菜单项")
        else:
            self.log("[右键菜单] 没有选中文本，不显示'继续深入学习'选项")
        
        if self._enable_image_context:
            menu.addSeparator()
            act = QAction("插入本地图片到摘要…", self)
            def _pick_and_insert():
                path, _ = QFileDialog.getOpenFileName(self, "选择图片", os.getcwd(), "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
                if path:
                    self.insert_image_from_path(path)
            act.triggered.connect(_pick_and_insert)
            menu.addAction(act)
            self.log("[右键菜单] 已添加'插入本地图片'菜单项")
        
        self.log("[右键菜单] 显示右键菜单")
        menu.exec(event.globalPos())
    
    def _on_deep_learning_requested(self):
        """Handle deep learning request for selected text"""
        self.log("[深入学习] 用户点击了'继续深入学习'菜单项")
        
        selected_text = self.textCursor().selectedText()
        self.log(f"[深入学习] 选中的文本长度: {len(selected_text)}")
        self.log(f"[深入学习] 选中的文本内容: {selected_text[:100]}..." if len(selected_text) > 100 else f"[深入学习] 选中的文本内容: {selected_text}")
        
        if not selected_text.strip():
            self.log("[深入学习] 错误: 没有选中任何文本")
            return
            
        # Find the main application window by traversing up the widget hierarchy
        main_window = self._find_main_window()
        self.log(f"[深入学习] 找到的主窗口类型: {type(main_window).__name__ if main_window else 'None'}")
        
        if not main_window or not hasattr(main_window, 'open_chatbot_panel'):
            self.log("[深入学习] 错误: 无法找到具有 open_chatbot_panel 方法的主窗口")
            return
            
        # Get cursor position to know where to insert summary later
        cursor = self.textCursor()
        cursor_position = cursor.position()
        self.log(f"[深入学习] 光标位置: {cursor_position}")
        
        try:
            self.log("[深入学习] 正在调用主窗口的 open_chatbot_panel 方法...")
            main_window.open_chatbot_panel(selected_text, cursor_position)
            self.log("[深入学习] 已成功打开聊天机器人面板")
        except Exception as e:
            self.log(f"[深入学习] 调用 open_chatbot_panel 时发生错误: {e}")
            import traceback
            self.log(f"[深入学习] 错误堆栈: {traceback.format_exc()}")
    
    def _on_practice_requested(self):
        """Handle practice request for selected text"""
        self.log("[练习模式] 用户点击了'开启练习'菜单项")
        
        selected_text = self.textCursor().selectedText()
        self.log(f"[练习模式] 选中的文本长度: {len(selected_text)}")
        
        if not selected_text.strip():
            self.log("[练习模式] 错误: 没有选中任何文本")
            return
            
        # Find the main application window
        main_window = self._find_main_window()
        self.log(f"[练习模式] 找到的主窗口类型: {type(main_window).__name__ if main_window else 'None'}")
        
        if not main_window or not hasattr(main_window, 'open_practice_panel'):
            self.log("[练习模式] 错误: 无法找到具有 open_practice_panel 方法的主窗口")
            return
            
        cursor_position = self.textCursor().position()
        self.log(f"[练习模式] 光标位置: {cursor_position}")
        
        try:
            self.log("[练习模式] 正在调用主窗口的 open_practice_panel 方法...")
            main_window.open_practice_panel(selected_text, cursor_position)
            self.log("[练习模式] 已成功打开练习面板")
        except Exception as e:
            self.log(f"[练习模式] 调用 open_practice_panel 时发生错误: {e}")
            import traceback
            self.log(f"[练习模式] 错误堆栈: {traceback.format_exc()}")
    
    def _on_knowledge_extraction_requested(self):
        """Handle knowledge point extraction request for selected text"""
        self.log("[知识点提取] 用户点击了'知识点提取'菜单项")
        
        selected_text = self.textCursor().selectedText()
        self.log(f"[知识点提取] 选中的文本长度: {len(selected_text)}")
        
        if not selected_text.strip():
            self.log("[知识点提取] 错误: 没有选中任何文本")
            return
            
        # Find the main application window
        main_window = self._find_main_window()
        self.log(f"[知识点提取] 找到的主窗口类型: {type(main_window).__name__ if main_window else 'None'}")
        
        if not main_window or not hasattr(main_window, 'open_knowledge_extraction_panel'):
            self.log("[知识点提取] 错误: 无法找到具有 open_knowledge_extraction_panel 方法的主窗口")
            return
            
        try:
            self.log("[知识点提取] 正在调用主窗口的 open_knowledge_extraction_panel 方法...")
            main_window.open_knowledge_extraction_panel(selected_text)
            self.log("[知识点提取] 已成功打开知识点提取面板")
        except Exception as e:
            self.log(f"[知识点提取] 调用 open_knowledge_extraction_panel 时发生错误: {e}")
            import traceback
            self.log(f"[知识点提取] 错误堆栈: {traceback.format_exc()}")
    
    def _find_main_window(self):
        """Find the main application window by traversing up the widget hierarchy"""
        widget = self
        while widget:
            self.log(f"[深入学习] 检查widget: {type(widget).__name__}")
            if hasattr(widget, 'open_chatbot_panel'):
                self.log(f"[深入学习] 找到具有 open_chatbot_panel 方法的widget: {type(widget).__name__}")
                return widget
            widget = widget.parent()
        self.log("[深入学习] 未找到具有 open_chatbot_panel 方法的widget")
        return None

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


class MarkdownHighlighter(QSyntaxHighlighter):
    """Lightweight Markdown syntax highlighter for QTextDocument."""
    def __init__(self, parent):
        super().__init__(parent)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Headings
        for level, size, weight in (
            (1, 18, QFont.Weight.Bold),
            (2, 16, QFont.Weight.DemiBold),
            (3, 14, QFont.Weight.DemiBold),
            (4, 13, QFont.Weight.Normal),
        ):
            fmt = QTextCharFormat()
            fmt.setFontWeight(weight)
            fmt.setForeground(QColor("#2b6cb0"))
            pattern = QRegularExpression(r"^\s{0,3}" + ("#" * level) + r"\s.*$")
            self._rules.append((pattern, fmt))

        # Bold **text**
        fmt_b = QTextCharFormat(); fmt_b.setFontWeight(QFont.Weight.Bold)
        self._rules.append((QRegularExpression(r"\*\*[^\n]+?\*\*"), fmt_b))
        # Italic *text*
        fmt_i = QTextCharFormat(); fmt_i.setFontItalic(True)
        self._rules.append((QRegularExpression(r"(?<!\*)\*[^\n]+?\*(?!\*)"), fmt_i))
        # Inline code `code`
        fmt_code = QTextCharFormat(); fmt_code.setForeground(QColor("#d19a66"))
        fmt_code.setFont(QFont("Consolas", 10))
        self._rules.append((QRegularExpression(r"`[^\n`]+`"), fmt_code))
        # Code block ```
        self._codeblock_start = QRegularExpression(r"^\s*```.*$")
        self._codeblock_end = QRegularExpression(r"^\s*```\s*$")
        self._codeblock_fmt = QTextCharFormat(); self._codeblock_fmt.setForeground(QColor("#a371f7"))
        self._codeblock_fmt.setFont(QFont("Consolas", 10))
        # Blockquote
        fmt_q = QTextCharFormat(); fmt_q.setForeground(QColor("#6a737d"))
        self._rules.append((QRegularExpression(r"^\s*>.*$"), fmt_q))
        # Lists - / * / + / 1.
        fmt_list = QTextCharFormat(); fmt_list.setForeground(QColor("#2f855a"))
        self._rules.append((QRegularExpression(r"^\s*([-*+]\s+).*$"), fmt_list))
        self._rules.append((QRegularExpression(r"^\s*(\d+)\.(\s+).*$"), fmt_list))
        # Links [text](url)
        fmt_link = QTextCharFormat(); fmt_link.setForeground(QColor("#0366d6"))
        self._rules.append((QRegularExpression(r"\[[^\]]+\]\([^\)]+\)"), fmt_link))
        # HR ---
        fmt_hr = QTextCharFormat(); fmt_hr.setForeground(QColor("#999"))
        self._rules.append((QRegularExpression(r"^\s*([-*_]){3,}\s*$"), fmt_hr))

    def highlightBlock(self, text: str) -> None:
        # Code block handling (multi-line)
        in_block = (self.previousBlockState() == 1)
        if in_block:
            self.setFormat(0, len(text), self._codeblock_fmt)
            if self._codeblock_end.match(text).hasMatch():
                self.setCurrentBlockState(0)
            else:
                self.setCurrentBlockState(1)
            return
        else:
            if self._codeblock_start.match(text).hasMatch():
                self.setFormat(0, len(text), self._codeblock_fmt)
                self.setCurrentBlockState(1)
                return
            self.setCurrentBlockState(0)

        # Single-line rules
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class ChatbotPanel(QDialog):
    """Chatbot panel for deep learning conversations"""
    
    def __init__(self, selected_text: str, insert_position: int, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI深入学习助手")
        self.resize(900, 700)
        self.selected_text = selected_text
        self.insert_position = insert_position
        self.config = config
        self.conversation_history = []
        self.conversation_id = self._generate_conversation_id()
        
        # Setup UI
        self._setup_ui()
        
        # Initialize message widgets list
        self._message_widgets = []
        
        # Only start initial conversation if not loading from history
        self._loading_from_history = False
        if not self._loading_from_history:
            self._start_initial_conversation()
    
    def _generate_conversation_id(self):
        """Generate unique conversation ID"""
        from datetime import datetime
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def resizeEvent(self, event):
        """Handle window resize to update message widths"""
        super().resizeEvent(event)
        # Update all message dimensions when window is resized
        if hasattr(self, '_message_widgets'):
            for message_widget, browser in self._message_widgets:
                if message_widget and browser:
                    QTimer.singleShot(10, lambda w=message_widget, b=browser: self._set_message_dimensions(w, b))
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar with history and controls
        toolbar_layout = QHBoxLayout()
        
        self.history_button = QPushButton("历史对话")
        self.history_button.clicked.connect(self._show_history)
        toolbar_layout.addWidget(self.history_button)
        
        self.new_chat_button = QPushButton("新对话")
        self.new_chat_button.clicked.connect(self._start_new_conversation)
        toolbar_layout.addWidget(self.new_chat_button)
        
        toolbar_layout.addStretch()
        
        self.conversation_label = QLabel(f"对话ID: {self.conversation_id}")
        self.conversation_label.setStyleSheet("color: #666; font-size: 10px;")
        toolbar_layout.addWidget(self.conversation_label)
        
        layout.addLayout(toolbar_layout)
        
        # Chat area (now takes full space)
        chat_group = QGroupBox("AI深入学习对话")
        chat_layout = QVBoxLayout(chat_group)
        
        # Scrollable chat area
        self.chat_scroll = QScrollArea()
        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_scroll.setWidget(self.chat_widget)
        self.chat_scroll.setWidgetResizable(True)
        chat_layout.addWidget(self.chat_scroll)
        
        # Input area
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入您的问题...")
        self.input_field.returnPressed.connect(self._send_message)
        
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send_message)
        
        self.summary_button = QPushButton("总结对话")
        self.summary_button.clicked.connect(self._summarize_conversation)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.summary_button)
        
        chat_layout.addLayout(input_layout)
        layout.addWidget(chat_group)
        
        # Bottom buttons
        bottom_layout = QHBoxLayout()
        
        save_button = QPushButton("保存对话")
        save_button.clicked.connect(self._save_conversation)
        bottom_layout.addWidget(save_button)
        
        bottom_layout.addStretch()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        bottom_layout.addWidget(close_button)
        
        layout.addLayout(bottom_layout)
    
    def _save_conversation(self):
        """Save conversation to history file"""
        if not self.conversation_history:
            return
            
        try:
            import os
            import json
            from datetime import datetime
            
            # Create conversations directory if it doesn't exist
            conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
            os.makedirs(conversations_dir, exist_ok=True)
            
            # Save conversation data
            conversation_data = {
                "id": self.conversation_id,
                "timestamp": datetime.now().isoformat(),
                "selected_text": self.selected_text,
                "conversation_history": self.conversation_history
            }
            
            filename = f"conversation_{self.conversation_id}.json"
            filepath = os.path.join(conversations_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(conversation_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"保存对话失败: {e}")
    
    def _show_history(self):
        """Show conversation history dialog"""
        dialog = ConversationHistoryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_conversation = dialog.get_selected_conversation()
            if selected_conversation:
                self._load_conversation(selected_conversation)
    
    def _load_conversation(self, conversation_data):
        """Load a conversation from history"""
        self._loading_from_history = True
        self.conversation_history = conversation_data.get("conversation_history", [])
        self.selected_text = conversation_data.get("selected_text", "")
        self.conversation_id = conversation_data.get("id", self._generate_conversation_id())
        
        # Update UI
        self.conversation_label.setText(f"对话ID: {self.conversation_id}")
        
        # Clear and reload chat display
        for i in reversed(range(self.chat_layout.count())):
            self.chat_layout.itemAt(i).widget().setParent(None)
        
        # Redisplay all messages
        for msg in self.conversation_history:
            if msg["role"] == "user":
                self._add_message("用户", msg["content"], True)
            else:
                self._add_message("AI助手", msg["content"], False)
    
    def _start_new_conversation(self):
        """Start a new conversation"""
        # Save current conversation if it has content
        if self.conversation_history:
            self._save_conversation()
        
        # Reset conversation state
        self.conversation_history = []
        self.conversation_id = self._generate_conversation_id()
        self.conversation_label.setText(f"对话ID: {self.conversation_id}")
        
        # Clear chat display
        for i in reversed(range(self.chat_layout.count())):
            self.chat_layout.itemAt(i).widget().setParent(None)
        
        # Start new conversation with selected text
        if self.selected_text.strip():
            self._start_initial_conversation()
    
    def _render_message_markdown(self, browser: QTextBrowser, md_text: str):
        """Render markdown text in a QTextBrowser widget"""
        try:
            import markdown
        except ImportError:
            # Fallback to plain text if markdown not available
            browser.setPlainText(md_text)
            return
        
        try:
            # Convert markdown to HTML
            html = markdown.markdown(md_text or "", extensions=["fenced_code", "tables", "nl2br"])
            
            # Add CSS styling to match the app theme
            styled_html = f"""
            <style>
                body {{
                    font-family: '微软雅黑', sans-serif;
                    font-size: 12px;
                    line-height: 1.6;
                    color: #333;
                    margin: 8px;
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: #2c3e50;
                    margin-top: 1em;
                    margin-bottom: 0.5em;
                }}
                code {{
                    background-color: #f4f4f4;
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-family: 'Consolas', 'Monaco', monospace;
                }}
                pre {{
                    background-color: #f8f8f8;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    padding: 10px;
                    overflow-x: auto;
                }}
                blockquote {{
                    border-left: 4px solid #ddd;
                    margin: 0;
                    padding-left: 16px;
                    color: #666;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                }}
                ul, ol {{
                    padding-left: 20px;
                }}
                li {{
                    margin-bottom: 4px;
                }}
            </style>
            <body>{html}</body>
            """
            
            browser.setHtml(styled_html)
            
            # Force document to adjust size immediately
            browser.document().adjustSize()
        except Exception as e:
            # Fallback to plain text with error message
            browser.setPlainText(f"Markdown渲染失败: {e}\n\n原始内容:\n{md_text}")
    
    
    def _set_message_dimensions(self, message_widget: QWidget, browser: QTextBrowser):
        """Set dimensions for message widget and browser with responsive width"""
        try:
            if not browser or not message_widget:
                return
            
            # Get available width from scroll area
            available_width = self.chat_scroll.viewport().width()
            if available_width <= 0:
                available_width = 800  # fallback width
            
            # Remove fixed width constraints and use expanding policy
            message_widget.setMaximumWidth(16777215)
            message_widget.setMinimumWidth(0)
            browser.setMaximumWidth(16777215)
            browser.setMinimumWidth(0)
            
            # Set size policies for responsive behavior
            message_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            
            # Set document text width to available width minus margins
            # Use a much larger maximum width to allow full expansion
            text_width = max(available_width - 50, 1200)  # Minimum 1200px width, or available width
            browser.document().setTextWidth(text_width)
            browser.document().adjustSize()
            
            # Calculate and set height based on content
            content_height = browser.document().size().height()
            browser_height = max(60, int(content_height + 20))  # 20px padding
            browser.setFixedHeight(browser_height)
            
            # Force layout update
            message_widget.updateGeometry()
            self.chat_widget.updateGeometry()
            
        except Exception as e:
            print(f"Dimension setting error: {e}")
    
    def closeEvent(self, event):
        """Save conversation when closing"""
        self._save_conversation()
        super().closeEvent(event)
    
    def _add_message(self, sender: str, message: str, is_user: bool = False):
        """Add a message to the chat display with markdown rendering"""
        message_widget = QWidget()
        message_layout = QVBoxLayout(message_widget)
        
        # Sender label
        sender_label = QLabel(sender)
        sender_label.setFont(QFont("微软雅黑", 10, QFont.Weight.Bold))
        sender_label.setStyleSheet(f"color: {'#0066cc' if is_user else '#cc6600'}")
        
        # Message content with markdown rendering
        message_browser = QTextBrowser()
        message_browser.setOpenExternalLinks(True)
        message_browser.setReadOnly(True)
        message_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        message_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        message_browser.setStyleSheet("border: 1px solid #ccc; border-radius: 5px; padding: 5px;")
        
        # Set line wrap mode
        message_browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        
        # Render markdown content first
        self._render_message_markdown(message_browser, message)
        
        message_layout.addWidget(sender_label)
        message_layout.addWidget(message_browser)
        message_layout.setContentsMargins(5, 5, 5, 10)
        
        self.chat_layout.addWidget(message_widget)
        
        # Store message widgets for resize handling
        if not hasattr(self, '_message_widgets'):
            self._message_widgets = []
        self._message_widgets.append((message_widget, message_browser))
        
        # Force immediate width and height adjustment
        QTimer.singleShot(1, lambda: self._set_message_dimensions(message_widget, message_browser))
        
        # Scroll to bottom
        QTimer.singleShot(100, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()))
    
    def _start_initial_conversation(self):
        """Start the conversation with the selected text"""
        initial_prompt = f"""请用中文对以下内容进行深入分析和详细描述：

{self.selected_text}

请从以下角度进行分析：
1. 核心概念解释
2. 具体应用场景
3. 相关技术原理
4. 实际案例分析"""
        
        self.conversation_history.append({"role": "user", "content": initial_prompt})
        self._add_message("用户", f"选中内容：{self.selected_text[:100]}{'...' if len(self.selected_text) > 100 else ''}", True)
        
        # Send to LLM
        self._send_to_llm(initial_prompt)
    
    def _send_message(self):
        """Send user message"""
        user_message = self.input_field.text().strip()
        if not user_message:
            return
        
        self.conversation_history.append({"role": "user", "content": user_message})
        self._add_message("用户", user_message, True)
        self.input_field.clear()
        
        # Send to LLM
        self._send_to_llm(user_message)
    
    def _send_to_llm(self, message: str):
        """Send message to LLM and get response"""
        # Start LLM worker
        self._llm_thread = QThread(self)
        self._llm_worker = ChatbotWorker(self.config, message, self.conversation_history)
        self._llm_worker.moveToThread(self._llm_thread)
        
        self._llm_thread.started.connect(self._llm_worker.start)
        self._llm_worker.responseReady.connect(self._on_llm_response)
        self._llm_worker.finished.connect(self._llm_thread.quit)
        self._llm_worker.finished.connect(lambda: setattr(self, "_llm_worker", None))
        
        self._llm_thread.start()
    
    @Slot(str)
    def _on_llm_response(self, response: str):
        """Handle LLM response"""
        if response.strip():
            self.conversation_history.append({"role": "assistant", "content": response})
            self._add_message("AI助手", response, False)
    
    def _summarize_conversation(self):
        """Summarize the conversation and insert into markdown editor"""
        if not self.conversation_history:
            QMessageBox.information(self, "总结对话", "没有对话内容可以总结。")
            return
        
        # Create Chinese summary prompt for better Chinese output
        conversation_text = "\n\n".join([
            f"{msg['role']}: {msg['content']}" for msg in self.conversation_history
        ])
        
        summary_prompt = f"""请用中文对以下对话进行知识点总结，要求：
1. 使用中文回答
2. 提取关键知识点和要点
3. 结构化展示，使用标题和列表
4. 突出重要概念和原理

对话内容：
{conversation_text}"""
        
        # Start summary worker
        self._summary_thread = QThread(self)
        self._summary_worker = ChatbotWorker(self.config, summary_prompt, [])
        self._summary_worker.moveToThread(self._summary_thread)
        
        self._summary_thread.started.connect(self._summary_worker.start)
        self._summary_worker.responseReady.connect(self._on_summary_ready)
        self._summary_worker.finished.connect(self._summary_thread.quit)
        self._summary_worker.finished.connect(lambda: setattr(self, "_summary_worker", None))
        
        self._summary_thread.start()
    
    @Slot(str)
    def _on_summary_ready(self, summary: str):
        """Handle summary ready and insert into parent editor"""
        if summary.strip():
            # Save conversation before closing
            self._save_conversation()
            
            # Find main window and insert summary
            main_window = self._find_main_window()
            if main_window and hasattr(main_window, 'insert_summary_at_position'):
                main_window.insert_summary_at_position(summary, self.insert_position)
            
            QMessageBox.information(self, "总结完成", "对话总结已插入到笔记中。")
            self.close()
    
    def _find_main_window(self):
        """Find the main application window"""
        widget = self.parent()
        while widget:
            if hasattr(widget, 'insert_summary_at_position'):
                return widget
            widget = widget.parent()
        return None


class ConversationHistoryDialog(QDialog):
    """Dialog for viewing and selecting conversation history"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("对话历史")
        self.resize(600, 400)
        self.selected_conversation = None
        self._setup_ui()
        self._load_conversations()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Search and filter
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索对话...")
        self.search_input.textChanged.connect(self._filter_conversations)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # Conversation list
        self.conversation_list = QListWidget()
        self.conversation_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.conversation_list)
        
        # Preview area
        preview_group = QGroupBox("对话预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(preview_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        delete_button = QPushButton("删除选中")
        delete_button.clicked.connect(self._delete_selected)
        button_layout.addWidget(delete_button)
        
        button_layout.addStretch()
        
        load_button = QPushButton("加载对话")
        load_button.clicked.connect(self.accept)
        button_layout.addWidget(load_button)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Connect selection change
        self.conversation_list.currentItemChanged.connect(self._on_selection_changed)
    
    def _load_conversations(self):
        """Load conversation files from disk"""
        try:
            import os
            import json
            from datetime import datetime
            
            conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
            if not os.path.exists(conversations_dir):
                return
            
            conversations = []
            for filename in os.listdir(conversations_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(conversations_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            conversations.append(data)
                    except Exception as e:
                        print(f"加载对话文件失败 {filename}: {e}")
            
            # Sort by timestamp (newest first)
            conversations.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            for conv in conversations:
                timestamp = conv.get('timestamp', '')
                conv_id = conv.get('id', '')
                selected_text = conv.get('selected_text', '')[:50]
                
                # Format timestamp
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    time_str = timestamp[:16] if timestamp else 'Unknown'
                
                item_text = f"[{time_str}] {conv_id} - {selected_text}..."
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, conv)
                self.conversation_list.addItem(item)
                
        except Exception as e:
            print(f"加载对话历史失败: {e}")
    
    def _filter_conversations(self):
        """Filter conversations based on search text"""
        search_text = self.search_input.text().lower()
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            visible = search_text in item.text().lower()
            item.setHidden(not visible)
    
    def _on_selection_changed(self, current, previous):
        """Update preview when selection changes"""
        if current:
            conv_data = current.data(Qt.ItemDataRole.UserRole)
            if conv_data:
                # Show conversation preview
                preview_text = f"选中内容: {conv_data.get('selected_text', '')[:200]}...\n\n"
                history = conv_data.get('conversation_history', [])
                for i, msg in enumerate(history[:3]):  # Show first 3 messages
                    role = '用户' if msg['role'] == 'user' else 'AI助手'
                    content = msg['content'][:100] + '...' if len(msg['content']) > 100 else msg['content']
                    preview_text += f"{role}: {content}\n\n"
                if len(history) > 3:
                    preview_text += f"... 还有 {len(history) - 3} 条消息"
                self.preview_text.setPlainText(preview_text)
    
    def _on_item_double_clicked(self, item):
        """Handle double click to load conversation"""
        self.accept()
    
    def _delete_selected(self):
        """Delete selected conversation"""
        current_item = self.conversation_list.currentItem()
        if not current_item:
            return
        
        reply = QMessageBox.question(self, "删除对话", "确定要删除这个对话吗？")
        if reply == QMessageBox.StandardButton.Yes:
            try:
                conv_data = current_item.data(Qt.ItemDataRole.UserRole)
                conv_id = conv_data.get('id', '')
                
                # Delete file
                import os
                conversations_dir = os.path.join(os.path.dirname(__file__), "conversations")
                filename = f"conversation_{conv_id}.json"
                filepath = os.path.join(conversations_dir, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                # Remove from list
                row = self.conversation_list.row(current_item)
                self.conversation_list.takeItem(row)
                
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"删除对话失败: {e}")
    
    def get_selected_conversation(self):
        """Get the selected conversation data"""
        current_item = self.conversation_list.currentItem()
        if current_item:
            return current_item.data(Qt.ItemDataRole.UserRole)
        return None


class ChatbotWorker(QObject):
    """Worker for chatbot LLM interactions"""
    responseReady = Signal(str)
    finished = Signal()
    
    def __init__(self, config: dict, message: str, conversation_history: list):
        super().__init__()
        self.config = config
        self.message = message
        self.conversation_history = conversation_history
    
    @Slot()
    def start(self):
        try:
            provider = self.config.get("llm_provider", "Ollama")
            if provider == "Ollama":
                response = self._call_ollama()
            else:
                response = self._call_gemini()
            self.responseReady.emit(response or "抱歉，无法获取回复。")
        except Exception as e:
            self.responseReady.emit(f"错误：{str(e)}")
        finally:
            self.finished.emit()
    
    def _call_ollama(self) -> str:
        url = self.config.get("ollama_api_url", "http://localhost:11434/api/generate")
        model = self.config.get("ollama_model", "deepseek-r1:1.5b")
        
        try:
            resp = requests.post(url, json={
                "model": model,
                "prompt": self.message,
                "stream": False
            }, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except Exception as e:
            return f"Ollama调用失败：{str(e)}"
    
    def _call_gemini(self) -> str:
        api_key = self.config.get("gemini_api_key", "").strip()
        model = self.config.get("gemini_model", "gemini-1.5-flash-002").strip()
        
        if not api_key:
            return "Gemini未配置API Key"
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {"parts": [{"text": self.message}]}
            ]
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if not resp.ok:
                return f"Gemini调用失败：HTTP {resp.status_code}"
            
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"].strip()
            return "无法解析Gemini响应"
        except Exception as e:
            return f"Gemini请求异常：{str(e)}"


class TranscriptionAppQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时语音转写及总结工具 (Qt 版)")
        self.resize(1200, 700)

        # UI setup
        self.current_md_path: str | None = None
        self.attachments_dir: str | None = None
        self.selected_device_index: int | None = None
        # Load config
        self.config = load_config()
        # Auto summary tracking
        self._summary_countdown: int | None = None  # Initialize countdown before UI setup
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_summary_tick)
        self._last_summary_len = 0
        self._auto_pos = 0  # last auto-summarized end position in transcription text
        self._pending_highlight: dict | None = None  # {type: 'auto'|'manual', start:int, length:int}
        self._manual_highlight_ranges: list[tuple[int, int]] = []  # Store manual highlight ranges [(start, length), ...]
        self._setup_ui()
        # Apply auto-summary timer based on config at startup
        self._apply_auto_summary_timer()

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
        
        # Chatbot panels
        self._chatbot_panels: list[ChatbotPanel] = []
        
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

        # Settings menu (must be created before use)
        settings_menu = menubar.addMenu("设置(&S)")
        act_app_settings = settings_menu.addAction("应用设置…")
        act_app_settings.triggered.connect(self.open_settings_dialog)
        act_input_device = settings_menu.addAction("设置输入设备…")
        act_input_device.triggered.connect(self.choose_input_device)

        # Logs menu
        log_menu = menubar.addMenu("日志(&L)")
        act_show_log = log_menu.addAction("显示日志面板")
        act_show_log.triggered.connect(self.show_log_dock)
        act_clear_log = log_menu.addAction("清空日志")
        act_clear_log.triggered.connect(self.clear_log)
        act_save_log = log_menu.addAction("保存日志…")
        act_save_log.triggered.connect(self.save_log)
        # View menu for showing docks
        view_menu = menubar.addMenu("视图(&V)")
        # 知识管理子菜单
        knowledge_menu = view_menu.addMenu("知识管理")
        act_global_km = knowledge_menu.addAction("全局知识管理…")
        act_global_km.triggered.connect(self.open_global_knowledge_manager)
        
        # Chatbot menu
        chatbot_menu = view_menu.addMenu("AI深入学习")
        act_chatbot_history = chatbot_menu.addAction("深入学习历史")
        act_chatbot_history.triggered.connect(self._show_chatbot_history)
        
        # (知识管理菜单已创建)
        act_error_review = knowledge_menu.addAction("错题复习")
        act_error_review.triggered.connect(self.open_error_question_review_panel)
        # 新增：技术练习（从菜单打开练习面板，不自动生成题目）
        act_practice_panel = knowledge_menu.addAction("技术练习")
        act_practice_panel.triggered.connect(self.open_practice_panel_from_menu)
        act_show_all_chatbots = chatbot_menu.addAction("显示所有对话窗口")
        act_show_all_chatbots.triggered.connect(self._show_all_chatbot_panels)
        act_close_all_chatbots = chatbot_menu.addAction("关闭所有对话窗口")
        act_close_all_chatbots.triggered.connect(self._close_all_chatbot_panels)
        
        self.setMenuBar(menubar)

        # Minimal central widget (docks hold all panels)
        central = QWidget(self)
        self.setCentralWidget(central)
        _ = QVBoxLayout(central)

        # Controls dock (top buttons)
        self.controls_dock = QDockWidget("控制面板", self)
        self.controls_dock.setObjectName("ControlsDock")
        self.controls_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        controls_panel = QWidget(self.controls_dock)
        controls_layout = QHBoxLayout(controls_panel)
        self.btn_start = QPushButton("开始录制")
        self.btn_start.setToolTip("开始音频录制并实时转写")
        self.btn_start.clicked.connect(self._on_start_clicked)
        controls_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止录制")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        controls_layout.addWidget(self.btn_stop)

        self.btn_save = QPushButton("保存笔记")
        self.btn_save.clicked.connect(self._on_save_clicked)
        controls_layout.addWidget(self.btn_save)

        self.btn_summary = QPushButton("手动总结")
        self.btn_summary.clicked.connect(self._on_summarize_clicked)
        controls_layout.addWidget(self.btn_summary)

        self.btn_screenshot = QPushButton("截图笔记")
        self.btn_screenshot.setToolTip("截图并插入到上方摘要")
        self.btn_screenshot.clicked.connect(self._on_screenshot_note_clicked)
        controls_layout.addWidget(self.btn_screenshot)
        controls_layout.addStretch(1)
        self.controls_dock.setWidget(controls_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.controls_dock)

        # Summary dock
        self.summary_dock = QDockWidget("笔记总结", self)
        self.summary_dock.setObjectName("SummaryDock")
        self.summary_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        summary_panel = QWidget(self.summary_dock)
        summary_layout = QVBoxLayout(summary_panel)
        lbl_summary = QLabel("笔记总结")
        lbl_summary.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        # Header row with title and mode toggle
        header = QWidget(summary_panel)
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.addWidget(lbl_summary)
        header_lay.addStretch(1)
        
        # Knowledge extraction button
        self.btn_knowledge_extract = QPushButton("知识提取")
        self.btn_knowledge_extract.setToolTip("提取当前笔记的知识点并进行管理")
        self.btn_knowledge_extract.clicked.connect(self._open_knowledge_management_panel)
        header_lay.addWidget(self.btn_knowledge_extract)
        
        self.btn_toggle_summary_mode = QPushButton("预览")  # click to switch to preview mode
        self.btn_toggle_summary_mode.setToolTip("切换为预览模式 (不影响底层内容更新)")
        self.btn_toggle_summary_mode.clicked.connect(self._toggle_summary_mode)
        header_lay.addWidget(self.btn_toggle_summary_mode)
        summary_layout.addWidget(header)
        self.summary_area = RichTextEditor(on_change=self._on_editor_changed, enable_image_context=True)
        self.summary_area.setFont(QFont("微软雅黑", 12))
        summary_layout.addWidget(self.summary_area)
        # In-panel Markdown preview (hidden by default)
        self.summary_preview = QTextBrowser(summary_panel)
        self.summary_preview.setOpenExternalLinks(True)
        # Match editor font in preview for consistent size
        try:
            self.summary_preview.setFont(self.summary_area.font())
        except Exception:
            pass
        self.summary_preview.hide()
        summary_layout.addWidget(self.summary_preview)
        # Apply markdown syntax highlighting to summary editor
        try:
            self._summary_highlighter = MarkdownHighlighter(self.summary_area.document())
        except Exception:
            self._summary_highlighter = None

        self.summary_dock.setWidget(summary_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.summary_dock)

        # Transcription dock
        self.transcription_dock = QDockWidget("实时语音转文字", self)
        self.transcription_dock.setObjectName("TranscriptionDock")
        self.transcription_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        trans_panel = QWidget(self.transcription_dock)
        trans_layout = QVBoxLayout(trans_panel)
        lbl_trans = QLabel("实时语音转文字")
        lbl_trans.setFont(QFont("微软雅黑", 10))
        trans_layout.addWidget(lbl_trans)
        self.transcription_area = RichTextEditor()
        self.transcription_area.setReadOnly(True)
        self.transcription_area.setFont(QFont("微软雅黑", 10))
        trans_layout.addWidget(self.transcription_area)
        self.transcription_dock.setWidget(trans_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.transcription_dock)

        # Keep preview updated when editing
        try:
            self.summary_area.textChanged.connect(self._update_md_preview)
        except Exception:
            pass

        # Default vertical stacking: Controls -> Summary -> Transcription
        try:
            self.setDockNestingEnabled(True)
            self.splitDockWidget(self.controls_dock, self.summary_dock, Qt.Orientation.Vertical)
            self.splitDockWidget(self.summary_dock, self.transcription_dock, Qt.Orientation.Vertical)
        except Exception:
            pass

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)
        # 新增：状态详情标签
        self.state_detail_label = QLabel("")
        self.state_detail_label.setMinimumWidth(300)  # 确保足够空间显示状态
        self.statusBar().addWidget(self.state_detail_label)
        # 初始化状态详情
        self._update_state_detail()
        # 倒计时定时器（每秒更新）
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(1000)  # 每秒更新
        # VU meter

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

        # View menu actions to re-show docks
        act_show_controls = view_menu.addAction("显示控制面板")
        act_show_controls.triggered.connect(self.controls_dock.show)
        act_show_summary = view_menu.addAction("显示笔记总结面板")
        act_show_summary.triggered.connect(self.summary_dock.show)
        act_show_trans = view_menu.addAction("显示转写面板")
        act_show_trans.triggered.connect(self.transcription_dock.show)
        act_show_log_view = view_menu.addAction("显示日志面板")
        act_show_log_view.triggered.connect(self.show_log_dock)

        # Restore previous layout (geometry + dock state) if available
        self._restore_layout()
        # Initial preview render
        try:
            self._update_md_preview()
        except Exception:
            pass

    def open_global_knowledge_manager(self):
        try:
            from global_knowledge_panel import GlobalKnowledgeManagerDialog
            dlg = GlobalKnowledgeManagerDialog(self.config, self)
            dlg.exec()
        except Exception as e:
            self.log(f"[题库管理] 打开失败: {e}")
            QMessageBox.critical(self, "错误", f"无法打开题库管理面板: {e}")

    # ---- File operations ----
    def set_current_document(self, md_path: str) -> None:
        self.current_md_path = md_path
        base_dir = os.path.dirname(md_path)
        self.attachments_dir = os.path.join(base_dir, "attachments")
        os.makedirs(self.attachments_dir, exist_ok=True)
        self.status_label.setText(f"当前文档: {os.path.basename(md_path)}")
        # Initialize auto summary position to current transcript length
        try:
            self._auto_pos = self.transcription_area.text_length()
        except Exception:
            self._auto_pos = 0
        # Reset manual highlight ranges when opening a new document
        self._manual_highlight_ranges = []

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
        self._auto_pos = 0
        # Reset manual highlight ranges when opening a new document
        self._manual_highlight_ranges = []
        try:
            self._update_md_preview()
        except Exception:
            pass

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
            # After loading, set auto position to current end to avoid summarizing historical content automatically
            try:
                self._auto_pos = self.transcription_area.text_length()
            except Exception:
                self._auto_pos = 0
            try:
                self._update_md_preview()
            except Exception:
                pass
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
        self._tr_worker = TranscriberWorker(model_size="large-v2", language_setting=self.config.get("whisper_language", "auto"))
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
        self._tr_thread.finished.connect(lambda: self._set_status("转写线程结束"))
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
        self._start_manual_summary()

    def _on_screenshot_note_clicked(self):
        try:
            self._open_screenshot_overlay()
        except Exception as e:
            QMessageBox.critical(self, "截图失败", str(e))

    # 打开截图覆盖层
    def _open_screenshot_overlay(self):
        screen = QApplication.primaryScreen()
        if not screen:
            raise RuntimeError("无法获取屏幕来进行截图")
        self._shot_overlay = ScreenshotOverlay(screen)
        self._shot_overlay.captured.connect(self._on_screenshot_captured)
        self._shot_overlay.showFullScreen()

    # 截图完成回调：插入到摘要区
    @Slot(QImage)
    def _on_screenshot_captured(self, img: QImage):
        try:
            if img and not img.isNull():
                self.summary_area.insert_image_from_qimage(img)
        finally:
            try:
                self._shot_overlay.close()
            except Exception:
                pass
            self._shot_overlay = None

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
            # Ensure default (black) format for appended text
            self.transcription_area.moveCursor(QTextCursor.MoveOperation.End)
            self.transcription_area.reset_current_format_to_default()
            self.transcription_area.insertPlainText(text + " ")
            self.transcription_area.reset_current_format_to_default()
            self.transcription_area.scrollToBottom()

    def _toggle_summary_mode(self):
        """Toggle between edit and preview modes for the summary panel (Obsidian-like)."""
        try:
            if self.summary_preview.isVisible():
                # Switch to edit mode
                ratio = self._get_view_center_ratio(self.summary_preview)
                self.summary_preview.hide()
                self.summary_area.show()
                self.btn_toggle_summary_mode.setText("预览")
                self.btn_toggle_summary_mode.setToolTip("切换为预览模式 (不影响底层内容更新)")
                # Apply center alignment
                self._scroll_to_center_ratio(self.summary_area, ratio)
            else:
                # Switch to preview mode
                self._update_md_preview()
                ratio = self._get_view_center_ratio(self.summary_area)
                self.summary_area.hide()
                self.summary_preview.show()
                self.btn_toggle_summary_mode.setText("编辑")
                self.btn_toggle_summary_mode.setToolTip("切换为编辑模式 (不影响底层内容更新)")
                # Apply center alignment
                self._scroll_to_center_ratio(self.summary_preview, ratio)
        except Exception:
            pass

    def _update_md_preview(self) -> None:
        """Render current summary markdown (with images) to the in-panel preview."""
        try:
            # Prefer exporting markdown with embedded images serialized to attachments
            if self.attachments_dir:
                md_text, _ = self.summary_area.export_markdown_with_images(self.attachments_dir)
            else:
                md_text = self.summary_area.toPlainText()
        except Exception:
            md_text = self.summary_area.toPlainText()

        # Convert Obsidian image placeholders ![[file.png]] to absolute file URLs for QTextBrowser
        try:
            import re as _re, os as _os
            from PySide6.QtCore import QUrl as _QUrl
            def _repl(m):
                fname = m.group(1)
                if self.attachments_dir:
                    p = _os.path.join(self.attachments_dir, fname)
                    return f"![{fname}]({_QUrl.fromLocalFile(p).toString()})"
                return f"![{fname}]({fname})"
            md_text = _re.sub(r"!\[\[(.*?)\]\]", _repl, md_text or "")
        except Exception:
            pass

        if not markdown:
            # Fallback: show raw text with a hint
            esc = (md_text or "").replace("&", "&amp;").replace("<", "&lt;")
            self.summary_preview.setHtml("<p style='color:#a00'>未安装 markdown 库。请运行: <code>pip install markdown</code></p><pre>" + esc + "</pre>")
            return

        # Set search path for relative resources
        try:
            if self.attachments_dir:
                self.summary_preview.setSearchPaths([self.attachments_dir])
        except Exception:
            pass

        try:
            html = markdown.markdown(md_text or "", extensions=["fenced_code", "tables"])
            # Inject base CSS to match editor font and size
            try:
                f = self.summary_area.font()
                base_css = f"<style> body {{ font-family: '{f.family()}'; font-size: {f.pointSize()}pt; }} pre, code {{ font-family: Consolas, monospace; }} </style>"
                html = base_css + html
            except Exception:
                pass
            self.summary_preview.setHtml(html)
        except Exception as e:
            esc = (md_text or "").replace("&", "&amp;").replace("<", "&lt;")
            self.summary_preview.setHtml(f"<p style='color:#a00'>Markdown 解析失败: {e}</p><pre>" + esc + "</pre>")

    # ---- Viewport sync helpers ----
    def _get_view_center_ratio(self, widget: QWidget) -> float:
        try:
            bar = widget.verticalScrollBar()
            if not bar:
                return 0.0
            maxv = max(1, bar.maximum() + bar.pageStep())
            center = bar.value() + bar.pageStep() / 2.0
            ratio = max(0.0, min(1.0, center / maxv))
            return float(ratio)
        except Exception:
            return 0.0

    def _scroll_to_center_ratio(self, widget: QWidget, ratio: float) -> None:
        try:
            bar = widget.verticalScrollBar()
            if not bar:
                return
            maxv = bar.maximum() + bar.pageStep()
            target_center = ratio * max(1, maxv)
            value = int(round(target_center - bar.pageStep() / 2.0))
            value = max(0, min(bar.maximum(), value))
            bar.setValue(value)
        except Exception:
            pass


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
        self.transcription_area.moveCursor(QTextCursor.MoveOperation.End)
        self.transcription_area.reset_current_format_to_default()
        self.transcription_area.insertPlainText(full_text_chunk)
        self.transcription_area.reset_current_format_to_default()
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
        # Save layout before exiting
        try:
            self._save_layout()
        except Exception:
            pass
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

    # ---- Settings dialog ----
    def open_settings_dialog(self):
        dlg = SettingsDialog(self.config, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            old_provider = self.config.get("llm_provider", "Gemini")
            self.config = dlg.result_config()
            new_provider = self.config.get("llm_provider", "Gemini")
            
            if save_config(self.config):
                self._set_status("配置已保存")
                
                # 如果LLM提供商发生变化，通知所有练习面板更新配置
                if old_provider != new_provider:
                    self.log(f"[配置更新] LLM提供商从 {old_provider} 切换到 {new_provider}")
                    self._notify_practice_panels_config_update()
                else:
                    # 即使提供商没变，也要更新配置（可能是模型名称等其他配置变了）
                    self._notify_practice_panels_config_update()
            else:
                QMessageBox.warning(self, "配置", "无法保存配置文件")
            # Apply auto summary timer
            self._apply_auto_summary_timer()
    
    def _notify_practice_panels_config_update(self):
        """通知所有打开的练习面板更新配置"""
        if hasattr(self, '_practice_panels'):
            for panel in self._practice_panels:
                if panel and not panel.isHidden():
                    try:
                        panel.update_config(self.config)
                        self.log(f"[配置更新] 已通知练习面板更新配置")
                    except Exception as e:
                        self.log(f"[配置更新] 通知练习面板失败: {e}")

    def _apply_auto_summary_timer(self):
        """Apply auto summary timer settings"""
        mode = self.config.get("summary_mode", "auto")
        interval = int(self.config.get("auto_summary_interval", 300))
        if mode == "auto":
            self._summary_countdown = interval  # 初始化倒计时
            self._auto_timer.start(max(5_000, interval * 1000))
            self._set_status(f"自动总结已开启，每 {interval}s 触发")
        else:
            self._auto_timer.stop()
            self._set_status("自动总结已关闭")




    # 新增：更新状态详情
    def _update_state_detail(self):
        """更新状态栏中的详细状态（总结模式、模型、倒计时等）"""
        parts = []
        # 总结模式
        mode = self.config.get("summary_mode", "auto")
        parts.append(f"总结: {'自动' if mode == 'auto' else '手动'}")
        # 倒计时（仅自动模式）
        if mode == "auto" and self._summary_countdown is not None:
            parts.append(f"{self._summary_countdown}s后自动总结")
        # 总结模型
        provider = self.config.get("llm_provider", "Ollama")
        if provider == "Gemini":
            model = self.config.get("gemini_model", "gemini-1.5-flash-002")
        else:
            model = self.config.get("ollama_model", "deepseek-r1:1.5b")
        parts.append(f"模型: {model}")
        # 设置状态详情
        self.state_detail_label.setText(" | ".join(parts))

    def _update_countdown(self):
        """每秒更新自动总结倒计时"""
        if self.config.get("summary_mode", "auto") == "auto" and self._summary_countdown is not None:
            self._summary_countdown -= 1
            if self._summary_countdown <= 0:
                interval = int(self.config.get("auto_summary_interval", 300))
                self._summary_countdown = interval  # 重置倒计时
            self._update_state_detail()



    # ---- Layout persistence ----
    def _restore_layout(self) -> None:
        """Restore window geometry and dock layout from config if present."""
        try:
            geo_b64 = self.config.get("main_window_geometry")
            state_b64 = self.config.get("main_window_state_v1")
            if geo_b64:
                try:
                    self.restoreGeometry(QByteArray.fromBase64(geo_b64.encode("ascii")))
                except Exception:
                    pass
            if state_b64:
                try:
                    self.restoreState(QByteArray.fromBase64(state_b64.encode("ascii")), 1)
                except Exception:
                    pass
        except Exception:
            pass

    def _save_layout(self) -> None:
        """Save window geometry and dock layout into config (base64 strings)."""
        try:
            geo_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
            state_b64 = bytes(self.saveState(1).toBase64()).decode("ascii")
            self.config["main_window_geometry"] = geo_b64
            self.config["main_window_state_v1"] = state_b64
            save_config(self.config)
        except Exception:
            pass

    # ---- Summarization ----
    def _collect_transcript_text(self, max_chars: int) -> str:
        text = self.transcription_area.toPlainText()
        if not text:
            return ""
        # Use tail max_chars
        return text[-max(0, max_chars):]
    
    def _start_manual_summary(self):
        # Pause auto summary timer to prevent interference
        self._auto_timer.stop()
        self.log("暂停自动总结定时器")
        
        start, length = self.transcription_area.selection_range()
        if length > 0:
            text = self.transcription_area.selected_text()
            if text.strip():
                # Store the highlight range
                self._manual_highlight_ranges.append((start, length))
                try:
                    self.log(f"手动总结：高亮选中文本 start={start}, length={length}")
                    self.transcription_area._highlight_with_html(self._manual_highlight_ranges, "green")
                except Exception as e:
                    self.log(f"高亮失败：{e}")
                self._run_summarizer(text)
                # Restart auto timer after starting summarizer
                self._apply_auto_summary_timer()
                return
        
        # Fallback for no selection
        max_chars = int(self.config.get("manual_summary_max_chars", 20000))
        text = self._collect_transcript_text(max_chars)
        if not text.strip():
            QMessageBox.information(self, "手动总结", "当前没有可总结的转写文本。")
            self._apply_auto_summary_timer()  # Restart timer
            return
        full_len = self.transcription_area.text_length()
        start2 = max(0, full_len - len(text))
        self._manual_highlight_ranges.append((start2, len(text)))
        try:
            self.log(f"手动总结：高亮尾部文本 start={start2}, length={len(text)}")
            self.transcription_area._highlight_with_html(self._manual_highlight_ranges, "green")
        except Exception as e:
            self.log(f"高亮失败：{e}")
        self._run_summarizer(text)
        # Restart auto timer
        self._apply_auto_summary_timer()

    def _auto_summary_tick(self):
        if self.config.get("summary_mode", "auto") != "auto":
            return
        max_chars = int(self.config.get("auto_summary_max_chars", 8000))
        full_text = self.transcription_area.toPlainText()
        end = len(full_text)
        start = self._auto_pos
        if end <= start:
            return
        win_start = max(start, end - max_chars)
        segment = full_text[win_start:end]
        if not segment.strip():
            # nothing meaningful
            self._auto_pos = end
            return
        self._last_summary_len = len(segment)
        self.log(f"自动总结触发，窗口=({win_start}->{end}) 长度={self._last_summary_len}")
        self._summary_countdown = int(self.config.get("auto_summary_interval", 300))  # 重置倒计时
        # Record pending highlight in blue; update _auto_pos after summary completes
        self._pending_highlight = {"type": "auto", "start": win_start, "length": end - win_start}
        self._run_summarizer(segment)

    def _run_summarizer(self, transcript_text: str):
        # Start summarizer worker
        self._sum_thread = QThread(self)
        self._sum_worker = SummarizerWorker(self.config, transcript_text, SUMMARY_PROMPT)

                # 更新动态状态
        summary_type = "手动" if transcript_text != self._collect_transcript_text(int(self.config.get("auto_summary_max_chars", 8000))) else "自动"
        self._set_status(f"录音中…转写中…{summary_type}总结中…" if self._rec_thread and self._tr_thread else f"{summary_type}总结中…")
        self._update_state_detail()
        self._sum_worker.moveToThread(self._sum_thread)
        self._sum_thread.started.connect(self._sum_worker.start)
        self._sum_worker.summaryReady.connect(self._on_summary_ready)
        self._sum_worker.status.connect(self._set_status)
        self._sum_worker.finished.connect(self._sum_thread.quit)
        self._sum_worker.finished.connect(lambda: setattr(self, "_sum_worker", None))
        self._sum_thread.start()

    @Slot(str)
    def _on_summary_ready(self, content: str):
        if not content:
            self.log("总结为空")
            return
        # Append to summary area
        if self.summary_area.toPlainText().strip():
            self.summary_area.insertPlainText("\n\n")
        self.summary_area.insertPlainText(content)
        self.summary_area.scrollToBottom()
        # Apply highlight to transcription window if pending (only for auto summaries)
        try:
            if self._pending_highlight and self._pending_highlight.get("type") == "auto":
                info = self._pending_highlight
                self.transcription_area.apply_color(int(info["start"]), int(info["length"]), QColor("blue"))
                self._auto_pos = int(info["start"]) + int(info["length"])
        except Exception as e:
            self.log(f"高亮失败：{e}")
        finally:
            self._pending_highlight = None
            self._update_state_detail()

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

    def open_chatbot_panel(self, selected_text: str, insert_position: int):
        """Open a new chatbot panel for deep learning"""
        self.log(f"[聊天面板] 正在打开深入学习面板")
        self.log(f"[聊天面板] 选中文本长度: {len(selected_text)}")
        self.log(f"[聊天面板] 插入位置: {insert_position}")
        
        try:
            chatbot_panel = ChatbotPanel(selected_text, insert_position, self.config, self)
            self._chatbot_panels.append(chatbot_panel)
            chatbot_panel.show()
            self.log("[聊天面板] 深入学习面板已成功创建并显示")
        except Exception as e:
            self.log(f"[聊天面板] 创建深入学习面板时发生错误: {e}")
            import traceback
            self.log(f"[聊天面板] 错误堆栈: {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"无法打开深入学习面板: {e}")

    def open_practice_panel(self, selected_text: str, insert_position: int):
        """Open a new practice panel for generating and solving practice questions"""
        self.log(f"[练习面板] 正在打开练习面板")
        self.log(f"[练习面板] 选中文本长度: {len(selected_text)}")
        self.log(f"[练习面板] 插入位置: {insert_position}")
        
        try:
            # 若当前存在活动的应用级模态窗口，先暂时解除其模态，避免全局输入被阻塞
            try:
                from PySide6.QtWidgets import QApplication
                amw = QApplication.activeModalWidget()
                if amw is not None and hasattr(amw, 'setWindowModality'):
                    amw.setWindowModality(Qt.WindowModality.NonModal)
                    amw.show()
            except Exception:
                pass

            # 独立对话框（无父级），应用级模态，确保可编辑与置前
            practice_panel = PracticePanel(selected_text, insert_position, self.config, None)
            if not hasattr(self, '_practice_panels'):
                self._practice_panels = []
            self._practice_panels.append(practice_panel)
            try:
                practice_panel.setWindowModality(Qt.WindowModality.ApplicationModal)
            except Exception:
                pass
            # 使用 exec() 进入模态事件循环，确保用户可直接在面板内输入
            practice_panel.exec()
            try:
                practice_panel.raise_()
                practice_panel.activateWindow()
            except Exception:
                pass
            self.log("[练习面板] 练习面板已成功创建并显示")
        except Exception as e:
            self.log(f"[练习面板] 创建练习面板时发生错误: {e}")
            import traceback
            self.log(f"[练习面板] 错误堆栈: {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"无法打开练习面板: {e}")

    def open_practice_panel_from_menu(self):
        """通过菜单打开技术练习面板：不依赖选中文本，也不自动生成题目"""
        try:
            # 若当前存在活动的应用级模态窗口，先暂时解除其模态，避免全局输入被阻塞
            try:
                from PySide6.QtWidgets import QApplication
                amw = QApplication.activeModalWidget()
                if amw is not None and hasattr(amw, 'setWindowModality'):
                    amw.setWindowModality(Qt.WindowModality.NonModal)
                    amw.show()
            except Exception:
                pass

            # 传入空的 selected_text，PracticePanel 内部会避免自动生成
            practice_panel = PracticePanel("", 0, self.config, None)
            if not hasattr(self, '_practice_panels'):
                self._practice_panels = []
            self._practice_panels.append(practice_panel)
            try:
                practice_panel.setWindowModality(Qt.WindowModality.ApplicationModal)
            except Exception:
                pass
            practice_panel.exec()
            try:
                practice_panel.raise_()
                practice_panel.activateWindow()
            except Exception:
                pass
            self.log("[练习面板] 通过菜单打开练习面板（不自动生成题目）")
        except Exception as e:
            import traceback
            self.log(f"[练习面板] 通过菜单打开失败: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"无法打开练习面板: {e}")

    def open_knowledge_extraction_panel(self, selected_text: str):
        """Open knowledge point extraction panel"""
        self.log(f"[知识点提取] 正在打开知识点提取面板")
        self.log(f"[知识点提取] 选中文本长度: {len(selected_text)}")
        
        try:
            from knowledge_point_ui import KnowledgePointExtractionPanel
            
            # Create and show the knowledge extraction panel
            panel = KnowledgePointExtractionPanel(selected_text, self.config, self)
            panel.show()
            
            self.log("[知识点提取] 知识点提取面板已打开")
            
        except Exception as e:
            self.log(f"[知识点提取] 打开知识点提取面板时发生错误: {e}")
            import traceback
            self.log(f"[知识点提取] 错误堆栈: {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"无法打开知识点提取面板: {e}")

    def open_error_question_review_panel(self):
        """Open error question review panel"""
        try:
            from error_question_ui import ErrorQuestionReviewDialog
            from knowledge_management import KnowledgeManagementSystem
            
            km_system = KnowledgeManagementSystem(self.config)
            dialog = ErrorQuestionReviewDialog(km_system, self)
            dialog.exec()
            
        except Exception as e:
            self.log(f"[错题复习] 打开错题复习面板时发生错误: {e}")
            QMessageBox.critical(self, "错误", f"无法打开错题复习面板: {e}")
    
    def _create_new_chatbot(self):
        """Create a new chatbot panel"""
        try:
            from chatbot_panel import ChatbotPanel
            chatbot_panel = ChatbotPanel(self.config, parent=self)
            self._chatbot_panels.append(chatbot_panel)
            chatbot_panel.show()
            chatbot_panel.raise_()
            chatbot_panel.activateWindow()
        except Exception as e:
            self.log(f"[AI深入学习] 创建新对话面板时发生错误: {e}")
            QMessageBox.critical(self, "错误", f"无法创建新对话面板: {e}")
    
    def _show_chatbot_history(self):
        """Show chatbot history dialog"""
        dialog = ConversationHistoryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_conversation = dialog.get_selected_conversation()
            if selected_conversation:
                # Create new chatbot panel with loaded conversation
                selected_text = selected_conversation.get("selected_text", "")
                chatbot_panel = ChatbotPanel(selected_text, 0, self.config, self)
                chatbot_panel._loading_from_history = True
                chatbot_panel._load_conversation(selected_conversation)
                self._chatbot_panels.append(chatbot_panel)
                chatbot_panel.show()
    
    def _show_all_chatbot_panels(self):
        """Show all chatbot panels"""
        for panel in self._chatbot_panels:
            if panel and not panel.isVisible():
                panel.show()
                panel.raise_()
                panel.activateWindow()
    
    def _close_all_chatbot_panels(self):
        """Close all chatbot panels"""
        panels_to_close = self._chatbot_panels.copy()
        for panel in panels_to_close:
            if panel:
                panel.close()
        self._chatbot_panels.clear()
    
    def _open_knowledge_management_panel(self):
        """打开知识管理面板"""
        try:
            # 获取当前笔记内容
            note_content = self.summary_area.toPlainText()
            if not note_content.strip():
                QMessageBox.warning(self, "提示", "当前笔记内容为空，请先编写笔记内容")
                return
            
            # 导入并打开知识管理面板
            from note_knowledge_panel import open_note_knowledge_panel
            open_note_knowledge_panel(note_content, self.config, self)
            
        except Exception as e:
            self.log(f"[知识管理] 打开知识管理面板时发生错误: {e}")
            QMessageBox.critical(self, "错误", f"无法打开知识管理面板: {e}")

    def insert_summary_at_position(self, summary: str, position: int):
        """Insert summary text at the specified position in the summary area"""
        try:
            cursor = self.summary_area.textCursor()
            cursor.setPosition(position)
            cursor.insertText(f"\n\n## 深入学习总结\n\n{summary}\n")
            self.summary_area.setTextCursor(cursor)
            self.summary_area.scrollToBottom()
            self.log(f"已插入深入学习总结，长度: {len(summary)}")
        except Exception as e:
            self.log(f"插入总结失败: {e}")
            # Fallback: append to end
            try:
                self.summary_area.moveCursor(QTextCursor.MoveOperation.End)
                self.summary_area.insertPlainText(f"\n\n## 深入学习总结\n\n{summary}\n")
                self.summary_area.scrollToBottom()
            except Exception as e2:
                self.log(f"备用插入方法也失败: {e2}")


# ===== Settings Dialog =====
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("应用设置")
        self.resize(520, 460)
        self._cfg = dict(cfg)  # copy

        layout = QVBoxLayout(self)

        # Provider group
        grp_provider = QGroupBox("大语言模型提供商")
        pv = QVBoxLayout(grp_provider)
        self.rb_deepseek = QRadioButton("DeepSeek (在线)")
        self.rb_gemini = QRadioButton("Gemini (云端)")
        self.rb_ollama = QRadioButton("Ollama (本地)")
        pv.addWidget(self.rb_deepseek)
        pv.addWidget(self.rb_gemini)
        pv.addWidget(self.rb_ollama)
        layout.addWidget(grp_provider)

        # Ollama settings
        grp_ollama = QGroupBox("Ollama 设置")
        form_o = QFormLayout(grp_ollama)
        self.ed_ollama_url = QLineEdit()
        self.ed_ollama_model = QLineEdit()
        form_o.addRow("API URL", self.ed_ollama_url)
        form_o.addRow("模型名称", self.ed_ollama_model)
        layout.addWidget(grp_ollama)

        # DeepSeek settings
        grp_deepseek = QGroupBox("DeepSeek 设置")
        form_d = QFormLayout(grp_deepseek)
        self.ed_deepseek_key = QLineEdit()
        self.ed_deepseek_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_deepseek_model = QLineEdit()
        self.ed_deepseek_url = QLineEdit()
        form_d.addRow("API Key", self.ed_deepseek_key)
        form_d.addRow("模型名称", self.ed_deepseek_model)
        form_d.addRow("API URL", self.ed_deepseek_url)
        layout.addWidget(grp_deepseek)

        # Gemini settings
        grp_gemini = QGroupBox("Gemini 设置")
        form_g = QFormLayout(grp_gemini)
        self.ed_gemini_key = QLineEdit()
        self.ed_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_gemini_model = QLineEdit()
        form_g.addRow("API Key", self.ed_gemini_key)
        form_g.addRow("模型名称", self.ed_gemini_model)
        layout.addWidget(grp_gemini)

        # Summary settings
        grp_summary = QGroupBox("总结设置")
        form_s = QFormLayout(grp_summary)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["auto", "manual"])
        self.sp_interval = QSpinBox(); self.sp_interval.setRange(10, 3600)
        self.sp_auto_max = QSpinBox(); self.sp_auto_max.setRange(100, 1000000)
        self.sp_manual_max = QSpinBox(); self.sp_manual_max.setRange(100, 1000000)
        self.cb_language = QComboBox(); self.cb_language.addItems(["auto", "zh", "en"]) 
        form_s.addRow("总结模式", self.cb_mode)
        form_s.addRow("自动总结间隔(秒)", self.sp_interval)
        form_s.addRow("自动总结最大字符数", self.sp_auto_max)
        form_s.addRow("手动总结最大字符数", self.sp_manual_max)
        form_s.addRow("Whisper语言", self.cb_language)
        layout.addWidget(grp_summary)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        # Load cfg values
        prov = self._cfg.get("llm_provider", "DeepSeek")
        if prov == "DeepSeek":
            self.rb_deepseek.setChecked(True)
        elif prov == "Gemini":
            self.rb_gemini.setChecked(True)
        else:
            self.rb_ollama.setChecked(True)
        self.ed_ollama_url.setText(self._cfg.get("ollama_api_url", "http://localhost:11434/api/generate"))
        self.ed_ollama_model.setText(self._cfg.get("ollama_model", "deepseek-r1:1.5b"))
        self.ed_deepseek_key.setText(self._cfg.get("deepseek_api_key", ""))
        self.ed_deepseek_model.setText(self._cfg.get("deepseek_model", "deepseek-chat"))
        self.ed_deepseek_url.setText(self._cfg.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions"))
        self.ed_gemini_key.setText(self._cfg.get("gemini_api_key", ""))
        self.ed_gemini_model.setText(self._cfg.get("gemini_model", "gemini-1.5-flash-002"))
        self.cb_mode.setCurrentText(self._cfg.get("summary_mode", "auto"))
        self.sp_interval.setValue(int(self._cfg.get("auto_summary_interval", 300)))
        self.sp_auto_max.setValue(int(self._cfg.get("auto_summary_max_chars", 8000)))
        self.sp_manual_max.setValue(int(self._cfg.get("manual_summary_max_chars", 20000)))
        self.cb_language.setCurrentText(self._cfg.get("whisper_language", "auto"))

        # Enable/disable groups by provider
        self.rb_deepseek.toggled.connect(lambda on: grp_deepseek.setEnabled(on))
        self.rb_gemini.toggled.connect(lambda on: grp_gemini.setEnabled(on))
        self.rb_ollama.toggled.connect(lambda on: grp_ollama.setEnabled(on))
        grp_deepseek.setEnabled(self.rb_deepseek.isChecked())
        grp_gemini.setEnabled(self.rb_gemini.isChecked())
        grp_ollama.setEnabled(self.rb_ollama.isChecked())

    def result_config(self) -> dict:
        cfg = dict(self._cfg)
        if self.rb_deepseek.isChecked():
            cfg["llm_provider"] = "DeepSeek"
        elif self.rb_gemini.isChecked():
            cfg["llm_provider"] = "Gemini"
        else:
            cfg["llm_provider"] = "Ollama"
        cfg["ollama_api_url"] = self.ed_ollama_url.text().strip()
        cfg["ollama_model"] = self.ed_ollama_model.text().strip()
        cfg["deepseek_api_key"] = self.ed_deepseek_key.text().strip()
        cfg["deepseek_model"] = self.ed_deepseek_model.text().strip()
        cfg["deepseek_api_url"] = self.ed_deepseek_url.text().strip()
        cfg["gemini_api_key"] = self.ed_gemini_key.text().strip()
        cfg["gemini_model"] = self.ed_gemini_model.text().strip()
        cfg["summary_mode"] = self.cb_mode.currentText()
        cfg["auto_summary_interval"] = int(self.sp_interval.value())
        cfg["auto_summary_max_chars"] = int(self.sp_auto_max.value())
        cfg["manual_summary_max_chars"] = int(self.sp_manual_max.value())
        cfg["whisper_language"] = self.cb_language.currentText()
        return cfg


# ===== Summarizer Worker =====
class SummarizerWorker(QObject):
    summaryReady = Signal(str)
    status = Signal(str)
    finished = Signal()

    def __init__(self, cfg: dict, transcript: str, prompt_tpl: str):
        super().__init__()
        self._cfg = cfg
        self._transcript = transcript
        self._prompt_tpl = prompt_tpl

    @Slot()
    def start(self):
        try:
            provider = self._cfg.get("llm_provider", "Ollama")
            text = self._transcript.strip()
            if not text:
                self.summaryReady.emit("")
                return
            prompt = self._prompt_tpl.format(text)
            if provider == "Ollama":
                content = self._summarize_with_ollama(prompt)
            else:
                content = self._summarize_with_gemini(prompt)
            self.summaryReady.emit(content or "")
        except Exception as e:
            self.status.emit(f"总结失败: {e}")
        finally:
            self.finished.emit()

    def _summarize_with_ollama(self, prompt: str) -> str:
        url = self._cfg.get("ollama_api_url", "http://localhost:11434/api/generate")
        model = self._cfg.get("ollama_model", "deepseek-r1:1.5b")
        self.status.emit(f"调用 Ollama: {model}")
        try:
            resp = requests.post(url, json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except Exception as e:
            self.status.emit(f"Ollama 调用失败: {e}")
            return ""

    def _summarize_with_gemini(self, prompt: str) -> str:
        api_key = self._cfg.get("gemini_api_key", "").strip()
        model = self._cfg.get("gemini_model", "gemini-1.5-flash-002").strip()
        if not api_key:
            self.status.emit("Gemini 未配置 API Key")
            return ""
        if not model:
            model = "gemini-1.5-flash-002"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}  # simple text prompt
            ]
        }
        self.status.emit(f"调用 Gemini: {model}")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if not resp.ok:
                self.status.emit(f"Gemini 调用失败: HTTP {resp.status_code}")
                # Try to surface short body for debugging
                try:
                    j = resp.json()
                    self.status.emit(f"错误详情: {str(j)[:300]}")
                except Exception:
                    self.status.emit(f"错误文本: {resp.text[:300]}")
                return ""
            data = resp.json()
            # Extract text
            try:
                candidates = data.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    parts = candidates[0]["content"].get("parts", [])
                    if parts and "text" in parts[0]:
                        return (parts[0]["text"] or "").strip()
            except Exception as e:
                self.status.emit(f"Gemini 解析失败: {e}")
            # Fallback: attempt to stringify data
            return ""
        except requests.exceptions.RequestException as e:
            self.status.emit(f"Gemini 请求异常: {e}")
            return ""
class ScreenshotOverlay(QWidget):
    captured = Signal(QImage)

    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._screen = screen
        self._screen_geo = screen.geometry()
        self._pixmap: QPixmap = screen.grabWindow(0)
        # HiDPI awareness
        self._dpr = float(self._pixmap.devicePixelRatio()) if hasattr(self._pixmap, 'devicePixelRatio') else 1.0
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selection: QRect | None = None
        self._double_clicked = False

    def paintEvent(self, event):
        painter = QPainter(self)
        # Draw the captured screen scaled to the widget's rect to match logical coordinates
        painter.drawPixmap(self.rect(), self._pixmap)
        # Dim the whole screen
        painter.fillRect(self.rect(), QBrush(QColor(0, 0, 0, 100)))
        # Draw selection area: undim + border
        if self._selection and not self._selection.isNull():
            sel = self._selection.normalized()
            # Re-draw original content inside selection to undim
            # Map logical selection rect to device pixels when copying from pixmap
            dev_sel = QRect(int(sel.x() * self._dpr), int(sel.y() * self._dpr), int(sel.width() * self._dpr), int(sel.height() * self._dpr))
            crop = self._pixmap.copy(dev_sel)
            painter.drawPixmap(sel, crop.scaled(sel.size()))
            # Border
            pen = QPen(QColor(0, 153, 255), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._update_selection()
            self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._current = e.position().toPoint()
            self._update_selection()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._current = e.position().toPoint()
            self._update_selection()
            self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._double_clicked = True
            self._confirm_capture()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_capture()
        elif e.key() == Qt.Key.Key_Escape:
            self.close()

    def resizeEvent(self, e):
        # Ensure overlay covers the target screen
        self.setGeometry(self._screen_geo)
        super().resizeEvent(e)

    def showEvent(self, e):
        # Fit overlay to screen geometry
        self.setGeometry(self._screen_geo)
        super().showEvent(e)

    def _update_selection(self):
        if self._origin is None or self._current is None:
            self._selection = None
            return
        x1, y1 = self._origin.x(), self._origin.y()
        x2, y2 = self._current.x(), self._current.y()
        self._selection = QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _confirm_capture(self):
        if self._selection and not self._selection.isNull():
            sel = self._selection.normalized()
            dev_sel = QRect(int(sel.x() * self._dpr), int(sel.y() * self._dpr), int(sel.width() * self._dpr), int(sel.height() * self._dpr))
            img = self._pixmap.copy(dev_sel).toImage()
            self.captured.emit(img)
        self.close()


# ===== Device level monitor dialog =====
class DeviceMonitorWorker(QObject):
    levelUpdated = Signal(int, float)  # (device_index, peak[0..1])
    listReady = Signal(list)           # list of tuples (index, label)
    finished = Signal()
    screenshotReady = Signal(str)      # filepath

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