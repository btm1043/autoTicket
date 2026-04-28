import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from autoticket_app.config import APP_NAME, ConfigError
from autoticket_app.ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    try:
        window = MainWindow()
    except ConfigError as exc:
        QMessageBox.critical(None, "ServiceNow Config Error", str(exc))
        sys.exit(1)
    window.show()
    sys.exit(app.exec())
