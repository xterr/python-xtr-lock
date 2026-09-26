<div align="center">

# xtr-lock

**Exclusive and shared locks around resources, held in memory, in files, in Redis, or across several stores at once.**

<img alt="python 3.11+" src="https://img.shields.io/badge/python-%E2%89%A5%203.11-3776AB?logo=python&logoColor=white">
<img alt="asyncio" src="https://img.shields.io/badge/asyncio-native-1f6feb">
<img alt="typed" src="https://img.shields.io/badge/typed-ty%20%2B%20basedpyright-1f6feb">
<img alt="license MIT" src="https://img.shields.io/badge/license-MIT-blue">

</div>

---

## Why?

Two workers pick up the same nightly report. Two requests renew the same subscription. A
cron job starts again while the last run is still going. Each is fixed by the same thing — only
one holder at a time — but *where* that holder is recorded depends on who else is competing:
tasks in one process, processes on one machine, or machines sharing a server.

This package keeps the lock the same and makes the place it lives a constructor argument:

- 🔒 **One lock API** — `acquire`, `acquire_read`, `refresh`, `release`, and `async with`.
- 🗄️ **Five stores** — in memory, files, Redis, nowhere, or a quorum of several.
- 📖 **Read and write modes** — many readers or one writer, with promotion and demotion.
- ⏳ **Lifetimes** — a lock that is never released expires instead of blocking forever.
- 🧩 **A bundle** — one `LockFactory` per named resource, configured in Python.

```python
from xtr_lock import FlockStore, LockFactory

factory = LockFactory(FlockStore())

async with factory.create_lock("reports:nightly"):
    await build_report()
```

## Install

```sh
uv add xtr-lock
uv add "xtr-lock[redis]"   # RedisStore, on redis-py's asyncio client
uv add "xtr-lock[di]"      # the bundle for xtr-dependency-injection
```

Requires Python 3.11+. Depends on `xtr-clock` and `xtr-logging-contracts`.

## Quick start

A `LockFactory` wraps one store and hands out one lock per resource:

```python
from xtr_lock import FlockStore, LockFactory

factory = LockFactory(FlockStore("/var/lock/app"))
lock = factory.create_lock("invoice:42")

if not await lock.acquire():  # someone else holds it: give up at once
    return

try:
    await issue_invoice(42)
finally:
    await lock.release()
```

`acquire(blocking=True)` waits instead of giving up, and `async with lock:` is the same wait
followed by a release on the way out, including when the block raises:

```python
async with factory.create_lock("invoice:42"):
    await issue_invoice(42)
```

Every method that touches the store is awaited. A lock is **never released because it was
garbage-collected**: use `async with`, or release it yourself.

### Giving up after a while

A blocking acquire waits as long as it takes. Put a limit on it with `asyncio.timeout`:
cancelling an acquire is safe, and takes back whatever the store may already have stored for
it — unless the holder held the lock before that acquire started.

```python
try:
    async with asyncio.timeout(5):
        await lock.acquire(blocking=True)
except TimeoutError:
    ...  # nothing is held
```

### Lifetimes

`create_lock(resource, ttl=300.0)` gives the lock five minutes by default. A store that can
expire locks (Redis, and a combined store over it) lets go of one whose holder died without
releasing it. A holder that needs longer pushes the expiry back:

```python
lock = factory.create_lock("import:catalogue", ttl=30)

async with lock:
    for batch in batches:
        await import_batch(batch)
        await lock.refresh()  # another 30 seconds from now
        # lock.get_remaining_lifetime() -> seconds left; lock.is_expired() -> bool
```

Lifetimes are durations, so they are counted on a monotonic clock: setting the system time back
never keeps a lock alive. Hand a clock to `LockFactory(store, clock=...)` to freeze time in a
test.

`refresh(ttl)` takes another duration for this one extension. Passing `ttl=None` to
`create_lock` sets no lifetime at all. Files and memory never expire locks, so there the lock
holds until released and `get_remaining_lifetime()` is `None`.

### Readers and writers

`acquire_read()` shares the lock with other readers and excludes any writer:

```python
reader = factory.create_lock("catalogue")
await reader.acquire_read()  # many readers at once
await reader.acquire()  # the only reader may become the writer
await reader.acquire_read()  # and the writer may step back down
```

On a store that cannot share, `acquire_read()` takes the exclusive lock instead.

### Holders and keys

A lock stands for a `Key`, and the key — not the resource name — is the holder. Two locks from
`create_lock("x")` are two holders and exclude each other. To act as the same holder again,
keep the key:

```python
from xtr_lock import Key

key = Key("invoice:42")
first = factory.create_lock_from_key(key)
again = factory.create_lock_from_key(key)  # the same holder: acquiring is not a conflict
```

> **One lock per task.** A lock shared between tasks — or two locks made from one key — is one
> holder: the second `acquire()` succeeds at once, because that holder already holds the lock,
> and either task's release lets go for both. What they do to the store takes turns, so the
> holder's state stays consistent, but they do not exclude each other. Give every task that
> must be excluded a lock of its own, from `create_lock`.

A key pickles, with whatever its store keeps on it, unless the store keeps something only this
process can use — an open file, for `FlockStore` — in which case pickling raises
`UnserializableKeyError`.

### Switching locking off

`NoLock` is a lock that always succeeds and never locks, for code that takes a lock but should
not coordinate in a given setup. `NullStore` does the same one level down, at the store.

```python
from xtr_lock import LockInterface, NoLock


class Importer:
    def __init__(self, lock: LockInterface | None = None) -> None:
        self._lock = lock or NoLock()
```

## Stores

| Store | Who is excluded | Its own wait | Read locks | Expires locks | DSN |
|---|---|---|---|---|---|
| `InMemoryStore` | tasks in this process | — | ✓ | — | `in-memory` |
| `FlockStore` | processes on this machine | ✓ | ✓ | — | `flock`, `flock:///path` |
| `RedisStore` | anything reaching the server | — | ✓ | ✓ | `redis://…`, `rediss://…`, `unix://…`, `valkey://…`, `valkeys://…` |
| `NullStore` | no one | ✓ (reads) | ✓ | — | `null` |
| `CombinedStore` | whatever its stores exclude | — | ✓ | when its stores do | — |

Where a store has no wait of its own, a blocking acquire retries every 100 ms, give or take
10 ms, sleeping on the event loop in between. `FlockStore` retries sooner at first (see below).

`StoreFactory.create_store(...)` builds any of them from a DSN, or a `RedisStore` from an
asyncio Redis client. Its error messages name a DSN's scheme only, never its credentials.

The Redis DSN rules are shared with every package that reaches Redis the same way:
`xtr_lock.store` exports `REDIS_SCHEMES`, `is_redis_dsn`, `create_redis_client`,
`is_redis_client` and `redis_installed`.

### `InMemoryStore`

A dictionary. Every method completes without awaiting, so tasks on one event loop never see
it half-updated. It is not meant to be shared between threads, and two instances know nothing
of each other.

### `FlockStore`

One file per resource under a directory (the system's temporary directory by default), locked
with the operating system's advisory file locks. Every key opens its own descriptor, so two keys
conflict whether they are in two processes or in one. Closing the descriptor lets go, so a
crashed process never leaves a lock behind.

- The file is named `xtr.<up to 50 characters of the resource>.<digest>.lock`, with anything
  outside `A-Za-z0-9._-` folded to `-`. The digest keeps resources that fold alike apart.
- New lock files are created readable and writable by everyone, whatever the umask, so
  processes run as different users can share them.
- A blocking wait tries again without blocking — after 10 ms, then twice as long each time, up
  to every 100 ms — sleeping on the event loop in between. No thread is parked in the system
  call, a cancelled wait holds nothing, and waiters are not served in arrival order (the
  operating system does not promise that either).
- Switching a key between reading and writing is not atomic at the operating-system level; if
  the switch fails, the key holds nothing rather than a lock it may have lost.
- POSIX only. The locks bind only processes using this store on the same machine, and a
  directory on a network file system may not honour them.

### `RedisStore`

Each resource is a sorted set named after it: one member per holder, scored with the moment
that holder's lock expires, and a marker member while it is held for writing. Every change is
one server-side script, so it lands whole; scripts are sent by digest and loaded on first use.
Expiry is measured on the server's clock when scripts may read it, and on this process's clock
otherwise.

```python
from redis.asyncio import Redis
from xtr_lock import RedisStore

store = RedisStore(Redis.from_url("redis://localhost:6379/0"))  # your client, you close it
store = RedisStore.from_url("redis://localhost:6379/0")  # its own client ...
await store.aclose()  # ... which it closes

store = RedisStore(client, prefix="app:locks:")  # keys named app:locks:<resource>
store = RedisStore.from_url("redis://localhost:6379/0?prefix=app:locks:")
```

- A lock is stored with `initial_ttl` (300 seconds by default) of life until the lock's own
  lifetime replaces it, so a holder that dies mid-acquire does not keep the lock forever.
- The Redis key is the resource after `prefix` (empty by default). Set one when the database is
  shared with anything else; in a DSN, the `prefix` option is the store's and never reaches the
  client.
- One server — standalone Redis or Valkey. Not a cluster, not Sentinel.

### `CombinedStore`

Keeps each lock in several stores and lets a strategy decide how many must agree:

```python
from xtr_lock import CombinedStore, ConsensusStrategy, RedisStore

store = CombinedStore(
    [RedisStore.from_url(f"redis://{host}") for host in ("a", "b", "c")],
    ConsensusStrategy(),  # a strict majority; UnanimousStrategy() wants all of them
)
```

- Stores are asked in order, and asking stops once the strategy can no longer be met; a lock
  that falls short is taken back out of every store before the conflict is reported.
- A lifetime is a deadline: each store gets what is left of it when its turn comes, so the lock
  never outlives the moment it was meant to end. If the deadline passes midway, the lock is
  reported expired.
- `save_read` falls back to `save` on any store that cannot share.
- Any store failing — conflict, network, anything — counts as a vote against.
- `await store.aclose()` closes every store that has something to close — a Redis store that
  opened its own connection — and raises the failures together, once all were asked.

### Writing a store

Implement `PersistingStoreInterface` (`save`, `delete`, `exists`, `put_off_expiration`), and add
`BlockingStoreInterface` (`wait_and_save`), `SharedLockStoreInterface` (`save_read`) or
`BlockingSharedLockStoreInterface` (`wait_and_save_read`) for what the store can also do; a
`Lock` looks for them and uses the best one. Keep per-holder state on the key under your store's
class (`key.set_state(MyStore, token)`), shorten the key's lifetime with `key.reduce_lifetime`
when the store sets one, and derive from `ExpiringStoreMixin` to have `_check_not_expired(key)`
take back a lock that expired while being stored.

## Kernel / bundle

With [xtr-dependency-injection](../xtr-dependency-injection), list the bundle and name the
resources:

```python
# app/bundles.py
from xtr_lock.bundle import LockBundle

BUNDLES = {LockBundle: {"all": True}}
```

```python
# app/config/lock.py
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

Each resource becomes a `LockFactory` qualified by its name; `default` is also provided without
a qualifier. A resource with several stores gets a `CombinedStore` with `ConsensusStrategy`.

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

| Store entry | Store |
|---|---|
| `"flock"` | `FlockStore` in `<temporary directory>/xtr-lock/<digest of the project directory>`, so two projects on one machine never share lock files |
| any DSN in the table above, or `env(...)` | what `StoreFactory` builds; a Redis connection opened from a DSN is closed with the container |
| `ConnectionReference(Redis, "locks")` | a `RedisStore`, without a prefix, on the client the container provides under that type and qualifier; the application keeps closing it |

- **Zero config**: with no configuration, `{"default": "flock"}`. Nothing is opened until a
  factory is first asked for.
- **Checked at boot**: booting reads the configuration, `env()` values included, and refuses a
  DSN no store serves, a Redis DSN without the `redis` extra, or a `ConnectionReference` the
  container does not provide — naming the resource, never a DSN's credentials. A variable a
  DSN needs must therefore be set when the application starts.
- **Logging**: when the logging bundle is active, a `lock` channel is added and every lock
  logs there — successes at debug, contention at info, failures at notice.
- The store of each resource is also provided, as `PersistingStoreInterface` qualified by the
  resource name. A resource given an empty list of stores is skipped.

## Errors

Every error derives from `LockError` and carries its data as typed attributes.

| Error | Raised when |
|---|---|
| `LockConflictedError` | Someone else holds the lock — returned as `False` by a non-blocking acquire |
| `LockAcquiringError` | Acquiring or extending failed for any other reason; the cause is chained |
| `LockExpiredError` | The lock's lifetime ran out before the store confirmed it (chained inside `LockAcquiringError` when it surfaces through `acquire` or `refresh`) |
| `LockReleasingError` | The store failed to let go, or still held the lock afterwards |
| `LockStorageError` | The storage itself failed: a lock file that cannot be opened, a server error reply |
| `InvalidArgumentError` | A bad argument: an unwritable lock directory, an unknown DSN, a `refresh` with no duration (also a `ValueError`) |
| `InvalidTtlError` | A store given a lifetime of zero or less |
| `UnserializableKeyError` | Pickling a key its store keeps process-only state on |

## Development

Developed in the [python-xtr](https://github.com/xterr/python-xtr) monorepo, under
`packages/xtr-lock`; run the commands below from there. The `python-xtr-lock` repository is a
read-only copy, so send issues and pull requests to the monorepo.

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run basedpyright && uv run ty check && uv run pytest
```

The Redis tests run against a real server when `REDIS_DSN` is set, and are skipped otherwise.
They use resources of their own and never flush the database:

```sh
REDIS_DSN=redis://localhost:6379/15 uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
