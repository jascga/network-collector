from setuptools import setup, find_packages

setup(
    name="network-collector",
    version="1.0.0",
    description="网络设备采集分析平台",
    packages=find_packages(include=["core", "core.*", "ui", "ui.*"]),
    python_requires=">=3.8",
    install_requires=[
        "paramiko>=3.0",
        "cryptography>=41.0",
        "openpyxl>=3.1",
        "jinja2>=3.1",
    ],
    extras_require={
        "gui": ["PyQt5>=5.15"],
        "web": ["requests>=2.28", "beautifulsoup4>=4.11"],
        "browser": ["playwright>=1.40"],
        "dev": ["pyyaml>=6.0", "pyinstaller>=6.0"],
        "all": ["PyQt5>=5.15", "requests>=2.28", "beautifulsoup4>=4.11", "playwright>=1.40", "pyyaml>=6.0", "pyinstaller>=6.0"],
    },
) 
