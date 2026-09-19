from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import jieba
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .config import settings


class DocNotFoundError(Exception):
    pass


class DocVersionConflictError(Exception):
    pass


@dataclass(frozen=True)
class DocPage:
    items: list[dict]
    total: int


def tokenize(text: str) -> list[str]:
    tokens = {token.strip().lower() for token in jieba.cut(text) if token.strip()}
    return sorted(tokens)


def version_etag(doc_id: str, version_no: int, title: str, content: str) -> str:
    digest = sha256(f"{doc_id}:{version_no}:{title}:{content}".encode("utf-8")).hexdigest()
    return digest[:32]


class DocsRepository:
    def __init__(self, db: Database):
        self.db = db
        self.docs: Collection = db["knowledge_docs"]
        self.versions: Collection = db["knowledge_doc_versions"]
        self.ensure_indexes()

    @classmethod
    def from_settings(cls) -> "DocsRepository":
        client: MongoClient = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=3000)
        return cls(client[settings.mongo_db])

    def ensure_indexes(self) -> None:
        self.docs.create_index([("tenant_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)])
        self.docs.create_index([("tenant_id", ASCENDING), ("tokens", ASCENDING)])
        self.versions.create_index([("doc_id", ASCENDING), ("version_no", ASCENDING)], unique=True)
        self.versions.create_index([("tenant_id", ASCENDING), ("doc_id", ASCENDING), ("version_no", DESCENDING)])

    def create(self, *, tenant_id: str, user_id: str, title: str, content: str) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        doc_id = f"doc_{uuid4().hex[:24]}"
        tokens = tokenize(f"{title}\n{content}")
        version = {
            "_id": f"docver_{uuid4().hex[:24]}",
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "version_no": 1,
            "title": title,
            "content": content,
            "etag": version_etag(doc_id, 1, title, content),
            "created_by": user_id,
            "created_at": now,
        }
        doc = {
            "_id": doc_id,
            "tenant_id": tenant_id,
            "title": title,
            "current_version": 1,
            "status": "active",
            "deleted_at": None,
            "tokens": tokens,
            "created_by": user_id,
            "created_at": now,
            "updated_at": now,
        }
        self.docs.insert_one(doc)
        try:
            self.versions.insert_one(version)
        except DuplicateKeyError:
            self.docs.delete_one({"_id": doc_id})
            raise DocVersionConflictError
        return self._join_current(doc, version)

    def list(self, *, tenant_id: str, query: str | None, page: int, size: int) -> DocPage:
        filter_: dict = {"tenant_id": tenant_id, "status": "active"}
        if query:
            query_tokens = tokenize(query)
            if query_tokens:
                filter_["tokens"] = {"$all": query_tokens}
        total = self.docs.count_documents(filter_)
        docs = list(
            self.docs.find(filter_)
            .sort("updated_at", DESCENDING)
            .skip((page - 1) * size)
            .limit(size)
        )
        items = [self._join_current(doc) for doc in docs]
        return DocPage(items=items, total=total)

    def get(self, *, tenant_id: str, doc_id: str) -> dict:
        doc = self.docs.find_one({"_id": doc_id, "tenant_id": tenant_id, "status": "active"})
        if doc is None:
            raise DocNotFoundError
        return self._join_current(doc)

    def update(self, *, tenant_id: str, user_id: str, doc_id: str, expected_version: int, title: str, content: str) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        next_version = expected_version + 1
        updated = self.docs.find_one_and_update(
            {
                "_id": doc_id,
                "tenant_id": tenant_id,
                "status": "active",
                "current_version": expected_version,
            },
            {
                "$set": {
                    "title": title,
                    "tokens": tokenize(f"{title}\n{content}"),
                    "updated_at": now,
                },
                "$inc": {"current_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            if self.docs.find_one({"_id": doc_id, "tenant_id": tenant_id, "status": "active"}) is None:
                raise DocNotFoundError
            raise DocVersionConflictError
        version = {
            "_id": f"docver_{uuid4().hex[:24]}",
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "version_no": next_version,
            "title": title,
            "content": content,
            "etag": version_etag(doc_id, next_version, title, content),
            "created_by": user_id,
            "created_at": now,
        }
        self.versions.insert_one(version)
        return self._join_current(updated, version)

    def delete(self, *, tenant_id: str, doc_id: str) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        result = self.docs.update_one(
            {"_id": doc_id, "tenant_id": tenant_id, "status": "active"},
            {"$set": {"status": "deleted", "deleted_at": now, "updated_at": now}},
        )
        if result.matched_count == 0:
            raise DocNotFoundError

    def rollback(self, *, tenant_id: str, user_id: str, doc_id: str, version_no: int) -> dict:
        source = self.versions.find_one({"doc_id": doc_id, "tenant_id": tenant_id, "version_no": version_no})
        if source is None:
            raise DocNotFoundError
        active = self.docs.find_one({"_id": doc_id, "tenant_id": tenant_id, "status": "active"})
        if active is None:
            raise DocNotFoundError
        next_version = int(active["current_version"]) + 1
        now = datetime.now(UTC).replace(tzinfo=None)
        updated = self.docs.find_one_and_update(
            {"_id": doc_id, "tenant_id": tenant_id, "status": "active"},
            {
                "$set": {
                    "title": source["title"],
                    "tokens": tokenize(f"{source['title']}\n{source['content']}"),
                    "updated_at": now,
                },
                "$inc": {"current_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise DocNotFoundError
        version = {
            "_id": f"docver_{uuid4().hex[:24]}",
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "version_no": next_version,
            "title": source["title"],
            "content": source["content"],
            "etag": version_etag(doc_id, next_version, source["title"], source["content"]),
            "created_by": user_id,
            "created_at": now,
            "rollback_from_version": version_no,
        }
        self.versions.insert_one(version)
        return self._join_current(updated, version)

    def _join_current(self, doc: dict, version: dict | None = None) -> dict:
        current = version or self.versions.find_one(
            {"doc_id": doc["_id"], "tenant_id": doc["tenant_id"], "version_no": doc["current_version"]}
        )
        if current is None:
            raise DocNotFoundError
        return {
            "id": doc["_id"],
            "tenant_id": doc["tenant_id"],
            "title": current["title"],
            "content": current["content"],
            "current_version": int(doc["current_version"]),
            "etag": current["etag"],
            "status": doc["status"],
            "tokens": doc.get("tokens", []),
            "created_by": doc["created_by"],
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"],
        }


_default_repo: DocsRepository | None = None


def get_docs_repo() -> DocsRepository:
    global _default_repo
    if _default_repo is None:
        _default_repo = DocsRepository.from_settings()
    return _default_repo
