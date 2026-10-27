"""Reference with MEDCoupling (runs INSIDE the simvia/code_aster image).
Usage: python3 ref_medcoupling.py file.med FIELD step output.npz"""
import sys
import numpy as np
import medcoupling as mc

path, field, step, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
mm = mc.MEDFileMesh.New(path)
mts = mc.MEDFileFieldMultiTS.New(path, field, True)
f1 = mts[step if step >= 0 else len(mts) + step]
res = {"coords": mm.getCoords().toNumPyArray(), "time": f1.getTime()[2]}
types = f1.getTypesOfFieldAvailable()
if mc.ON_GAUSS_PT in types:
    fld = f1.field(mm)
    res["vals"] = fld.getArray().toNumPyArray()
    res["loc"] = fld.getLocalizationOfDiscr().toNumPyArray()
else:
    arr, pfl = f1.getFieldWithProfile(mc.ON_NODES, 0, mm)
    full = np.full((mm.getNumberOfNodes(), arr.getNumberOfComponents()), np.nan)
    full[pfl.toNumPyArray()] = arr.toNumPyArray()
    res["vals"] = full
np.savez(out, **res)
print("ok", path, field, "t =", res["time"], res["vals"].shape)
