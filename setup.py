from setuptools import setup, find_packages

try:
    with open('requirements.txt', encoding='utf-16') as fp:
        install_requires = fp.read()
except:
    with open('requirements.txt') as fp:
        install_requires = fp.read()

setup(
    name='vnav-acquisition',
    version='1.5.1',
    description='Vibronav acquisition tools',
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
        'vnav_acquisition': ['*.js', '*.css', '*.html', '*.txt']
    },
    data_files=[],
    entry_points={
        'console_scripts': ['vnav_acquisition=vnav_acquisition.webserver:main',
                            'vnav_wav_process=vnav_acquisition.clean:main',
                            'vnav_audio_video_sync=vnav_acquisition.sync:main',
                            'vnav_annotate_positions=vnav_acquisition.track_position:main',
                            'vnav_video_video_sync=vnav_acquisition.sync_video:main',
                            'vnav_audio_video_sync_new=vnav_acquisition.sync_new:main'],
    }
)
