"""Job handler modules. Drop a module here that uses @job_handler; the worker imports them all."""

import importlib
import pkgutil


def load_all() -> None:
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")
