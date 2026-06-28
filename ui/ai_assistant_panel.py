# ui/ai_assistant_panel.py
# RAG 질의응답 패널(독립 QWidget). 네트워크 호출은 워커 스레드에서만(UI 안 얼게).
# Task 5에서 QDockWidget에 담아 메인 창 오른쪽에 붙인다.
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTextBrowser,
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices

from ui import style as S
from core import rag_client

EXAMPLES = [
    ("step width SD가 뭔가요?", "auto"),
    ("결과를 어떻게 내보내나요?", "manual"),
    ("국소 동적 안정성과 보행 변동성 차이는?", "paper"),
]
MODES = [("자동", "auto"), ("사용법", "manual"), ("논문", "paper")]


def doi_url(doi):
    doi = (doi or "").strip()
    if not doi:
        return ""
    if doi.startswith("http"):
        return doi
    return f"https://doi.org/{doi}"


class AskWorker(QThread):
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, base_url, question, mode):
        super().__init__()
        self.base_url, self.question, self.mode = base_url, question, mode
        self._cancelled = False

    def cancel(self):
        self._cancelled = True  # 요청을 죽이지 않음 — 결과만 버림

    def run(self):
        try:
            res = rag_client.ask(self.base_url, self.question, self.mode)
            if not self._cancelled:
                self.done.emit(res)
        except rag_client.RagError as e:
            if not self._cancelled:
                self.failed.emit(str(e))
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(f"예상치 못한 오류: {e}")


class HealthWorker(QThread):
    result = pyqtSignal(bool)

    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url

    def run(self):
        try:
            rag_client.health(self.base_url)
            self.result.emit(True)
        except Exception:
            self.result.emit(False)


class AiAssistantPanel(QWidget):
    def __init__(self, parent=None, base_url="http://localhost:8000"):
        super().__init__(parent)
        self.base_url = base_url
        self._worker = None
        self._health_worker = None
        self._closing = False
        self._dots = 0
        self.setObjectName("aiPanel")
        self.setMinimumWidth(320)
        self._build_ui()
        self._apply_style()
        self._check_health()

    def _build_ui(self):
        root = QVBoxLayout(self)

        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("연결 확인 중…")
        top = QHBoxLayout()
        top.addWidget(self.status_dot)
        top.addWidget(self.status_text)
        top.addStretch(1)
        root.addLayout(top)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("질문을 입력하세요 (Enter)")
        self.input.returnPressed.connect(self._on_ask)
        self.mode = QComboBox()
        for label, _ in MODES:
            self.mode.addItem(label)
        self.ask_btn = QPushButton("질문")
        self.ask_btn.setObjectName("askBtn")
        self.ask_btn.clicked.connect(self._on_ask)
        row.addWidget(self.input, 1)
        row.addWidget(self.mode)
        row.addWidget(self.ask_btn)
        root.addLayout(row)

        ex = QHBoxLayout()
        ex.addWidget(QLabel("예시:"))
        for text, m in EXAMPLES:
            b = QPushButton(text)
            b.setObjectName("exampleBtn")
            b.clicked.connect(lambda _, t=text, mm=m: self._fill_example(t, mm))
            ex.addWidget(b)
        ex.addStretch(1)
        root.addLayout(ex)

        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(False)
        root.addWidget(self.answer, 1)

        root.addWidget(QLabel("출처"))
        self.sources = QTextBrowser()
        self.sources.setMaximumHeight(120)
        self.sources.setOpenLinks(False)
        self.sources.anchorClicked.connect(self._open_source)
        root.addWidget(self.sources)

        self.retry_btn = QPushButton("다시 시도")
        self.retry_btn.clicked.connect(self._on_ask)
        self.retry_btn.hide()
        root.addWidget(self.retry_btn)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget#aiPanel {{ background: {S.BG_DARK}; }}
            QLabel {{ color: {S.TEXT_SECONDARY}; font-family: {S.FONT_FAMILY}; font-size: {S.FONT_SIZE_BASE}; }}
            QLineEdit, QComboBox, QTextBrowser {{
                background: {S.BG_INPUT}; color: {S.TEXT_PRIMARY};
                border: 1px solid {S.BORDER}; border-radius: {S.BORDER_RADIUS_MD};
                padding: {S.SPACING_SM}; font-family: {S.FONT_FAMILY}; font-size: {S.FONT_SIZE_BASE};
            }}
            QLineEdit:focus {{ border: 1px solid {S.BORDER_FOCUS}; }}
            QPushButton#askBtn {{
                background: {S.ACCENT_TEAL}; color: {S.TEXT_INVERSE};
                border: none; border-radius: {S.BORDER_RADIUS_MD};
                padding: {S.SPACING_SM} {S.SPACING_LG}; min-height: {S.BUTTON_HEIGHT};
                font-weight: {S.FONT_WEIGHT_BOLD};
            }}
            QPushButton#askBtn:disabled {{ background: {S.TEXT_MUTED}; }}
            QPushButton#exampleBtn {{
                background: {S.BG_PANEL}; color: {S.TEXT_SECONDARY};
                border: 1px solid {S.BORDER}; border-radius: {S.BORDER_RADIUS_FULL};
                padding: {S.SPACING_XS} {S.SPACING_MD}; font-size: {S.FONT_SIZE_SMALL};
            }}
            QLabel#statusDot {{ min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px;
                border-radius: 5px; background: {S.TEXT_MUTED}; }}
        """)

    def _set_dot(self, color):
        self.status_dot.setStyleSheet(
            f"min-width:10px;max-width:10px;min-height:10px;max-height:10px;border-radius:5px;background:{color};")

    def _fill_example(self, text, mode):
        self.input.setText(text)
        for i, (_, m) in enumerate(MODES):
            if m == mode:
                self.mode.setCurrentIndex(i)

    def _check_health(self):
        self.status_text.setText("연결 확인 중…")
        self._health_worker = HealthWorker(self.base_url)
        self._health_worker.result.connect(self._on_health)
        self._health_worker.start()

    def _on_health(self, ok):
        if self._closing:
            return
        if ok:
            self._set_dot(S.ACCENT_GREEN)
            self.status_text.setText("연결됨")
        else:
            self._set_dot(S.ACCENT_RED)
            self.status_text.setText("연결 끊김 — serve.py가 켜져 있는지 확인하세요")

    def _on_ask(self):
        q = self.input.text().strip()
        if not q or (self._worker and self._worker.isRunning()):
            return
        self.retry_btn.hide()
        self.answer.clear()
        self.sources.clear()
        self.ask_btn.setEnabled(False)
        self.ask_btn.setText("생성 중…")
        self._start_dots()
        mode = MODES[self.mode.currentIndex()][1]
        self._worker = AskWorker(self.base_url, q, mode)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _start_dots(self):
        if getattr(self, "_timer", None):
            self._timer.stop()
        self._dots = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(400)
        self._tick()

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.status_text.setText("검색·답변 생성 중" + "." * self._dots)

    def _stop_busy(self):
        if getattr(self, "_timer", None):
            self._timer.stop()
        self.ask_btn.setEnabled(True)
        self.ask_btn.setText("질문")
        self.status_text.setStyleSheet("")  # 이전 에러 빨강색 해제

    def _on_done(self, res):
        if self._closing:
            return
        self._stop_busy()
        self.status_text.setText(f"완료 ({res.get('timings', {}).get('llm', '?')}s)")
        self.answer.setPlainText(res.get("answer", ""))
        lines = []
        for i, s in enumerate(res.get("sources", []), 1):
            url = doi_url(s.get("doi", ""))
            label = s.get("source", "?")
            if url:
                lines.append(f'[{i}] <a href="{url}">{label}</a>')
            else:
                lines.append(f"[{i}] {label}")
        self.sources.setHtml("<br>".join(lines) if lines else "(출처 없음)")

    def _on_failed(self, msg):
        if self._closing:
            return
        self._stop_busy()
        self.status_text.setText(msg)
        self.status_text.setStyleSheet(f"color: {S.ACCENT_RED};")
        self.retry_btn.show()

    def _open_source(self, url: QUrl):
        if url.toString():
            QDesktopServices.openUrl(url)

    def set_base_url(self, url):
        """설정창에서 URL 변경 시 호출 — 갱신 후 연결 상태 재확인."""
        self.base_url = url or "http://localhost:8000"
        self._check_health()

    def shutdown(self):
        """앱 종료 시 메인 창의 closeEvent에서 호출 — 워커 정리(크래시 방지)."""
        self._closing = True
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
            if self._worker.isRunning():
                try:
                    self._worker.done.disconnect()
                    self._worker.failed.disconnect()
                except Exception:
                    pass
        if self._health_worker and self._health_worker.isRunning():
            self._health_worker.wait(2000)
            if self._health_worker.isRunning():
                try:
                    self._health_worker.result.disconnect()
                except Exception:
                    pass
