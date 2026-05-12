"""Lil Word app bootstrap."""

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from app.utils.settings import Settings
from app.services.project_service import ProjectService
from app.ui.main_window import MainWindow

# ── Logging ──────────────────────────────────────────────────────────────────

_LOG_DIR = Path.home() / ".lil_word"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("lil_word")


def main():
    log.info("=" * 60)
    log.info("Lil Word starting")
    log.info("  python executable : %s", sys.executable)
    log.info("  python version    : %s", sys.version)
    log.info("  source root       : %s", Path(__file__).resolve().parent)
    log.info("  log file          : %s", _LOG_FILE)
    log.info("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("Lil Word")
    app.setStyle("Fusion")

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Dark-ish palette for a less ugly default look
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ToolTipBase, QColor(220, 220, 220))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(55, 55, 58))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.BrightText, QColor(255, 100, 100))
    palette.setColor(QPalette.Link, QColor(90, 170, 255))
    palette.setColor(QPalette.Highlight, QColor(65, 105, 225))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    # Stylesheet polish
    app.setStyleSheet("""
        QPushButton {
            padding: 4px 12px;
            border: 1px solid #555;
            border-radius: 4px;
            background: #3a3a3d;
        }
        QPushButton:hover {
            background: #4a4a4f;
            border-color: #777;
        }
        QPushButton:pressed {
            background: #2a2a2d;
        }
        QPushButton:disabled {
            color: #666;
            border-color: #444;
        }
        QTableWidget {
            gridline-color: #444;
            border: 1px solid #444;
        }
        QHeaderView::section {
            background: #3a3a3d;
            border: 1px solid #444;
            padding: 4px;
        }
        QSlider::groove:horizontal {
            height: 6px;
            background: #555;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            width: 14px;
            margin: -4px 0;
            background: #4183c4;
            border-radius: 7px;
        }
        QProgressBar {
            border: 1px solid #555;
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #4183c4;
            border-radius: 3px;
        }
        QSplitter::handle {
            background: #555;
            width: 3px;
        }
    """)

    # Settings & project DB
    settings = Settings()
    db_dir = Path.home() / ".lil_word"
    db_dir.mkdir(exist_ok=True)
    project_svc = ProjectService(db_dir / "projects.db")

    window = MainWindow(settings, project_svc)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
