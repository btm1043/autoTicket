import sys
import re
import json
from pathlib import Path
from dataclasses import dataclass

from PyQt5.QtCore import QUrl, QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSplitter, QMessageBox, QInputDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage

import extract_msg  # pip install extract-msg


START_URL = "https://127.0.0.1:8443"
SN_HOST_REGEX = r"(service-now\.com|your-internal-servicenow-host)"
REQUIRED_DOM_SELECTOR = "#incident\\.short_description, input[name='incident.short_description']"
ALLOW_INSECURE_TLS_FOR_HOSTS = {"127.0.0.1", "localhost"}


@dataclass
class ParsedEmail:
    subject: str
    body: str


def parse_msg(path: str) -> ParsedEmail:
    msg = extract_msg.Message(path)
    msg.process()
    return ParsedEmail(
        subject=msg.subject or "",
        body=(msg.body or "").strip(),
    )


def extract_fields(email: ParsedEmail) -> dict:
    return {
        "short_description": email.subject.strip()[:160],
        "description": email.body.strip(),
        "caller_name": "",
        "caller_email": "",
        "category": "",
        "subcategory": "",
    }


def js_str(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def build_servicenow_fill_js(fields: dict) -> str:
    short_desc = fields.get("short_description", "")
    desc = fields.get("description", "")
    caller_name = fields.get("caller_name", "")
    caller_email = fields.get("caller_email", "")
    category = fields.get("category", "")
    subcategory = fields.get("subcategory", "")

    return f"""
(() => {{
  const out = {{}};

  function setBySelector(sel, value) {{
    const el = document.querySelector(sel);
    if (!el) return false;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    return true;
  }}

  function setField(fieldName, value, selectors) {{
    let ok = false;

    if (window.g_form && typeof window.g_form.setValue === 'function') {{
      try {{
        window.g_form.setValue(fieldName, value);
        ok = true;
      }} catch (e) {{
        out[fieldName + "_g_form_error"] = String(e);
      }}
    }}

    if (!ok && selectors && selectors.length) {{
      for (const sel of selectors) {{
        if (setBySelector(sel, value)) {{
          ok = true;
          break;
        }}
      }}
    }}

    out[fieldName] = ok;
  }}

  setField("short_description", {js_str(short_desc)}, [
    "#incident\\\\.short_description",
    "input[name='incident.short_description']",
    "input[name='short_description']"
  ]);

  setField("description", {js_str(desc)}, [
    "#incident\\\\.description",
    "textarea[name='incident.description']",
    "textarea[name='description']"
  ]);

  setField("caller_id", {js_str(caller_name or caller_email)}, [
    "#sys_display\\\\.incident\\\\.caller_id",
    "input[name='sys_display.incident.caller_id']",
    "input[name='caller_id']"
  ]);

  setField("category", {js_str(category)}, [
    "#incident\\\\.category",
    "select[name='incident.category']",
    "select[name='category']"
  ]);

  setField("subcategory", {js_str(subcategory)}, [
    "#incident\\\\.subcategory",
    "select[name='incident.subcategory']",
    "select[name='subcategory']"
  ]);

  out.url = window.location.href;
  out.title = document.title;
  return out;
}})();
"""


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
            "✅ Ready: drop a .msg file here"
            if armed else
            "Navigate to ServiceNow form, then drop a .msg file here"
        )
        self.update_style()

    def update_style(self):
        bg = "rgba(0,120,0,0.55)" if self.armed else "rgba(0,0,0,0.55)"
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: white;
                padding: 10px;
                font-size: 14px;
            }}
        """)

    def dragEnterEvent(self, e):
        if not self.armed:
            e.ignore()
            return
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if Path(u.toLocalFile()).suffix.lower() == ".msg":
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        if not self.armed:
            return
        for u in e.mimeData().urls():
            path = u.toLocalFile()
            if Path(path).suffix.lower() == ".msg":
                self.main_window.load_msg_file(path)
                e.acceptProposedAction()
                return


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, parent=None, log_fn=None, insecure_tls_hosts=None):
        super().__init__(profile, parent)
        self._log_fn = log_fn or (lambda _: None)
        self._insecure_tls_hosts = {
            str(h).strip().lower()
            for h in (insecure_tls_hosts or [])
            if str(h).strip()
        }

    def _safe_log(self, msg: str):
        try:
            self._log_fn(msg)
        except Exception:
            pass

    def _error_details(self, cert_error):
        host = ""
        code = ""
        desc = ""
        overridable = False

        try:
            url = cert_error.url()
            if url is not None:
                host = url.host().lower()
        except Exception:
            pass

        try:
            code = str(cert_error.error())
        except Exception:
            code = ""

        try:
            desc = str(cert_error.errorDescription())
        except Exception:
            desc = ""

        try:
            overridable = bool(cert_error.isOverridable())
        except Exception:
            overridable = False

        return host, code, desc, overridable

    def certificateError(self, cert_error):
        host, code, desc, overridable = self._error_details(cert_error)
        if host in self._insecure_tls_hosts and overridable:
            self._safe_log(
                f"[tls][warn] ignoring certificate error for trusted local host '{host}' "
                f"(code={code}, desc={desc})"
            )
            return True

        self._safe_log(
            f"[tls][error] certificate error blocked "
            f"(host={host or 'unknown'}, code={code}, desc={desc}, overridable={overridable})"
        )
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ServiceNow Form Filler Debug")
        self.resize(1500, 900)

        self.profile = QWebEngineProfile("sn-profile", self)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self.view = QWebEngineView(self)
        self.profile = QWebEngineProfile("sn-profile", self)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.ForcePersistentCookies
        )

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

        if self.client_cert_selection_supported:
            self.log("[tls] client certificate selection is enabled")
        else:
            self.log("[tls] client certificate selection signal not available in this QtWebEngine build")

        self.view.setUrl(QUrl(START_URL))

    def log(self, msg: str):
        self.log_output.append(msg)

    @staticmethod
    def _cert_value_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value if v)
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
        except Exception as e:
            self.log(f"[tls][error] could not read certificates: {e}")
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
        for i, cert in enumerate(certs):
            label = self._describe_cert(cert, i)
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
        except Exception as e:
            self.log(f"[tls][error] failed to apply certificate selection: {e}")
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
        if not re.search(SN_HOST_REGEX, url, re.IGNORECASE):
            self.log("[ready] not on ServiceNow host")
            self.drop_label.set_armed(False)
            return

        QTimer.singleShot(500, self.check_dom_ready)

    def check_dom_ready(self):
        js = f"""
(() => {{
  return {{
    ready: Boolean(document.querySelector({REQUIRED_DOM_SELECTOR!r})),
    url: window.location.href,
    title: document.title
  }};
}})();
"""
        self.view.page().runJavaScript(js, self.on_ready_checked)

    def on_ready_checked(self, result):
        ready = bool(result.get("ready")) if isinstance(result, dict) else False
        self.drop_label.set_armed(ready)
        self.log(f"[ready] {result}")

    def load_msg_file(self, path: str):
        self.log(f"[msg] loading {path}")
        try:
            email = parse_msg(path)
            fields = extract_fields(email)
            self.set_json(fields)
            self.parsed_output.setPlainText(json.dumps(fields, indent=2))
            self.log("[msg] parsed and loaded into JSON panel")
        except Exception as e:
            QMessageBox.critical(self, "MSG Parse Error", str(e))
            self.log(f"[msg][error] {e}")

    def set_json(self, data: dict):
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
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            self.log(f"[json][error] {e}")

    def load_example_json(self):
        example = {
            "short_description": "VPN disconnecting for remote user",
            "description": "User reports VPN drops every 5 minutes with error 809. Started this morning.",
            "caller_name": "John Smith",
            "caller_email": "john.smith@example.com",
            "category": "Network",
            "subcategory": "VPN"
        }
        self.set_json(example)
        self.parsed_output.setPlainText(json.dumps(example, indent=2))
        self.log("[json] loaded example")

    def fill_from_json(self):
        try:
            fields = self.get_json()
            self.parsed_output.setPlainText(json.dumps(fields, indent=2))
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            self.log(f"[fill][error] invalid json: {e}")
            return

        js = build_servicenow_fill_js(fields)
        self.log("[fill] running JS")
        self.view.page().runJavaScript(js, self.on_fill_result)

    def on_fill_result(self, result):
        try:
            pretty = json.dumps(result, indent=2)
        except Exception:
            pretty = str(result)
        self.log(f"[fill][result]\n{pretty}")


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
