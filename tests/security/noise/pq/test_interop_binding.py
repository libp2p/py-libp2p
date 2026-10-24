"""
Tests for the transcript-binding flag on the interop harnesses.

The simulated downgrade is the harnesses' negative control: both peers claim
to prefer a protocol neither runs, so the check must refuse the session. With
the binding off nothing runs the check, so such a run would pass while
exercising nothing. These tests pin that the combination is refused.
"""

import importlib.util
import pathlib
import sys
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_INTEROP_BINDING = _REPO_ROOT / "scripts" / "_interop_binding.py"


def _load_interop_binding() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_interop_binding_under_test", _INTEROP_BINDING
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


interop_binding = _load_interop_binding()


def test_a_simulated_downgrade_with_the_binding_off_is_refused() -> None:
    with pytest.raises(ValueError, match="tests nothing"):
        interop_binding.binding_for_mode("off", simulate_downgrade=True)


def test_the_binding_off_without_a_simulation_is_still_none() -> None:
    assert interop_binding.binding_for_mode("off") is None


@pytest.mark.parametrize("mode", ["extension", "identity"])
def test_a_simulated_downgrade_puts_the_phantom_first(mode: str) -> None:
    config = interop_binding.binding_for_mode(mode, simulate_downgrade=True)

    assert config is not None
    assert config.security_protocols[0] == interop_binding.PHANTOM_PREFERRED
