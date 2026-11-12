"""Byte-preserving image attachments referenced by versioned Markdown notes."""
import hashlib
import re
from pathlib import Path, PureWindowsPath

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FORMATS = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp'}
LINK = re.compile(r'!\[原图\d+\]\(\.assets/([0-9a-f-]{36})/([0-9a-f]{64})(\.(?:png|jpg|webp))\)')


def validate(data, suffix):
    valid = (suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')
        or suffix in {'.jpg','.jpeg'} and data.startswith(b'\xff\xd8\xff')
        or suffix == '.webp' and data.startswith(b'RIFF') and data[8:12] == b'WEBP')
    if not data or len(data) > MAX_IMAGE_BYTES or not valid:
        raise ValueError('图片须为文件头匹配的PNG、JPEG或WebP，单张上限10MiB')


def prepare(service, space, note_id, paths):
    if not isinstance(paths, list) or len(paths) > 5 or any(not isinstance(p,str) for p in paths):
        raise ValueError('image_paths须为最多5个vault内暂存路径的列表')
    assets, seen = [], set()
    incoming = service._path(f'{space}/.incoming')
    for relative in paths:
        if Path(relative).is_absolute() or PureWindowsPath(relative).drive:
            raise PermissionError('image_paths只接受vault相对路径')
        path = service._path(relative)
        if not path.is_relative_to(incoming):
            raise PermissionError('原图须先放入目标空间的.incoming目录，不接受其他路径')
        try:
            with path.open('rb') as stream:
                data = stream.read(MAX_IMAGE_BYTES+1)
        except OSError:
            raise ValueError('原图暂存文件不可读，请先将原始文件复制到目标空间的.incoming目录') from None
        suffix = path.suffix.lower()
        validate(data, suffix)
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        suffix = '.jpg' if suffix == '.jpeg' else suffix
        assets.append((f'{space}/.assets/{note_id}/{sha}{suffix}', data))
    return assets


def append_links(body, assets, space):
    if not assets:
        return body
    return body + '\n\n' + '\n'.join(f'![原图{i}]({relative[len(space)+1:]})'
        for i,(relative,_) in enumerate(assets,1))


def describe(service, row):
    images, seen = [], set()
    for note_id, sha, suffix in LINK.findall(row['body']):
        if note_id != str(row['id']) or sha in seen:
            continue
        seen.add(sha)
        relative = f"{row['space']}/.assets/{note_id}/{sha}{suffix}"
        images.append({'image_id':sha,'media_type':FORMATS[suffix], 'relative_path':relative,
            'available':service._path(relative).is_file(), 'citation':f'memory-image://{note_id}/{sha}'})
    return images
