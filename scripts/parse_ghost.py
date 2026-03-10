import struct
import io
import os
import lzma

class ZeepGhostParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.header = {}
        self.frames = []

    def parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Ghost file not found: {self.file_path}")

        with open(self.file_path, 'rb') as f:
            raw_data = f.read()

        # Zeepkist GTR Ghost files usually start with LZMA (5D 00 00 01 00)
        # 13 byte header: 5 bytes properties, 8 bytes uncompressed size
        if raw_data.startswith(b'\x5d\x00\x00'):
            print(f"Decompressing LZMA ghost: {self.file_path}")
            try:
                # Standard lzma module supports the 13-byte header format (FORMAT_ALONE)
                decompressed = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
                reader = io.BytesIO(decompressed)
            except Exception as e:
                print(f"LZMA Decompression (FORMAT_ALONE) failed: {e}. Trying raw.")
                try:
                    # Fallback: try raw if the header is somehow non-standard
                    decompressed = lzma.decompress(raw_data[13:], format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 24}])
                    reader = io.BytesIO(decompressed)
                except Exception as e2:
                    print(f"LZMA Decompression (RAW) failed: {e2}")
                    raise e
        else:
            reader = io.BytesIO(raw_data)

        data = reader.read()
        total_len = len(data)
        
        # We search for a reasonable frame count and frame size
        # We start looking from the end of common small headers (0 to 150 bytes)
        for offset in range(0, min(150, total_len)):
            remaining = total_len - offset
            if remaining >= 4:
                potential_count = struct.unpack('<i', data[offset:offset+4])[0]
                
                # Check for 32-byte frames (float time, Vector3 pos, Quaternion rot)
                if potential_count > 0 and (remaining - 4) >= (potential_count * 32):
                    # verify it's not a huge number
                    if potential_count < 100000:
                        print(f"Detected {potential_count} frames at offset {offset+4} with size 32")
                        self.frames = self._extract_frames(data[offset+4:], potential_count, 32)
                        if len(self.frames) > 0:
                            return self.header, self.frames

                # Check for 28-byte frames (Vector3 pos, Quaternion rot)
                if potential_count > 0 and (remaining - 4) >= (potential_count * 28):
                    if potential_count < 100000:
                        print(f"Detected {potential_count} frames at offset {offset+4} with size 28")
                        self.frames = self._extract_frames(data[offset+4:], potential_count, 28)
                        if len(self.frames) > 0:
                            return self.header, self.frames

        # Fallback division search
        for frame_size in [32, 28]:
            if total_len % frame_size == 0:
                print(f"Fallback: Exact division match for frame size {frame_size}")
                self.frames = self._extract_frames(data, total_len // frame_size, frame_size)
                return self.header, self.frames

        # Final effort: brute force searching for float blocks
        for offset in range(min(total_len - 32, 500)):
            try:
                # Look for a pattern of 8 floats where the first is a timestamp
                test = struct.unpack('<ffffffff', data[offset:offset+32])
                if 0 <= test[0] < 3600 and all(-10000 < x < 10000 for x in test[1:4]):
                    count = (total_len - offset) // 32
                    print(f"Brute force match at offset {offset} with 32-byte frames")
                    self.frames = self._extract_frames(data[offset:], count, 32)
                    return self.header, self.frames
            except:
                continue

        raise RuntimeError(f"Could not find valid ghost frame structure in file. Decompressed size: {total_len} bytes")

    def _extract_frames(self, data, count, size):
        frames = []
        for i in range(count):
            start = i * size
            buf = data[start : start + size]
            if len(buf) < size: break
            
            try:
                if size == 32:
                    # time, pos(x,y,z), rot(x,y,z,w)
                    f = struct.unpack('<ffffffff', buf)
                    frames.append({
                        'time': f[0],
                        'pos': (float(f[1]), float(f[2]), float(f[3])),
                        'rot': (float(f[4]), float(f[5]), float(f[6]), float(f[7]))
                    })
                elif size == 28:
                    # pos(x,y,z), rot(x,y,z,w)
                    f = struct.unpack('<fffffff', buf)
                    frames.append({
                        'pos': (float(f[0]), float(f[1]), float(f[2])),
                        'rot': (float(f[3]), float(f[4]), float(f[5]), float(f[6]))
                    })
            except:
                break
        return frames

if __name__ == "__main__":
    pass
