# Authentication (who are you?) and authorization (what are you allowed to do?).
#
# Flow:
#   1. POST /auth/login with username + password
#   2. We check the password hash in the database
#   3. We return a JWT (a signed token) that contains the username and role
#   4. Client sends "Authorization: Bearer <token>" on every next request
#   5. We verify the signature + expiry and read the role from the token

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config

bearer_scheme = HTTPBearer(auto_error=False)


# ---------- passwords ----------
# We never store plain passwords, only a bcrypt hash of them.

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password, password_hash):
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ---------- JWT ----------

def create_token(username, role):
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token):
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Dependency: use it in an endpoint to require a logged-in user.
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_token(credentials.credentials)
    return {"username": payload["sub"], "role": payload["role"]}


# ---------- RBAC (role based access control) ----------
# Which role can do what:
ROLE_PERMISSIONS = {
    "admin": ["chat", "view_metrics", "view_reports", "manage_users"],
    "user": ["chat"],
    "readonly": ["view_reports"],
}


def require_permission(permission):
    # Returns a dependency that checks the logged-in user's role has this permission.
    def checker(user=Depends(get_current_user)):
        if permission not in ROLE_PERMISSIONS.get(user["role"], []):
            raise HTTPException(status_code=403, detail="Not allowed for your role")
        return user

    return checker
