from universal_runtime.core.hashing import sha256_text


def test_sha256_stable():
    assert sha256_text('abc') == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
