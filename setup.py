from setuptools import Distribution, setup
from wheel.bdist_wheel import bdist_wheel


class BinaryDistribution(Distribution):
    """Mark the package as platform-specific because it embeds the Go UI."""

    def has_ext_modules(self):
        return True


class PlatformWheel(bdist_wheel):
    """Use a Python-agnostic tag while retaining the native platform tag."""

    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _python, _abi, platform = super().get_tag()
        return "py3", "none", platform


setup(
    distclass=BinaryDistribution,
    cmdclass={"bdist_wheel": PlatformWheel},
)
