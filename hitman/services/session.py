"""Open request tabs and their unsaved drafts."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from hitman.core.http import HttpResponse
from hitman.core.models import Request, new_id


@dataclass
class OpenTab:
    request: Request                       # the working draft
    baseline: Request                      # last saved state (or the blank request it started as)
    saved: bool = False                    # True when the request lives in a collection
    id: str = field(default_factory=lambda: new_id("t_"))
    response: HttpResponse | None = None
    loading: bool = False
    section: str = "params"                # params | auth | headers | body
    response_section: str = "body"         # body | headers
    response_view: str = "pretty"          # pretty | raw

    @property
    def dirty(self) -> bool:
        return self.request != self.baseline


def _blank_tab() -> OpenTab:
    request = Request()
    return OpenTab(request=request, baseline=request.copy())


class Session(QObject):
    """Tab list plus the active tab. Emits fine-grained signals so views can update cheaply."""

    tabs_changed = Signal()            # tabs added/removed/reordered or active tab switched
    tab_updated = Signal(str)          # a tab's draft, dirty state, response or loading flag changed

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.tabs: list[OpenTab] = [_blank_tab()]
        self.active_id: str = self.tabs[0].id

    # --------------------------------------------------------------- lookup
    @property
    def active(self) -> OpenTab:
        return self.tab(self.active_id) or self.tabs[0]

    def tab(self, tab_id: str) -> OpenTab | None:
        return next((t for t in self.tabs if t.id == tab_id), None)

    def tab_for_request(self, request_id: str) -> OpenTab | None:
        return next((t for t in self.tabs if t.saved and t.request.id == request_id), None)

    # ------------------------------------------------------------- mutation
    def set_active(self, tab_id: str) -> None:
        if self.tab(tab_id) and tab_id != self.active_id:
            self.active_id = tab_id
            self.tabs_changed.emit()

    def open_saved(self, request: Request, replace_clean_active: bool = False) -> OpenTab:
        existing = self.tab_for_request(request.id)
        if existing:
            self.set_active(existing.id)
            return existing
        tab = OpenTab(request=request.copy(), baseline=request.copy(), saved=True)
        self._insert(tab, replace_clean_active)
        return tab

    def open_draft(self, request: Request, replace_clean_active: bool = False) -> OpenTab:
        """Open an unsaved request (from history or an import)."""
        draft = request.copy()
        draft.id = Request().id
        tab = OpenTab(request=draft, baseline=draft.copy(), saved=False)
        self._insert(tab, replace_clean_active)
        return tab

    def new_tab(self) -> OpenTab:
        tab = _blank_tab()
        self._insert(tab, False, reuse_pristine=False)
        return tab

    def _insert(self, tab: OpenTab, replace_clean_active: bool, reuse_pristine: bool = True) -> None:
        """Add `tab` and activate it. A clean active tab is replaced when asked to, and an untouched
        blank tab is always reused so opening a request doesn't leave an empty tab behind."""
        current = self.active
        pristine = reuse_pristine and not current.saved and current.response is None
        if (replace_clean_active or pristine) and not current.dirty and not current.loading:
            index = self.tabs.index(current)
            self.tabs[index] = tab
        else:
            self.tabs.append(tab)
        self.active_id = tab.id
        self.tabs_changed.emit()

    def close(self, tab_id: str) -> None:
        tab = self.tab(tab_id)
        if tab is None:
            return
        index = self.tabs.index(tab)
        self.tabs.remove(tab)
        if not self.tabs:
            self.tabs.append(_blank_tab())
        if self.active_id == tab_id or not self.tab(self.active_id):
            self.active_id = self.tabs[min(index, len(self.tabs) - 1)].id
        self.tabs_changed.emit()

    def close_where(self, predicate) -> None:
        doomed = [t.id for t in self.tabs if predicate(t)]
        for tab_id in doomed:
            self.close(tab_id)

    def cycle(self, step: int = 1) -> None:
        index = self.tabs.index(self.active)
        self.set_active(self.tabs[(index + step) % len(self.tabs)].id)

    def touch(self, tab_id: str) -> None:
        """Signal that a tab's state changed (after mutating its draft in place)."""
        self.tab_updated.emit(tab_id)

    def mark_saved(self, tab_id: str, request: Request) -> None:
        tab = self.tab(tab_id)
        if tab is None:
            return
        tab.request = request.copy()
        tab.baseline = request.copy()
        tab.saved = True
        self.tab_updated.emit(tab_id)
        self.tabs_changed.emit()

    def revert(self, tab_id: str) -> None:
        tab = self.tab(tab_id)
        if tab:
            tab.request = tab.baseline.copy()
            self.tab_updated.emit(tab_id)

    def sync_saved(self, lookup) -> None:
        """After collections change: refresh baselines/names, close tabs whose request was deleted.

        `lookup(request_id)` returns the saved Request or None.
        """
        changed = False
        for tab in list(self.tabs):
            if not tab.saved:
                continue
            saved = lookup(tab.request.id)
            if saved is None:
                self.close(tab.id)
                continue
            if saved.name != tab.baseline.name:
                if tab.request.name == tab.baseline.name:
                    tab.request.name = saved.name
                tab.baseline.name = saved.name
                changed = True
                self.tab_updated.emit(tab.id)
        if changed:
            self.tabs_changed.emit()

    def set_loading(self, tab_id: str, loading: bool) -> None:
        tab = self.tab(tab_id)
        if tab:
            tab.loading = loading
            self.tab_updated.emit(tab_id)

    def set_response(self, tab_id: str, response: HttpResponse | None) -> None:
        tab = self.tab(tab_id)
        if tab:
            tab.response = response
            tab.loading = False
            self.tab_updated.emit(tab_id)

    # ---------------------------------------------------------- persistence
    def to_state(self) -> dict:
        return {
            "active": self.active_id,
            "tabs": [{"id": t.id, "saved": t.saved, "section": t.section,
                      "request": t.request.to_dict(), "baseline": t.baseline.to_dict()} for t in self.tabs],
        }

    def restore(self, state: dict, lookup) -> None:
        tabs: list[OpenTab] = []
        for entry in (state or {}).get("tabs", []):
            try:
                request = Request.from_dict(entry["request"])
                baseline = Request.from_dict(entry.get("baseline") or entry["request"])
            except (KeyError, TypeError):
                continue
            saved = bool(entry.get("saved"))
            if saved:
                current = lookup(request.id)
                if current is None:
                    saved, baseline = False, Request(id=request.id)
                else:
                    baseline = current
            tabs.append(OpenTab(request=request, baseline=baseline, saved=saved,
                                id=entry.get("id") or new_id("t_"), section=entry.get("section", "params")))
        if tabs:
            self.tabs = tabs
            active = state.get("active")
            self.active_id = active if self.tab(active) else tabs[0].id
            self.tabs_changed.emit()
