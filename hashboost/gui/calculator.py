"""Калькулятор розетки: тариф, доходность алгоритма, доход/свет/прибыль."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..config import TARIFF_PRESETS, UNIT_MULTIPLIERS, save_config
from ..core.advisor import best_rig_algorithm
from ..core.market import SOURCE
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


def short_coin(coin: str) -> str:
    """«Pearl (PRL)» → «Pearl»: в таблице каждый символ на счету."""
    return coin.split(" (")[0]


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
        self.mode = QComboBox()
        self.mode.addItem("Однотарифный", "single")
        self.mode.addItem("Двухтарифный (день / ночь)", "dual")
        self.mode.setCurrentIndex(1 if cfg.tariff_mode == "dual" else 0)
        self.preset = QComboBox()
        self.preset.addItem("Свой тариф")
        self.preset.addItems(list(TARIFF_PRESETS))
        for i, values in enumerate(TARIFF_PRESETS.values(), start=1):
            if values == (cfg.tariff_per_kwh, cfg.tariff_day, cfg.tariff_night):
                self.preset.setCurrentIndex(i)
        self.tariff = spin(0, 1000, 2, f" {cur}/кВт·ч", 0.1)
        self.tariff.setValue(cfg.tariff_per_kwh)
        self.day = spin(0, 1000, 2, f" {cur}/кВт·ч", 0.1)
        self.day.setValue(cfg.tariff_day)
        self.night = spin(0, 1000, 2, f" {cur}/кВт·ч", 0.1)
        self.night.setValue(cfg.tariff_night)
        self.night_from = QSpinBox()
        self.night_from.setRange(0, 23)
        self.night_from.setSuffix(":00")
        self.night_from.setValue(cfg.night_start_hour)
        self.night_to = QSpinBox()
        self.night_to.setRange(0, 23)
        self.night_to.setSuffix(":00")
        self.night_to.setValue(cfg.night_end_hour)
        hours = QHBoxLayout()
        hours.addWidget(QLabel("с"))
        hours.addWidget(self.night_from)
        hours.addWidget(QLabel("до"))
        hours.addWidget(self.night_to)
        self.effective = QLabel()
        self.effective.setObjectName("muted")
        self.effective.setWordWrap(True)
        self.psu = spin(50, 100, 1, " %", 1)
        self.psu.setValue(cfg.psu_efficiency * 100)
        self.base = spin(0, 2000, 0, " Вт", 5)
        self.base.setValue(cfg.rig_base_power_w)
        form.addRow("Счётчик", self.mode)
        form.addRow("Тарифы", self.preset)
        form.addRow("Тариф", self.tariff)
        form.addRow("День", self.day)
        form.addRow("Ночь", self.night)
        self.night_hours_row = QWidget()
        self.night_hours_row.setLayout(hours)
        hours.setContentsMargins(0, 0, 0, 0)
        form.addRow("Ночная зона", self.night_hours_row)
        form.addRow("", self.effective)
        form.addRow("КПД блока питания", self.psu)
        form.addRow("Платформа (CPU, плата)", self.base)
        self.power_form = form
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
        self.night_only = QLabel()
        self.night_only.setWordWrap(True)
        grid.addWidget(self.night_only, 5, 0, 1, 3)
        right.addWidget(totals)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["GPU", "Хешрейт", "Вт", f"Доход {cur}/сут", f"Свет {cur}/сут",
                                              f"Чистыми {cur}/сут"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table, 1)

        advice_box = QGroupBox("Самая выгодная монета для каждой карты")
        ab = QVBoxLayout(advice_box)
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Курс доллара для цен карт:"))
        self.usd = spin(1, 1000, 2, f" {cur}/$", 0.5)
        self.usd.setValue(cfg.usd_rate)
        rate_row.addWidget(self.usd)
        rate_row.addStretch()
        ab.addLayout(rate_row)
        self.advice = QTableWidget(0, 7)
        self.advice.setHorizontalHeaderLabels(["GPU", "Лучшая монета", "Хешрейт / Вт", f"Чистыми {cur}/сут",
                                               "Другие монеты", f"Цена карты, {cur}", "Окупаемость"])
        self.advice.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.advice.horizontalHeader().setStretchLastSection(True)
        self.advice.verticalHeader().setVisible(False)
        self.advice.itemChanged.connect(self._price_edited)
        ab.addWidget(self.advice, 1)
        self.advice_note = QLabel()
        self.advice_note.setObjectName("muted")
        self.advice_note.setWordWrap(True)
        ab.addWidget(self.advice_note)
        right.addWidget(advice_box, 2)
        lay.addLayout(right, 3)

        self.algo.currentTextChanged.connect(self._load_algo)
        self._load_algo(self.algo.currentText())
        for w in (self.tariff, self.day, self.night, self.psu, self.base, self.revenue, self.fee, self.usd):
            w.valueChanged.connect(self._apply_live)
        for w in (self.night_from, self.night_to):
            w.valueChanged.connect(self._apply_live)
        self._loading_preset = False
        for w in (self.tariff, self.day, self.night):
            w.valueChanged.connect(self._tariff_edited)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.preset.currentIndexChanged.connect(self._preset_chosen)
        self.unit.currentTextChanged.connect(self._apply_live)
        self._mode_changed()
        self.refresh_advice()

    # --- тариф ---
    def _mode_changed(self, *_):
        dual = self.mode.currentData() == "dual"
        self.power_form.setRowVisible(self.tariff, not dual)
        for widget in (self.day, self.night, self.night_hours_row):
            self.power_form.setRowVisible(widget, dual)
        self._apply_live()

    def _tariff_edited(self, *_):
        if not self._loading_preset:
            self.preset.setCurrentIndex(0)  # тариф правят руками — это уже не пресет

    def _preset_chosen(self, index: int) -> None:
        if index <= 0:
            return
        single, day, night = TARIFF_PRESETS[self.preset.currentText()]
        self._loading_preset = True
        self.tariff.setValue(single)
        self.day.setValue(day)
        self.night.setValue(night)
        self.night_from.setValue(23)
        self.night_to.setValue(7)
        self._loading_preset = False
        self._apply_live()

    def _describe_tariff(self) -> None:
        cfg = self.runtime.cfg
        cur = cfg.currency
        if cfg.tariff_mode == "dual":
            text = (f"Ночь {cfg.night_hours} ч, день {24 - cfg.night_hours} ч. "
                    f"При работе 24/7 средняя цена {cfg.effective_tariff():.2f} {cur}/кВт·ч")
        else:
            text = f"Цена 24/7: {cfg.effective_tariff():.2f} {cur}/кВт·ч"
        self.effective.setText(text + ". Пресеты — тарифы Москвы с 01.10.2026.")

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
        if not hasattr(self, "advice"):
            return  # виджеты ещё создаются
        cfg = self.runtime.cfg
        cfg.tariff_mode = self.mode.currentData()
        cfg.tariff_per_kwh = self.tariff.value()
        cfg.tariff_day = self.day.value()
        cfg.tariff_night = self.night.value()
        cfg.night_start_hour = self.night_from.value()
        cfg.night_end_hour = self.night_to.value()
        cfg.usd_rate = self.usd.value()
        cfg.psu_efficiency = self.psu.value() / 100
        cfg.rig_base_power_w = self.base.value()
        a = cfg.algorithm(self.algo.currentText())
        a.coin = self.coin.text()
        a.revenue_per_unit_day = self.revenue.value()
        a.unit = self.unit.currentText()
        a.pool_fee_pct = self.fee.value()
        a.price_api_url = self.api_url.text().strip()
        a.price_json_path = self.api_path.text().strip()
        self._describe_tariff()
        self.refresh_advice()

    # --- лучшая монета и окупаемость ---
    def refresh_advice(self) -> None:
        cfg = self.runtime.cfg
        cur = cfg.currency
        advice = self.runtime.advice()
        self.advice.blockSignals(True)
        self.advice.setRowCount(len(advice))
        for row, card in enumerate(advice):
            best = card.best
            others = ", ".join(f"{short_coin(e.coin)} {e.profit.net_per_day:.2f}" for e in card.estimates[1:]) or "—"
            label = self.runtime.rig[card.gpu.index].label.replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "")
            if best is None:
                cells = [label, "нет данных", "—", "—", others]
            else:
                cells = [label, short_coin(best.coin),
                         f"{format_hashrate(best.hashrate)} / {best.power_w:.0f}", f"{best.profit.net_per_day:.2f}",
                         others]
            days = card.payback_days
            if card.price <= 0:
                payback = "укажите цену"
            elif days is None:
                payback = "не окупится"
            else:
                payback = f"{days:.0f} дн."
            cells += [f"{card.price:.0f}", payback]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col in (1, 2) and best is not None:
                    item.setToolTip(f"Данные: {best.source}")
                if col == 6 and days:
                    item.setToolTip(f"≈ {days / 30:.1f} мес.")
                if col != 5:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                else:
                    item.setData(Qt.UserRole, card.gpu.uid)
                    item.setToolTip("Цена покупки карты; по умолчанию — цена из рейтинга Kryptex по курсу")
                if col == 3 and best is not None:
                    item.setForeground(QColor(theme.GOOD if best.profit.net_per_day >= 0 else theme.BAD))
                self.advice.setItem(row, col, item)
        self.advice.blockSignals(False)
        rig_best = best_rig_algorithm(advice)
        note = (f"До калибровки — типичные цифры модели ({SOURCE}), после — замеры ваших карт. "
                f"Окупаемость = цена карты / чистая прибыль на лучшей монете при текущем тарифе.")
        if rig_best:
            coin = cfg.algorithm(rig_best[0]).coin or rig_best[0]
            note += f" Если весь риг майнит одну монету, выгоднее всего {coin}: {rig_best[1]:.2f} {cur}/сут."
        self.advice_note.setText(note)

    def _price_edited(self, item: QTableWidgetItem) -> None:
        uid = item.data(Qt.UserRole)
        if not uid:
            return
        try:
            price = float(item.text().replace(" ", "").replace(",", "."))
        except ValueError:
            price = None
        if price is None or price < 0:
            self.runtime.cfg.card_prices.pop(uid, None)
        else:
            self.runtime.cfg.card_prices[uid] = price
        self.refresh_advice()

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
            cfg = self.runtime.cfg
            if cfg.tariff_mode == "dual":
                night = self.runtime.profit.night_only(t)
                better = night.net_per_day > t.net_per_day
                self.night_only.setText(
                    f"Только ночью ({cfg.night_start_hour}:00–{cfg.night_end_hour}:00): "
                    f"{night.net_per_day:.2f} {cfg.currency}/сут против {t.net_per_day:.2f} при 24/7 — "
                    + ("выгоднее майнить только ночью." if better else "круглосуточно выгоднее."))
                self.night_only.setVisible(True)
            else:
                self.night_only.setVisible(False)
        self.table.setRowCount(len(snap.gpus))
        for row, (idx, g) in enumerate(sorted(snap.gpus.items())):
            p = g.profit
            cells = [self.runtime.rig[idx].label, format_hashrate(g.miner.hashrate) if g.miner else "—",
                     f"{g.telemetry.power_w:.0f}" if g.telemetry and g.telemetry.power_w else "—",
                     f"{p.revenue_per_day:.2f}" if p else "—", f"{p.cost_per_day:.2f}" if p else "—",
                     f"{p.net_per_day:.2f}" if p else "—"]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
