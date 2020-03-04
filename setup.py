import setuptools
from configparser import ConfigParser

requirements = ConfigParser()
requirements.read('Pipfile')

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="feishu_bot",  # Replace with your own username
    version="0.0.1",
    author="Yuanefi Zhu",
    author_email="abovemoon@outlook.com",
    description="SDK for interacting with Feishu(previously Lark)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yuanfeiz/feishu-bot",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=requirements.options('packages'))
