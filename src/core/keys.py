import aiofiles
from cryptography.hazmat.primitives import serialization


class Keys:
    _private_key = None
    _public_key = None

    @classmethod
    async def initialize(cls, private_key_path: str, public_key_path: str, private_key_password: str):
        if cls._private_key is None:
            async with aiofiles.open(private_key_path, "rb") as f:
                private_key_data = await f.read()
            cls._private_key = serialization.load_pem_private_key(
                data=private_key_data,
                password=private_key_password.encode(),
            )

        if cls._public_key is None:
            async with aiofiles.open(public_key_path) as f:
                cls._public_key = await f.read()

    @classmethod
    def get_private_key(cls):
        return cls._private_key

    @classmethod
    def get_public_key(cls):
        return cls._public_key
