"""Read-only SGA lister/extractor (format as in aoemods/AOEMods.Essence ArchiveReader). usage: sga_list.py archive.sga substr [outdir]"""
import struct, sys, zlib, os
def rd(f, fmt): return struct.unpack(fmt, f.read(struct.calcsize(fmt)))
def main(path, sub, out=None):
    f = open(path, 'rb')   # read only
    magic = f.read(8); ver, prod = rd(f, '<HH'); f.read(128)
    blob_off, blob_len, data_off, data_len, unk = rd(f, '<QIQQI'); f.read(256)
    f.seek(blob_off)
    toc_o, toc_n, fol_o, fol_n, fil_o, fil_n, str_o, str_l, h_o, h_l, bs = rd(f, '<11I')
    print('magic', magic, 'ver', ver, 'prod', prod, 'tocs', toc_n, 'folders', fol_n, 'files', fil_n, file=sys.stderr)
    f.seek(blob_off + toc_o); tocs = [(f.read(64), f.read(64)) + rd(f, '<5I') for _ in range(toc_n)]
    f.seek(blob_off + fol_o); fol = [rd(f, '<5I') for _ in range(fol_n)]
    f.seek(blob_off + fil_o); fil = [rd(f, '<IIQIIBBI') for _ in range(fil_n)]
    f.seek(blob_off + str_o); strs = f.read(str_l)
    def cs(o): return strs[o:strs.index(b'\0', o)].decode('utf8', 'replace')
    res = []
    def walk(fi, prefix):
        no, fs, fe, ls, le = fol[fi]; name = cs(no).replace('\\', '/')
        p = name if '/' in name or not prefix else prefix + '/' + name   # names may already be full paths
        for i in range(fs, fe): walk(i, p)
        for i in range(ls, le):
            fo = fil[i]; res.append((p + '/' + cs(fo[0]), fo))
    for t in tocs: walk(t[6], '')
    n = 0
    for p, fo in res:
        if sub.lower() in p.lower():
            print(p, fo[3], fo[4], 'storage', fo[6]); n += 1
            if out:
                f.seek(data_off + fo[2]); raw = f.read(fo[3])
                if fo[6] == 0: dat = raw
                elif fo[6] in (1, 2): dat = zlib.decompress(raw)
                else:
                    import brotli; dat = brotli.decompress(raw)
                assert len(dat) == fo[4], (len(dat), fo[4])
                dst = os.path.join(out, p.replace('/', os.sep)); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, 'wb').write(dat)
    print('matches', n, 'of', len(res), file=sys.stderr)
main(*sys.argv[1:])
