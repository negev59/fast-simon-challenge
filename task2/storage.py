"""Storage backends for the key-value database.

The database logic only needs a few primitives: fetch, save and delete an
entity by key, group writes into a transaction, and wipe everything.
Each store is bound to a single namespace, which is what gives every `db`
its own isolated copy of the data.
"""
from contextlib import contextmanager

from google.cloud import datastore

# Datastore commits (and delete_multi) accept at most 500 keys per call.
MAX_BATCH_SIZE = 500


class DatastoreStore:
    """Stores entities in Google Cloud Datastore, inside one namespace."""

    def __init__(self, client, namespace=None):
        self._client = client
        self._namespace = namespace or None  # None is the default namespace

    def _key(self, kind, key_id):
        return self._client.key(kind, key_id, namespace=self._namespace)

    def get(self, kind, key_id):
        return self.get_many([(kind, key_id)])[0]

    def get_many(self, kind_and_ids):
        """Fetch several entities in one round trip; None for missing ones.

        Inside a transaction the client reads through it automatically.
        """
        if not kind_and_ids:
            return []
        keys = [self._key(kind, key_id) for kind, key_id in kind_and_ids]
        found = {entity.key: dict(entity) for entity in self._client.get_multi(keys)}
        return [found.get(key) for key in keys]

    def put(self, kind, key_id, data):
        entity = datastore.Entity(key=self._key(kind, key_id))
        entity.update(data)
        self._client.put(entity)

    def delete(self, kind, key_id):
        self._client.delete(self._key(kind, key_id))

    def transaction(self):
        """Writes made inside are applied atomically when the block exits."""
        return self._client.transaction()

    def delete_all(self, kinds):
        for kind in kinds:
            query = self._client.query(kind=kind, namespace=self._namespace)
            query.keys_only()
            keys = [entity.key for entity in query.fetch()]
            for start in range(0, len(keys), MAX_BATCH_SIZE):
                self._client.delete_multi(keys[start:start + MAX_BATCH_SIZE])


class MemoryStore:
    """In-memory store that mimics Datastore transactions, used by the tests.

    Like Datastore, writes inside a transaction are buffered until commit (so
    reads don't see them), and writing the same key twice in one transaction
    is an error. This lets the tests catch code that would break on Datastore.
    """

    def __init__(self, data):
        self._data = data  # {(kind, key_id): dict}, shared per namespace
        self._pending = None

    def get(self, kind, key_id):
        value = self._data.get((kind, key_id))
        return dict(value) if value is not None else None

    def get_many(self, kind_and_ids):
        return [self.get(kind, key_id) for kind, key_id in kind_and_ids]

    def put(self, kind, key_id, data):
        self._write((kind, key_id), dict(data))

    def delete(self, kind, key_id):
        self._write((kind, key_id), None)

    def _write(self, key, value):
        if self._pending is None:
            self._apply(key, value)
            return
        if key in self._pending:
            raise ValueError(f"{key} written twice in one transaction")
        self._pending[key] = value

    def _apply(self, key, value):
        if value is None:
            self._data.pop(key, None)
        else:
            self._data[key] = value

    @contextmanager
    def transaction(self):
        self._pending = {}
        try:
            yield
            for key, value in self._pending.items():
                self._apply(key, value)
        finally:
            self._pending = None

    def delete_all(self, kinds):
        for key in [key for key in self._data if key[0] in kinds]:
            del self._data[key]


class MemoryBackend:
    """Hands out MemoryStores, keeping each namespace's data separate."""

    def __init__(self):
        self.namespaces = {}

    def __call__(self, namespace=None):
        return MemoryStore(self.namespaces.setdefault(namespace or None, {}))
