import sys
import re
from pathlib import Path
from dataclasses import dataclass

from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile

import extract_msg  # pip install extract-msg


# --------- configure these ----------
START_URL = "https://your-internal-servicenow-host/"  # entry URL (will redirect through SSO)
SN_HOST_REGEX = r"(service-now\.com|your-internal-servicenow-host)"  # tighten this
# Example: require a specific form field to exist before enabling drop
REQUIRED_DOM_SELECTOR = "#incident\\.short_description, input[name='incident.short_description']"
# -----------------------------------


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
    """
    TODO: replace with your real parsing logic.
    For now: use subject as short description, body as description.
    """
    return {
        "short_description": email.subject.strip()[:160],
        "description": email.body.strip(),
    }


def build_servicenow_fill_js(fields: dict) -> str:
    # Classic ServiceNow often supports g_form.setValue('field', 'value')
    # Field names usually omit the table prefix when using g_form (e.g., 'short_description').
    short_desc = fields.get("short_description", "")
    desc = fields.get("description", "")

    # Escape using JS string literals via repr-like behavior
    def js_str(s: str) -> str:
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"

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

  // 1) Try g_form (best for classic UI)
  if (window.g_form && typeof window.g_form.setValue === 'function') {{
    try {{
      window.g_form.setValue('short_description', {js_str(short_desc)});
      window.g_form.setValue('description', {js_str(desc)});
      out.g_form = true;
    }} catch (e) {{
      out.g_form_error = String(e);
    }}
  }} else {{
    out.g_form = false;
  }}

  // 2) Fallback to common IDs/names (adjust to your form/table)
  out.short_description_dom =
    setBySelector("#incident\\\\.short_description", {js_str(short_desc)}) ||
    setBySelector("input[name='incident.short_description']", {js_str(short_desc)}) ||
    setBySelector("input[name='short_description']", {js_str(short_desc)});

  out.description_dom =
    setBySelector("#incident\\\\.description", {js_str(desc)}) ||
    setBySelector("textarea[name='incident.description']", {js_str(desc)}) ||
    setBySelector("textarea[name='description']", {js_str(desc)});

  return out;
}})();
"""


class DropOverlay(QLabel):
    """
    A simple overlay label that becomes the drop target once armed.
    """
    def __init__(self):
        super().__init__("Navigate to the ServiceNow form, then drop a .msg here")
        self.setStyleSheet("""
            QLabel {
                background: rgba(0,0,0,0.55);
                color: white;
                padding: 10px;
                font-size: 14px;
            }
        """)
        self.setWordWrap(True)
        self.setAcceptDrops(True)
        self.armed = False

    def set_armed(self, armed: bool):
        self.armed = armed
        if armed:
            self.setText("✅ Ready: drop a .msg file to auto-fill the ServiceNow form")
            self.setStyleSheet("""
                QLabel {
                    background: rgba(0,120,0,0.55);
                    color: white;
                    padding: 10px;
                    font-size: 14px;
                }
            """)
        else:
            self.setText("Navigate to the ServiceNow form, then drop a .msg here")
            self.setStyleSheet("""
                QLabel {
                    background: rgba(0,0,0,0.55);
                    color: white;
                    padding: 10px;
                    font-size: 14px;
                }
            """)

    def dragEnterEvent(self, e):
        if not self.armed:
            e.ignore()
            return
        if e.mimeData().hasUrls():
            if any(Path(u.toLocalFile()).suffix.lower() == ".msg" for u in e.mimeData().urls()):
                e.acceptProposedAction()
                return
        e.ignore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ServiceNow Form Filler (MSG → WebForm)")
        self.resize(1200, 850)

        self.profile = QWebEngineProfile("sn-profile", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

        self.view = QWebEngineView(self)
        self.view.setPage(self.profile.createStandardPage())

        self.overlay = DropOverlay()
        self.overlay.dropEvent = self.on_drop  # bind dynamically

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.overlay, 0)
        self.setCentralWidget(root)

        self.view.urlChanged.connect(self.on_url_changed)
        self.view.loadFinished.connect(self.on_load_finished)

        self.view.setUrl(QUrl(START_URL))

    def is_on_servicenow_host(self, url: str) -> bool:
        return re.search(SN_HOST_REGEX, url, re.IGNORECASE) is not None

    def on_url_changed(self, url: QUrl):
        # Disarm while navigating
        self.overlay.set_armed(False)

    def on_load_finished(self, ok: bool):
        if not ok:
            self.overlay.set_armed(False)
            return

        url = self.view.url().toString()
        if not self.is_on_servicenow_host(url):
            self.overlay.set_armed(False)
            return

        # Check DOM readiness: required selector exists (poll once after brief delay)
        QTimer.singleShot(500, self.check_dom_ready)

    def check_dom_ready(self):
        js = f"Boolean(document.querySelector({REQUIRED_DOM_SELECTOR!r}))"
        self.view.page().runJavaScript(js, self.on_dom_ready_checked)

    def on_dom_ready_checked(self, exists):
        self.overlay.set_armed(bool(exists))

    def on_drop(self, e):
        if not self.overlay.armed:
            return

        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        msg_paths = [u.toLocalFile() for u in urls if Path(u.toLocalFile()).suffix.lower() == ".msg"]
        if not msg_paths:
            return

        email = parse_msg(msg_paths[0])
        fields = extract_fields(email)
        js = build_servicenow_fill_js(fields)

        self.view.page().runJavaScript(js, lambda res: self.overlay.setText(f"✅ Filled. Result: {res}"))
        e.acceptProposedAction()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
