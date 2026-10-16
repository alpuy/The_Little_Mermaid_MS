"""Headless Master System emulator for tests: Genesis Plus GX libretro core driven
through ctypes (core built with the debug hooks of test/gpgx_debug.patch).

    emu = SMS('build/mermaid.sms')
    emu.run(60, pad=0)          # frames, pad bits (see BTN)
    emu.ram(0xC000, 16)         # Z80 address space RAM (C000-DFFF)
    emu.screenshot('x.png')
"""
import ctypes as C, os, struct, zlib

CORE = os.environ.get('GPGX_CORE', '/home/user/emu/gpgx/genesis_plus_gx_libretro.so')

# pad bits
UP, DOWN, LEFT, RIGHT, B1, B2, PAUSE = 1, 2, 4, 8, 16, 32, 64
_RETRO_ID = {UP: 4, DOWN: 5, LEFT: 6, RIGHT: 7, B1: 0, B2: 8, PAUSE: 3}

ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIOB_CB = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)


class GameInfo(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]


class Variable(C.Structure):
    _fields_ = [('key', C.c_char_p), ('value', C.c_char_p)]


OPTIONS = {
    b'genesis_plus_gx_system_hw': b'master system II',
    b'genesis_plus_gx_region_detect': b'ntsc-u',
    b'genesis_plus_gx_bios': b'disabled',
    b'genesis_plus_gx_overscan': b'disabled',
    b'genesis_plus_gx_left_border': b'disabled',
    b'genesis_plus_gx_overclock': b'100%',
}


class SMS:
    def __init__(self, rom, audio=False):
        self.lib = C.CDLL(CORE)
        self.pad = 0
        self.frame = None
        self.audio = [] if audio else None
        self._keep = []
        sysdir = C.c_char_p(b'/tmp')

        def env(cmd, data):
            if cmd in (9, 31):                       # system / save directory
                C.cast(data, C.POINTER(C.c_char_p))[0] = sysdir.value
                return True
            if cmd == 10:                            # pixel format
                return True
            if cmd == 15:                            # get variable
                v = C.cast(data, C.POINTER(Variable))[0]
                val = OPTIONS.get(v.key)
                if val is None:
                    C.cast(data, C.POINTER(Variable))[0].value = None   # core default
                    return False
                C.cast(data, C.POINTER(Variable))[0].value = val
                return True
            return False

        def video(data, w, h, pitch):
            if data:
                self.frame = (C.string_at(data, pitch * h), w, h, pitch)

        def audio_s(l, r):
            pass

        def audio_b(data, frames):
            if self.audio is not None:
                self.audio.append(C.string_at(data, frames * 4))
            return frames

        def poll():
            pass

        def state(port, device, index, id_):
            if port != 0 or device != 1:
                return 0
            for bit, rid in _RETRO_ID.items():
                if rid == id_ and self.pad & bit:
                    return 1
            return 0

        self._cbs = [ENV_CB(env), VIDEO_CB(video), AUDIO_CB(audio_s), AUDIOB_CB(audio_b), POLL_CB(poll), STATE_CB(state)]
        L = self.lib
        L.retro_set_environment(self._cbs[0])
        L.retro_set_video_refresh(self._cbs[1])
        L.retro_set_audio_sample(self._cbs[2])
        L.retro_set_audio_sample_batch(self._cbs[3])
        L.retro_set_input_poll(self._cbs[4])
        L.retro_set_input_state(self._cbs[5])
        L.retro_init()
        data = open(rom, 'rb').read()
        self._rom = C.create_string_buffer(data, len(data))
        gi = GameInfo(os.path.abspath(rom).encode(), C.cast(self._rom, C.c_void_p), len(data), None)
        if not L.retro_load_game(C.byref(gi)):
            raise RuntimeError('load failed')
        L.retro_get_memory_data.restype = C.c_void_p
        L.retro_get_memory_size.restype = C.c_size_t
        L.retro_set_controller_port_device(0, 1)
        # debug hooks
        self.dbg_enable = C.c_uint.in_dll(L, 'dbg_enable')
        self.dbg_count_en = C.c_uint.in_dll(L, 'dbg_count_en')
        self.dbg_hits = (C.c_uint * 65536).in_dll(L, 'dbg_hits')
        self.dbg_trace = (C.c_ushort * 65536).in_dll(L, 'dbg_trace')
        self.dbg_trace_pos = C.c_uint.in_dll(L, 'dbg_trace_pos')
        self.dbg_stop_pc = C.c_uint.in_dll(L, 'dbg_stop_pc')
        self.dbg_stopped = C.c_uint.in_dll(L, 'dbg_stopped')
        self.frames = 0

    # ------------------------------------------------------------ running
    def run(self, n=1, pad=None):
        if pad is not None:
            self.pad = pad
        for _ in range(n):
            self.lib.retro_run()
            self.frames += 1

    def run_until_pc(self, pc, max_frames=100000):
        """run until the Z80 executes address pc (the frame is cut short there)"""
        self.dbg_enable.value = 1
        self.dbg_stopped.value = 0
        self.dbg_stop_pc.value = pc
        for _ in range(max_frames):
            self.lib.retro_run()
            self.frames += 1
            if self.dbg_stopped.value:
                return True
        return False

    # ------------------------------------------------------------ memory
    def _ram_buf(self):
        p = self.lib.retro_get_memory_data(2)
        n = self.lib.retro_get_memory_size(2)
        return p, n

    def ram(self, addr, n=1):
        """read Z80 RAM (C000-DFFF, mirrored at E000-FFFF)"""
        p, size = self._ram_buf()
        off = (addr - 0xC000) & 0x1FFF
        b = C.string_at(p, 0x2000)
        out = bytes(b[(off + i) & 0x1FFF] for i in range(n))
        return out

    def poke(self, addr, data):
        p, size = self._ram_buf()
        off = (addr - 0xC000) & 0x1FFF
        for i, v in enumerate(data):
            C.cast(p, C.POINTER(C.c_ubyte))[(off + i) & 0x1FFF] = v

    def vram(self):
        return bytes((C.c_ubyte * 0x4000).in_dll(self.lib, 'vram'))

    def cram(self):
        return bytes((C.c_ubyte * 0x40).in_dll(self.lib, 'cram'))

    def vdpreg(self):
        return bytes((C.c_ubyte * 0x20).in_dll(self.lib, 'reg'))

    def z80(self):
        """PC, SP of the Z80"""
        b = bytes((C.c_ubyte * 64).in_dll(self.lib, 'Z80'))
        pc = struct.unpack_from('<H', b, 0)[0]
        sp = struct.unpack_from('<H', b, 4)[0]
        return pc, sp

    def trace(self, n=64):
        pos = self.dbg_trace_pos.value
        return [self.dbg_trace[(pos - n + i) & 0xFFFF] for i in range(n)]

    # ------------------------------------------------------------ profiler
    def profile_start(self, interval=2000, cap=200000, tag_addr=0xC000):
        self._prof = (C.c_uint * cap)()
        C.c_uint.in_dll(self.lib, 'dbg_prof_n').value = 0
        C.c_uint.in_dll(self.lib, 'dbg_prof_cap').value = cap
        C.c_void_p.in_dll(self.lib, 'dbg_prof_buf').value = C.cast(self._prof, C.c_void_p).value
        C.c_uint.in_dll(self.lib, 'dbg_tag_addr').value = tag_addr
        C.c_uint.in_dll(self.lib, 'dbg_prof_interval').value = interval
        self.dbg_enable.value = 1

    def profile_stop(self):
        C.c_uint.in_dll(self.lib, 'dbg_prof_interval').value = 0
        n = C.c_uint.in_dll(self.lib, 'dbg_prof_n').value
        return [(v & 0xFFFF, v >> 16) for v in self._prof[:n]]

    # ------------------------------------------------------------ video / audio
    def screenshot(self, path):
        data, w, h, pitch = self.frame
        rows = []
        for y in range(h):
            row = bytearray([0])
            line = data[y * pitch:y * pitch + w * 2]
            for x in range(w):
                v = line[2 * x] | line[2 * x + 1] << 8
                r = (v >> 11) & 31; g = (v >> 5) & 63; b = v & 31
                row += bytes((r * 255 // 31, g * 255 // 63, b * 255 // 31))
            rows.append(bytes(row))
        raw = zlib.compress(b''.join(rows), 6)

        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + \
            chunk(b'IDAT', raw) + chunk(b'IEND', b'')
        open(path, 'wb').write(png)

    def save_wav(self, path):
        pcm = b''.join(self.audio)
        hdr = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 2, 44100, 44100 * 4, 4, 16) + \
            b'data' + struct.pack('<I', len(pcm))
        open(path, 'wb').write(hdr + pcm)
