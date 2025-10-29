from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://pbase.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0 Safari/537.36"
)


class PBaseLoginError(RuntimeError):
    """Raised when login fails."""


def _normalize_url(url: str, base_url: str) -> str:
    """Return an absolute URL anchored at the configured base."""
    if not url:
        raise ValueError("Empty URL provided.")
    resolved = urljoin(base_url if base_url.endswith("/") else f"{base_url}/", url)
    parts = urlparse(resolved)
    # PBase sometimes points to //www.pbase.com/..., so normalize the scheme.
    if not parts.scheme:
        resolved = "https:" + resolved
    return resolved


@dataclass
class PBaseClient:
    """Thin wrapper over requests.Session with login helpers."""

    username: str
    password: str
    base_url: str = DEFAULT_BASE_URL
    request_delay: float = 0.0
    session: requests.Session = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not self.session:
            self.session = requests.Session()
        self.session.headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
        self._last_request_ts: float = 0.0

    def login(self) -> None:
        """Authenticate against the PBase login form."""
        login_url = _normalize_url("login", self.base_url)
        logger.debug("Fetching login form: %s", login_url)
        response = self.session.get(login_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        form = self._locate_login_form(soup)
        if not form:
            raise PBaseLoginError("Unable to locate login form on page.")

        payload = self._build_login_payload(form)
        logger.debug("Submitting login form to %s with fields %s", form["action"], list(payload))
        post_url = _normalize_url(form.get("action") or "login", self.base_url)
        submit = self.session.post(post_url, data=payload)
        submit.raise_for_status()

        if not self._is_authenticated(submit.text):
            # Some login flows redirect; follow once more to be sure.
            if submit.history:
                final = submit
            else:
                final = self.session.get(_normalize_url("myaccount", self.base_url))
            if not self._is_authenticated(final.text):
                raise PBaseLoginError("PBase login failed; verify credentials.")

    def get(self, url: str, *, stream: bool = False, headers: Optional[dict] = None) -> requests.Response:
        """GET wrapper that throttles requests if delay is configured."""
        full_url = _normalize_url(url, self.base_url) if not url.startswith(("http://", "https://")) else url
        self._respect_delay()
        logger.debug("GET %s", full_url)
        response = self.session.get(full_url, stream=stream, headers=headers)
        response.raise_for_status()
        return response

    def get_soup(self, url: str) -> BeautifulSoup:
        """Retrieve a page and parse into BeautifulSoup."""
        response = self.get(url)
        return BeautifulSoup(response.text, "html.parser")

    def iter_links(self, soup: BeautifulSoup) -> Iterable[str]:
        """Yield absolute hrefs for all anchor tags in the soup."""
        for anchor in soup.find_all("a"):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            yield _normalize_url(href, self.base_url)

    def _locate_login_form(self, soup: BeautifulSoup) -> Optional[dict]:
        """Return dict representation of the login form."""
        form = None
        for candidate in soup.find_all("form"):
            method = (candidate.get("method") or "").lower()
            if method != "post":
                continue
            if candidate.find("input", {"type": "password"}):
                form = candidate
                break
        if not form:
            return None
        action = form.get("action")
        payload = {}
        username_field = None
        password_field = None
        for field in form.find_all("input"):
            name = field.get("name")
            if not name:
                continue
            value = field.get("value") or ""
            field_type = (field.get("type") or "").lower()
            if field_type == "password":
                password_field = name
            elif field_type in {"text", "email"} and "user" in name.lower():
                username_field = name
            payload[name] = value
        if not username_field:
            # try select the first text input if not inferred
            text_inputs = [
                field.get("name")
                for field in form.find_all("input")
                if (field.get("type") or "text").lower() in {"text", "email"}
            ]
            if text_inputs:
                username_field = text_inputs[0]
        if not password_field:
            pwd_inputs = [
                field.get("name")
                for field in form.find_all("input")
                if (field.get("type") or "").lower() == "password"
            ]
            if pwd_inputs:
                password_field = pwd_inputs[0]
        if not username_field or not password_field:
            raise PBaseLoginError("Login form does not contain expected username/password inputs.")
        payload[username_field] = self.username
        payload[password_field] = self.password
        return {"action": action, "payload": payload}

    def _build_login_payload(self, form: dict) -> dict:
        """Extract payload from form structure."""
        return dict(form["payload"])

    @staticmethod
    def _is_authenticated(html: str) -> bool:
        """Heuristic: successful login pages show a 'logout' link."""
        lowered = html.lower()
        return "logout" in lowered and "login" not in lowered

    def _respect_delay(self) -> None:
        if self.request_delay <= 0:
            return
        delta = time.monotonic() - self._last_request_ts
        if delta < self.request_delay:
            time.sleep(self.request_delay - delta)
        self._last_request_ts = time.monotonic()
