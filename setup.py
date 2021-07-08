from setuptools import find_packages, setup

VERSION = "0.1.0"
DESCRIPTION = "A headless clone of Mega Crit's Slay the Spire"


def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="decapitate_the_spire",
    version=VERSION,
    author="Janzen Brewer-Krebs",
    author_email="janzen@toypiper.com",
    description=DESCRIPTION,
    long_description=readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/jahabrewer/decapitate-the-spire",
    packages=find_packages(),
    install_requires=[],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Topic :: Games/Entertainment",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
