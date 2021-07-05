from setuptools import find_packages, setup

VERSION = "0.0.2"
DESCRIPTION = "TODO"


def readme():
    with open("README.rst") as f:
        return f.read()


setup(
    name="decapitate_the_spire",
    version=VERSION,
    author="Janzen Brewer-Krebs",
    author_email="decapitatethespire@toypiper.com",
    description=DESCRIPTION,
    long_description=readme(),
    packages=find_packages(),
    install_requires=[],
    keywords=["python"],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Topic :: Games/Entertainment",
    ],
)
