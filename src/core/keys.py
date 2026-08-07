from pathlib import Path

from cryptography.hazmat.primitives import serialization

from src.core.config import BASE_DIR, configs


class Keys:
    _private_key: str | None = None
    _public_key: str | None = None

    @classmethod
    def load_keys(cls) -> None:
        """Читает PEM из файлов в память. Private key в .env может быть encrypted — расшифровываем."""
        private_path = Path(configs.private_key_path)
        public_path = Path(configs.public_key_path)
        if not private_path.is_absolute():
            private_path = BASE_DIR / private_path
        if not public_path.is_absolute():
            public_path = BASE_DIR / public_path

        with open(private_path, "rb") as f:
            private_pem = f.read()

        private_key = serialization.load_pem_private_key(
            data=private_pem,
            password=configs.private_key_password.encode(),
        )
        cls._private_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        with open(public_path) as f:
            cls._public_key = f.read()

    @classmethod
    def get_private_key(cls) -> str:
        if cls._private_key is None:
            raise RuntimeError("Keys not loaded. Call Keys.load_keys() first.")
        return cls._private_key

    @classmethod
    def get_public_key(cls) -> str:
        if cls._public_key is None:
            raise RuntimeError("Keys not loaded. Call Keys.load_keys() first.")
        return cls._public_key
