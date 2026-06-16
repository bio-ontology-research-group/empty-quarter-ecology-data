import csv

raw_data = """Ag concentration,http://purl.obolibrary.org/obo/CHEBI_131422
Al concentration,http://purl.obolibrary.org/obo/CHEBI_26676
Al2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_28984
As concentration,http://purl.obolibrary.org/obo/CHEBI_30188
Au concentration,http://purl.obolibrary.org/obo/CHEBI_27563
Ba concentration,http://purl.obolibrary.org/obo/CHEBI_29840
BaO concentration,http://purl.obolibrary.org/obo/CHEBI_22694
Bi concentration,http://purl.obolibrary.org/obo/CHEBI_131437
Br concentration,http://purl.obolibrary.org/obo/CHEBI_22872
Ca concentration,http://purl.obolibrary.org/obo/CHEBI_22927
CaO concentration,http://purl.obolibrary.org/obo/CHEBI_22984
Cd concentration,http://purl.obolibrary.org/obo/CHEBI_31344
Ce concentration,http://purl.obolibrary.org/obo/CHEBI_22977
CeO2 concentration,http://purl.obolibrary.org/obo/CHEBI_23081
Cl concentration,http://purl.obolibrary.org/obo/CHEBI_131424
Co concentration,http://purl.obolibrary.org/obo/CHEBI_23153
CoO concentration,http://purl.obolibrary.org/obo/CHEBI_23356
Cr concentration,http://purl.obolibrary.org/obo/CHEBI_50822
Cr2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_28073
Cs concentration,http://purl.obolibrary.org/obo/CHEBI_50812
Cu concentration,http://purl.obolibrary.org/obo/CHEBI_23053
CuO concentration,http://purl.obolibrary.org/obo/CHEBI_28694
Dy concentration,http://purl.obolibrary.org/obo/CHEBI_50823
Er concentration,http://purl.obolibrary.org/obo/CHEBI_23883
Eu concentration,http://purl.obolibrary.org/obo/CHEBI_23929
Fe concentration,http://purl.obolibrary.org/obo/CHEBI_23992
Fe2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_18248
Ga concentration,http://purl.obolibrary.org/obo/CHEBI_50819
Gd concentration,http://purl.obolibrary.org/obo/CHEBI_27531
Ge concentration,http://purl.obolibrary.org/obo/CHEBI_24185
Hf concentration,http://purl.obolibrary.org/obo/CHEBI_27521
Hg concentration,http://purl.obolibrary.org/obo/CHEBI_24467
Ho concentration,http://purl.obolibrary.org/obo/CHEBI_25202
I concentration,http://purl.obolibrary.org/obo/CHEBI_24610
Ir concentration,http://purl.obolibrary.org/obo/CHEBI_24859
K concentration,http://purl.obolibrary.org/obo/CHEBI_24873
K2O concentration,http://purl.obolibrary.org/obo/CHEBI_26216
La concentration,http://purl.obolibrary.org/obo/CHEBI_131423
La2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_24963
Lu concentration,http://purl.obolibrary.org/obo/CHEBI_131424
Mg concentration,http://purl.obolibrary.org/obo/CHEBI_25112
MgO concentration,http://purl.obolibrary.org/obo/CHEBI_25107
Mn concentration,http://purl.obolibrary.org/obo/CHEBI_31673
MnO concentration,http://purl.obolibrary.org/obo/CHEBI_18291
Mo concentration,http://purl.obolibrary.org/obo/CHEBI_131433
Na concentration,http://purl.obolibrary.org/obo/CHEBI_28685
Na2O concentration,http://purl.obolibrary.org/obo/CHEBI_26642
Nb concentration,http://purl.obolibrary.org/obo/CHEBI_78659
Nd concentration,http://purl.obolibrary.org/obo/CHEBI_25557
Nd2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_25490
Ni concentration,http://purl.obolibrary.org/obo/CHEBI_131426
NiO concentration,http://purl.obolibrary.org/obo/CHEBI_28112
Os concentration,http://purl.obolibrary.org/obo/CHEBI_50824
P concentration,http://purl.obolibrary.org/obo/CHEBI_25712
P2O5 concentration,http://purl.obolibrary.org/obo/CHEBI_26004
Pb concentration,http://purl.obolibrary.org/obo/CHEBI_37583
PbO concentration,http://purl.obolibrary.org/obo/CHEBI_25016
Pr concentration,http://purl.obolibrary.org/obo/CHEBI_131428
PrO2 concentration,http://purl.obolibrary.org/obo/CHEBI_26257
Pt concentration,http://purl.obolibrary.org/obo/CHEBI_131425
Rb concentration,http://purl.obolibrary.org/obo/CHEBI_26156
Re concentration,http://purl.obolibrary.org/obo/CHEBI_26421
S concentration,http://purl.obolibrary.org/obo/CHEBI_26487
SO3 concentration,http://purl.obolibrary.org/obo/CHEBI_26833
Sb concentration,http://purl.obolibrary.org/obo/CHEBI_29324
Sc concentration,http://purl.obolibrary.org/obo/CHEBI_22567
Se concentration,http://purl.obolibrary.org/obo/CHEBI_26537
Si concentration,http://purl.obolibrary.org/obo/CHEBI_27511
SiO2 concentration,http://purl.obolibrary.org/obo/CHEBI_27573
Sm concentration,http://purl.obolibrary.org/obo/CHEBI_30563
Sm2O3 concentration,http://purl.obolibrary.org/obo/CHEBI_26523
Sn concentration,http://purl.obolibrary.org/obo/CHEBI_131427
Sr concentration,http://purl.obolibrary.org/obo/CHEBI_27051
SrO concentration,http://purl.obolibrary.org/obo/CHEBI_26799
Ta concentration,http://purl.obolibrary.org/obo/CHEBI_131435
Tb concentration,http://purl.obolibrary.org/obo/CHEBI_26847
Th concentration,http://purl.obolibrary.org/obo/CHEBI_26903
Ti concentration,http://purl.obolibrary.org/obo/CHEBI_26986
TiO2 concentration,http://purl.obolibrary.org/obo/CHEBI_27008
Tm concentration,http://purl.obolibrary.org/obo/CHEBI_51050
U concentration,http://purl.obolibrary.org/obo/CHEBI_26998
V concentration,http://purl.obolibrary.org/obo/CHEBI_27197
V2O5 concentration,http://purl.obolibrary.org/obo/CHEBI_27266
W concentration,http://purl.obolibrary.org/obo/CHEBI_50825
Y concentration,http://purl.obolibrary.org/obo/CHEBI_27250
Yb concentration,http://purl.obolibrary.org/obo/CHEBI_27306
Zn concentration,http://purl.obolibrary.org/obo/CHEBI_27303
ZnO concentration,http://purl.obolibrary.org/obo/CHEBI_27363
Zr concentration,http://purl.obolibrary.org/obo/CHEBI_36560
ZrO2 concentration,http://purl.obolibrary.org/obo/CHEBI_27335"""

latex = []
latex.append(r"\begin{longtable}{ll}")
latex.append(
    r"\caption{Mapping of XRF measurement qualities to ChEBI identifiers.} \label{tab:chebi_mapping} \\"
)
latex.append(r"\toprule")
latex.append(r"Analyte Quality & ChEBI Class \\")
latex.append(r"\midrule")
latex.append(r"\endfirsthead")
latex.append(r"\toprule")
latex.append(r"Analyte Quality & ChEBI Class \\")
latex.append(r"\midrule")
latex.append(r"\endhead")
latex.append(r"\bottomrule")
latex.append(r"\endfoot")

for line in raw_data.split("\n"):
    if not line:
        continue
    parts = line.split(",")
    rak_label = parts[0]
    chebi_uri = parts[1]
    chebi_id = chebi_uri.split("/")[-1]
    chebi_id = chebi_id.replace("_", ":")
    latex.append(f"{rak_label} & \\url{{{chebi_uri}}} ({chebi_id}) \\\\")

latex.append(r"\end{longtable}")

with open("paper/xrf_table.tex", "w") as f:
    f.write("\n".join(latex))
