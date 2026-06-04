# security_utils.py
# ── Compatibility shim: passlib 1.7.4 checks bcrypt.__about__.__version__
#    which was removed in bcrypt 4.x. Patch it before passlib loads.
import bcrypt as _bcrypt_mod
if not hasattr(_bcrypt_mod, '__about__'):
    class _About:
        __version__ = getattr(_bcrypt_mod, '__version__', '4.0.0')
    _bcrypt_mod.__about__ = _About()

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
