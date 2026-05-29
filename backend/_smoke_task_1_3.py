"""Quick smoke test for task 1.3 (_make_backup_meta serverVersionTag)."""
from sql_repository import _make_backup_meta, compute_server_version_tag


class FakeRow(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


row = FakeRow(
    schema_version=1,
    created_at='2025-01-01 00:00:00.000000',
    updated_at='2025-01-02 03:04:05.123456',
    compression='jpeg_1280_q80',
    size_bytes=1024,
    members_count=5,
    member_photos_count=2,
    assets_count=1,
    checksum_sha256='a' * 64,
)

m1 = _make_backup_meta(row, True)
m2 = _make_backup_meta(row, True)
expected = compute_server_version_tag(row['updated_at'], row['checksum_sha256'])
print('m1.tag:', m1['serverVersionTag'])
print('m2.tag:', m2['serverVersionTag'])
print('expected:', expected)
assert m1['serverVersionTag'] == m2['serverVersionTag'] == expected
assert len(m1['serverVersionTag']) == 64

m3 = _make_backup_meta(None, False)
print('no-row tag:', m3['serverVersionTag'], 'exists:', m3['exists'])
assert m3['serverVersionTag'] is None
assert m3['exists'] is False

m4 = _make_backup_meta(row, False)
print('row+exists=False tag:', m4['serverVersionTag'])
assert m4['serverVersionTag'] is None
assert m4['exists'] is False

# Sanity: only updated_at + checksum determine the tag
row_b = FakeRow(row)
row_b['size_bytes'] = 99999
m5 = _make_backup_meta(row_b, True)
assert m5['serverVersionTag'] == expected, 'tag must depend only on updated_at + checksum'

print('OK: task 1.3 smoke test passed')
