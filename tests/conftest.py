import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "examples", "thick_tube", "tube_resu.med")

# Lamé solution of the example (examples/thick_tube/tube.comm): mm, MPa
P, A, B, E, NU = 10.0, 50.0, 60.0, 200000.0, 0.3


@pytest.fixture(scope="session")
def example():
    return os.path.realpath(EXAMPLE)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Outputs and the remembered language go to a temporary folder."""
    monkeypatch.setenv("ASTER_VIEW_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def lame(r):
    a = P * A ** 2 / (B ** 2 - A ** 2)
    b = a * B ** 2
    sr, st = a - b / r ** 2, a + b / r ** 2
    ur = ((1 - NU) * a * r + (1 + NU) * b / r) / E
    return sr, st, ur
