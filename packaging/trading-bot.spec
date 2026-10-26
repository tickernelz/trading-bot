import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
dropped = {name for name in os.environ.get("TB_DROPPED", "").split(",") if name}
pwa = Path(os.environ["TB_PWA_DIR"])


def present(package):
    try:
        __import__(package)
    except ImportError:
        return False
    return True


def modules(*packages):
    found = []
    for package in packages:
        if present(package):
            found += collect_submodules(package)
    return found


def metadata(*distributions):
    found = []
    for name in distributions:
        try:
            found += copy_metadata(name)
        except Exception:
            pass
    return found


datas = [
    (str(root / "config" / "config.example.yaml"), "config"),
    (str(root / "config" / "gateway.example.yaml"), "config"),
    (str(root / "engine" / "strategies"), "engine/strategies"),
    (str(root / "gateway" / "locales"), "gateway/locales"),
    (str(pwa), "pwa"),
]
datas += collect_data_files("freqtrade", include_py_files=True)
datas += collect_data_files("ccxt")
datas += collect_data_files("jsonschema_specifications")
datas += collect_data_files("langchain")
datas += collect_data_files("deepagents")
datas += metadata(
    "freqtrade", "ccxt", "langchain", "langchain-core", "langchain-openai", "langchain-anthropic", "langgraph",
    "deepagents", "openai", "anthropic", "pydantic", "httpx", "fastapi", "uvicorn", "starlette", "pywebpush",
)

hiddenimports = modules(
    "tbapp", "engine", "gateway", "analytics", "tb_swarm", "freqtrade", "ccxt", "uvicorn", "websockets",
    "deepagents", "langchain", "langchain_core", "langchain_openai", "langchain_anthropic", "langgraph",
    "talib", "technical", "ft_pandas_ta", "pywebpush", "py_vapid", "http_ece", "sqlalchemy.dialects",
)
if "pyarrow" not in dropped:
    hiddenimports += modules("pyarrow")

analysis = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "pytest", "sphinx", "matplotlib"] + (["pyarrow"] if "pyarrow" in dropped else []),
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="trading-bot",
    console=True,
    upx=False,
)
COLLECT(executable, analysis.binaries, analysis.datas, upx=False, name="trading-bot")
