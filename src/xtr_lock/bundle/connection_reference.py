"""Names a connection the container already provides, for a lock store to use."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import final

__all__ = ["ConnectionReference"]


@final
@dataclass(frozen=True, slots=True)
class ConnectionReference:
    """Points a lock resource at a connection registered in the container.

    Use it in :attr:`~xtr_lock.bundle.LockConfig.resources` where a DSN would
    go, to have the store share a client the application already builds —
    its pool, its credentials, its lifecycle — instead of opening its own.
    The service is fetched when the store is first needed, and turned into a
    store the way :meth:`~xtr_lock.store.StoreFactory.create_store` turns any
    connection. The application keeps closing it.

    ```python
    LockConfig(resources={"default": ConnectionReference(Redis, "locks")})
    ```

    Attributes:
        service: The type the connection is registered under.
        qualifier: The qualifier it is registered with, if any.
    """

    service: type[object]
    qualifier: Hashable | None = None
