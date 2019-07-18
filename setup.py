import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pytest-orchestration",
    version="0.0.10",
    author="Simon Lindberg",
    author_email="lindberg.simon@gmail.com",
    description="A pytest plugin for orchestrating tests",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/simlind/pytest-orchestration",
    packages=setuptools.find_packages(exclude=['test*']),
    entry_points={"pytest11": ["orchestration = orchestration.plugin"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Framework :: Pytest"
    ],
)