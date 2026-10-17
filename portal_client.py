"""Thin client for the hosted portal's API. Only talks to the address the tutor configured."""
from urllib.parse import urlparse

import requests

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class PortalError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PortalClient:
    def __init__(self, base_url: str, token: str, session=None, timeout: float = 15):
        base_url = (base_url or "").strip().rstrip("/")
        u = urlparse(base_url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise PortalError("Enter the portal address, for example https://tutor-portal.example.com")
        if u.scheme == "http" and u.hostname not in LOCAL_HOSTS:
            raise PortalError("Use an https:// address. Student names and answers are sent to this server, "
                              "so the connection must be encrypted.")
        if not (token or "").strip():
            raise PortalError("Enter your API token from the portal dashboard.")
        self.base, self.token, self.timeout = base_url, token.strip(), timeout
        self.s = session or requests.Session()

    def _req(self, method: str, path: str, **kw):
        try:
            r = self.s.request(method, f"{self.base}/api/v1{path}", timeout=self.timeout,
                               headers={"Authorization": f"Bearer {self.token}"}, **kw)
        except requests.RequestException as e:
            raise PortalError(f"Can't reach the portal at {self.base}. Check the address and your connection.") from e
        if r.status_code >= 400:
            try:
                msg = r.json().get("error", "")
            except ValueError:
                msg = ""
            raise PortalError(msg or f"The portal returned an error ({r.status_code}).", r.status_code)
        try:
            return r.json()
        except ValueError:
            raise PortalError("The portal sent a reply this app can't read. Is the address right?")

    def ping(self) -> dict:
        return self._req("GET", "/ping")

    def students(self) -> list[dict]:
        return self._req("GET", "/students")["students"]

    def add_student(self, name: str, level: str = "") -> dict:
        return self._req("POST", "/students", json={"name": name, "level": level})

    def delete_student(self, portal_student_id: int):
        self._req("DELETE", f"/students/{portal_student_id}")

    def new_link(self, portal_student_id: int) -> dict:
        return self._req("POST", f"/students/{portal_student_id}/new-link")

    def assign(self, title, subject, due, student_ids, questions, mcq_key) -> list[dict]:
        return self._req("POST", "/assignments", json={
            "title": title, "subject": subject, "due": due, "student_ids": student_ids,
            "questions": questions, "mcq_key": mcq_key})["assignments"]

    def withdraw(self, assignment_id: int):
        self._req("DELETE", f"/assignments/{assignment_id}")

    def submissions(self) -> list[dict]:
        return self._req("GET", "/submissions")["submissions"]

    def feedback(self, assignment_id: int, score: int, total: int, comment: str = ""):
        self._req("POST", f"/assignments/{assignment_id}/feedback",
                  json={"score": score, "total": total, "comment": comment})
