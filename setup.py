from setuptools import setup

setup(
    name="surgeon",
    version="0.1.0",
    py_modules=[
        "cli",
        "execution_engine",
        "trace_parser",
        "patch_engine",
        "orchestrator"
    ],
    install_requires=[
        "litellm",
        "python-dotenv"
    ],
    entry_points={
        "console_scripts": [
            "surgeon=cli:main"
        ]
    }
)
