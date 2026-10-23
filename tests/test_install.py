import plistlib
import subprocess
from pathlib import Path

import pytest

from gh_notify import bundle, instance, launchagent


def test_info_plist_identity_and_agent_mode():
    info = bundle.build_info_plist()
    assert info["CFBundleIdentifier"] == bundle.BUNDLE_ID
    assert info["CFBundleExecutable"] == bundle.LAUNCHER_NAME
    assert info["LSUIElement"] is True


def test_program_arguments_and_plist(tmp_path):
    runtime = bundle.PythonRuntime(
        Path("/py/lib/libpython3.13.dylib"), Path("/py"), "/sp:/src"
    )
    args = bundle.program_arguments(Path("/app/launcher"), runtime, "run")
    assert args == [
        "/app/launcher", "/py/lib/libpython3.13.dylib", "/py", "/sp:/src",
        "-c", bundle.ENTRY_CODE, "run",
    ]  # fmt: skip
    plist = launchagent.build_plist(args, tmp_path / "log")
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["ProgramArguments"] == args
    plistlib.dumps(plist)


def test_current_runtime_points_at_real_files():
    runtime = bundle.current_runtime()
    assert runtime.libpython.is_file()
    assert runtime.path


def test_find_libpython_standalone_layout(tmp_path):
    lib = tmp_path / "lib" / "libpython3.13.dylib"
    lib.parent.mkdir()
    lib.touch()
    assert bundle.find_libpython(tmp_path, "libpython3.13.dylib") == lib


def test_find_libpython_framework_layout(tmp_path):
    # Homebrew: base_prefix is the Versions/3.14 directory, LDLIBRARY is framework-relative
    lib = tmp_path / "Python"
    lib.touch()
    (tmp_path / "lib").mkdir()
    ldlibrary = "Python.framework/Versions/3.14/Python"
    assert bundle.find_libpython(tmp_path, ldlibrary) == lib


def test_find_libpython_reports_searched_paths(tmp_path):
    with pytest.raises(bundle.BundleError, match="libpython not found") as exc:
        bundle.find_libpython(tmp_path, "libpython3.13.dylib")
    assert str(tmp_path / "lib" / "libpython3.13.dylib") in str(exc.value)


def test_find_libpython_without_ldlibrary(tmp_path):
    with pytest.raises(bundle.BundleError, match="LDLIBRARY"):
        bundle.find_libpython(tmp_path, "")


def test_build_bundle_is_signed_idempotent_and_runs_python(tmp_path):
    app = tmp_path / "T.app"
    launcher = bundle.build_bundle(app)
    first = launcher.read_bytes()
    bundle.build_bundle(app)
    assert launcher.read_bytes() == first
    verify = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)], check=False
    )
    assert verify.returncode == 0

    runtime = bundle.current_runtime()
    code = (
        "import sys, Foundation;"
        "print(Foundation.NSBundle.mainBundle().bundleIdentifier());"
        "sys.exit(7)"
    )
    result = subprocess.run(
        [str(launcher), str(runtime.libpython), str(runtime.home), runtime.path, "-c", code],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 7  # exit codes pass through for KeepAlive
    assert result.stdout.strip() == bundle.BUNDLE_ID  # the process has the app identity


def test_second_lock_fails_until_first_released(tmp_path):
    path = tmp_path / "app.lock"
    first = instance.acquire(path)
    with pytest.raises(instance.AlreadyRunningError):
        instance.acquire(path)
    first.close()
    instance.acquire(path).close()
