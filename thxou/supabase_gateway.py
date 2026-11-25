import httpx
from flask import current_app, request


class SupabaseGateway:
    def __init__(self, token=None):
        self.token = token or request.cookies.get("access_token")
        self.headers = {"apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"]}
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def rpc(self, name, payload=None):
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.post(f"/rest/v1/rpc/{name}", headers=self.headers, json=payload or {})
            response.raise_for_status()
            return response.json() if response.content else None

    def table(self, name, params=None):
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.get(f"/rest/v1/{name}", headers=self.headers, params=params or {})
            response.raise_for_status()
            return response.json()

    @classmethod
    def request_otp(cls, phone, captcha_token):
        headers = {"apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"]}
        payload = {"phone": phone, "options": {"captcha_token": captcha_token}}
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.post("/auth/v1/otp", headers=headers, json=payload)
            response.raise_for_status()

    @classmethod
    def verify_otp(cls, phone, code):
        headers = {"apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"]}
        payload = {"phone": phone, "token": code, "type": "sms"}
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.post("/auth/v1/verify", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    @classmethod
    def refresh_session(cls, refresh_token):
        headers = {"apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"]}
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.post(
                "/auth/v1/token",
                params={"grant_type": "refresh_token"},
                headers=headers,
                json={"refresh_token": refresh_token},
            )
            response.raise_for_status()
            return response.json()

    @classmethod
    def revoke_session(cls, access_token):
        headers = {
            "apikey": current_app.config["SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {access_token}",
        }
        with httpx.Client(base_url=current_app.config["SUPABASE_URL"], timeout=current_app.config["DATA_TIMEOUT"]) as client:
            response = client.post("/auth/v1/logout", headers=headers)
            response.raise_for_status()
