import logging

logger = logging.getLogger(__name__)
"""
    Encrypt the data with AES, in CBC mode

    The padding method used is PKCS7
"""
def encrypt(data, aes):
    if type(data) not in (bytes, bytearray):
        data = data.encode('utf-8')

    data        = bytearray(data)
    size        = len(data)
    mod         = size % 16 # cipher requires n * 16 bytes block to work
    nb_blocks   = (size - mod) / 16 + (1 if mod > 0 else 0)
    stuff_size  = ((16 - mod) if mod > 0 else 0)

    # Stuff the last block if not exactly 16 bytes long, according to PKCS7 
    for i in range(stuff_size):
        data.append(int(stuff_size))

    return aes.encrypt(bytes(data))
