import json
from pathlib import Path

from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView

from autoticket_app.browser import BrowserPage, build_profile, get_local_app_data_dir
from autoticket_app.config import (
    ALLOW_INSECURE_TLS_FOR_HOSTS,
    APP_NAME,
    PROFILE_NAME,
    load_servicenow_settings,
)
from autoticket_app.features import build_example_ticket, build_ticket_from_email
from autoticket_app.models import Ticket
from autoticket_app.msg_parser import parse_msg
from autoticket_app.servicenow import (
    build_ready_check_js,
    build_servicenow_fill_js,
    is_servicenow_url,
)


class DropLabel(QLabel):
    def __init__(self, main_window):
        super().__init__("Navigate to ServiceNow form, then drop a .msg file here")
        self.main_window = main_window
        self.setAcceptDrops(True)
        self.armed = False
        self.update_style()

    def set_armed(self, armed: bool):
        self.armed = armed
        self.setText(
            "Ready: drop a .msg file here"
            if armed
            else "Navigate to ServiceNow form, then drop a .msg file here"
        )
        self.update_style()

    def update_style(self):
        bg = "rgba(0,120,0,0.55)" if self.armed else "rgba(0,0,0,0.55)"
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: white;
                padding: 10px;
                font-size: 14px;
            }}
        """
        )

    def dragEnterEvent(self, event):
        if not self.armed:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() == ".msg":
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        if not self.armed:
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() == ".msg":
                self.main_window.load_msg_file(path)
                event.acceptProposedAction()
                return


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ServiceNow Form Filler Debug")
        self.resize(1500, 900)

        self.local_data_dir = get_local_app_data_dir(APP_NAME)
        config_result = load_servicenow_settings(self.local_data_dir)
        self.servicenow_settings = config_result.settings
        self.config_warnings = config_result.warnings
        self.profile = build_profile(self, self.local_data_dir, PROFILE_NAME)

        self._build_browser()
        self._build_controls()
        self._build_layout()
        self._log_startup()

        self.view.setUrl(QUrl(self.servicenow_settings.start_url))

    def _build_browser(self):
        self.view = QWebEngineView(self)
        self.page = BrowserPage(
            self.profile,
            self.view,
            log_fn=self.log,
            insecure_tls_hosts=ALLOW_INSECURE_TLS_FOR_HOSTS,
        )
        self.view.setPage(self.page)
        self.view.urlChanged.connect(self.on_url_changed)
        self.view.loadFinished.connect(self.on_load_finished)
        self.client_cert_selection_supported = hasattr(self.page, "selectClientCertificate")
        if self.client_cert_selection_supported:
            self.page.selectClientCertificate.connect(self.on_select_client_certificate)

        self.drop_label = DropLabel(self)

    def _build_controls(self):
        self.json_input = QTextEdit()
        self.json_input.setPlaceholderText("Paste normalized ticket JSON here...")

        self.parsed_output = QTextEdit()
        self.parsed_output.setReadOnly(True)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        self.btn_check_ready = QPushButton("Check Ready")
        self.btn_check_ready.clicked.connect(self.check_dom_ready)

        self.btn_fill_json = QPushButton("Fill From JSON")
        self.btn_fill_json.clicked.connect(self.fill_from_json)

        self.btn_pretty_json = QPushButton("Pretty JSON")
        self.btn_pretty_json.clicked.connect(self.pretty_json)

        self.btn_clear_log = QPushButton("Clear Log")
        self.btn_clear_log.clicked.connect(self.log_output.clear)

        self.btn_load_example = QPushButton("Load Example JSON")
        self.btn_load_example.clicked.connect(self.load_example_json)

    def _build_layout(self):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_check_ready)
        btn_row.addWidget(self.btn_fill_json)
        btn_row.addWidget(self.btn_pretty_json)
        btn_row.addWidget(self.btn_load_example)
        btn_row.addWidget(self.btn_clear_log)

        right_layout.addWidget(QLabel("JSON Test Input"))
        right_layout.addWidget(self.json_input, 3)
        right_layout.addLayout(btn_row)
        right_layout.addWidget(QLabel("Parsed / Normalized Fields"))
        right_layout.addWidget(self.parsed_output, 2)
        right_layout.addWidget(QLabel("Debug Log"))
        right_layout.addWidget(self.log_output, 2)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.view, 1)
        left_layout.addWidget(self.drop_label, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([950, 550])

        self.setCentralWidget(splitter)

    def _log_startup(self):
        self.log(f"[profile] local data dir: {self.local_data_dir}")
        self.log(f"[config] ServiceNow profile: {self.servicenow_settings.source_path}")
        for warning in self.config_warnings:
            self.log(warning)
        if self.client_cert_selection_supported:
            self.log("[tls] client certificate selection is enabled")
        else:
            self.log("[tls] client certificate selection signal not available in this QtWebEngine build")

    def log(self, msg: str):
        self.log_output.append(msg)

    @staticmethod
    def _cert_value_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value if item)
        return str(value)

    def _cert_subject(self, cert, key: str) -> str:
        try:
            return self._cert_value_text(cert.subjectInfo(key)).strip()
        except Exception:
            return ""

    def _cert_issuer(self, cert, key: str) -> str:
        try:
            return self._cert_value_text(cert.issuerInfo(key)).strip()
        except Exception:
            return ""

    def _describe_cert(self, cert, index: int) -> str:
        subject = self._cert_subject(cert, "CN") or self._cert_subject(cert, "O") or "(unknown subject)"
        issuer = self._cert_issuer(cert, "CN") or self._cert_issuer(cert, "O") or "(unknown issuer)"

        serial = ""
        try:
            serial = str(cert.serialNumber()).strip()
        except Exception:
            serial = ""

        expires = ""
        try:
            expires = cert.expiryDate().toString(Qt.ISODate)
        except Exception:
            expires = ""

        bits = [f"{index + 1}. {subject}", f"issuer={issuer}"]
        if serial:
            bits.append(f"serial={serial}")
        if expires:
            bits.append(f"expires={expires}")
        return " | ".join(bits)

    def on_select_client_certificate(self, selection):
        try:
            certs = list(selection.certificates())
        except Exception as exc:
            self.log(f"[tls][error] could not read certificates: {exc}")
            try:
                selection.selectNone()
            except Exception:
                pass
            return

        if not certs:
            self.log("[tls] server requested a client certificate but none were available")
            try:
                selection.selectNone()
            except Exception:
                pass
            return

        host = ""
        port = ""
        try:
            host = str(selection.host())
        except Exception:
            pass
        try:
            port = str(selection.port())
        except Exception:
            pass

        item_to_cert = {}
        items = []
        for index, cert in enumerate(certs):
            label = self._describe_cert(cert, index)
            while label in item_to_cert:
                label += " "
            item_to_cert[label] = cert
            items.append(label)

        prompt = "Server requested an X.509 client certificate.\nSelect which certificate to use:"
        if host or port:
            prompt += f"\n\nTarget: {host}:{port}"

        picked_label, ok = QInputDialog.getItem(
            self,
            "Select X.509 Certificate",
            prompt,
            items,
            0,
            False,
        )

        if not ok:
            self.log("[tls] certificate selection canceled; no client certificate was sent")
            try:
                selection.selectNone()
            except Exception:
                pass
            return

        cert = item_to_cert.get(picked_label)
        if cert is None:
            self.log("[tls][error] certificate selection was invalid")
            try:
                selection.selectNone()
            except Exception:
                pass
            return

        try:
            selection.select(cert)
            self.log(f"[tls] selected client certificate: {picked_label}")
        except Exception as exc:
            self.log(f"[tls][error] failed to apply certificate selection: {exc}")
            try:
                selection.selectNone()
            except Exception:
                pass

    def on_url_changed(self, url: QUrl):
        self.drop_label.set_armed(False)
        self.log(f"[nav] {url.toString()}")

    def on_load_finished(self, ok: bool):
        self.log(f"[load] ok={ok}")
        if not ok:
            self.drop_label.set_armed(False)
            return

        url = self.view.url().toString()
        if not is_servicenow_url(url, self.servicenow_settings.host_regex):
            self.log("[ready] not on ServiceNow host")
            self.drop_label.set_armed(False)
            return

        QTimer.singleShot(500, self.check_dom_ready)

    def check_dom_ready(self):
        js = build_ready_check_js(self.servicenow_settings.ready_dom_selector)
        self.view.page().runJavaScript(js, self.on_ready_checked)

    def on_ready_checked(self, result):
        ready = bool(result.get("ready")) if isinstance(result, dict) else False
        self.drop_label.set_armed(ready)
        self.log(f"[ready] {result}")

    def load_msg_file(self, path: str):
        self.log(f"[msg] loading {path}")
        try:
            email = parse_msg(path)
            ticket = build_ticket_from_email(email)
            self.set_ticket(ticket)
            self.log("[msg] parsed and loaded into JSON panel")
        except Exception as exc:
            QMessageBox.critical(self, "MSG Parse Error", str(exc))
            self.log(f"[msg][error] {exc}")

    def set_ticket(self, ticket: Ticket):
        data = ticket.to_dict()
        self.set_json(data)
        self.parsed_output.setPlainText(json.dumps(data, indent=2))

    def set_json(self, data):
        if isinstance(data, Ticket):
            data = data.to_dict()
        self.json_input.setPlainText(json.dumps(data, indent=2))

    def get_json(self) -> dict:
        text = self.json_input.toPlainText().strip()
        if not text:
            return {}
        return json.loads(text)

    def pretty_json(self):
        try:
            data = self.get_json()
            self.set_json(data)
            self.log("[json] formatted")
        except Exception as exc:
            QMessageBox.warning(self, "Invalid JSON", str(exc))
            self.log(f"[json][error] {exc}")

    def load_example_json(self):
        self.set_ticket(build_example_ticket())
        self.log("[json] loaded example")

    def fill_from_json(self):
        try:
            ticket = Ticket.from_dict(self.get_json())
            self.parsed_output.setPlainText(json.dumps(ticket.to_dict(), indent=2))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid JSON", str(exc))
            self.log(f"[fill][error] invalid json: {exc}")
            return

        js = build_servicenow_fill_js(ticket, self.servicenow_settings.field_bindings)
        self.log("[fill] running JS")
        self.view.page().runJavaScript(js, self.on_fill_result)

    def on_fill_result(self, result):
        try:
            pretty = json.dumps(result, indent=2)
        except Exception:
            pretty = str(result)
        self.log(f"[fill][result]\n{pretty}")
