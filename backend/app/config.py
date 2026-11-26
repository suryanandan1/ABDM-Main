from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATABASE_DIR = BACKEND_DIR.parent / "database"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(DATABASE_DIR / 'hospital.db').as_posix()}"
    jwt_secret: str
    jwt_expire_minutes: int = 480
    session_idle_minutes: int = 30
    cookie_secure: bool = True
    password_scrypt_n: int = 2**15
    mfa_required_roles: str = ""
    mfa_issuer: str = "ABDM Hospital"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    hospital_name: str = "City General Hospital"
    hospital_code: str = "CGH"
    admin_username: str = "admin"
    admin_password: str | None = None

    mistral_api_key: str | None = None
    ai_model: str = "mistral-large-latest"
    ai_ocr_model: str = "mistral-ocr-latest"
    # OCR.space (https://ocr.space/ocrapi). When the key is set it does the OCR instead of Mistral.
    # Free key: 1 MB per file, 3 PDF pages. PRO keys come with their own endpoint URL.
    ocr_space_api_key: str | None = None
    ocr_space_url: str = "https://api.ocr.space/parse/image"
    ocr_space_engine: int = 2  # 1, 2 or 3 (3 = best for handwriting/tables, separate quota)
    upload_dir: Path = BACKEND_DIR / "uploads"
    max_upload_mb: int = 20
    fhir_validator_jar: Path = BACKEND_DIR / "tools" / "validator_cli.jar"
    java_path: str | None = None
    fhir_tx_server: str = "https://tx.fhir.org"

    abdm_hip_id: str | None = None
    # Only the patient may give, deny or revoke consent (patient portal). Staff "simulate patient" endpoints
    # stay off unless explicitly turned on for automated tests or demos.
    allow_staff_consent_simulation: bool = False
    abdm_hiu_id: str | None = None

    record_sealing_key: str | None = None
    record_sealing_old_keys: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        if value.startswith("change-me"):
            raise ValueError("JWT_SECRET still has the example value from .env.example; generate a new one")
        return value

    @field_validator("record_sealing_key")
    @classmethod
    def strong_sealing_key(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            return None
        if value is not None and len(value) < 32:
            raise ValueError("RECORD_SEALING_KEY must be at least 32 characters")
        return value

    @field_validator("password_scrypt_n")
    @classmethod
    def scrypt_cost(cls, value: int) -> int:
        if value < 2**14 or value & (value - 1):
            raise ValueError("PASSWORD_SCRYPT_N must be a power of two, at least 16384")
        return value

    @property
    def mfa_required_role_list(self) -> set[str]:
        return {r.strip() for r in self.mfa_required_roles.split(",") if r.strip()}

    @property
    def record_sealing_old_key_list(self) -> list[str]:
        return [k.strip() for k in self.record_sealing_old_keys.split(",") if k.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
