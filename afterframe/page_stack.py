from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPauseAnimation,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from .constants import APP_NAME, APP_VERSION_SHORT, ICON_FONT_FAMILY, ui_font
from .theme import ThemeAnimator, rgba, theme_for_page


class PageStack(QWidget):
    """A page container that switches pages with a squeeze-style transition."""

    switch_started = Signal(bool)
    switch_finished = Signal(bool)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._pages: list[QWidget] = []
        self._current_index = -1
        self._anim_group = None

    def add_page(self, page: QWidget) -> int:
        page.setParent(self)
        page.hide()
        self._pages.append(page)
        if self._current_index == -1:
            self._current_index = 0
            page.setGeometry(self.rect())
            page.show()
        return len(self._pages) - 1

    def current_index(self) -> int:
        return self._current_index

    def switch_page(self, index: int) -> None:
        if index == self._current_index or not (0 <= index < len(self._pages)):
            return

        old_page = self._pages[self._current_index]
        new_page = self._pages[index]
        direction = 1 if index > self._current_index else -1
        self._current_index = index

        w = self.width()
        h = self.height()

        new_page.show()
        new_page.raise_()

        if direction > 0:
            # New page comes from below, squeezes old page upward.
            new_page.setGeometry(0, h, w, h)
            self._animate(
                old_page,
                QRect(0, 0, w, h),
                QRect(0, 0, w, 0),
                new_page,
                QRect(0, h, w, h),
                QRect(0, 0, w, h),
            )
        else:
            # New page comes from above, squeezes old page downward.
            new_page.setGeometry(0, -h, w, h)
            self._animate(
                old_page,
                QRect(0, 0, w, h),
                QRect(0, h, w, 0),
                new_page,
                QRect(0, -h, w, h),
                QRect(0, 0, w, h),
            )

    def _animate(
        self,
        old_page: QWidget,
        old_start: QRect,
        old_end: QRect,
        new_page: QWidget,
        new_start: QRect,
        new_end: QRect,
    ) -> None:
        old_page.setGeometry(old_start)
        new_page.setGeometry(new_start)

        duration = 550
        easing = QEasingCurve.OutBack

        anim_old = QPropertyAnimation(old_page, b"geometry")
        anim_old.setDuration(duration)
        anim_old.setStartValue(old_start)
        anim_old.setEndValue(old_end)
        anim_old.setEasingCurve(easing)

        anim_new = QPropertyAnimation(new_page, b"geometry")
        anim_new.setDuration(duration)
        anim_new.setStartValue(new_start)
        anim_new.setEndValue(new_end)
        anim_new.setEasingCurve(easing)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_old)
        self._anim_group.addAnimation(anim_new)
        self._anim_group.finished.connect(
            lambda: self._on_switch_finished(old_page, new_page)
        )

        self.switch_started.emit(True)
        self._anim_group.start()

    def _on_switch_finished(
        self, old_page: QWidget, new_page: QWidget
    ) -> None:
        old_page.hide()
        new_page.setGeometry(self.rect())
        self.switch_finished.emit(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._pages and 0 <= self._current_index < len(self._pages):
            page = self._pages[self._current_index]
            page.setGeometry(self.rect())
            page.show()
            page.raise_()
            page.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        for i, page in enumerate(self._pages):
            if i == self._current_index and page.isVisible():
                page.setGeometry(self.rect())


class _SidebarAccent(QWidget):
    """Small vertical accent bar marking the active icon."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(118, 185, 0))
        painter.drawRect(self.rect())


class Sidebar(QFrame):
    """A slim vertical sidebar with icon buttons for page switching."""

    page_selected = Signal(int)

    ICON_SIZE = 52
    WIDTH = 72
    ACCENT_WIDTH = 4

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setFrameShape(QFrame.NoFrame)
        # The background is painted in paintEvent so it can follow the current
        # page theme; only the buttons need stylesheet rules.
        self.setStyleSheet("""
            Sidebar {
                background: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 14)
        layout.setSpacing(0)

        # Icons live in their own top-aligned column so the bottom of the
        # sidebar stays free for the brand signature.
        self._icon_layout = QVBoxLayout()
        self._icon_layout.setContentsMargins(0, 0, 0, 0)
        self._icon_layout.setSpacing(12)
        self._icon_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addLayout(self._icon_layout)
        layout.addStretch(1)

        self._buttons: list[QPushButton] = []
        self._current_index = -1

        # Page-following chrome palette, cross-faded on page switches.
        self._theme = theme_for_page(0)
        self._themer = ThemeAnimator(self._apply_theme, self)

        self._accent = _SidebarAccent(self)
        self._accent.hide()
        self._anim_accent: QSequentialAnimationGroup | None = None

    def set_theme(self, theme: dict, animate: bool = True) -> None:
        """Adopt the palette of the page that is now active."""
        self._themer.to(theme, animate=animate)

    @staticmethod
    def _button_style(theme: dict) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {rgba(theme['icon_idle'])};
                border: none;
                border-radius: 14px;
                font-family: "{ICON_FONT_FAMILY}";
                font-size: 22px;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: {rgba(theme['icon_hover'])};
            }}
            QPushButton:checked {{
                color: {rgba(theme['icon_active'])};
            }}
        """

    def _apply_theme(self, theme: dict) -> None:
        self._theme = theme
        style = self._button_style(theme)
        for btn in self._buttons:
            btn.setStyleSheet(style)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._theme["chrome_bg"])
        painter.setPen(QPen(self._theme["chrome_border"], 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        self._draw_signature(painter)

    def _draw_signature(self, painter: QPainter) -> None:
        """Rotated brand wordmark plus a green version tag, bottom-left.

        Drawn here (rather than as a widget) so it follows the page theme and
        fades with it during page switches.
        """
        if self.height() < 220:
            return

        accent = QColor(self._theme["icon_active"])
        text_color = QColor(self._theme["text"])
        text_color.setAlpha(120)
        rule_color = QColor(self._theme["text"])
        rule_color.setAlpha(45)

        bottom = self.height() - 14

        # Version tag at the very bottom, centered.
        ver_font = ui_font(7)
        ver_font.setWeight(QFont.Bold)
        ver_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        painter.setFont(ver_font)
        ver_metrics = QFontMetrics(ver_font)
        version = APP_VERSION_SHORT.upper()
        ver_w = ver_metrics.horizontalAdvance(version)
        painter.setPen(accent)
        painter.drawText(
            QPointF((self.width() - ver_w) / 2.0, bottom - 2), version
        )

        # Rotated wordmark reading bottom-to-top above the version tag.
        word_font = ui_font(9)
        word_font.setWeight(QFont.Bold)
        word_font.setLetterSpacing(QFont.AbsoluteSpacing, 2.4)
        painter.setFont(word_font)
        word_metrics = QFontMetrics(word_font)
        word = APP_NAME.upper()

        # Keep clear of the wordmark: some fonts draw glyph boxes wider than
        # the reported advance, so the gap is deliberately generous.
        start_y = bottom - ver_metrics.height() - 26
        ascent = word_metrics.ascent()
        descent = word_metrics.descent()
        word_w = word_metrics.horizontalAdvance(word)
        # Center the rotated glyphs horizontally: after rotating -90 the text
        # grows upward and its glyph box spans [pivot.x - descent, pivot.x + ascent].
        pivot_x = self.width() / 2.0 - (ascent - descent) / 2.0

        painter.save()
        painter.translate(pivot_x, start_y)
        painter.rotate(-90)
        painter.setPen(text_color)
        painter.drawText(QPointF(0, 0), word)
        # Thin rule alongside the wordmark (on its left once rotated). It runs
        # along the text direction, i.e. offset in rotated-Y only.
        painter.setPen(QPen(rule_color, 1))
        rule_y = descent + 8
        painter.drawLine(QPointF(0, rule_y), QPointF(word_w, rule_y))
        painter.restore()

        # Small brand square just above the wordmark.
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        side = 4.0
        top_y = start_y - word_w - 10
        painter.drawRect(
            QRectF(self.width() / 2.0 - side / 2.0, top_y - side, side, side)
        )

    def add_icon(self, icon: str, tooltip: str = "") -> int:
        btn = QPushButton(icon)
        btn.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(True)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(self._button_style(self._theme))
        idx = len(self._buttons)
        btn.clicked.connect(lambda checked, i=idx: self._on_clicked(i))
        self._icon_layout.addWidget(btn, 0, Qt.AlignHCenter)
        self._buttons.append(btn)
        btn.raise_()
        if idx == 0:
            btn.setChecked(True)
            self._current_index = 0
        return idx

    def set_current(self, index: int) -> None:
        if index == self._current_index or not (0 <= index < len(self._buttons)):
            return
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)

        self._current_index = index
        target_geo = self._buttons[index].geometry()
        target_accent = self._accent_geometry(target_geo)

        if not self._accent.isVisible():
            self._accent.setGeometry(target_accent)
            self._accent.show()
            self._raise_buttons()
            return

        start_accent = self._accent.geometry()
        self._anim_accent = QSequentialAnimationGroup(self)
        pause = QPauseAnimation(70, self)
        accent_anim = QPropertyAnimation(self._accent, b"geometry", self)
        accent_anim.setDuration(480)
        accent_anim.setStartValue(start_accent)
        accent_anim.setEndValue(target_accent)
        accent_anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim_accent.addAnimation(pause)
        self._anim_accent.addAnimation(accent_anim)
        self._anim_accent.start()

    def clear_selection(self) -> None:
        """Deselect every icon (used while a page without an icon is open)."""
        self._current_index = -1
        for btn in self._buttons:
            btn.setChecked(False)
        if self._anim_accent is not None:
            self._anim_accent.stop()
        self._accent.hide()

    def _accent_geometry(self, btn_geo: QRect) -> QRect:
        return QRect(
            btn_geo.x(),
            btn_geo.y(),
            self.ACCENT_WIDTH,
            btn_geo.height(),
        )

    def _on_clicked(self, index: int) -> None:
        self.set_current(index)
        self.page_selected.emit(index)

    def _raise_buttons(self) -> None:
        for btn in self._buttons:
            btn.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._current_index >= 0:
            geo = self._accent_geometry(self._buttons[self._current_index].geometry())
            self._accent.setGeometry(geo)
            self._accent.show()
            self._raise_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._current_index >= 0:
            geo = self._accent_geometry(self._buttons[self._current_index].geometry())
            self._accent.setGeometry(geo)
            self._raise_buttons()
