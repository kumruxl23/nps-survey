from setuptools import find_packages, setup

setup(
    name="NPSSurveyAutomation",
    version="1.0",
    packages=find_packages(exclude=["*.test", "*.tests", "test", "tests"]),
    include_package_data=True,
    root_script_source_version="python3.11",
    check_format=False,
    test_command="brazilpython_pytest",
)
