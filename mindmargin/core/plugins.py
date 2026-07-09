import importlib
import inspect
import logging
import pkgutil
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.core.events import publish
from mindmargin.core.hardening import utcnow

logger = logging.getLogger(__name__)


class PluginState(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    LOADED = "loaded"
    UNLOADED = "unloaded"
    ERROR = "error"


@dataclass
class PluginMetadata:
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class PluginHook:
    name: str
    handler: Callable
    priority: int = 100


class Plugin:
    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self.state = PluginState.DISABLED
        self._hooks: list[PluginHook] = []
        self._module = None

    def on_load(self):
        pass

    def on_unload(self):
        pass

    def on_enable(self):
        pass

    def on_disable(self):
        pass

    def add_hook(self, name: str, handler: Callable, priority: int = 100):
        self._hooks.append(PluginHook(name=name, handler=handler, priority=priority))
        self._hooks.sort(key=lambda h: h.priority)

    @property
    def hooks(self) -> list[PluginHook]:
        return list(self._hooks)


class PluginManager:
    def __init__(self, plugin_dir: str = ""):
        self._plugins: dict[str, Plugin] = {}
        self._hooks: dict[str, list[PluginHook]] = {}
        self._lock = threading.RLock()
        self._plugin_dir = Path(plugin_dir) if plugin_dir else None

    def discover(self, paths: Optional[list[str]] = None) -> list[str]:
        found = []
        search_paths = paths or []
        if self._plugin_dir and self._plugin_dir.is_dir():
            search_paths.append(str(self._plugin_dir))
        for importer, modname, ispkg in pkgutil.iter_modules(search_paths):
            if modname.startswith("_"):
                continue
            if modname not in self._plugins:
                found.append(modname)
        return found

    def load(self, name: str, module_path: Optional[str] = None) -> bool:
        with self._lock:
            if name in self._plugins:
                return False
            try:
                if module_path and module_path not in sys.path:
                    sys.path.insert(0, module_path)
                mod = importlib.import_module(name)
                plugin = self._create_from_module(mod, name)
                if not plugin:
                    plugin = Plugin(PluginMetadata(name=name))
                plugin._module = mod
                plugin.state = PluginState.LOADED
                plugin.on_load()
                self._plugins[name] = plugin
                self._register_hooks(plugin)
                publish("plugin.loaded", data={"name": name}, source="plugin")
                logger.info("Loaded plugin: %s v%s", name, plugin.metadata.version)
                return True
            except Exception as e:
                logger.error("Failed to load plugin '%s': %s", name, e)
                return False

    def _create_from_module(self, mod, name: str) -> Optional[Plugin]:
        for _, obj in inspect.getmembers(mod):
            if inspect.isclass(obj) and issubclass(obj, Plugin) and obj is not Plugin:
                return obj()
        return None

    def _register_hooks(self, plugin: Plugin):
        for hook in plugin._hooks:
            if hook.name not in self._hooks:
                self._hooks[hook.name] = []
            self._hooks[hook.name].append(hook)
            self._hooks[hook.name].sort(key=lambda h: h.priority)

    def unload(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
            if not plugin:
                return False
            try:
                plugin.on_unload()
                self._remove_hooks(plugin)
                self._plugins.pop(name)
                plugin.state = PluginState.UNLOADED
                publish("plugin.unloaded", data={"name": name}, source="plugin")
                logger.info("Unloaded plugin: %s", name)
                return True
            except Exception as e:
                logger.error("Failed to unload plugin '%s': %s", name, e)
                return False

    def _remove_hooks(self, plugin: Plugin):
        for hook in plugin._hooks:
            if hook.name in self._hooks:
                self._hooks[hook.name] = [h for h in self._hooks[hook.name] if h.handler != hook.handler]
                if not self._hooks[hook.name]:
                    del self._hooks[hook.name]

    def enable(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state not in (PluginState.DISABLED, PluginState.LOADED):
                return False
            deps = plugin.metadata.dependencies
            for dep_name in deps:
                dep = self._plugins.get(dep_name)
                if not dep or dep.state != PluginState.ENABLED:
                    logger.warning("Dependency '%s' not enabled for plugin '%s'", dep_name, name)
                    return False
            plugin.state = PluginState.ENABLED
            plugin.on_enable()
            publish("plugin.enabled", data={"name": name}, source="plugin")
            return True

    def disable(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state != PluginState.ENABLED:
                return False
            for p in self._plugins.values():
                if p.state == PluginState.ENABLED and name in p.metadata.dependencies:
                    logger.warning("Cannot disable '%s': required by '%s'", name, p.metadata.name)
                    return False
            plugin.state = PluginState.DISABLED
            plugin.on_disable()
            publish("plugin.disabled", data={"name": name}, source="plugin")
            return True

    def get(self, name: str) -> Optional[Plugin]:
        with self._lock:
            return self._plugins.get(name)

    def list_all(self) -> list[Plugin]:
        with self._lock:
            return list(self._plugins.values())

    def list_by_state(self, state: PluginState) -> list[Plugin]:
        return [p for p in self.list_all() if p.state == state]

    def run_hook(self, hook_name: str, **kwargs) -> list[Any]:
        results = []
        with self._lock:
            hooks = list(self._hooks.get(hook_name, []))
        for hook in hooks:
            try:
                results.append(hook.handler(**kwargs))
            except Exception as e:
                logger.error("Hook '%s' handler failed: %s", hook_name, e)
                results.append(None)
        return results

    def validate_dependencies(self, name: str) -> list[str]:
        missing = []
        plugin = self._plugins.get(name)
        if not plugin:
            return ["Plugin not found"]
        for dep_name in plugin.metadata.dependencies:
            dep = self._plugins.get(dep_name)
            if not dep:
                missing.append(f"Missing dependency: {dep_name}")
            elif dep.state not in (PluginState.ENABLED, PluginState.LOADED):
                missing.append(f"Dependency not active: {dep_name}")
        return missing
