# ui/ai_assistant_panel.py
# RAG 질의응답 패널(독립 QWidget) — 채팅형 UI.
# 네트워크 호출은 워커 스레드에서만(UI 안 얼게). Task 5에서 QDockWidget에 담아 우측에 붙인다.
# 색·치수는 ui.style 토큰(S.*)만 사용(테마 적응). 이모지 금지.
import math
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices

from ui import style as S
from core import rag_client

# 빈 상태 예시 질문 2개(세로). mode는 항상 auto.
EXAMPLES = [
    "What is step width SD?",
    "How do I export results?",
]


def doi_url(doi):
    doi = (doi or "").strip()
    if not doi:
        return ""
    if doi.startswith("http"):
        return doi
    return f"https://doi.org/{doi}"


class TypingIndicator(QWidget):
    """대기 중 '생각하는 점' — 점 3개가 시차를 두고 은은하게 맥동(opacity pulse).
    Claude의 thinking indicator 느낌. 이모지 없이 색은 S.* 토큰만 사용."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dots = []
        self._effects = []
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 6, 0, 6)
        h.setSpacing(5)
        for _ in range(3):
            d = QFrame()
            d.setFixedSize(7, 7)
            d.setStyleSheet(
                f"background:{S.TEXT_MUTED}; border-radius:3px;")
            eff = QGraphicsOpacityEffect(d)
            eff.setOpacity(0.3)
            d.setGraphicsEffect(eff)
            self._dots.append(d)
            self._effects.append(eff)
            h.addWidget(d)
        h.addStretch(1)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0.0
        self._timer.start(50)

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._phase += 0.22
        for i, eff in enumerate(self._effects):
            # 점마다 위상차 → 물결처럼 흐르는 맥동. 0.25~1.0 사이.
            s = math.sin(self._phase - i * 0.9)
            eff.setOpacity(0.25 + 0.75 * (s * 0.5 + 0.5))


class AskWorker(QThread):
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, base_url, question, mode, history=None):
        super().__init__()
        self.base_url, self.question, self.mode = base_url, question, mode
        self.history = history or []
        self._cancelled = False

    def cancel(self):
        self._cancelled = True  # 요청을 죽이지 않음 — 결과만 버림

    def run(self):
        try:
            res = rag_client.ask(self.base_url, self.question, self.mode, history=self.history)
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
        self._has_messages = False
        self._last_question = ""
        self._history = []  # 멀티턴: 최근 대화 [{role, content}, ...]
        self._pending_body = None
        self._pending_src = None
        self._pending_indicator = None
        self._pending_res = None
        # 타이핑(typewriter) 상태
        self._type_tokens = []
        self._type_idx = 0
        self._type_timer = None
        self._cursor_timer = None
        self._cursor_on = True
        self.setObjectName("aiPanel")
        self.setMinimumWidth(320)
        self._build_ui()
        self._apply_style()
        self._show_empty()
        self._check_health()

    # ---- UI 골격 ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 연결 상태(작고 차분하게, 상단 한 줄)
        status = QHBoxLayout()
        status.setContentsMargins(12, 8, 12, 4)
        self.status_dot = QLabel()
        self.status_dot.setObjectName("statusDot")
        self.status_text = QLabel("Checking…")
        self.status_text.setObjectName("statusText")
        # 상태 글자/점을 클릭하면 연결을 다시 확인(재연결).
        self.status_text.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_text.setToolTip("클릭하면 연결을 다시 확인합니다 / Click to reconnect")
        self.status_text.mousePressEvent = lambda e: self._check_health()
        status.addWidget(self.status_dot)
        status.addWidget(self.status_text)
        status.addStretch(1)
        root.addLayout(status)

        # 대화 영역(스크롤)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_host = QWidget()
        self._chat_host.setObjectName("chatHost")
        self._chat_layout = QVBoxLayout(self._chat_host)
        self._chat_layout.setContentsMargins(12, 8, 12, 8)
        self._chat_layout.setSpacing(10)
        self._scroll.setWidget(self._chat_host)
        root.addWidget(self._scroll, 1)

        # 입력 바(하단 고정) — 둥근 박스 안에 입력창 + 원형 보내기 버튼
        bar = QFrame()
        bar.setObjectName("inputBar")
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(10, 4, 4, 4)
        hb.setSpacing(4)
        self.input = QLineEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("Type a message…")
        self.input.returnPressed.connect(self._on_ask)
        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.clicked.connect(self._on_ask)
        hb.addWidget(self.input, 1)
        hb.addWidget(self.send_btn)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(12, 4, 12, 12)
        wrap.addWidget(bar)
        root.addLayout(wrap)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget#aiPanel {{ background: {S.BG_DARK}; }}
            QWidget#chatHost {{ background: {S.BG_DARK}; }}
            QScrollArea {{ background: {S.BG_DARK}; border: none; }}
            QLabel#statusText {{ color: {S.TEXT_MUTED}; font-family: {S.FONT_FAMILY};
                font-size: {S.FONT_SIZE_SMALL}; }}
            QLabel#statusDot {{ min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px;
                border-radius: 4px; background: {S.TEXT_MUTED}; }}
            QLabel#emptyPrompt {{ color: {S.TEXT_MUTED}; font-family: {S.FONT_FAMILY};
                font-size: {S.FONT_SIZE_BASE}; }}
            QLabel#userBubble {{ background: {S.BG_HOVER}; color: {S.TEXT_PRIMARY};
                font-family: {S.FONT_FAMILY}; font-size: {S.FONT_SIZE_BASE};
                border-radius: {S.BORDER_RADIUS_MD};
                padding: {S.SPACING_SM} {S.SPACING_MD}; }}
            QLabel#answerBody {{ color: {S.TEXT_PRIMARY}; font-family: {S.FONT_FAMILY};
                font-size: {S.FONT_SIZE_BASE}; padding: {S.SPACING_XS} 0; }}
            QLabel#sourceLine {{ color: {S.TEXT_MUTED}; font-family: {S.FONT_FAMILY};
                font-size: {S.FONT_SIZE_SMALL}; }}
            QPushButton#exampleBtn {{ background: {S.BG_PANEL}; color: {S.TEXT_SECONDARY};
                border: 1px solid {S.BORDER}; border-radius: {S.BORDER_RADIUS_MD};
                padding: {S.SPACING_SM} {S.SPACING_MD}; font-family: {S.FONT_FAMILY};
                font-size: {S.FONT_SIZE_SMALL}; text-align: left; }}
            QPushButton#exampleBtn:hover {{ background: {S.BG_HOVER}; }}
            QFrame#inputBar {{ background: {S.BG_INPUT}; border: 1px solid {S.BORDER};
                border-radius: {S.BORDER_RADIUS_LG}; }}
            QLineEdit#chatInput {{ background: transparent; border: none; color: {S.TEXT_PRIMARY};
                font-family: {S.FONT_FAMILY}; font-size: {S.FONT_SIZE_BASE}; }}
            QPushButton#sendBtn {{ background: {S.ACCENT_TEAL}; color: {S.TEXT_INVERSE};
                border: none; border-radius: 16px; font-weight: {S.FONT_WEIGHT_BOLD};
                font-size: {S.FONT_SIZE_LARGE}; }}
            QPushButton#sendBtn:disabled {{ background: {S.TEXT_MUTED}; }}
        """)

    def _set_dot(self, color):
        self.status_dot.setStyleSheet(
            f"min-width:8px;max-width:8px;min-height:8px;max-height:8px;"
            f"border-radius:4px;background:{color};")

    # ---- 대화 영역 관리 ----
    def _clear_chat(self):
        while self._chat_layout.count():
            item = self._chat_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_empty(self):
        """첫 진입/대화 없음 — 가운데에 안내 + 예시 버튼."""
        self._clear_chat()
        self._has_messages = False
        self._chat_layout.addStretch(1)

        center = QWidget()
        v = QVBoxLayout(center)
        v.setSpacing(10)
        prompt = QLabel("Ask about the literature or how to use the app")
        prompt.setObjectName("emptyPrompt")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(prompt)
        for text in EXAMPLES:
            b = QPushButton(text)
            b.setObjectName("exampleBtn")
            b.clicked.connect(lambda _=False, t=text: self._fill_and_send(t))
            v.addWidget(b)
        self._chat_layout.addWidget(center)
        self._chat_layout.addStretch(1)

    def _enter_message_mode(self):
        self._clear_chat()
        self._chat_layout.addStretch(1)  # 메시지를 위로 쌓기 위한 말단 stretch
        self._has_messages = True

    def _append(self, widget):
        # 말단 stretch 바로 앞에 삽입(위→아래 누적).
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, widget)

    def _add_user_bubble(self, text):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setObjectName("userBubble")
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lab.setWordWrap(True)
        h.addWidget(lab, 1)  # 우측 좁은 칩 대신 전체 폭으로 길게
        self._append(row)

    def _add_answer_block(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        indicator = TypingIndicator()
        body = QLabel("")
        body.setObjectName("answerBody")
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.hide()  # 답 도착 후 타이핑 시작 때 표시
        src = QLabel("")
        src.setObjectName("sourceLine")
        src.setTextFormat(Qt.TextFormat.RichText)
        src.setWordWrap(True)
        src.setOpenExternalLinks(False)
        src.linkActivated.connect(self._open_link)
        src.hide()
        v.addWidget(indicator)
        v.addWidget(body)
        v.addWidget(src)
        self._append(box)
        return body, src, indicator

    def _scroll_bottom_later(self):
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))

    # ---- 동작 ----
    def _fill_and_send(self, text):
        self.input.setText(text)
        self._on_ask()

    def _check_health(self):
        if self._health_worker and self._health_worker.isRunning():
            return  # 이미 확인 중이면 중복 방지
        self.status_text.setText("Checking…")
        self._health_worker = HealthWorker(self.base_url)
        self._health_worker.result.connect(self._on_health)
        self._health_worker.start()

    def _on_health(self, ok):
        if self._closing:
            return
        if ok:
            self._set_dot(S.ACCENT_GREEN)
            self.status_text.setText("Connected")
        else:
            self._set_dot(S.ACCENT_RED)
            self.status_text.setText("Disconnected — check serve.py")

    def _on_ask(self):
        q = self.input.text().strip()
        if not q or (self._worker and self._worker.isRunning()):
            return
        if not self._has_messages:
            self._enter_message_mode()
        self._last_question = q
        self.input.clear()
        self._add_user_bubble(q)
        self._pending_body, self._pending_src, self._pending_indicator = self._add_answer_block()
        self._set_busy(True)
        self._pending_indicator.start()
        self._scroll_bottom_later()
        self._worker = AskWorker(self.base_url, q, "auto", history=list(self._history))
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_busy(self, busy):
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)

    def _stop_indicator(self):
        if self._pending_indicator is not None:
            self._pending_indicator.stop()
            self._pending_indicator.hide()

    # ---- 타이핑(typewriter) ----
    def _stop_typing(self):
        for t in (self._type_timer, self._cursor_timer):
            if t is not None:
                t.stop()
        self._type_timer = None
        self._cursor_timer = None

    def _start_typing(self, text):
        """답변 텍스트를 단어 단위로 점진 노출 + 끝에 깜빡이는 커서."""
        self._stop_indicator()
        self._stop_typing()
        # 공백을 포함해 토큰화(줄바꿈/연속 공백 보존).
        self._type_tokens = re.findall(r"\S+\s*", text) or ([text] if text else [])
        self._type_idx = 0
        self._cursor_on = True
        if self._pending_body is not None:
            self._pending_body.setStyleSheet("")
            self._pending_body.setText("")
            self._pending_body.show()
        if not self._type_tokens:
            self._finish_typing()
            return
        # 긴 답변도 ~3초 안에 끝나도록 틱당 토큰 수를 조절.
        self._type_step = max(1, len(self._type_tokens) // 150)
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_tick)
        self._type_timer.start(18)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._cursor_blink)
        self._cursor_timer.start(450)
        self._render_typing()

    def _typed_text(self):
        return "".join(self._type_tokens[:self._type_idx])

    def _render_typing(self):
        if self._pending_body is None:
            return
        cursor = "▍" if self._cursor_on else " "  # ▍ / 빈 폭 유지
        self._pending_body.setText(self._typed_text() + cursor)

    def _type_tick(self):
        self._type_idx = min(self._type_idx + self._type_step, len(self._type_tokens))
        self._render_typing()
        # 타이핑 따라 살짝씩 스크롤(끝에 거의 붙어 있을 때만).
        sb = self._scroll.verticalScrollBar()
        if sb.maximum() - sb.value() < 80:
            sb.setValue(sb.maximum())
        if self._type_idx >= len(self._type_tokens):
            self._finish_typing()

    def _cursor_blink(self):
        self._cursor_on = not self._cursor_on
        self._render_typing()

    def _finish_typing(self):
        self._stop_typing()
        if self._pending_body is not None:
            self._pending_body.setText(self._typed_text())  # 커서 제거, 최종 고정
        res = self._pending_res
        self._pending_res = None
        if res is not None:
            self._render_sources(res.get("sources", []))
            self.status_text.setText(f"Done ({res.get('timings', {}).get('llm', '?')}s)")
        self._scroll_bottom_later()

    def _on_done(self, res):
        if self._closing:
            return
        self._stop_indicator()
        self._set_busy(False)
        if res.get("error"):  # 방어적(서비스가 200으로 error 준 경우)
            self._render_error(res["error"])
            return
        self._set_dot(S.ACCENT_GREEN)  # 답이 왔으니 연결 정상
        answer_text = res.get("answer", "")
        # 멀티턴: 성공한 질문/답변을 대화 기억에 추가(최근 3턴=6메시지만 유지)
        if answer_text:
            self._history.append({"role": "user", "content": self._last_question})
            self._history.append({"role": "assistant", "content": answer_text})
            self._history = self._history[-6:]
        # Sources/상태는 타이핑이 끝난 뒤 표시 — res를 보관.
        self._pending_res = res
        self._start_typing(answer_text)

    def _render_sources(self, sources):
        if self._pending_src is None:
            return
        lines = []
        for i, s in enumerate(sources, 1):
            url = doi_url(s.get("doi", ""))
            label = s.get("source", "?")
            if url:
                lines.append(f'[{i}] <a href="{url}" style="color:{S.ACCENT_TEAL};">{label}</a>')
            else:
                lines.append(f"[{i}] {label}")
        if lines:
            self._pending_src.setText("Sources · " + "  ".join(lines))
            self._pending_src.show()

    def _on_failed(self, msg):
        if self._closing:
            return
        self._stop_indicator()
        self._set_busy(False)
        self._set_dot(S.ACCENT_RED)  # 실패 = 연결 문제일 수 있음
        self._render_error(msg)

    def _render_error(self, msg):
        self._stop_indicator()
        self._stop_typing()
        if self._pending_body is not None:
            self._pending_body.show()
            self._pending_body.setStyleSheet(f"color: {S.ACCENT_RED};")
            self._pending_body.setText(msg)
        if self._pending_src is not None:
            self._pending_src.setText('<a href="retry" style="color:%s;">Retry</a>' % S.ACCENT_TEAL)
            self._pending_src.show()
        self._scroll_bottom_later()

    def _open_link(self, href):
        if href == "retry":
            if self._last_question:
                self.input.setText(self._last_question)
                self._on_ask()
            return
        if href:
            QDesktopServices.openUrl(QUrl(href))

    def set_base_url(self, url):
        """설정창에서 URL 변경 시 호출 — 갱신 후 연결 상태 재확인."""
        self.base_url = url or "http://localhost:8000"
        self._check_health()

    def showEvent(self, e):
        # 패널을 (다시) 열 때마다 연결 상태를 재확인 → 토글로 재연결.
        super().showEvent(e)
        if not self._closing:
            self._check_health()

    def shutdown(self):
        """앱 종료 시 메인 창의 closeEvent에서 호출 — 워커 정리(크래시 방지).
        패널은 dock에 임베드돼 자체 closeEvent를 못 받으므로 외부에서 호출한다."""
        self._closing = True
        self._stop_typing()
        self._stop_indicator()
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
