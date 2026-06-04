from setuptools import setup, find_packages

setup(
    name="repo-coach",
    version="2.0.0",
    packages=find_packages(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "repo-coach=core.cli.main:main",
        ],
    },
    install_requires=[],  # uses only stdlib + optional tree-sitter
)
