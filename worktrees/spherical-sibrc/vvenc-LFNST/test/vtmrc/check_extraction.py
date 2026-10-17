"""Audit every source byte except documented mechanical transformations/whitespace."""
from pathlib import Path
import difflib
import hashlib
import json
import os
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('VTM_SOURCE_DIR', 'I:/001-IBRC-exps/VTM-23.0-anchor-clean'))
NAMES = {'EncRCSeq': 'VtmRcSeq', 'EncRCGOP': 'VtmRcGOP',
         'EncRCPic': 'VtmRcPic', 'TRCLCU': 'VtmRcCtuState', 'RateCtrl': 'VtmRateCtrl'}

def expected_extraction(original, extension):
    for old, new in NAMES.items():
        original = re.sub(r'\b' + old + r'\b', new, original)
    original = original.replace('#include "../CommonLib/CommonDef.h"', '#include "Dependencies.h"')
    original = original.replace('#include "../EncoderLib/EncCfg.h"', '')
    original = original.replace('#include "../CommonLib/ChromaFormat.h"', '')
    original = original.replace('#include "VtmRateCtrl.h"', '#include "RateCtrl.h"')
    original = original.replace('DISTORTION_PRECISION_ADJUSTMENT', 'VTMRC_DISTORTION_PRECISION_ADJUSTMENT')
    original = original.replace('CHECK(', 'VTMRC_CHECK(')
    for name in ['ALPHA', 'BETA1', 'BETA2', 'LAMBDA_PREC']:
        original = re.sub(r'\b' + name + r'\b', 'VTMRC_' + name, original)
    if extension == 'h':
        original = original.replace('__ENCRATECTRL__', 'VVENC_VTMRC_RATECTRL_H')
        original = original.replace('const int g_RCInvalidQPValue',
                                    'namespace vvenc { namespace vtmrc {\n\nconst int g_RCInvalidQPValue')
        original = original.replace('\n#endif', '\n} } // namespace vvenc::vtmrc\n\n#endif')
    else:
        original = original.replace('#define VTMRC_LAMBDA_PREC', 'namespace vvenc { namespace vtmrc {\n\n#define VTMRC_LAMBDA_PREC')
        original += '\n} } // namespace vvenc::vtmrc\n'
    return original

def normalized(text):
    # Line-ending and blank-line formatting only; interior whitespace and arithmetic remain exact.
    return '\n'.join(line.rstrip() for line in text.splitlines() if line.strip())

def audit(expected, actual):
    expected, actual = normalized(expected), normalized(actual)
    if expected != actual:
        diff = '\n'.join(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                              fromfile='mechanical extraction', tofile='actual', n=2))
        raise AssertionError('Undocumented extraction change:\n' + diff)

provenance = json.loads((ROOT/'docs/vtm23-rc/provenance.json').read_text())
for extension in ['cpp', 'h']:
    path = SOURCE/('source/Lib/EncoderLib/RateCtrl.' + extension)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == provenance['files'][extension], 'Reference source hash changed'
    expected = expected_extraction(path.read_text(), extension)
    actual = (ROOT/('source/Lib/EncoderLib/VtmRcCompat/RateCtrl.' + extension)).read_text()
    audit(expected, actual)
    # Deliberately mutate a real arithmetic expression/constant in memory, never the source file.
    needle = 'm_bitsLeft -= bits;' if extension == 'cpp' else 'g_RCInvalidQPValue = -999;'
    replacement = 'm_bitsLeft += bits;' if extension == 'cpp' else 'g_RCInvalidQPValue = -998;'
    assert needle in actual, 'Negative mutation anchor missing'
    mutated = actual.replace(needle, replacement, 1)
    try:
        audit(expected, mutated)
    except AssertionError:
        pass
    else:
        raise AssertionError('Arithmetic mutation was accepted: ' + extension)
print('PASS: cpp/h exact mechanical extraction; both deliberate arithmetic mutations rejected; reference SHA256 verified')
