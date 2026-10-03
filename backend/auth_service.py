"""
auth_service.py — Login with Amazon Cognito (user pools created by infra/ Terraform)

Two pools:
  farmers — phone number + SMS one-time code, no password. Logs in once; the
            app then refreshes tokens silently (refresh token rotates on every
            use, so an active farmer never sees the login screen again).
  admins  — dashboard staff: email + password + authenticator-app MFA,
            roles from Cognito groups (admin / field_officer / viewer).

The backend is the only Cognito client (confidential, with a client secret), so
OTP SMS can only be triggered through our rate-limited endpoints.

API calls to Cognito are synchronous (boto3); routers run them in a worker thread.
Access tokens are verified locally against the pool's public keys (JWKS), so
checking a request costs no network call.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional
from urllib.parse import quote

import boto3
import jwt
from botocore.exceptions import ClientError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Only Indian mobile numbers by default: limits SMS cost and toll-fraud exposure.
# Comma-separated E.164 prefixes, e.g. "+91,+977".
ALLOWED_PHONE_PREFIXES = [
    p.strip() for p in os.environ.get("ALLOWED_PHONE_PREFIXES", "+91").split(",") if p.strip()
]

STAFF_ROLES = ("admin", "field_officer", "viewer")


class AuthError(Exception):
    """Login failed. `code` is a stable string the frontend translates."""

    def __init__(self, code: str, status: int = 400, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Pool:
    name: str
    pool_id: str
    client_id: str
    client_secret: str

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{REGION}.amazonaws.com/{self.pool_id}"

    def secret_hash(self, username: str) -> str:
        digest = hmac.new(
            self.client_secret.encode(), (username + self.client_id).encode(), hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode()


def _pool(prefix: str, name: str) -> Optional[Pool]:
    values = [os.environ.get(f"COGNITO_{prefix}_{k}", "") for k in ("POOL_ID", "CLIENT_ID", "CLIENT_SECRET")]
    return Pool(name, *values) if all(values) else None


@lru_cache(maxsize=None)
def farmer_pool() -> Optional[Pool]:
    return _pool("FARMER", "farmers")


@lru_cache(maxsize=None)
def admin_pool() -> Optional[Pool]:
    return _pool("ADMIN", "admins")


def _require(pool: Optional[Pool]) -> Pool:
    if pool is None:
        raise AuthError("auth_not_configured", 503, "Cognito is not configured on the server.")
    return pool


@lru_cache(maxsize=None)
def _cognito():
    return boto3.client("cognito-idp", region_name=REGION)


# Cognito error code -> (our code, HTTP status)
_ERRORS = {
    "CodeMismatchException":         ("invalid_code", 400),
    "ExpiredCodeException":          ("code_expired", 400),
    "NotAuthorizedException":        ("not_authorized", 401),
    "TooManyRequestsException":      ("too_many_requests", 429),
    "LimitExceededException":        ("too_many_requests", 429),
    "TooManyFailedAttemptsException": ("too_many_requests", 429),
    "CodeDeliveryFailureException":  ("sms_failed", 502),
    "InvalidPasswordException":      ("weak_password", 400),
    "UserNotConfirmedException":     ("not_authorized", 401),
    "UserNotFoundException":         ("not_authorized", 401),
    "EnableSoftwareTokenMFAException": ("invalid_code", 400),
}


def _translate(exc: ClientError) -> AuthError:
    aws_code = exc.response["Error"]["Code"]
    code, status = _ERRORS.get(aws_code, ("auth_failed", 502))
    if code == "auth_failed":
        logger.error("Unexpected Cognito error %s: %s", aws_code, exc)
    return AuthError(code, status, exc.response["Error"].get("Message", aws_code))


def _call(fn, **kwargs) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except ClientError as exc:
        raise _translate(exc) from exc


def _tokens(result: dict[str, Any], username: str) -> dict[str, Any]:
    tokens = {
        "access_token":  result["AccessToken"],
        "expires_in":    result["ExpiresIn"],
        "token_type":    "Bearer",
        "username":      username,   # needed to refresh (secret hash)
    }
    if result.get("RefreshToken"):
        tokens["refresh_token"] = result["RefreshToken"]
    return tokens


def _lookup(pool: Pool, login: str) -> Optional[dict[str, Any]]:
    """AdminGetUser by phone/email alias. Returns None if the user doesn't exist."""
    try:
        return _cognito().admin_get_user(UserPoolId=pool.pool_id, Username=login)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "UserNotFoundException":
            return None
        raise _translate(exc) from exc


# ---------------------------------------------------------------------------
# Farmers: phone + SMS OTP
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    """Accept '98765 43210', '09876543210', '+91-98765-43210' etc. Return E.164."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        digits = digits.lstrip("0")
        if len(digits) == 10:                  # Indian mobile without country code
            digits = "+91" + digits
        else:
            digits = "+" + digits
    if not _PHONE_RE.match(digits):
        raise AuthError("invalid_phone")
    if not any(digits.startswith(p) for p in ALLOWED_PHONE_PREFIXES):
        raise AuthError("phone_not_supported")
    if digits.startswith("+91") and (len(digits) != 13 or digits[3] not in "6789"):
        raise AuthError("invalid_phone")
    return digits


def start_phone_login(phone: str) -> dict[str, Any]:
    """
    Send an OTP. New numbers are signed up (Cognito sends a confirmation code);
    existing numbers get a sign-in code. Either way the farmer just sees "enter the code".
    """
    pool = _require(farmer_pool())
    client = _cognito()
    user = _lookup(pool, phone)

    if user is None or user["UserStatus"] == "UNCONFIRMED":
        if user is None:
            _call(
                client.sign_up,
                ClientId=pool.client_id,
                SecretHash=pool.secret_hash(phone),
                Username=phone,
                UserAttributes=[{"Name": "phone_number", "Value": phone}],
            )
        else:
            _call(
                client.resend_confirmation_code,
                ClientId=pool.client_id,
                SecretHash=pool.secret_hash(phone),
                Username=phone,
            )
        return {"flow": "signup", "session": None}

    username = user["Username"]   # the Cognito id (sub); the phone is only an alias
    resp = _call(
        client.admin_initiate_auth,
        UserPoolId=pool.pool_id,
        ClientId=pool.client_id,
        AuthFlow="USER_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PREFERRED_CHALLENGE": "SMS_OTP",
            "SECRET_HASH": pool.secret_hash(username),
        },
    )
    if resp.get("ChallengeName") != "SMS_OTP":
        logger.error("Unexpected challenge for farmer sign-in: %s", resp.get("ChallengeName"))
        raise AuthError("auth_failed", 502)
    return {"flow": "signin", "session": resp["Session"]}


def verify_phone_login(phone: str, code: str, flow: str, session: Optional[str]) -> dict[str, Any]:
    """Check the OTP and return tokens. Also returns the user's id and phone."""
    pool = _require(farmer_pool())
    client = _cognito()
    code = (code or "").strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise AuthError("invalid_code")

    if flow == "signup":
        confirmed = _call(
            client.confirm_sign_up,
            ClientId=pool.client_id,
            SecretHash=pool.secret_hash(phone),
            Username=phone,
            ConfirmationCode=code,
        )
        user = _lookup(pool, phone)
        if user is None:
            raise AuthError("auth_failed", 502)
        username = user["Username"]
        # Sign in straight after confirming, using the session Cognito returns
        # (no second SMS).
        resp = _call(
            client.admin_initiate_auth,
            UserPoolId=pool.pool_id,
            ClientId=pool.client_id,
            AuthFlow="USER_AUTH",
            AuthParameters={"USERNAME": username, "SECRET_HASH": pool.secret_hash(username)},
            Session=confirmed["Session"],
        )
    elif flow == "signin" and session:
        user = _lookup(pool, phone)
        if user is None:
            raise AuthError("not_authorized", 401)
        username = user["Username"]
        resp = _call(
            client.admin_respond_to_auth_challenge,
            UserPoolId=pool.pool_id,
            ClientId=pool.client_id,
            ChallengeName="SMS_OTP",
            Session=session,
            ChallengeResponses={
                "USERNAME": username,
                "SMS_OTP_CODE": code,
                "SECRET_HASH": pool.secret_hash(username),
            },
        )
    else:
        raise AuthError("invalid_request")

    if "AuthenticationResult" not in resp:
        logger.error("Farmer login ended with challenge %s", resp.get("ChallengeName"))
        raise AuthError("auth_failed", 502)
    return {**_tokens(resp["AuthenticationResult"], username), "user_id": _attr(user, "sub"), "phone": phone}


def _attr(user: dict[str, Any], name: str) -> Optional[str]:
    for a in user.get("UserAttributes", []):
        if a["Name"] == name:
            return a["Value"]
    return None


# ---------------------------------------------------------------------------
# Shared: refresh and logout
# ---------------------------------------------------------------------------

def refresh(pool: Pool, username: str, refresh_token: str) -> dict[str, Any]:
    """
    New access token from a refresh token. The farmer pool rotates refresh tokens
    (a new one comes back each time); the admin pool keeps the same one.
    """
    if pool.name == "farmers":
        resp = _call(
            _cognito().get_tokens_from_refresh_token,
            RefreshToken=refresh_token,
            ClientId=pool.client_id,
            ClientSecret=pool.client_secret,
        )
    else:
        resp = _call(
            _cognito().admin_initiate_auth,
            UserPoolId=pool.pool_id,
            ClientId=pool.client_id,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token, "SECRET_HASH": pool.secret_hash(username)},
        )
    return _tokens(resp["AuthenticationResult"], username)


def delete_farmer(username: str) -> None:
    """Permanently delete the farmer's Cognito user (their phone number can sign up again later)."""
    pool = _require(farmer_pool())
    try:
        _cognito().admin_delete_user(UserPoolId=pool.pool_id, Username=username)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "UserNotFoundException":
            raise _translate(exc) from exc


def logout(pool: Pool, refresh_token: str) -> None:
    """Revoke the refresh token (and the access tokens issued from it)."""
    try:
        _cognito().revoke_token(Token=refresh_token, ClientId=pool.client_id, ClientSecret=pool.client_secret)
    except ClientError as exc:
        # Logging out with an already invalid token is not an error for the user.
        logger.info("revoke_token failed: %s", exc.response["Error"]["Code"])


# ---------------------------------------------------------------------------
# Staff: email + password + TOTP MFA
# ---------------------------------------------------------------------------

def _staff_step(pool: Pool, username: str, resp: dict[str, Any]) -> dict[str, Any]:
    """Turn a Cognito response into either tokens or the next step for the dashboard UI."""
    if "AuthenticationResult" in resp:
        return {"status": "ok", **_tokens(resp["AuthenticationResult"], username)}

    challenge = resp.get("ChallengeName")
    step = {"status": "challenge", "challenge": challenge, "session": resp["Session"], "username": username}
    if challenge == "MFA_SETUP":
        assoc = _call(_cognito().associate_software_token, Session=resp["Session"])
        user = _lookup(pool, username)
        label = quote(f"KisanMitra:{(user and _attr(user, 'email')) or username}")
        step.update(
            session=assoc["Session"],
            secret=assoc["SecretCode"],
            otpauth_uri=f"otpauth://totp/{label}?secret={assoc['SecretCode']}&issuer=KisanMitra",
        )
    elif challenge not in ("NEW_PASSWORD_REQUIRED", "SOFTWARE_TOKEN_MFA"):
        logger.error("Unsupported staff challenge %s", challenge)
        raise AuthError("auth_failed", 502)
    return step


def staff_login(email: str, password: str) -> dict[str, Any]:
    pool = _require(admin_pool())
    user = _lookup(pool, email.strip().lower())
    if user is None:
        raise AuthError("not_authorized", 401)
    username = user["Username"]
    resp = _call(
        _cognito().admin_initiate_auth,
        UserPoolId=pool.pool_id,
        ClientId=pool.client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password, "SECRET_HASH": pool.secret_hash(username)},
    )
    return _staff_step(pool, username, resp)


def staff_challenge(
    username: str, challenge: str, session: str,
    new_password: Optional[str] = None, code: Optional[str] = None,
) -> dict[str, Any]:
    pool = _require(admin_pool())
    client = _cognito()
    base = {"USERNAME": username, "SECRET_HASH": pool.secret_hash(username)}

    if challenge == "NEW_PASSWORD_REQUIRED":
        if not new_password:
            raise AuthError("weak_password")
        responses = {**base, "NEW_PASSWORD": new_password}
    elif challenge == "SOFTWARE_TOKEN_MFA":
        responses = {**base, "SOFTWARE_TOKEN_MFA_CODE": (code or "").strip()}
    elif challenge == "MFA_SETUP":
        verified = _call(
            client.verify_software_token, Session=session, UserCode=(code or "").strip(),
            FriendlyDeviceName="Kisan Mitra dashboard",
        )
        if verified.get("Status") != "SUCCESS":
            raise AuthError("invalid_code")
        session = verified["Session"]
        responses = base
    else:
        raise AuthError("invalid_request")

    resp = _call(
        client.admin_respond_to_auth_challenge,
        UserPoolId=pool.pool_id,
        ClientId=pool.client_id,
        ChallengeName=challenge,
        Session=session,
        ChallengeResponses=responses,
    )
    return _staff_step(pool, username, resp)


# ---------------------------------------------------------------------------
# Verifying access tokens on API requests
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _jwks(issuer: str) -> jwt.PyJWKClient:
    # Keys are cached; a new key id triggers one refetch (Cognito key rotation).
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def verify_access_token(pool: Pool, token: str) -> dict[str, Any]:
    try:
        key = _jwks(pool.issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], issuer=pool.issuer,
            options={"require": ["exp", "iss", "sub", "token_use", "client_id"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token_expired", 401) from exc
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise AuthError("invalid_token", 401) from exc

    if claims["token_use"] != "access" or claims["client_id"] != pool.client_id:
        raise AuthError("invalid_token", 401)
    return claims


@dataclass(frozen=True)
class Farmer:
    user_id: str      # Cognito sub
    username: str


@dataclass(frozen=True)
class Staff:
    user_id: str
    username: str
    roles: tuple[str, ...]


_bearer = HTTPBearer(auto_error=False)


def _http(exc: AuthError) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return HTTPException(status_code=exc.status, detail=exc.code, headers=headers)


# Temporary guest mode (AUTH_DISABLED=1): no login, every caller is "guest-<ip>". Per-guest rate
# limits still apply (ratelimit.py). Turn it off (unset the variable) once SMS login is live.
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "").lower() in ("1", "true", "yes")


def current_farmer(
    request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)
) -> Farmer:
    """FastAPI dependency: the logged-in farmer, or 401 (a per-IP guest when AUTH_DISABLED)."""
    if AUTH_DISABLED:
        return Farmer(user_id=f"guest-{client_ip(request)}", username="guest")
    if creds is None:
        raise _http(AuthError("not_authenticated", 401))
    try:
        claims = verify_access_token(_require(farmer_pool()), creds.credentials)
    except AuthError as exc:
        raise _http(exc) from exc
    return Farmer(user_id=claims["sub"], username=claims.get("username", claims["sub"]))


def require_staff(*roles: str):
    """FastAPI dependency factory: a logged-in staff member with one of `roles` (default: any)."""
    allowed = set(roles or STAFF_ROLES)

    def dependency(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Staff:
        if creds is None:
            raise _http(AuthError("not_authenticated", 401))
        try:
            claims = verify_access_token(_require(admin_pool()), creds.credentials)
        except AuthError as exc:
            raise _http(exc) from exc
        user_roles = tuple(claims.get("cognito:groups", []))
        if not allowed.intersection(user_roles):
            raise _http(AuthError("forbidden", 403))
        return Staff(user_id=claims["sub"], username=claims.get("username", claims["sub"]), roles=user_roles)

    return dependency


def client_ip(request: Request) -> str:
    """Caller IP. The ALB appends the real client IP as the last X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
