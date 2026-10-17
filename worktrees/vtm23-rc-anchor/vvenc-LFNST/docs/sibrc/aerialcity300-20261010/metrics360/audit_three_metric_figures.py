from pathlib import Path
import json
from pypdf import PdfReader
from PIL import Image
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
audit={}
for name in ('frame_bitrate','frame_spsnr'):
    with Image.open(D/(name+'.png')) as im:
        assert im.size==(4296,2940)
        assert all(abs(v-600)<1 for v in im.info['dpi'])
    r=PdfReader(D/(name+'.pdf'));assert len(r.pages)==1
    p=r.pages[0];assert abs(float(p.mediabox.width)-7.16*72)<0.01
    assert abs(float(p.mediabox.height)-4.9*72)<0.01
    fonts=p['/Resources'].get_object()['/Font'].get_object();records=[]
    for key,obj in fonts.items():
        font=obj.get_object();assert font['/Subtype']!='/Type3'
        descendants=font.get('/DescendantFonts',[obj])
        for child in descendants:
            f=child.get_object();d=f['/FontDescriptor'].get_object()
            assert '/FontFile2' in d,'TrueType font not embedded'
            records.append({'font':str(f['/BaseFont']),'subtype':str(f['/Subtype']),'embedded':'FontFile2'})
    assert records
    audit[name]={'png_pixels':[4296,2940],'dpi':600,'pdf_inches':[7.16,4.9],'fonts':records}
(D/'figure_format_audit.json').write_text(json.dumps(audit,indent=2))
print('PASS: both 600-dpi PNGs, PDF dimensions and embedded TrueType descendant fonts')
