import os
import re
import subprocess
import sys
from pathlib import Path


def _run_inline(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=proc_env
    )


def test_libp2p_debug_single_module():
    """LIBP2P_DEBUG sets module-specific level for network swarm."""
    logging_py = Path(__file__).resolve().parents[3] / "libp2p/utils/logging.py"
    code = (
        f"import importlib.util, logging; "
        f"spec=importlib.util.spec_from_file_location('libp2p.utils.logging', r'{logging_py}'); "
        f"mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
        f"mod.setup_logging(); "
        f"print('LEVEL', logging.getLogger('libp2p.network.swarm').getEffectiveLevel())"
    )
    cp = _run_inline(code, {"LIBP2P_DEBUG": "network:DEBUG"})
    assert cp.returncode == 0, cp.stderr
    assert "LEVEL 10" in cp.stdout  # DEBUG == 10


def test_libp2p_debug_multiple_modules():
    """LIBP2P_DEBUG supports combined module config."""
    logging_py = Path(__file__).resolve().parents[3] / "libp2p/utils/logging.py"
    code = (
        f"import importlib.util, logging; "
        f"spec=importlib.util.spec_from_file_location('libp2p.utils.logging', r'{logging_py}'); "
        f"mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
        f"mod.setup_logging(); "
        f"print('S', logging.getLogger('libp2p.network').getEffectiveLevel()); "
        f"print('G', logging.getLogger('libp2p.pubsub.gossipsub').getEffectiveLevel())"
    )
    cp = _run_inline(code, {"LIBP2P_DEBUG": "network:DEBUG,pubsub.gossipsub:INFO"})
    assert cp.returncode == 0, cp.stderr
    # network DEBUG -> 10, gossipsub INFO -> 20
    assert re.search(r"^S 10$", cp.stdout, re.M)
    assert re.search(r"^G 20$", cp.stdout, re.M)


def test_libp2p_debug_global_level():
    """Global level affects root libp2p logger."""
    logging_py = Path(__file__).resolve().parents[3] / "libp2p/utils/logging.py"
    code = (
        f"import importlib.util, logging; "
        f"spec=importlib.util.spec_from_file_location('libp2p.utils.logging', r'{logging_py}'); "
        f"mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
        f"mod.setup_logging(); "
        f"print(logging.getLogger('libp2p').getEffectiveLevel())"
    )
    cp = _run_inline(code, {"LIBP2P_DEBUG": "WARNING"})
    assert cp.returncode == 0, cp.stderr
    assert "30" in cp.stdout  # WARNING == 30

