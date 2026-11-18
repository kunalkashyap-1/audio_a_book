"""Request and response models. Routers shape IO here; the worker owns the manifest shape."""

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    provider: str
    provider_version: str
    speech: str
    queue: dict
    auth_required: bool
