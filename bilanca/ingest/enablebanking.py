"""Tanek klient za Enable Banking API (PSD2 / Open Banking).

API: https://api.enablebanking.com — REST z avtentikacijo prek podpisanega JWT (RS256).
JWT podpišemo z zasebnim ključem, pridobljenim ob registraciji aplikacije; Application ID
gre v glavo kot `kid`.

Tok povezave:
    1. GET  /aspsps?country=SI       → seznam bank
    2. POST /auth                     → vrne url na banko (privolitev)
    3. (uporabnik potrdi pri banki, banka preusmeri nazaj s ?code=...)
    4. POST /sessions {code}          → session_id + seznam računov (uid)
    5. GET  /accounts/{uid}/details   → IBAN
    6. GET  /accounts/{uid}/transactions → transakcije (Berlin Group)

Vse napake (manjkajoče poverilnice, omrežje, 4xx/5xx) se prevedejo v EnableBankingError.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from bilanca import config


class EnableBankingError(RuntimeError):
    """Napaka pri komunikaciji z Enable Banking (ali manjkajoče poverilnice)."""


class EnableBankingClient:
    """Klient s samodejnim podpisovanjem JWT (predpomnjen do izteka)."""

    def __init__(
        self,
        app_id: str | None = None,
        key_path: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._app_id = app_id if app_id is not None else config.ENABLE_BANKING_APP_ID
        self._key_path = key_path if key_path is not None else config.ENABLE_BANKING_KEY_PATH
        self._base = (base_url or config.ENABLE_BANKING_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._jwt: str = ""
        self._jwt_expires: float = 0.0

    # ----------------------------------------------------------------- avtentikacija
    def _token(self) -> str:
        if not (self._app_id and self._key_path):
            raise EnableBankingError(
                "Enable Banking ni nastavljen. Vpiši ENABLE_BANKING_APP_ID in pot do zasebnega "
                "ključa (ENABLE_BANKING_KEY_PATH) v datoteko .env."
            )
        # JWT velja 1 uro; osvežimo z 1-minutno rezervo.
        if self._jwt and time.monotonic() < self._jwt_expires - 60:
            return self._jwt
        try:
            with open(self._key_path, "rb") as fh:
                private_key = fh.read()
        except OSError as exc:
            raise EnableBankingError(
                f"Zasebnega ključa ni mogoče prebrati ({self._key_path}): {exc}"
            ) from exc

        iat = int(time.time())
        try:
            token = jwt.encode(
                {
                    "iss": "enablebanking.com",
                    "aud": "api.enablebanking.com",
                    "iat": iat,
                    "exp": iat + 3600,
                },
                private_key,
                algorithm="RS256",
                headers={"typ": "JWT", "kid": self._app_id},
            )
        except Exception as exc:  # noqa: BLE001 — napačen ključ ipd.
            raise EnableBankingError(f"Napaka pri podpisovanju JWT: {exc}") from exc

        self._jwt = token
        self._jwt_expires = time.monotonic() + 3600
        return token

    # ----------------------------------------------------------------- osnovni klic
    def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}
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
            raise EnableBankingError(f"Napaka pri povezavi z Enable Banking: {exc}") from exc

        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("message") or body.get("error") or str(body)
            except Exception:  # noqa: BLE001
                detail = resp.text[:300]
            raise EnableBankingError(f"Enable Banking napaka {resp.status_code}: {detail}")
        if not resp.content:
            return {}
        return resp.json()

    # ----------------------------------------------------------------- API metode
    def list_aspsps(self, country: str | None = None) -> list[dict[str, Any]]:
        """Banke v dani državi: [{name, country, logo, ...}]."""
        country = (country or config.ENABLE_BANKING_COUNTRY).upper()
        data = self._request("GET", "/aspsps", params={"country": country})
        return data.get("aspsps", []) if isinstance(data, dict) else (data or [])

    def start_auth(
        self, aspsp_name: str, country: str, redirect_url: str, state: str, valid_days: int = 90
    ) -> dict[str, Any]:
        """Začne privolitev; vrne {url} (stran banke), kamor preusmerimo uporabnika."""
        valid_until = (datetime.now(UTC) + timedelta(days=valid_days)).isoformat()
        return self._request(
            "POST",
            "/auth",
            json={
                "access": {"valid_until": valid_until},
                "aspsp": {"name": aspsp_name, "country": country},
                "state": state,
                "redirect_url": redirect_url,
                "psu_type": "personal",
            },
        )

    def create_session(self, code: str) -> dict[str, Any]:
        """Iz kode (iz callbacka) ustvari sejo; vrne {session_id, accounts: [...]}."""
        return self._request("POST", "/sessions", json={"code": code})

    def get_account_details(self, account_uid: str) -> dict[str, Any]:
        """Podatki računa; IBAN je pod account_id.iban (ali iban)."""
        return self._request("GET", f"/accounts/{account_uid}/details")

    def get_account_transactions(
        self, account_uid: str, date_from: str | None = None
    ) -> dict[str, Any]:
        """Transakcije računa: {transactions: [...]} (Berlin Group zapisi)."""
        params = {"date_from": date_from} if date_from else None
        return self._request("GET", f"/accounts/{account_uid}/transactions", params=params)
