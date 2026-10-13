"""User preferences."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from hitman.core.http import SendOptions


@dataclass
class Settings:
    # General
    theme: str = "dark"            # dark | light | system
    font_size: int = 13            # editor font size in px
    open_in_new_tab: bool = True
    ask_before_close: bool = True
    restore_tabs: bool = True
    # Requests
    timeout_ms: int = 30000
    max_redirects: int = 10
    follow_redirects: bool = True
    verify_ssl: bool = True
    encode_url: bool = True
    use_system_proxy: bool = True
    # Layout
    layout: str = "stacked"        # stacked | side-by-side
    sidebar_visible: bool = True
    sidebar_section: str = "collections"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> Settings:
        settings = cls()
        for f in fields(cls):
            if data and f.name in data and isinstance(data[f.name], type(getattr(settings, f.name))):
                setattr(settings, f.name, data[f.name])
        return settings

    def send_options(self) -> SendOptions:
        return SendOptions(timeout_ms=self.timeout_ms, follow_redirects=self.follow_redirects,
                           max_redirects=self.max_redirects, verify_ssl=self.verify_ssl,
                           encode_url=self.encode_url, use_system_proxy=self.use_system_proxy)
