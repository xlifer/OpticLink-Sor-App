import pytest




@pytest.fixture
def qapp_or_skip():
    """QApplication για tests που χρειάζονται widgets (offscreen)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
