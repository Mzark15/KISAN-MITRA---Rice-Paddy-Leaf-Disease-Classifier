"""
routers/auth.py — Login endpoints (Amazon Cognito behind the backend)

Farmers (phone + SMS OTP, once — the app refreshes silently afterwards):
  POST  /auth/otp/start    send a code
  POST  /auth/otp/verify   check the code → access + refresh tokens
  POST  /auth/refresh      new access token (and a new refresh token)
  POST  /auth/logout       revoke the refresh token
  GET   /auth/me           profile
  PATCH /auth/me           update language / village / name
  DELETE /auth/me          delete the account and its data (Play Store requirement)

Staff (dashboard: email + password + authenticator-app MFA):
  POST /admin/auth/login, /admin/auth/challenge, /admin/auth/refresh, /admin/auth/logout
  GET  /admin/auth/me

Errors use a stable `detail` code (e.g. "invalid_code", "too_many_requests")
that the frontend translates into the farmer's language.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

import auth_service
import database
from auth_service import AuthError, Farmer, Staff, current_farmer, require_staff
from schemas import (
    OtpStartRequest, OtpStartResponse, OtpVerifyRequest, LogoutRequest, ProfileUpdate,
    RefreshRequest, StaffChallengeRequest, StaffLoginRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

RESEND_AFTER_SECONDS = 30

# (limit, window seconds). OTP SMS cost money, so they are throttled per phone
# number and per IP, and shared across server instances via DynamoDB.
OTP_LIMITS_PHONE = [(1, RESEND_AFTER_SECONDS), (5, 3600)]
OTP_LIMITS_IP = [(20, 3600)]
VERIFY_LIMITS_PHONE = [(10, 3600)]
STAFF_LOGIN_LIMITS = [(10, 900)]


def _raise(exc: AuthError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    raise HTTPException(status_code=exc.status, detail=exc.code, headers=headers) from exc


async def _call(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except AuthError as exc:
        _raise(exc)


async def _throttle(key: str, limits: list[tuple[int, int]]) -> None:
    for limit, window in limits:
        try:
            ok = await database.rate_limit_ok(f"{key}#{window}", limit, window)
        except Exception as exc:
            # Fail closed: without the limiter, OTP endpoints could be abused for SMS spam.
            logger.error("Rate limiter unavailable: %s", exc)
            raise HTTPException(status_code=503, detail="service_unavailable") from exc
        if not ok:
            raise HTTPException(status_code=429, detail="too_many_requests")


def _phone(raw: str) -> str:
    try:
        return auth_service.normalize_phone(raw)
    except AuthError as exc:
        _raise(exc)


# ---------------------------------------------------------------------------
# Farmers
# ---------------------------------------------------------------------------

@router.post("/auth/otp/start", response_model=OtpStartResponse, summary="Send a login code by SMS")
async def otp_start(body: OtpStartRequest, request: Request):
    phone = _phone(body.phone)
    await _throttle(f"otp-ip:{auth_service.client_ip(request)}", OTP_LIMITS_IP)
    await _throttle(f"otp-phone:{phone}", OTP_LIMITS_PHONE)
    result = await _call(auth_service.start_phone_login, phone)
    return OtpStartResponse(phone=phone, resend_after=RESEND_AFTER_SECONDS, **result)


@router.post("/auth/otp/verify", summary="Check the SMS code and log in")
async def otp_verify(body: OtpVerifyRequest):
    phone = _phone(body.phone)
    await _throttle(f"verify-phone:{phone}", VERIFY_LIMITS_PHONE)
    tokens = await _call(auth_service.verify_phone_login, phone, body.code, body.flow, body.session)
    user = await database.upsert_user(tokens.pop("user_id"), tokens.pop("phone"))
    return {**tokens, "user": user}


@router.post("/auth/refresh", summary="Get a new access token")
async def refresh(body: RefreshRequest):
    pool = auth_service.farmer_pool()
    if pool is None:
        _raise(AuthError("auth_not_configured", 503))
    return await _call(auth_service.refresh, pool, body.username, body.refresh_token)


@router.post("/auth/logout", summary="Log out (revoke the refresh token)")
async def logout(body: LogoutRequest):
    pool = auth_service.farmer_pool()
    if pool is not None:
        await asyncio.to_thread(auth_service.logout, pool, body.refresh_token)
    return {"ok": True}


@router.get("/auth/me", summary="The logged-in farmer's profile")
async def me(farmer: Farmer = Depends(current_farmer)):
    user = await database.get_user(farmer.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


@router.patch("/auth/me", summary="Update profile")
async def update_me(body: ProfileUpdate, farmer: Farmer = Depends(current_farmer)):
    return await database.update_user_profile(farmer.user_id, **body.model_dump())


@router.delete("/auth/me", summary="Delete my account and data")
async def delete_me(farmer: Farmer = Depends(current_farmer)):
    # Data first: if Cognito then fails, the farmer can still log in and retry.
    removed = await database.delete_user_data(farmer.user_id)
    await _call(auth_service.delete_farmer, farmer.username)
    logger.info("Deleted account %s (%d diagnoses)", farmer.user_id, removed)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Staff (dashboard)
# ---------------------------------------------------------------------------

@router.post("/admin/auth/login", summary="Staff login: email + password")
async def staff_login(body: StaffLoginRequest, request: Request):
    await _throttle(f"staff-ip:{auth_service.client_ip(request)}", STAFF_LOGIN_LIMITS)
    await _throttle(f"staff-email:{body.email.lower()}", STAFF_LOGIN_LIMITS)
    return await _call(auth_service.staff_login, body.email, body.password)


@router.post("/admin/auth/challenge", summary="Staff login: new password / MFA setup / MFA code")
async def staff_challenge(body: StaffChallengeRequest):
    await _throttle(f"staff-user:{body.username}", STAFF_LOGIN_LIMITS)
    return await _call(
        auth_service.staff_challenge,
        body.username, body.challenge, body.session, body.new_password, body.code,
    )


@router.post("/admin/auth/refresh", summary="Staff: new access token")
async def staff_refresh(body: RefreshRequest):
    pool = auth_service.admin_pool()
    if pool is None:
        _raise(AuthError("auth_not_configured", 503))
    return await _call(auth_service.refresh, pool, body.username, body.refresh_token)


@router.post("/admin/auth/logout", summary="Staff logout")
async def staff_logout(body: LogoutRequest):
    pool = auth_service.admin_pool()
    if pool is not None:
        await asyncio.to_thread(auth_service.logout, pool, body.refresh_token)
    return {"ok": True}


@router.get("/admin/auth/me", summary="The logged-in staff member")
async def staff_me(staff: Staff = Depends(require_staff())):
    return {"user_id": staff.user_id, "username": staff.username, "roles": list(staff.roles)}
