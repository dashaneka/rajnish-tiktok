# created by rajnish sahani
from __future__ import annotations

import html
import json
import re
import ssl
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import yt_dlp


class TikTokError(Exception):
    pass


class TikTokDownloader:
    PAGE_LIMIT = 16 * 1024 * 1024
    CDN_DOMAINS = ('tiktok.com', 'tiktokcdn.com', 'tiktokcdn-us.com',
                   'tiktokcdn-eu.com', 'byteoversea.com', 'ibytedtos.com', 'ibyteimg.com')
    HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}

    def __init__(self, max_download_bytes: int = 256 * 1024 * 1024):
        self.max_download_bytes = max_download_bytes

    @staticmethod
    def _validate(url: str, domains: tuple[str, ...]) -> str:
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
                or not any(host == d or host.endswith('.' + d) for d in domains)):
            raise TikTokError('please use an https tiktok link')
        return url

    @classmethod
    def validate_tiktok_url(cls, url: str) -> str:
        return cls._validate(url, ('tiktok.com',))

    def _client(self):
        return httpx.Client(headers=self.HEADERS, timeout=20, verify=ssl.create_default_context(), follow_redirects=False)

    def _fetch(self, url: str, *, image: bool = False) -> tuple[str, bytes, str]:
        domains = self.CDN_DOMAINS if image else ('tiktok.com',)
        limit = self.max_download_bytes if image else self.PAGE_LIMIT
        with self._client() as client:
            for _ in range(10):
                self._validate(url, domains)
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        location = response.headers.get('location')
                        if not location:
                            raise TikTokError('tiktok returned an invalid redirect')
                        url = urljoin(str(response.url), location)
                        continue
                    response.raise_for_status()
                    kind = response.headers.get('content-type', '').split(';')[0].lower()
                    if image and not kind.startswith('image/'):
                        raise TikTokError('tiktok did not return an image file')
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise TikTokError('download exceeded the temporary storage limit')
                        chunks.append(chunk)
                    return str(response.url), b''.join(chunks), kind
        raise TikTokError('too many redirects from tiktok')

    def resolve_url(self, url: str) -> str:
        self.validate_tiktok_url(url)
        # Full post URLs need no preliminary network request.
        if re.fullmatch(r'/@[^/]+/(?:video|photo)/\d+/?', urlsplit(url).path):
            return url
        p = urlsplit(url)
        if p.hostname not in ('vm.tiktok.com', 'vt.tiktok.com', 'www.tiktok.com', 'tiktok.com') or not re.fullmatch(r'/(?:t/)?[A-Za-z0-9_-]+/?', p.path):
            raise TikTokError('send an individual video or photo post, not a profile or live stream')
        return self._fetch(url)[0]

    @staticmethod
    def extract_photo_urls(page: str, post_id: str) -> list[list[str]]:
        # Restrict extraction to the requested post; never take recommended media.
        def find(value):
            if isinstance(value, dict):
                if str(value.get('id', '')) == post_id and isinstance(value.get('imagePost'), dict):
                    return value['imagePost']
                for child in value.values():
                    found = find(child)
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = find(child)
                    if found is not None:
                        return found
            return None

        for raw in re.findall(r'<script\b[^>]*>(.*?)</script\s*>', page, re.S | re.I):
            try:
                data = json.loads(raw)
            except ValueError:
                try:
                    data = json.loads(html.unescape(raw))
                except ValueError:
                    continue
            post = find(data)
            if post is None:
                continue
            images = post.get('images', [])
            if not isinstance(images, list) or not 1 <= len(images) <= 35:
                raise TikTokError('this photo post has an unsupported image count')
            result = []
            for image in images:
                choices = []
                if not isinstance(image, dict):
                    raise TikTokError('tiktok returned incomplete photo data')
                for key in ('originalImageURL', 'imageURL', 'displayImage'):
                    value = image.get(key) or {}
                    if isinstance(value, dict):
                        for url in value.get('urlList', []):
                            if isinstance(url, str) and url not in choices:
                                choices.append(url)
                if not choices:
                    raise TikTokError('tiktok did not expose all photos in this post')
                result.append(choices)
            return result
        raise TikTokError('tiktok did not expose this photo post; it may be blocked, private or unavailable')

    def _photos(self, url: str, post_id: str, output: Path) -> list[Path]:
        _, data, _ = self._fetch(url)
        choices = self.extract_photo_urls(data.decode('utf-8', errors='replace'), post_id)
        paths, total = [], 0
        for index, urls in enumerate(choices, 1):
            downloaded = None
            for candidate in urls[:6]:
                try:
                    _, content, kind = self._fetch(candidate, image=True)
                    suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/avif': '.avif'}.get(kind)
                    if not content or not suffix:
                        continue
                    downloaded = content, suffix
                    break
                except (httpx.HTTPError, TikTokError, ValueError):
                    continue
            if downloaded is None:
                raise TikTokError('a photo could not be downloaded; try this post again later')
            content, suffix = downloaded
            total += len(content)
            if total > self.max_download_bytes:
                raise TikTokError('download exceeded the temporary storage limit')
            path = output / f'tiktok_{post_id}_{index:02d}{suffix}'
            path.write_bytes(content)
            paths.append(path)
        return paths

    def download(self, url: str, output: Path) -> list[Path]:
        resolved = self.resolve_url(url)
        match = re.fullmatch(r'/@[^/]+/(video|photo)/(\d+)/?', urlsplit(resolved).path)
        if not match:
            raise TikTokError('the link did not resolve to an individual tiktok post')
        kind, post_id = match.groups()
        # Remove tracking parameters and keep only the requested post.
        canonical = 'https://www.tiktok.com' + urlsplit(resolved).path
        output.mkdir(parents=True, exist_ok=True)
        if kind == 'photo':
            return self._photos(canonical, post_id, output)
        options = {
            'format': 'bestvideo*+bestaudio/best', 'merge_output_format': 'mp4',
            'outtmpl': str(output / 'tiktok_%(id)s.%(ext)s'),
            'noplaylist': True, 'cachedir': False, 'quiet': True, 'no_warnings': True,
            'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2,
            'extractor_retries': 1, 'concurrent_fragment_downloads': 4,
            'max_filesize': self.max_download_bytes,
            'compat_opts': {'no-certifi'},
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(canonical, download=False)
            if not info or str(info.get('id')) != post_id or info.get('_type') in ('playlist', 'multi_video'):
                raise TikTokError('tiktok returned an unexpected post')
            formats = info.get('formats') or []
            if not any(f.get('vcodec') not in (None, 'none') for f in formats):
                # Older share URLs can use /video/ for slideshows. Never return just their soundtrack.
                return self._photos(canonical, post_id, output)
            ydl.process_ie_result(info, download=True)
        files = [p for p in output.iterdir() if p.is_file() and p.stem == f'tiktok_{post_id}'
                 and p.suffix.lower() in ('.mp4', '.webm', '.mkv', '.mov', '.m4v')]
        if not files:
            raise TikTokError('no complete video was downloaded; it may exceed the storage limit')
        return [max(files, key=lambda p: p.stat().st_size)]


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, TikTokError):
        return str(exc)
    text = str(exc).lower()
    if '429' in text or 'rate limit' in text:
        return 'tiktok is rate-limiting requests; wait and try again later'
    if any(term in text for term in ('403', 'blocked', 'login', 'private', 'captcha', 'not available', 'unable to extract', 'webpage is empty')):
        return 'tiktok refused access from this server, or the post is unavailable; try another public link later'
    if 'timed out' in text or 'timeout' in text:
        return 'tiktok took too long to respond; try again later'
    return 'tiktok download failed; check the server logs for the error type'


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker':
        raise SystemExit('use: tiktok_downloader.py --worker URL OUTPUT_DIR MAX_BYTES')
    try:
        files = TikTokDownloader(int(sys.argv[4])).download(sys.argv[2], Path(sys.argv[3]))
        print(json.dumps({'tikbot_result': True, 'files': [p.name for p in files]}), flush=True)
    except Exception as exc:
        # Do not expose signed media URLs, credentials, or arbitrary network responses.
        print(f'downloader error type: {type(exc).__name__}', flush=True)
        print(json.dumps({'tikbot_result': True, 'error': friendly_error(exc)}), flush=True)
        raise SystemExit(1)
