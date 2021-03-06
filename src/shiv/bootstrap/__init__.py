import site
import sys
import shutil

from importlib import import_module
from pathlib import Path
from py_compile import compile

from .environment import Environment
from .interpreter import execute_interpreter
from .utils import current_zipfile, silence_stderr


def import_string(import_name):
    """Returns a callable for a given setuptools style import string

    :param import_name: A console_scripts style import string
    """
    import_name = str(import_name).replace(":", ".")
    try:
        import_module(import_name)
    except ImportError:
        if "." not in import_name:
            # this is a case like "import name", where continuing to the
            # next style of import would not improve the situation, so
            # we raise here.
            raise

    else:
        return sys.modules[import_name]

    # this is a case where the previous attempt may have failed due to
    # not being importable. ("not a package", etc)
    module_name, obj_name = import_name.rsplit(".", 1)
    try:
        module = __import__(module_name, None, None, [obj_name])
    except ImportError:
        # Recurse to support importing modules not yet set up by the parent module
        # (or package for that matter)
        module = import_string(module_name)

    try:
        return getattr(module, obj_name)

    except AttributeError as e:
        raise ImportError(e)


def cache_path(archive, root_dir, build_id):
    """Returns a ~/.shiv cache directory for unzipping site-packages during bootstrap.

    :param ZipFile archive: The zipfile object we are bootstrapping from.
    :param str buidl_id: The build id generated at zip creation.
    """
    root = root_dir or Path("~/.shiv").expanduser()
    name = Path(archive.filename).stem
    return root / f"{name}_{build_id}"


def extract_site_packages(archive, target_path):
    """Extract everything in site-packages to a specified path.

    :param ZipFile archive: The zipfile object we are bootstrapping from.
    :param Path target_path: The path to extract our zip to.
    """
    target_path_tmp = Path(target_path.parent, target_path.stem + ".tmp")

    for filename in archive.namelist():
        if filename.startswith("site-packages"):
            archive.extract(filename, target_path_tmp)

    # compile pyc with stderr silenced
    with silence_stderr():
        for py_file in target_path_tmp.glob('**/*.py'):
            compile(py_file)

    # atomic move
    shutil.move(target_path_tmp.as_posix(), target_path.as_posix())


def bootstrap():
    """Actually bootstrap our shiv environment."""

    # get a handle of the currently executing zip file
    archive = current_zipfile()

    # create an environment object (a combination of env vars and json metadata)
    env = Environment.from_json(archive.read("environment.json").decode())

    # get a site-packages directory (from env var or via build id)
    site_packages = cache_path(archive, env.root, env.build_id) / "site-packages"

    # determine if first run or forcing extract
    if not site_packages.exists() or env.force_extract:
        extract_site_packages(archive, site_packages.parent)

    # stdlib blessed way of extending path
    site.addsitedir(site_packages)

    # do entry point import and call
    if env.entry_point is not None and env.interpreter is None:
        mod = import_string(env.entry_point)
        try:
            mod()
        except TypeError as e:
            # catch "<module> is not callable", which is thrown when the entry point's
            # callable shares a name with it's parent module
            # e.g. "from foo.bar import bar; bar()"
            getattr(mod, env.entry_point.replace(":", ".").split(".")[1])()
    else:
        # drop into interactive mode
        execute_interpreter()


if __name__ == "__main__":
    bootstrap()
