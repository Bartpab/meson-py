import os
from setuptools import setup, Command, find_packages

with open('requirements.txt') as f:
    required = f.read().splitlines()

class CleanCommand(Command):
    """Custom clean command to tidy up the project root."""
    user_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        os.system('rm -vrf ./build ./dist ./*.pyc ./*.tgz ./*.egg-info')

setup(
	name='MesonPy',
	version = "0.0.1",
	author = "Gael Pabois",
	author_email = "gael.pabois@gmail.com",
	packages = find_packages(),
	url="https://github.com/Bartpab/meson-py",
	license="LICENSE",
	description="Websocket based python wrapper for Electron projects",
	long_description=open('README.md').read(),
	install_requires=required,
	cmdclass={
		'clean': CleanCommand,
	}
)
