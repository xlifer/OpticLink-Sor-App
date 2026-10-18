"""3.5.2: πλαίσια ορίων στο PDF, όνομα αρχείου στην εξαγωγή, μαύρο Link map στο σκούρο θέμα."""
import pytest

from otdr_report.matching import Project, find_sor_files
from otdr_report.pdf_report import ReportBuilder, TitledBox, default_pdf_name, generate_reports
from otdr_report.settings import ReportSettings
from otdr_report.synthetic import make_cable


def _proj(tmp_path, names=("C1_SCP1",), n=2):
    for k, name in enumerate(names):
        make_cable(tmp_path / f"in{k}", name, n, seed=k + 1)
    p = Project()
    p.load(find_sor_files(tmp_path))
    return p


def test_threshold_box_in_pdf(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    p = _proj(tmp_path)
    c = p.sorted_cables()[0]
    s = ReportSettings(summary_page=True)
    s.thresholds.check_total_loss = True
    s.thresholds.max_total_loss = 20.0
    out = generate_reports([(c, c.sorted_fibers())], tmp_path / "out", s)
    txt = " ".join(pg.extract_text() for pg in pypdf.PdfReader(out[0]).pages)
    for needle in ("Threshold", "Splice loss", "Connector loss", "Reflection", "Slope dB/km", "Span loss",
                   "0.300", "0.750", "20.000"):
        assert needle in txt, needle
    assert "PASS criteria" not in txt                                   # όχι πια απλό κείμενο
    boxes = ReportBuilder(s).threshold_boxes([1310, 1550])
    assert len(boxes) == 1 and isinstance(boxes[0], TitledBox)
    s.thresholds.enabled = False
    assert ReportBuilder(s).threshold_boxes([1310]) == []               # χωρίς κριτήρια: χωρίς πλαίσιο


def test_export_custom_name(tmp_path):
    p = _proj(tmp_path)
    c = p.sorted_cables()[0]
    parts = [(c, c.sorted_fibers())]
    assert default_pdf_name(parts, True) == "C1_SCP1_0001-0002"
    out = generate_reports(parts, tmp_path / "out", ReportSettings(summary_page=False), name="Παράδοση FTTH")
    assert [x.name for x in out] == ["Παράδοση FTTH.pdf"]
    out2 = generate_reports(parts, tmp_path / "out", ReportSettings(summary_page=False), name="Παράδοση FTTH")
    assert out2[0].name == "Παράδοση FTTH (2).pdf"                      # ποτέ σιωπηλή αντικατάσταση


def test_export_dialog_name_default_and_multi(qapp_or_skip, tmp_path):
    from otdr_report import app as appmod
    p = _proj(tmp_path, names=("A_SCP1", "B_SCP2"))
    dlg = appmod.ExportDialog(p, ReportSettings(one_pdf_per_cable=True), str(tmp_path), ["A_SCP1"])
    for i in range(dlg.cables.topLevelItemCount()):                     # μόνο το A
        it = dlg.cables.topLevelItem(i)
        it.setCheckState(0, appmod.Qt.Checked if it.text(0) == "A_SCP1" else appmod.Qt.Unchecked)
    assert dlg.name.isEnabled() and dlg.name.text() == "A_SCP1_0001-0002"
    dlg.name.setText("Δικό μου.pdf")
    dlg.name.textEdited.emit("Δικό μου.pdf")
    assert dlg.file_name() == "Δικό μου"
    dlg.cables.topLevelItem(1).setCheckState(0, appmod.Qt.Checked)      # 2 καλώδια, ένα PDF το καθένα
    assert not dlg.name.isEnabled() and dlg.file_name() is None
    dlg.all_in_one.setChecked(True)                                     # όλα σε ένα → ξανά όνομα
    assert dlg.name.isEnabled() and dlg.name.text().startswith("OTDR_report_")
    import shiboken6
    shiboken6.delete(dlg)


def test_linkmap_black_in_dark_with_contrast(qapp_or_skip, tmp_path):
    from PySide6.QtCore import QPoint
    from otdr_report import theme
    from otdr_report.linkmap_widget import LinkMapWidget
    from otdr_report.settings import prepare
    from otdr_report.sor import parse_sor
    p = _proj(tmp_path, n=1)
    f = p.sorted_cables()[0].sorted_fibers()[0]
    sor = prepare(parse_sor(f.measurements[1310].path), ReportSettings())
    app = qapp_or_skip
    try:
        for mode, bg in (("dark", "#000000"), ("light", "#ffffff")):
            theme.apply_theme(app, mode)
            w = LinkMapWidget()
            w.resize(800, 170)
            w.set_measurement(sor, ReportSettings().thresholds)
            img = w.grab().toImage()
            assert img.pixelColor(QPoint(3, 160)).name() == bg
            text = w.colors()["text"]
            lum = lambda c: 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()   # noqa: E731
            assert abs(lum(text) - lum(w.colors()["bg"])) > 0.6                         # έντονη αντίθεση
            w.deleteLater()
    finally:
        theme.apply_theme(app, "light")
