import zlib,struct,glob,sys
def rd(f):
    d=open(f,'rb').read();p=8;idat=b''
    while p<len(d):
        n,t=struct.unpack('>I4s',d[p:p+8]);c=d[p+8:p+8+n];p+=12+n
        if t==b'IHDR':w,h=struct.unpack('>II',c[:8])
        if t==b'IDAT':idat+=c
    raw=zlib.decompress(idat);s=w*3+1
    return w,h,[raw[i*s+1:(i+1)*s] for i in range(h)]
def ch(t,d):
    c=struct.pack('>I',len(d))+t+d;return c+struct.pack('>I',zlib.crc32(t+d))
def sheet(files,out):
    tiles=[rd(f) for f in files];H=tiles[0][1];W=tiles[0][0]
    rows=[b''.join(t[2][y] for t in tiles) for y in range(H)]
    raw=b''.join(b'\0'+r for r in rows)
    open(out,'wb').write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',W*len(tiles),H,8,2,0,0,0))+ch(b'IDAT',zlib.compress(raw))+ch(b'IEND',b''))
if __name__=='__main__': sheet(sys.argv[2:],sys.argv[1])
