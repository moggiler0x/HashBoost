"""Общие элементы интерфейса: плитки показателей, статусы, спарклайны."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QTableWidget, QVBoxLayout, QWidget

from . import theme


class Pill(QLabel):
    """Короткий цветной статус: «Норма», «СИМУЛЯЦИЯ», «майнер онлайн»."""

    def __init__(self, text: str = "", color: str = theme.MUTED):
        super().__init__(text)
        self.set(text, color)

    def set(self, text: str, color: str) -> None:
        self.setText(text)
        self.setStyleSheet(theme.pill_style(color))


class StatTile(QFrame):
    """Плитка KPI: подпись, крупное значение и строка-пояснение."""

    def __init__(self, caption: str, accent: bool = False, value_size: int = 24):
        super().__init__()
        self.setObjectName("tileAccent" if accent else "tile")
        self._size = value_size
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        cap = QLabel(caption.upper())
        cap.setObjectName("caption")
        self.value = QLabel("—")
        self.sub = QLabel("")
        self.sub.setObjectName("faint")
        lay.addWidget(cap)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        self.set("—")

    def set(self, text: str, color: str | None = None, sub: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size: {self._size}px; font-weight: 700; color: {color or theme.TEXT};")
        if sub is not None:
            self.sub.setText(sub)
        self.sub.setVisible(bool(self.sub.text()))


class Metric(QWidget):
    """Компактный показатель внутри карточки: значение над подписью."""

    def __init__(self, caption: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.value = QLabel("—")
        cap = QLabel(caption)
        cap.setObjectName("faint")
        lay.addWidget(self.value)
        lay.addWidget(cap)
        self.set("—")

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {color or theme.TEXT};")


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    return line


class Sparkline(QWidget):
    """Мини-график без осей; над ним подпись и текущее значение."""

    def __init__(self, caption: str, color: str, height: int = 34, fill: bool = True, header: bool = True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.value = QLabel("—")
        self.value.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
        if header:
            head = QHBoxLayout()
            cap = QLabel(caption)
            cap.setObjectName("faint")
            head.addWidget(cap)
            head.addStretch()
            head.addWidget(self.value)
            lay.addLayout(head)
        self.plot = pg.PlotWidget()
        self.plot.setFixedHeight(height)
        theme.style_plot(self.plot, axes=False)
        self.curve = self.plot.plot(pen=pg.mkPen(color, width=1.8))
        self._fill = fill
        if fill:
            self.curve.setFillLevel(0)
            self.curve.setBrush(theme.fill_brush(color))
        lay.addWidget(self.plot)

    def set_data(self, xs: list[float], ys: list[float], text: str) -> None:
        self.value.setText(text)
        if not ys:
            return
        lo, hi = min(ys), max(ys)
        span = max(hi - lo, abs(hi) * 0.04, 1e-9)
        bottom = lo - span * 0.6
        if self._fill:
            self.curve.setFillLevel(bottom)
        self.curve.setData(xs, ys)
        self.plot.setYRange(bottom, hi + span * 0.25, padding=0)
        if len(xs) > 1:
            self.plot.setXRange(xs[0], xs[-1], padding=0)


def polish_forms(root: QWidget) -> None:
    """Подписи форм по центру строки и отступ текста в числовых полях.

    QSS-отступ у QSpinBox в Qt 6 игнорируется, поэтому поля правятся напрямую.
    """
    for box in root.findChildren(QAbstractSpinBox):
        if box.lineEdit() is not None:
            box.lineEdit().setTextMargins(6, 0, 0, 0)
    for table in root.findChildren(QTableWidget):
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setDefaultSectionSize(38)
    for form in root.findChildren(QFormLayout):
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.LabelRole)
            field = form.itemAt(row, QFormLayout.FieldRole)
            if label is None or field is None or label.widget() is None:
                continue
            label.widget().setMinimumHeight(field.sizeHint().height())
            label.widget().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)


def page(content: QWidget, title: str, subtitle: str, extra: QWidget | None = None) -> QWidget:
    """Обёртка экрана: заголовок, подзаголовок, справа необязательный блок."""
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(28, 22, 28, 18)
    lay.setSpacing(16)
    head = QHBoxLayout()
    text = QVBoxLayout()
    text.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    s = QLabel(subtitle)
    s.setObjectName("pageSubtitle")
    text.addWidget(t)
    text.addWidget(s)
    head.addLayout(text)
    head.addStretch()
    if extra is not None:
        head.addWidget(extra, 0, Qt.AlignVCenter)
    lay.addLayout(head)
    content.layout().setContentsMargins(0, 0, 0, 0)
    polish_forms(content)
    lay.addWidget(content, 1)
    return wrap
