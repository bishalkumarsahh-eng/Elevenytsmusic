# Existing Juno X Music plugins are preserved.
# This loader also loads the newly-added Artistbots group-management systems.
from pathlib import Path


def _list_modules():
    mod_dir = Path(__file__).parent
    modules = []
    for file in mod_dir.rglob("*.py"):
        if not file.is_file() or file.name == "__init__.py" or "__pycache__" in file.parts:
            continue
        rel = file.relative_to(mod_dir)
        modules.append(str(rel.with_suffix("")).replace("\\", ".").replace("/", "."))
    return modules


all_modules = frozenset(sorted(_list_modules()))
