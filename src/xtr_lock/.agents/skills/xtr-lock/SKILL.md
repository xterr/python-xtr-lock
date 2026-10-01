---
name: xtr-lock
description: How to take exclusive and shared locks around resources with xtr-lock, in memory, in files, in Redis, or across several stores. Use when only one worker, request or cron run may do something at a time, when code needs a mutex, critical section, read/write lock, leader election, "already running" guard, distributed lock, lock TTL or lock refresh; also when adding LockBundle to an application on xtr-dependency-injection, or picking between InMemoryStore, FlockStore, RedisStore, NullStore and CombinedStore.
---

# xtr-lock

A lock is the same everywhere; the place the holder is recorded is a constructor argument. Build
one `LockFactory` around one store, ask it for a lock per resource, and `async with` it. Every
call that touches the store is awaited.

## Quick reference

- Take a `LockInterface` (or `SharedLockInterface` for read locks) as a constructor argument, not
  a store and not a `Lock`. Switching coordination off then means handing in a `NoLock()`.
- Wrap a critical section: `async with factory.create_lock("reports:nightly"):`.
- Give up at once instead: `if not await lock.acquire(): return`.
- Wait, but not forever: `async with asyncio.timeout(5): await lock.acquire(blocking=True)`.
- Hold longer than the ttl: `await lock.refresh()` inside the block.
- Many readers, one writer: `await lock.acquire_read()`.
- Act as the same holder twice: keep a `Key` and use `create_lock_from_key(key)`.
- Never rely on garbage collection to release. Use `async with`, or `release()` in a `finally`.
- In an application: activate `LockBundle`, inject `LockFactory`.

## Take a lock

```python
from xtr_lock import FlockStore, LockFactory

factory = LockFactory(FlockStore("/var/lock/app"))
lock = factory.create_lock("invoice:42")

if not await lock.acquire():  # someone else holds it
    return

try:
    await issue_invoice(42)
finally:
    await lock.release()
```

`async with lock:` is a blocking acquire plus a release on the way out, including when the block
raises. Opening a block on a lock its holder already holds leaves it held.

| Call | Does |
| --- | --- |
| `await lock.acquire(blocking=False)` | `True` once held, `False` when someone else holds it |
| `await lock.acquire(blocking=True)` | Waits on the event loop until it can be held |
| `await lock.acquire_read(blocking=False)` | Shares with other readers, excludes writers |
| `await lock.refresh(ttl=None)` | Pushes the expiry back; `None` reuses the lock's own ttl |
| `await lock.release()` | Lets go |
| `await lock.is_acquired()` | Asks the store whether this holder still holds it |
| `lock.is_expired()`, `lock.get_remaining_lifetime()` | Local, no store call; lifetime is `None` when unset |

A blocking acquire waits as long as it takes; bound it with `asyncio.timeout`. Cancelling is
safe — it takes back whatever the store may already have stored, unless the holder held the lock
before that acquire started.

```python
try:
    async with asyncio.timeout(5):
        await lock.acquire(blocking=True)
except TimeoutError:
    ...  # nothing is held
```

## Lifetimes

`create_lock(resource, ttl=DEFAULT_TTL)` gives the lock 300 seconds. Pass `ttl=None` for no
lifetime. Lifetimes are durations, counted on a monotonic clock, so moving the system time never
stretches one.

```python
lock = factory.create_lock("import:catalogue", ttl=30)

async with lock:
    for batch in batches:
        await import_batch(batch)
        await lock.refresh()  # another 30 seconds
```

Only a store that can expire locks (`RedisStore`, and a `CombinedStore` over it) actually drops a
dead holder's lock. On `InMemoryStore` and `FlockStore` the lock holds until released and
`get_remaining_lifetime()` is `None`.

## Holders and keys

The `Key` is the holder, not the resource name. Two locks from `create_lock("x")` are two holders
and exclude each other. Keep the key to be the same holder again:

```python
from xtr_lock import Key

key = Key("invoice:42")
first = factory.create_lock_from_key(key)
again = factory.create_lock_from_key(key)  # same holder: acquiring is not a conflict
```

**One lock per task.** A lock shared between two tasks, or two locks made from one key, is one
holder: the second `acquire()` succeeds at once and either task's `release()` lets go for both.
Give every task that must be excluded its own lock from `create_lock`.

A key pickles unless its store keeps process-only state on it — an open file, for `FlockStore` —
where pickling raises `UnserializableKeyError`.

## Pick a store

| Store | Excludes | Read locks | Expires locks | DSN |
| --- | --- | --- | --- | --- |
| `InMemoryStore()` | tasks in this process | ✓ | — | `in-memory` |
| `FlockStore(path=None)` | processes on this machine (POSIX only) | ✓ | — | `flock`, `flock:///path` |
| `RedisStore(client)` | anything reaching the server | ✓ | ✓ | `redis://`, `rediss://`, `unix://`, `valkey://`, `valkeys://` |
| `NullStore()` | no one | ✓ | — | `null` |
| `CombinedStore(stores, strategy)` | whatever its stores do | ✓ | when its stores do | — |

- `FlockStore()` with no path uses a directory private to this user under the system's temporary
  directory, so those locks bind one user's processes only. Lock files are never removed.
- `RedisStore` wants one standalone Redis or Valkey server. Not a cluster, not Sentinel.
- `StoreFactory.create_store(dsn_or_client)` builds any of them; `StoreFactory.validate(dsn)`
  checks a DSN without connecting.

```python
from redis.asyncio import Redis

from xtr_lock import RedisStore

store = RedisStore(Redis.from_url("redis://localhost:6379/0"))  # your client, you close it
store = RedisStore.from_url("redis://localhost:6379/0?prefix=app:locks:")  # its own client
await store.close()  # closes only a connection it opened itself
```

Set `prefix` whenever the database is shared with anything else. `initial_ttl` (300s) is how long
a lock lives between being stored and the lock's own lifetime landing on it. Keep server clocks
synchronized: the holder counts the remaining lifetime locally, the server expires the key on its
own wall clock.

Several stores, with a quorum:

```python
from xtr_lock import CombinedStore, ConsensusStrategy, RedisStore, UnanimousStrategy

store = CombinedStore(
    [RedisStore.from_url(f"redis://{host}:6379") for host in ("a", "b", "c")],
    ConsensusStrategy(),  # a strict majority; UnanimousStrategy() wants all of them
)
```

Any store failing — conflict, network, anything — counts as a vote against, and a lock that falls
short is taken back out of every store before the conflict is reported.

To switch coordination off, `NoLock()` always succeeds and never coordinates, and `NullStore()`
does the same one level down:

```python
from xtr_lock import LockInterface, NoLock


class Importer:
    def __init__(self, lock: LockInterface | None = None) -> None:
        self._lock = lock or NoLock()
```

## Testing

The package ships no test helpers; it needs none.

- Give the code under test `LockFactory(InMemoryStore())` — two locks on one resource really do
  exclude each other, with no files and no server.
- Assert the uncoordinated path with `NoLock()` or `LockFactory(NullStore())`.
- Test expiry without waiting: `LockFactory(store, clock=MockClock("2026-01-01"))`, then
  `clock.sleep(...)`. The clock is read for lifetimes and waits only.
- In an application test, replace the service:
  `boot_for_test(kernel, overrides={LockFactory: LockFactory(InMemoryStore())})`.

```python
from xtr_lock import InMemoryStore, LockFactory


async def test_only_one_run_at_a_time() -> None:
    factory = LockFactory(InMemoryStore())
    held = factory.create_lock("reports:nightly")

    assert await held.acquire() is True
    assert await factory.create_lock("reports:nightly").acquire() is False
```

## Use in an application

1. **Install** — `uv add "xtr-lock[di]"`; add `redis` for locks across machines and `logging` for
   the lock channel.
2. **Activate** — `LockBundle: {"all": True}` in `BUNDLES` in `<app>/bundles.py`, imported from
   `xtr_lock.bundle`.
3. **Brings along** — the logging bundle, when xtr-logging is installed. Nothing otherwise.
4. **Configure** — optional; with no configuration the `default` resource is `{"default": "flock"}`,
   file locks under `kernel.share_dir`:

   ```python
   # <app>/config/lock.py
   from xtr_dependency_injection import configure, env
   from xtr_lock.bundle import LockConfig


   @configure
   def lock() -> LockConfig:
       return LockConfig(
           resources={
               "default": "flock",
               "reports": env("REPORTS_LOCK_DSN"),
               "invoices": ["redis://a:6379", "redis://b:6379", "redis://c:6379"],
           }
       )
   ```

   A store entry is `"flock"`, any DSN above, `env(...)`, or `Reference(Redis, "locks")` for a
   client the container already provides. Several entries get a `CombinedStore` with
   `ConsensusStrategy`.
5. **Environment** — nothing required, but a DSN given as `env(...)` must be set when the
   application boots: boot checks every resource and refuses an unserved DSN, a Redis DSN without
   the `redis` extra, or a `Reference` the container does not provide.
6. **Ignore** — `var/` in `.gitignore`: lock files live under `kernel.share_dir`.
7. **Use** — inject `LockFactory` for the `default` resource, or qualify by resource name. Each
   resource's store is also provided as `PersistingStoreInterface` under the same qualifier.

   ```python
   from typing import Annotated

   from xtr_dependency_injection import Target, as_service
   from xtr_lock import LockFactory


   @as_service
   class ReportBuilder:
       def __init__(
           self,
           locks: LockFactory,  # the default resource
           report_locks: Annotated[LockFactory, Target("reports")],
       ) -> None: ...
   ```

8. **Check** — `debug:bundles` shows `lock` as `listed` and `active`.
9. **Remove** — drop the `BUNDLES` entry, delete `<app>/config/lock.py`, then `uv remove xtr-lock`
   — unless xtr-cache or xtr-scheduler is installed, which depend on it.

## Errors

Everything derives from `LockError` and carries typed attributes.

| Error | Raised when | Carries |
| --- | --- | --- |
| `LockConflictedError` | Someone else holds it, and waiting was asked for | `.resource` |
| `LockAcquiringError` | Acquiring or extending failed otherwise; cause chained | `.resource`, `.reason` |
| `LockExpiredError` | The lifetime ran out before the store confirmed | `.resource` |
| `LockReleasingError` | The store failed to let go, or still holds it | `.resource`, `.reason` |
| `LockStorageError` | The storage itself failed | `.reason` |
| `InvalidArgumentError` | Bad argument: unwritable directory, unknown DSN, `refresh` with no ttl anywhere. Also a `ValueError` | `.reason` |
| `InvalidTtlError` | A store given a lifetime of zero or less | `.ttl` |
| `UnserializableKeyError` | Pickling a key its store keeps process-only state on | `.resource` |

A non-blocking `acquire()` returns `False` on contention rather than raising; only
`blocking=True` turns contention into `LockConflictedError`.

## Do not

- Do not depend on `Lock` or on a concrete store in application code; depend on `LockInterface`
  or `SharedLockInterface` and let the container pick the store.
- Do not share one lock, or one `Key`, between tasks that must exclude each other.
- Do not expect a dropped lock to be released. Only `FlockStore` closes a dropped key's file, and
  that is tidying descriptors, not a release contract.
- Do not call `refresh()` on a lock created with `ttl=None` and no argument: that is an
  `InvalidArgumentError`.
- Do not expect `InMemoryStore` or `FlockStore` to expire a lock, or `get_remaining_lifetime()`
  to return a number there.
- Do not use `InMemoryStore` across processes, or `FlockStore` across machines.
- Do not point a `RedisStore` at a cluster or at Sentinel, and do not share a Redis database
  without a `prefix`.
- Do not use `time.monotonic()` or a system clock to test expiry; hand `LockFactory` a clock.
