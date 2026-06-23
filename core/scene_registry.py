"""
scene_registry.py — 场景插件注册表

扫描 plugins/ 目录加载所有场景插件。
"""
import importlib
from pathlib import Path
from typing import Optional


class SceneInfo:
    """场景插件元数据 + 实例引用。"""

    def __init__(self, name: str, module, mod_path: Path):
        self.name = name
        self.module = module
        self.path = mod_path
        self.scene = getattr(module, "SCENE", {})
        self.device_rules = getattr(module, "DEVICE_RULES", [])
        self.command_mapping = getattr(module, "COMMAND_MAPPING", {})
        self.bundled_commands = getattr(module, "BUNDLED_COMMANDS", [])
        self.input_params = getattr(module, "INPUT_PARAMS", [])
        self.result_layout = getattr(module, "RESULT_LAYOUT", {})
        self.render_task_form = getattr(module, "render_task_form", None)
        self.analyze = getattr(module, "analyze", None)

    @property
    def display_name(self) -> str:
        return self.scene.get("name", self.name)

    @property
    def version(self) -> str:
        return self.scene.get("version", "0.0.0")

    @property
    def description(self) -> str:
        return self.scene.get("description", "")

    @property
    def icon(self) -> str:
        return self.scene.get("icon", "🔌")


class SceneRegistry:
    """场景注册表（单例使用）。"""

    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.scenes: dict[str, SceneInfo] = {}
        self._load_all()

    def _load_all(self):
        """扫描 plugins/ 下所有目录，加载有 __init__.py 的。"""
        if not self.plugins_dir.exists():
            return
        for p in sorted(self.plugins_dir.iterdir()):
            if not p.is_dir():
                continue
            if p.name.startswith("__"):
                continue
            if not (p / "__init__.py").exists():
                continue
            try:
                mod = importlib.import_module(f"plugins.{p.name}")
                self.scenes[p.name] = SceneInfo(p.name, mod, p)
            except Exception as e:
                print(f"[SceneRegistry] 加载插件失败 {p.name}: {e}")

    def list_scenes(self) -> list[SceneInfo]:
        return list(self.scenes.values())

    def get(self, name: str) -> Optional[SceneInfo]:
        return self.scenes.get(name)

    def reload(self):
        """热重载（开发用）。"""
        self.scenes.clear()
        self._load_all()


# 全局单例
_registry: Optional[SceneRegistry] = None


def get_registry(plugins_dir: str = "plugins") -> SceneRegistry:
    """获取全局单例。"""
    global _registry
    if _registry is None:
        _registry = SceneRegistry(plugins_dir)
    return _registry
