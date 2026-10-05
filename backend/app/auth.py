import hashlib
import hmac
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from .models import User, LoginSession, Membership, Project, RateBucket
from .errors import AppError

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = hasher.hash("dummy-password-not-a-user")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def csrf_token(settings):
    body = f"{int(time.time())}.{secrets.token_urlsafe(24)}"
    sig = hmac.new(settings.csrf_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def validate_csrf(request, settings):
    if request.headers.get("origin") not in settings.allowed_origins:
        raise AppError("CSRF_REJECTED", "请求来源不被允许", 403)
    token = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get("spd_csrf", "")
    try:
        body, signature = token.rsplit(".", 1)
        issued = int(body.split(".", 1)[0])
        expected = hmac.new(settings.csrf_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(token, cookie) and hmac.compare_digest(signature, expected) and 0 <= time.time() - issued < 86400
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise AppError("CSRF_REJECTED", "请求校验已失效，请刷新页面", 403)


def issue_session(db, user, response, settings, old_token=None):
    if old_token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old_token)))
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id, expires_at=time.time() + settings.session_ttl_seconds))
    response.set_cookie("spd_session", token, max_age=settings.session_ttl_seconds, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")


def current_user(db, token):
    session = db.get(LoginSession, digest(token or ""))
    if not session or session.expires_at <= time.time():
        raise AppError("UNAUTHENTICATED", "请先登录", 401)
    return db.get(User, session.user_id)


def require_project(db, actor_id, project_id):
    member = db.get(Membership, (actor_id, project_id))
    if not member:
        raise AppError("NOT_FOUND", "资源不存在或不可访问", 404)
    return db.get(Project, project_id)


def me_view(db, user):
    projects = db.scalars(select(Project).join(Membership).where(Membership.user_id == user.id)).all()
    return {"user": {"id": user.id, "email": user.email, "display_name": user.display_name},
            "projects": [{"id": p.id, "name": p.name, "synthetic": p.synthetic} for p in projects],
            "capabilities": ["read_synthetic", "run_analysis"]}


def rate_limit(factory, settings, namespace, identity):
    now = time.time()
    key = digest(f"{namespace}:{identity}:{int(now // settings.rate_window_seconds)}")
    with factory() as db:
        count = db.execute(update(RateBucket).where(RateBucket.key == key).values(count=RateBucket.count + 1).returning(RateBucket.count)).scalar_one_or_none()
        if count is None:
            try:
                with db.begin_nested():
                    db.add(RateBucket(key=key, count=1, expires_at=now + settings.rate_window_seconds * 2))
                    db.flush()
                count = 1
            except IntegrityError:
                count = db.execute(update(RateBucket).where(RateBucket.key == key).values(count=RateBucket.count + 1).returning(RateBucket.count)).scalar_one()
        db.execute(delete(RateBucket).where(RateBucket.expires_at < now))
        db.commit()
    if count > settings.rate_limit:
        raise AppError("RATE_LIMITED", "请求过于频繁，请稍后重试", 429, True)
