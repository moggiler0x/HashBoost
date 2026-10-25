"""Настройки: майнер, параметры калибровки, пороги watchdog."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..config import save_config
from ..core.runtime import Runtime
from ..miners import MINER_KINDS
from .calculator import spin


def ispin(minimum: int, maximum: int, suffix: str = "", step: int = 1) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    if suffix:
        box.setSuffix(suffix)
    return box


def parse_algo_args(text: str) -> dict[str, str]:
    """Строки вида «алгоритм: аргументы» → словарь."""
    result = {}
    for line in text.splitlines():
        name, sep, args = line.partition(":")
        if sep and name.strip() and args.strip():
            result[name.strip()] = args.strip()
    return result


class SettingsView(QWidget):
    def __init__(self, runtime: Runtime):
        super().__init__()
        self.runtime = runtime
        cfg = runtime.cfg
        lay = QHBoxLayout(self)
        col1, col2 = QVBoxLayout(), QVBoxLayout()

        miner = QGroupBox("Майнер")
        f = QFormLayout(miner)
        self.kind = QComboBox()
        for key, title in MINER_KINDS.items():
            self.kind.addItem(title, key)
        self.kind.setCurrentIndex(max(0, list(MINER_KINDS).index(cfg.miner.kind)) if cfg.miner.kind in MINER_KINDS else 0)
        self.api = QLineEdit(cfg.miner.api_url)
        self.exe = QLineEdit(cfg.miner.executable)
        self.exe.setPlaceholderText("пусто — майнер запускается вручную")
        self.args = QLineEdit(cfg.miner.args)
        self.algorithm = QLineEdit(cfg.miner.algorithm)
        f.addRow("Тип", self.kind)
        f.addRow("Адрес API", self.api)
        f.addRow("Исполняемый файл", self.exe)
        f.addRow("Аргументы", self.args)
        f.addRow("Алгоритм", self.algorithm)
        self.algo_args = QPlainTextEdit("\n".join(f"{k}: {v}" for k, v in cfg.miner.algo_args.items()))
        self.algo_args.setPlaceholderText("poseidon2: --algorithm poseidon2 --pool ... --wallet ...\n"
                                          "pearlhash: --algorithm pearlhash --pool ... --wallet ...")
        self.algo_args.setToolTip("Аргументы майнера для каждой монеты, по строке на алгоритм. "
                                  "Нужны мульти-калибровке, чтобы она сама переключала монеты.")
        self.algo_args.setFixedHeight(70)
        f.addRow("Аргументы по монетам", self.algo_args)
        col1.addWidget(miner)

        wd = QGroupBox("Watchdog")
        f = QFormLayout(wd)
        w = cfg.watchdog
        self.wd_enabled = QCheckBox("включён")
        self.wd_enabled.setChecked(w.enabled)
        self.t_gpu = spin(50, 110, 0, " °C")
        self.t_gpu.setValue(w.max_gpu_temp_c)
        self.t_hot = spin(60, 120, 0, " °C")
        self.t_hot.setValue(w.max_hotspot_temp_c)
        self.t_vram = spin(60, 120, 0, " °C")
        self.t_vram.setValue(w.max_vram_temp_c)
        self.miner_timeout = spin(10, 600, 0, " с", 5)
        self.miner_timeout.setValue(w.miner_timeout_s)
        f.addRow("", self.wd_enabled)
        f.addRow("Предел GPU", self.t_gpu)
        f.addRow("Предел HotSpot", self.t_hot)
        f.addRow("Предел VRAM", self.t_vram)
        f.addRow("Майнер молчит дольше", self.miner_timeout)
        col1.addWidget(wd)
        col1.addStretch()

        tune = QGroupBox("Калибровка")
        f = QFormLayout(tune)
        t = cfg.tuning
        self.stab = spin(10, 600, 0, " с", 10)
        self.stab.setValue(t.stabilization_s)
        self.warm = spin(0, 300, 0, " с", 5)
        self.warm.setValue(t.warmup_s)
        self.core_step = ispin(5, 100, " МГц", 5)
        self.core_step.setValue(t.core_step_mhz)
        self.mem_step = ispin(10, 500, " МГц", 10)
        self.mem_step.setValue(t.mem_step_mhz)
        self.v_step = ispin(5, 50, " мВ", 5)
        self.v_step.setValue(t.voltage_step_mv)
        self.v_min = ispin(-400, 0, " мВ", 10)
        self.v_min.setValue(t.min_voltage_offset_mv)
        self.margin = ispin(0, 60, " мВ", 5)
        self.margin.setValue(t.safety_margin_mv)
        self.drop = spin(1, 50, 1, " %")
        self.drop.setValue(t.max_hashrate_drop_pct)
        f.addRow("Стабилизация шага", self.stab)
        f.addRow("Прогрев после смены", self.warm)
        f.addRow("Шаг частоты ядра", self.core_step)
        f.addRow("Шаг частоты памяти", self.mem_step)
        f.addRow("Шаг напряжения", self.v_step)
        f.addRow("Предел андервольта", self.v_min)
        f.addRow("Запас надёжности", self.margin)
        f.addRow("Допустимая просадка хешрейта", self.drop)
        col2.addWidget(tune)

        save = QPushButton("Сохранить настройки")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        col2.addWidget(save)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        col2.addWidget(self.note)
        col2.addStretch()
        lay.addLayout(col1, 1)
        lay.addLayout(col2, 1)

    def _save(self) -> None:
        cfg = self.runtime.cfg
        old_miner = (cfg.miner.kind, cfg.miner.api_url, cfg.miner.executable, cfg.miner.args, dict(cfg.miner.algo_args))
        cfg.miner.kind = self.kind.currentData()
        cfg.miner.api_url = self.api.text().strip()
        cfg.miner.executable = self.exe.text().strip()
        cfg.miner.args = self.args.text().strip()
        cfg.miner.algorithm = self.algorithm.text().strip() or cfg.miner.algorithm
        cfg.miner.algo_args = parse_algo_args(self.algo_args.toPlainText())
        w = cfg.watchdog
        w.enabled = self.wd_enabled.isChecked()
        w.max_gpu_temp_c, w.max_hotspot_temp_c, w.max_vram_temp_c = self.t_gpu.value(), self.t_hot.value(), self.t_vram.value()
        w.miner_timeout_s = self.miner_timeout.value()
        t = cfg.tuning
        t.stabilization_s, t.warmup_s = self.stab.value(), self.warm.value()
        t.core_step_mhz, t.mem_step_mhz = self.core_step.value(), self.mem_step.value()
        t.voltage_step_mv, t.min_voltage_offset_mv = self.v_step.value(), self.v_min.value()
        t.safety_margin_mv, t.max_hashrate_drop_pct = self.margin.value(), self.drop.value()
        save_config(cfg)
        changed = old_miner != (cfg.miner.kind, cfg.miner.api_url, cfg.miner.executable, cfg.miner.args,
                                cfg.miner.algo_args)
        self.note.setText("Сохранено." + (" Настройки майнера вступят в силу после перезапуска программы." if changed else ""))
