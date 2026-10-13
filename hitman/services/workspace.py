"""The workspace: collections, environments, history and settings, with change signals."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from hitman.core.http import HttpResponse
from hitman.core.models import (Auth, Collection, Environment, Folder, HistoryEntry, Node, Request,
                                Variable, find_path, regenerate_ids)
from hitman.core.variables import build_scope
from hitman.services.settings import Settings
from hitman.storage.database import Database
from hitman.storage.repositories import (CollectionRepository, EnvironmentRepository,
                                         HistoryRepository, SettingsRepository)


@dataclass
class Location:
    """Where a node lives: its collection and the folders above it."""
    collection: Collection
    folders: list[Folder]
    node: Node | Collection

    @property
    def breadcrumb(self) -> list[str]:
        return [self.collection.name] + [f.name for f in self.folders]

    @property
    def parent_id(self) -> str | None:
        return self.folders[-1].id if self.folders else None


class Workspace(QObject):
    collections_changed = Signal()
    environments_changed = Signal()
    active_environment_changed = Signal()
    history_changed = Signal()
    settings_changed = Signal()

    def __init__(self, db: Database, parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self._collections_repo = CollectionRepository(db)
        self._env_repo = EnvironmentRepository(db)
        self._history_repo = HistoryRepository(db)
        self._settings_repo = SettingsRepository(db)

        self.settings = Settings.from_dict(self._settings_repo.get("settings"))
        self.collections: list[Collection] = self._collections_repo.load_all()
        self.environments: list[Environment] = self._env_repo.load_all()
        if not any(e.is_global for e in self.environments):
            self.environments.insert(0, Environment(id="globals", name="Globals", color="head", is_global=True))
            self._env_repo.replace_all(self.environments)
        active = self._settings_repo.get("active_environment")
        self.active_env_id: str | None = active if self.environment(active) else None

    # ------------------------------------------------------------ settings
    def update_settings(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self.settings, key, value)
        self._settings_repo.set("settings", self.settings.to_dict())
        self.settings_changed.emit()

    def ui_state(self, key: str, default=None):
        return self._settings_repo.get(f"ui.{key}", default)

    def set_ui_state(self, key: str, value) -> None:
        self._settings_repo.set(f"ui.{key}", value)

    # --------------------------------------------------------- collections
    def _reload_collections(self) -> None:
        self.collections = self._collections_repo.load_all()
        self.collections_changed.emit()

    def collection(self, collection_id: str | None) -> Collection | None:
        return next((c for c in self.collections if c.id == collection_id), None)

    def locate(self, node_id: str | None) -> Location | None:
        if not node_id:
            return None
        for collection in self.collections:
            if collection.id == node_id:
                return Location(collection, [], collection)
            path = find_path(collection.items, node_id)
            if path:
                return Location(collection, [n for n in path[:-1] if isinstance(n, Folder)], path[-1])
        return None

    def saved_request(self, request_id: str) -> Request | None:
        loc = self.locate(request_id)
        return loc.node.copy() if loc and isinstance(loc.node, Request) else None

    def create_collection(self, name: str, base_url: str = "", auth_type: str = "none",
                          auth: Auth | None = None) -> Collection:
        variables = [Variable(key="baseUrl", value=base_url.strip())] if base_url.strip() else []
        collection = Collection(name=name, auth=auth or Auth.with_variables(auth_type), variables=variables)
        self._collections_repo.create(collection)
        self._reload_collections()
        return collection

    def add_collection(self, collection: Collection) -> None:
        """Insert a fully-built collection (from an import)."""
        self._collections_repo.create(collection)
        self._reload_collections()

    def update_collection(self, collection_id: str, *, name: str | None = None, auth: Auth | None = None,
                          variables: list[Variable] | None = None) -> None:
        self._collections_repo.update_meta(collection_id, name=name, auth=auth, variables=variables)
        self._reload_collections()

    def duplicate_collection(self, collection_id: str) -> Collection | None:
        source = self.collection(collection_id)
        if source is None:
            return None
        copy = source.copy()
        copy.id = Collection().id
        copy.name = f"{source.name} copy"
        regenerate_ids(copy.items)
        self._collections_repo.create(copy)
        self._reload_collections()
        return copy

    def delete_collection(self, collection_id: str) -> None:
        self._collections_repo.delete(collection_id)
        self._reload_collections()

    def add_folder(self, collection_id: str, parent_id: str | None, name: str = "New folder") -> Folder:
        folder = Folder(name=name)
        self._collections_repo.add_item(collection_id, parent_id, folder)
        self._reload_collections()
        return folder

    def add_request(self, collection_id: str, parent_id: str | None, request: Request,
                    after_id: str | None = None) -> None:
        self._collections_repo.add_item(collection_id, parent_id, request.copy(), after_id)
        self._reload_collections()

    def update_request(self, request: Request) -> None:
        self._collections_repo.update_request(request)
        self._reload_collections()

    def rename(self, node_id: str, name: str) -> None:
        if self.collection(node_id):
            self._collections_repo.update_meta(node_id, name=name)
        else:
            self._collections_repo.rename_item(node_id, name)
        self._reload_collections()

    def delete_item(self, item_id: str) -> None:
        self._collections_repo.delete_item(item_id)
        self._reload_collections()

    # -------------------------------------------------------- environments
    def environment(self, env_id: str | None) -> Environment | None:
        return next((e for e in self.environments if e.id == env_id), None)

    @property
    def active_environment(self) -> Environment | None:
        return self.environment(self.active_env_id)

    @property
    def global_environment(self) -> Environment | None:
        return next((e for e in self.environments if e.is_global), None)

    def set_active_environment(self, env_id: str | None) -> None:
        self.active_env_id = env_id if self.environment(env_id) and not self.environment(env_id).is_global else None
        self._settings_repo.set("active_environment", self.active_env_id)
        self.active_environment_changed.emit()

    def save_environments(self, environments: list[Environment], active_id: str | None) -> None:
        self._env_repo.replace_all(environments)
        self.environments = self._env_repo.load_all()
        self.environments_changed.emit()
        self.set_active_environment(active_id)

    def variable_scope(self, collection: Collection | None) -> dict[str, str]:
        layers = [collection.variables if collection else []]
        if self.global_environment:
            layers.append(self.global_environment.variables)
        if self.active_environment:
            layers.append(self.active_environment.variables)
        return build_scope(*layers)

    # ------------------------------------------------------------- history
    def history(self, limit: int = 200) -> list[HistoryEntry]:
        return self._history_repo.list(limit)

    def record_history(self, request: Request, response: HttpResponse, saved_id: str | None) -> None:
        self._history_repo.add(HistoryEntry(
            method=request.method, url=response.url, status=response.status_code if response.ok else None,
            duration_ms=response.elapsed_ms, size=response.size if response.ok else 0,
            created_at=time.time(), request=request.copy(), request_id=saved_id))
        self.history_changed.emit()

    def clear_history(self) -> None:
        self._history_repo.clear()
        self.history_changed.emit()
