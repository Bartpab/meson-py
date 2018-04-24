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
    stuff_size  = 16 - mod

    # Stuff the last block if not exactly 16 bytes long, according to PKCS7
    for i in range(stuff_size):
        data.append(int(stuff_size))

    return aes.encrypt(bytes(data))

def unpad(bin_str):
    size                = len(bin_str)
    last_byte           = bin_str[size - 1]

    # Test PKCS7 padding, else return the whole thing
    pkcs7_pad_pattern   = int(last_byte)
    if pkcs7_pad_pattern <= 16: # 0 - 15 bytes
        is_pkcs7 = True
        for i in range(size - pkcs7_pad_pattern, size - 1):
            if bin_str[i] != last_byte:
                is_pkcs7 = False
        if is_pkcs7:
            return bin_str[0:size - pkcs7_pad_pattern]

    else:
        return bin_str

def decrypt(bin_data, aes):
    padded_bin_data = aes.decrypt(bin_data)
    unpadded_bin_data = unpad(padded_bin_data)
    return unpadded_bin_data.decode('utf-8')
