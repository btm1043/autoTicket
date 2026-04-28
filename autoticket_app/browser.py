from pathlib import Path

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile


def get_local_app_data_dir(app_name: str) -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if location:
        base_dir = Path(location)
    else:
        base_dir = Path.home() / "AppData" / "Local" / app_name

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def build_profile(parent, local_data_dir: Path, profile_name: str) -> QWebEngineProfile:
    profile = QWebEngineProfile(profile_name, parent)
    webengine_dir = local_data_dir / "qtwebengine" / profile_name
    storage_dir = webengine_dir / "storage"
    cache_dir = webengine_dir / "cache"

    storage_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    profile.setPersistentStoragePath(str(storage_dir))
    profile.setCachePath(str(cache_dir))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    return profile


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, parent=None, log_fn=None, insecure_tls_hosts=None):
        super().__init__(profile, parent)
        self._log_fn = log_fn or (lambda _: None)
        self._insecure_tls_hosts = {
            str(host).strip().lower()
            for host in (insecure_tls_hosts or [])
            if str(host).strip()
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
