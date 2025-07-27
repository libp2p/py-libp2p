from pathlib import (
    Path,
)
import subprocess
from tempfile import (
    TemporaryDirectory,
)
import venv

from libp2p.utils.paths import get_venv_pip, get_venv_python, get_venv_activate_script


def create_venv(parent_path: Path) -> Path:
    venv_path = parent_path / "package-smoke-test"
    venv.create(venv_path, with_pip=True)
    subprocess.run(
        [get_venv_pip(venv_path), "install", "-U", "pip", "setuptools"], check=True
    )
    return venv_path


def find_wheel(project_path: Path) -> Path:
    wheels = list(project_path.glob("dist/*.whl"))

    if len(wheels) != 1:
        raise Exception(
            f"Expected one wheel. Instead found: {wheels} "
            f"in project {project_path.absolute()}"
        )

    return wheels[0]


def install_wheel(venv_path: Path, wheel_path: Path) -> None:
    subprocess.run(
        [get_venv_pip(venv_path), "install", f"{wheel_path}"],
        check=True,
    )


def test_install_local_wheel() -> None:
    with TemporaryDirectory() as tmpdir:
        venv_path = create_venv(Path(tmpdir))
        wheel_path = find_wheel(Path("."))
        install_wheel(venv_path, wheel_path)
        print("Installed", wheel_path.absolute(), "to", venv_path)
        activate_script = get_venv_activate_script(venv_path)
        if activate_script.suffix == '.bat':
            print(f"Activate with `{activate_script}`")
        else:
            print(f"Activate with `source {activate_script}`")
        input("Press enter when the test has completed. The directory will be deleted.")


if __name__ == "__main__":
    test_install_local_wheel()
