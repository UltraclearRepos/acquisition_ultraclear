from setuptools import setup, find_packages

try:
    with open('requirements.txt', encoding='utf-16') as fp:
        install_requires = fp.read()
except:
    with open('requirements.txt') as fp:
        install_requires = fp.read()

setup(
    name='uclr-acquisition',
    version='0.1.0',
    description='Ultraclear acquisition tools',
    author='Dominik Rzepka',
    author_email='dominik.rzepka@gmail.com',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3'
    ],
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={},
    package_data={
        'uclr_acquisition': ['*.js', '*.css', '*.html', '*.txt']
    },
    data_files=[],
    entry_points={
        'console_scripts': ['uclr_acquisition=uclr_acquisition.webserver:main'],
    }
)
