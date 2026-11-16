"""Módulo de firma electrónica para documentos PDF."""

from pyhanko.pdf_utils import layout

# Parche de compatibilidad para Python 3.14 (donde Fraction(a, b) exige tipos Rational y rechaza floats)
_orig_recalc = layout.BoxConstraints._recalculate


def _safe_recalc(self):
    if self._width is not None and isinstance(self._width, float):
        self._width = int(round(self._width))
    if self._height is not None and isinstance(self._height, float):
        self._height = int(round(self._height))
    return _orig_recalc(self)


layout.BoxConstraints._recalculate = _safe_recalc

__version__ = "0.1.0"
