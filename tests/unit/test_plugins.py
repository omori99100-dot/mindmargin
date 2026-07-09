import tempfile

import pytest

from mindmargin.core.plugins import PluginManager, Plugin, PluginMetadata, PluginState, PluginHook


class TestPluginMetadata:
    def test_defaults(self):
        m = PluginMetadata(name="test")
        assert m.name == "test"
        assert m.version == "0.1.0"
        assert m.description == ""
        assert m.author == ""
        assert m.dependencies == []


class TestPlugin:
    def test_lifecycle_hooks(self):
        p = Plugin(PluginMetadata(name="test"))
        assert p.state == PluginState.DISABLED
        p.on_load()
        p.on_enable()
        p.on_disable()
        p.on_unload()

    def test_add_hook(self):
        p = Plugin(PluginMetadata(name="test"))
        def h1(**kw): return 1
        def h2(**kw): return 2
        p.add_hook("init", h1, priority=50)
        p.add_hook("init", h2, priority=10)
        assert len(p.hooks) == 2
        assert p.hooks[0].priority == 10
        assert p.hooks[1].priority == 50

    def test_hooks_property_returns_copy(self):
        p = Plugin(PluginMetadata(name="test"))
        p.add_hook("h", lambda **kw: None)
        hooks = p.hooks
        assert len(hooks) == 1


class TestPluginManager:
    @pytest.fixture
    def mgr(self):
        return PluginManager()

    def test_discover_empty(self, mgr):
        found = mgr.discover()
        assert isinstance(found, list)

    def test_load_nonexistent(self, mgr):
        assert not mgr.load("nonexistent_plugin_xyz")

    def test_unload_nonexistent(self, mgr):
        assert not mgr.unload("nonexistent")

    def test_load_twice(self, mgr):
        assert not mgr.load("nonexistent_plugin_xyz")
        assert not mgr.load("nonexistent_plugin_xyz")

    def test_enable_without_load(self, mgr):
        assert not mgr.enable("nonexistent")

    def test_disable_without_enable(self, mgr):
        assert not mgr.disable("nonexistent")

    def test_get_nonexistent(self, mgr):
        assert mgr.get("nonexistent") is None

    def test_list_all_empty(self, mgr):
        assert mgr.list_all() == []

    def test_list_by_state_empty(self, mgr):
        assert mgr.list_by_state(PluginState.ENABLED) == []

    def test_validate_dependencies_missing(self, mgr):
        deps = mgr.validate_dependencies("nonexistent")
        assert len(deps) == 1


class TestPluginHooks:
    @pytest.fixture
    def mgr_with_plugins(self):
        mgr = PluginManager()
        p1 = Plugin(PluginMetadata(name="p1"))
        p1.add_hook("startup", lambda **kw: "p1_started")
        p1.add_hook("shutdown", lambda **kw: "p1_stopped")
        p2 = Plugin(PluginMetadata(name="p2"))
        p2.add_hook("startup", lambda **kw: "p2_started", priority=50)
        mgr._plugins["p1"] = p1
        mgr._plugins["p2"] = p2
        mgr._register_hooks(p1)
        mgr._register_hooks(p2)
        return mgr

    def test_run_hook(self, mgr_with_plugins):
        results = mgr_with_plugins.run_hook("startup")
        assert len(results) == 2
        assert "p2_started" in results
        assert "p1_started" in results

    def test_run_hook_unknown(self, mgr_with_plugins):
        results = mgr_with_plugins.run_hook("unknown")
        assert results == []

    def test_run_hook_error_isolated(self, mgr_with_plugins):
        p3 = Plugin(PluginMetadata(name="p3"))
        p3.add_hook("startup", lambda **kw: 1/0)
        mgr_with_plugins._plugins["p3"] = p3
        mgr_with_plugins._register_hooks(p3)
        results = mgr_with_plugins.run_hook("startup")
        assert len(results) == 3
        assert results[2] is None


class TestPluginEnableDisable:
    @pytest.fixture
    def mgr(self):
        mgr = PluginManager()
        p = Plugin(PluginMetadata(name="my_plugin", dependencies=[]))
        p.state = PluginState.LOADED
        mgr._plugins["my_plugin"] = p
        return mgr

    def test_enable(self, mgr):
        assert mgr.enable("my_plugin")
        assert mgr.get("my_plugin").state == PluginState.ENABLED

    def test_disable(self, mgr):
        mgr.enable("my_plugin")
        assert mgr.disable("my_plugin")
        assert mgr.get("my_plugin").state == PluginState.DISABLED

    def test_enable_twice(self, mgr):
        mgr.enable("my_plugin")
        assert not mgr.enable("my_plugin")

    def test_disable_not_enabled(self, mgr):
        assert not mgr.disable("my_plugin")

    def test_dependency_check_on_enable(self, mgr):
        mgr._plugins["dep_a"] = Plugin(PluginMetadata(name="dep_a"))
        mgr._plugins["dep_a"].state = PluginState.LOADED
        p_with_dep = Plugin(PluginMetadata(name="dependent", dependencies=["dep_a"]))
        p_with_dep.state = PluginState.LOADED
        mgr._plugins["dependent"] = p_with_dep
        assert not mgr.enable("dependent")

    def test_dependency_satisfied(self, mgr):
        mgr._plugins["dep_b"] = Plugin(PluginMetadata(name="dep_b"))
        mgr._plugins["dep_b"].state = PluginState.ENABLED
        p_with_dep = Plugin(PluginMetadata(name="dependent2", dependencies=["dep_b"]))
        p_with_dep.state = PluginState.LOADED
        mgr._plugins["dependent2"] = p_with_dep
        assert mgr.enable("dependent2")

    def test_cannot_disable_required_by_other(self, mgr):
        mgr.enable("my_plugin")
        p_dep = Plugin(PluginMetadata(name="dependent3", dependencies=["my_plugin"]))
        p_dep.state = PluginState.ENABLED
        mgr._plugins["dependent3"] = p_dep
        assert not mgr.disable("my_plugin")


class TestPluginValidateDeps:
    @pytest.fixture
    def mgr(self):
        mgr = PluginManager()
        p = Plugin(PluginMetadata(name="base"))
        p.state = PluginState.ENABLED
        mgr._plugins["base"] = p
        return mgr

    def test_valid_deps(self, mgr):
        p = Plugin(PluginMetadata(name="child", dependencies=["base"]))
        p.state = PluginState.ENABLED
        mgr._plugins["child"] = p
        assert mgr.validate_dependencies("child") == []

    def test_missing_dep(self, mgr):
        p = Plugin(PluginMetadata(name="orphan", dependencies=["missing_dep"]))
        mgr._plugins["orphan"] = p
        deps = mgr.validate_dependencies("orphan")
        assert any("missing" in d.lower() for d in deps)

    def test_not_active_dep(self, mgr):
        mgr._plugins["inactive"] = Plugin(PluginMetadata(name="inactive"))
        p = Plugin(PluginMetadata(name="waiter", dependencies=["inactive"]))
        mgr._plugins["waiter"] = p
        deps = mgr.validate_dependencies("waiter")
        assert any("not active" in d.lower() for d in deps)


class TestPluginUnload:
    @pytest.fixture
    def mgr(self):
        mgr = PluginManager()
        p = Plugin(PluginMetadata(name="unload_me"))
        p.state = PluginState.LOADED
        mgr._plugins["unload_me"] = p
        return mgr

    def test_unload(self, mgr):
        assert mgr.unload("unload_me")
        assert mgr.get("unload_me") is None

    def test_unload_removes_hooks(self, mgr):
        p = mgr.get("unload_me")
        p.add_hook("init", lambda **kw: None)
        mgr._register_hooks(p)
        assert "init" in mgr._hooks
        mgr.unload("unload_me")
        assert "init" not in mgr._hooks


class TestPluginEdgeCases:
    def test_discover_with_plugin_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PluginManager(plugin_dir=tmpdir)
            found = mgr.discover()
            assert isinstance(found, list)

    def test_unload_exception_logged(self):
        mgr = PluginManager()
        p = Plugin(PluginMetadata(name="bad_unload"))
        def broken_on_unload():
            raise ValueError("unload fail")
        p.on_unload = broken_on_unload
        p.state = PluginState.LOADED
        mgr._plugins["bad_unload"] = p
        assert not mgr.unload("bad_unload")
