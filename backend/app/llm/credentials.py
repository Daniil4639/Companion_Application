"""OS credentials only; never fall back to a plaintext file or SQLite."""
import asyncio
import keyring
from .schemas import ProviderError


class CredentialStore:
    service = "Folliant.LLM"

    def _call(self, method, *args):
        try:
            backend = keyring.get_keyring()
            module = type(backend).__module__
            if module not in {"keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService",
                              "keyring.backends.kwallet", "keyring.backends.libsecret"}:
                raise RuntimeError("Secure OS keyring unavailable")
            return getattr(backend, method)(self.service, *args)
        except Exception:
            raise ProviderError("credential_store", "Secure OS credential storage is unavailable") from None

    async def get(self, reference):
        return await asyncio.to_thread(self._call, "get_password", reference)

    async def set(self, reference, value):
        await asyncio.to_thread(self._call, "set_password", reference, value)

    async def delete(self, reference):
        await asyncio.to_thread(self._call, "delete_password", reference)
