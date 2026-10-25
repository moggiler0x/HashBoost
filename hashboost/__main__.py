"""Точка входа: ``python -m hashboost``."""
from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import data_dir, load_config


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="hashboost", description="Авто-андервольт и оптимизация доходности GPU")
    p.add_argument("--simulate", action="store_true", help="режим симуляции без реальных карт")
    p.add_argument("--time-scale", type=float, default=30.0,
                   help="ускорение времени в симуляции (по умолчанию 30×)")
    p.add_argument("--tune", type=int, metavar="GPU", help="откалибровать карту без GUI и сохранить профиль")
    p.add_argument("--algorithm", help="алгоритм (по умолчанию из настроек)")
    p.add_argument("--reset-on-exit", action="store_true", help="вернуть стоковые настройки при выходе")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--version", action="version", version=f"HashBoost {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(data_dir() / "hashboost.log",
                                                                                encoding="utf-8")])
    cfg = load_config()
    if args.simulate or sys.platform == "darwin":
        cfg.simulate = True  # на macOS доступна только симуляция
    if args.algorithm:
        cfg.miner.algorithm = args.algorithm

    from .core.runtime import Runtime

    runtime = Runtime(cfg, sim_time_scale=args.time_scale)
    if runtime.sim is not None:
        runtime.sim.algorithm = cfg.miner.algorithm

    if args.tune is not None:
        from .core.autotune import TunerCallbacks

        tuner = runtime.make_tuner(TunerCallbacks())  # ход калибровки пишется в лог
        try:
            result = tuner.run(args.tune)
        except KeyboardInterrupt:
            tuner.cancel()
            return 1
        runtime.save_tune_result(result)
        runtime.shutdown(reset_clocks=False)
        return 0

    from .gui.main_window import run_gui

    code = run_gui(runtime)
    if args.reset_on_exit:
        runtime.rig.reset_all()
    return code


if __name__ == "__main__":
    sys.exit(main())
