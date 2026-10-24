import importlib
import pkgutil

import oncall


def test_every_module_imports():
    names = [m.name for m in pkgutil.walk_packages(oncall.__path__, "oncall.")]
    assert "oncall.tools.metrics" in names
    for name in names:
        importlib.import_module(name)
