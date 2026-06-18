"""Tanek klient za GoCardless Bank Account Data (PSD2 / Open Banking, prej Nordigen).

API: https://bankaccountdata.gocardless.com/api/v2/ — REST z žetonom (Bearer).
Tok povezave:
    1. token/new  → access žeton (predpomnimo v procesu do izteka)
    2. institutions?country=si  → seznam bank
    3. requisitions  → ustvari privolitev, dobiš povezavo (link) na banko
    4. (uporabnik potrdi pri banki, banka preusmeri nazaj)
    5. requisitions/{id}  → seznam account_id-jev povezanih računov
    6. accounts/{id}/details + /transactions  → IBAN in transakcije

Vse omrežne napake in manjkajoče poverilnice se prevedejo v GoCardlessError z uporabniku
prijaznim sporočilom (klicatelj ga pokaže namesto 500).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from bilanca import config


class GoCardlessError(RuntimeError):
    """Napaka pri komunikaciji z GoCardless (ali manjkajoče poverilnice)."""


class GoCardlessClient:
    """Klient z avtomatskim osveževanjem dostopnega žetona."""

    def __init__(
        self,
        secret_id: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._secret_id = secret_id if secret_id is not None else config.GOCARDLESS_SECRET_ID
        self._secret_key = secret_key if secret_key is not None else config.GOCARDLESS_SECRET_KEY
        self._base = (base_url or config.GOCARDLESS_BASE_URL).rstrip("/") + "/api/v2"
        self._timeout = timeout
        self._access: str = ""
        self._access_expires: float = 0.0

    # ----------------------------------------------------------------- avtentikacija
    def _ensure_token(self) -> str:
        if not (self._secret_id and self._secret_key):
            raise GoCardlessError(
                "GoCardless poverilnice niso nastavljene. Vpiši GOCARDLESS_SECRET_ID in "
                "GOCARDLESS_SECRET_KEY v datoteko .env."
            )
        # 60 s rezerve pred dejanskim iztekom.
        if self._access and time.monotonic() < self._access_expires - 60:
            return self._access
        data = self._request(
            "POST",
            "/token/new/",
            json={"secret_id": self._secret_id, "secret_key": self._secret_key},
            auth=False,
        )
        self._access = data.get("access", "")
        self._access_expires = time.monotonic() + float(data.get("access_expires", 3600))
        if not self._access:
            raise GoCardlessError("GoCardless ni vrnil dostopnega žetona (preveri poverilnice).")
        return self._access

    # ----------------------------------------------------------------- osnovni klic
    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._ensure_token()}"
        try:
            resp = httpx.request(
                method,
                self._base + path,
                json=json,
                params=params,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise GoCardlessError(f"Napaka pri povezavi z GoCardless: {exc}") from exc

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("summary") or str(body)
            except Exception:  # noqa: BLE001
                detail = resp.text[:300]
            raise GoCardlessError(f"GoCardless napaka {resp.status_code}: {detail}")
        if not resp.content:
            return {}
        return resp.json()

    # ----------------------------------------------------------------- API metode
    def list_institutions(self, country: str = "si") -> list[dict[str, Any]]:
        """Banke v dani državi: [{id, name, logo, ...}]."""
        data = self._request("GET", "/institutions/", params={"country": country})
        # API vrne seznam neposredno.
        return data if isinstance(data, list) else data.get("results", [])

    def create_requisition(
        self, institution_id: str, redirect_url: str, reference: str
    ) -> dict[str, Any]:
        """Ustvari privolitev; vrne {id, link, ...} (link = stran banke za potrditev)."""
        return self._request(
            "POST",
            "/requisitions/",
            json={
                "institution_id": institution_id,
                "redirect": redirect_url,
                "reference": reference,
                "user_language": "SL",
            },
        )

    def get_requisition(self, requisition_id: str) -> dict[str, Any]:
        """Stanje privolitve: {status, accounts: [account_id, ...], ...}."""
        return self._request("GET", f"/requisitions/{requisition_id}/")

    def delete_requisition(self, requisition_id: str) -> None:
        """Odstrani privolitev pri GoCardless (preklic dostopa)."""
        self._request("DELETE", f"/requisitions/{requisition_id}/")

    def get_account_details(self, account_id: str) -> dict[str, Any]:
        """Podatki računa; IBAN je pod data['account']['iban']."""
        data = self._request("GET", f"/accounts/{account_id}/details/")
        return data.get("account", {})

    def get_account_transactions(
        self, account_id: str, date_from: str | None = None
    ) -> dict[str, Any]:
        """Transakcije računa: {transactions: {booked: [...], pending: [...]}}."""
        params = {"date_from": date_from} if date_from else None
        return self._request("GET", f"/accounts/{account_id}/transactions/", params=params)
