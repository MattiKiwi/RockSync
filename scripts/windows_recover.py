import sys
import base64

def decode_product_key(digital_product_id):
    key_offset = 52
    digits = "BCDFGHJKMPQRTVWXY2346789"
    decoded_chars = []
    pid = list(digital_product_id[key_offset:key_offset + 15])
    for i in range(25):
        current = 0
        for j in range(14, -1, -1):
            current = current * 256
            current = pid[j] + current
            pid[j] = current // 24
            current = current % 24
        decoded_chars.insert(0, digits[current])
    for i in range(5, 25, 6):
        decoded_chars.insert(i, '-')
    return ''.join(decoded_chars)

if __name__ == "__main__":
    with open("/home/matti/Downloads/DigitalProductId.bin", "rb") as f:
        digital_product_id = list(f.read())
    print(decode_product_key(digital_product_id))
