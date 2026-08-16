"""
ffmpeg link builder
copied as into build step in Dockerfile

Adapted from tubearchivist (https://github.com/tubearchivist/tubearchivist),
licensed GPL-3.0. Downloads GPL ffmpeg/ffprobe builds from
https://github.com/yt-dlp/FFmpeg-Builds; see the License section of the README
for the redistribution notice covering the published images.
"""

import json
import os
import sys
import tarfile
import urllib.request
from enum import Enum

API_URL = 'https://api.github.com/repos/yt-dlp/FFmpeg-Builds/releases/latest'
BINARIES = ['ffmpeg', 'ffprobe']


class PlatformFilter(Enum):
    """options"""

    ARM64 = 'linuxarm64'
    AMD64 = 'linux64'


def get_assets():
    """get all available assets from latest build"""
    with urllib.request.urlopen(API_URL) as f:
        return json.loads(f.read().decode('utf-8'))


def pick_url(all_links, platform):
    """pick url for platform"""
    filter_by = PlatformFilter[platform.split('/')[1].upper()].value
    options = [i for i in all_links['assets'] if filter_by in i['name']]
    if not options:
        msg = f'no valid asset found for filter {filter_by}'
        raise ValueError(msg)

    return options[0]['browser_download_url']


def download_extract(url):
    """download and extract binaries"""
    print('download file')
    filename, _ = urllib.request.urlretrieve(url)
    print('extract file')
    with tarfile.open(filename, 'r:xz') as tar:
        for member in tar.getmembers():
            member.name = os.path.basename(member.name)
            if member.name in BINARIES:
                print(f'extract {member.name}')
                tar.extract(member, member.name)


def main():
    """entry point"""
    args = sys.argv
    if len(args) < 2 or not args[1]:
        # Defaulting here would bake amd64 binaries into an arm64 image, and the
        # mismatch only surfaces as `exec format error` at transcode time. The
        # build host's own arch is no better a guess, since this cross-builds.
        msg = 'TARGETPLATFORM is required (e.g. linux/amd64); build with BuildKit/buildx'
        raise SystemExit(msg)

    platform = args[1]

    all_links = get_assets()
    url = pick_url(all_links, platform)
    download_extract(url)


if __name__ == '__main__':
    main()
