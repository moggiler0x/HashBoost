"""Калькулятор розетки: тариф, доходность алгоритма, доход/свет/прибыль."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..config import UNIT_MULTIPLIERS, save_config
from ..core.profit import fetch_revenue
from ..core.runtime import Runtime, Snapshot
from ..models import format_hashrate
from . import theme


def spin(minimum: float, maximum: float, decimals: int, suffix: str = "", step: float = 1.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    if suffix:
        box.setSuffix(suffix)
    return box


class Calculator(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        cfg = runtime.cfg
        cur = cfg.currency
        lay = QHBoxLayout(self)

        left = QVBoxLayout()
        power_box = QGroupBox("Розетка")
        form = QFormLayout(power_box)
        self.tariff = spin(0, 1000, 3, f" {cur}/кВт·ч", 0.1)
        self.tariff.setValue(cfg.tariff_per_kwh)
        self.psu = spin(50, 100, 1, " %", 1)
        self.psu.setValue(cfg.psu_efficiency * 100)
        self.base = spin(0, 2000, 0, " Вт", 5)
        self.base.setValue(cfg.rig_base_power_w)
        form.addRow("Тариф", self.tariff)
        form.addRow("КПД блока питания", self.psu)
        form.addRow("Платформа (CPU, плата)", self.base)
        left.addWidget(power_box)

        algo_box = QGroupBox("Доходность монеты")
        aform = QFormLayout(algo_box)
        self.algo = QComboBox()
        self.algo.addItems(sorted(cfg.algorithms))
        self.algo.setCurrentText(runtime.algorithm)
        self.coin = QLineEdit()
        self.revenue = spin(0, 1e9, 6, "", 0.01)
        self.unit = QComboBox()
        self.unit.addItems(list(UNIT_MULTIPLIERS))
        self.fee = spin(0, 100, 2, " %", 0.1)
        self.api_url = QLineEdit()
        self.api_url.setPlaceholderText("https://... (необязательно)")
        self.api_path = QLineEdit()
        self.api_path.setPlaceholderText("путь к числу в JSON, например data.revenue")
        aform.addRow("Алгоритм", self.algo)
        aform.addRow("Монета", self.coin)
        rev_row = QHBoxLayout()
        rev_row.addWidget(self.revenue, 1)
        rev_row.addWidget(QLabel(f"{cur}/сут за 1"))
        rev_row.addWidget(self.unit)
        aform.addRow("Доход", rev_row)
        aform.addRow("Комиссия пула", self.fee)
        aform.addRow("API доходности", self.api_url)
        aform.addRow("Поле в ответе", self.api_path)
        fetch = QPushButton("Подтянуть по API")
        fetch.clicked.connect(self._fetch)
        aform.addRow("", fetch)
        left.addWidget(algo_box)

        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        left.addWidget(save)
        left.addStretch()
        lay.addLayout(left, 2)

        right = QVBoxLayout()
        totals = QGroupBox("Итог по ригу")
        grid = QGridLayout(totals)
        headers = ["", "в сутки", "в месяц"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setObjectName("muted")
            grid.addWidget(lbl, 0, col)
        self.cells = {}
        for row, (key, caption) in enumerate([("gross", "Грязный доход"), ("cost", "Электричество"),
                                              ("net", "Чистая прибыль")], start=1):
            grid.addWidget(QLabel(caption), row, 0)
            for col, period in enumerate(("day", "month"), start=1):
                lbl = QLabel("—")
                lbl.setObjectName("big")
                grid.addWidget(lbl, row, col)
                self.cells[(key, period)] = lbl
        self.wall = QLabel()
        self.wall.setObjectName("muted")
        grid.addWidget(self.wall, 4, 0, 1, 3)
        right.addWidget(totals)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["GPU", "Хешрейт", "Вт", f"Доход {cur}/сут", f"Свет {cur}/сут",
                                              f"Чистыми {cur}/сут"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table, 1)
        lay.addLayout(right, 3)

        self.algo.currentTextChanged.connect(self._load_algo)
        self._load_algo(self.algo.currentText())
        for w in (self.tariff, self.psu, self.base, self.revenue, self.fee):
            w.valueChanged.connect(self._apply_live)
        self.unit.currentTextChanged.connect(self._apply_live)

    def _load_algo(self, name: str) -> None:
        a = self.runtime.cfg.algorithm(name)
        for w in (self.revenue, self.fee, self.unit):
            w.blockSignals(True)
        self.coin.setText(a.coin)
        self.revenue.setValue(a.revenue_per_unit_day)
        self.unit.setCurrentText(a.unit)
        self.fee.setValue(a.pool_fee_pct)
        self.api_url.setText(a.price_api_url)
        self.api_path.setText(a.price_json_path)
        for w in (self.revenue, self.fee, self.unit):
            w.blockSignals(False)

    def _apply_live(self, *_):
        cfg = self.runtime.cfg
        cfg.tariff_per_kwh = self.tariff.value()
        cfg.psu_efficiency = self.psu.value() / 100
        cfg.rig_base_power_w = self.base.value()
        a = cfg.algorithm(self.algo.currentText())
        a.coin = self.coin.text()
        a.revenue_per_unit_day = self.revenue.value()
        a.unit = self.unit.currentText()
        a.pool_fee_pct = self.fee.value()
        a.price_api_url = self.api_url.text().strip()
        a.price_json_path = self.api_path.text().strip()

    def _save(self) -> None:
        self._apply_live()
        save_config(self.runtime.cfg)

    def _fetch(self) -> None:
        self._apply_live()
        a = self.runtime.cfg.algorithm(self.algo.currentText())
        try:
            self.revenue.setValue(fetch_revenue(a))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Доходность", f"Не удалось получить данные: {exc}")

    def refresh(self, snap: Snapshot) -> None:
        t = snap.total
        if t:
            values = {("gross", "day"): t.revenue_per_day, ("gross", "month"): t.revenue_per_month,
                      ("cost", "day"): t.cost_per_day, ("cost", "month"): t.cost_per_month,
                      ("net", "day"): t.net_per_day, ("net", "month"): t.net_per_month}
            for key, value in values.items():
                lbl = self.cells[key]
                lbl.setText(f"{value:,.2f} {self.runtime.cfg.currency}".replace(",", " "))
                if key[0] == "net":
                    lbl.setStyleSheet(f"color: {theme.GOOD if value >= 0 else theme.BAD};")
            self.wall.setText(f"Потребление из розетки: {t.wall_power_w:.0f} Вт · "
                              f"{t.wall_power_w * 24 / 1000:.1f} кВт·ч в сутки")
        self.table.setRowCount(len(snap.gpus))
        for row, (idx, g) in enumerate(sorted(snap.gpus.items())):
            p = g.profit
            cells = [self.runtime.rig[idx].label, format_hashrate(g.miner.hashrate) if g.miner else "—",
                     f"{g.telemetry.power_w:.0f}" if g.telemetry and g.telemetry.power_w else "—",
                     f"{p.revenue_per_day:.2f}" if p else "—", f"{p.cost_per_day:.2f}" if p else "—",
                     f"{p.net_per_day:.2f}" if p else "—"]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
