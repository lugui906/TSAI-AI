from setuptools import setup, find_packages

setup(
    name="aim",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "httpx",
    ],
    entry_points={
        "console_scripts": [
            "aim=aim.cli:main",
        ],
    },
    python_requires=">=3.8",
)
